"""Der Gemini-Sprecher: Googles Sprachsynthese ueber die Interactions API (Spec 8).

**Eine Anfrageform.** `POST .../v1beta/interactions` mit dem woertlichen Transkript des Blocks
als Text; die Stimme steht in `generation_config.speech_config`, ein Stil nur als
`speech_metadata` neben dem Text -- nie als Anweisung im Text, nie `systemInstruction`, nie
`mime_type` oder `sample_rate` im `response_format` (das Modell 2.5 Pro antwortet darauf mit HTTP
400 und liefert ohne Angabe PCM).

**Das Format entscheiden die Bytes.** Die Antwort nennt einen `mime_type`; die ersten vier Bytes
der Daten sagen, ob es eine RIFF-WAV ist. Widersprechen sie sich, gewinnen die Bytes und das Log
nennt es: ein WAV-Kopf als Samples geschrieben knackte am Blockanfang, kopfloses PCM als WAV
gelesen waere Unsinn.

**Token.** Die Felder der Nutzungsangabe wurden firsthand aus einer echten Antwort des Modells
gelesen (2026-10-30, `usage` der Interactions-Antwort): Eingabe-Text-Token stehen in
`usage.input_tokens_by_modality[modality == "text"].tokens`, Ausgabe-Audio-Token in
`usage.output_tokens_by_modality[modality == "audio"].tokens`. Fehlt ein Feld, ist der Wert
`None` -- nie 0 als Ersatz.
"""

from __future__ import annotations

import base64
import binascii
import io
import logging
import queue
import re
import tempfile
import threading
import time
import wave
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

from mkn_kern import anfrage

from mkn_audio.arbeiter_client import Arbeiter
from mkn_audio.arbeitsverzeichnis import fingerabdruck
from mkn_audio.mastern import SAMPLERATE, atomar, ffmpeg, temp_ordner
from mkn_audio.sprecher import (
    ERSATZ_ZEICHEN_JE_S,
    PROBE_SATZ,
    Auftrag,
    Ausweis,
    Block,
    Messwerte,
    SprecherFehler,
    Verbrauch,
    erste_woerter,
)
from mkn_audio.stimmen import Stimme, WegKonfig
from mkn_audio.typen import Mp4Fehler, Stueck

URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
"""Die eine Adresse der Interactions API; das Modell steht im Rumpf."""

SPERRCODES = frozenset(
    {"content_blocked", "safety", "prohibited_content", "blocklist", "jailbreak"}
)
"""`error.code` einer HTTP-400-Antwort, die eine Sperre des Inhalts meldet (Spec 8.3)."""

EINGABE_TOKEN_MAX = 8192
"""Eingabegrenze je Anfrage (Modellseite); geschaetzt wird mit Zeichen/3 als obere Schranke."""

ZEICHEN_JE_TOKEN = 3

WARTEN_429 = (15, 45, 120, 240, 300)
"""Wartezeiten (s) nach einem 429, zusammen mehr als ein 10-Minuten-Fenster (Spec 8.3)."""

WARTEN_SERVER_S = 20
WARTEN_NETZ_S = 10
WARTEN_OHNE_AUDIO_S = 5
VERSUCHE_FEHLERANTWORT = 4
"""Fehlerantworten (500/503, Netz, Zeitueberschreitung, Antwort ohne Audio): Wartezeit je
Ursache, je Block hoechstens so viele Versuche (Spec 8.3)."""

DREI_429 = 3
"""Nach so vielen 429 in einem Lauf halbiert die Vergabe ihre Gleichzeitigkeit dauerhaft."""

STAND_ALLE = 10
"""Alle so viele Bloecke meldet das Sprechen einen Stand (LP-30)."""

AUDIO_TOKEN_JE_S = 25
TOKEN_TOLERANZ = 0.05
"""Audio-Token sind 25 je Sekunde (Modellseite); mehr Abweichung als 5 % gegen die gemessene
Dauer ist eine Warnung."""

_SATZENDE = re.compile(r"(?<=[.!?…])(\s+)")

MODALITAET_TEXT = "text"
MODALITAET_AUDIO = "audio"

_LOG = logging.getLogger("mkn_audio.gemini")

_PCM_TYPEN = frozenset({"audio/l16"})
_WAV_TYPEN = frozenset({"audio/wav", "audio/x-wav", "audio/wave"})

Transport = anfrage.Transport

Token = dict[str, int | None]


class _Abbruch(Exception):
    """Der Lauf hat sich beendet, waehrend dieser Faden noch Arbeit hatte (kein Fehler)."""


class _Wartend(SprecherFehler):
    """Eine Fehlerantwort mit eigener Wartezeit bis zum naechsten Versuch."""

    def __init__(self, meldung: str, warten_s: float) -> None:
        super().__init__(meldung, "Fehlerantwort")
        self.warten_s = warten_s


def _usd(betrag: float) -> str:
    """Dollarbetrag mit Komma; unter einem Dollar vier Stellen (Cent-Betraege sind sonst 0,00)."""
    return f"{betrag:.4f}".replace(".", ",") if betrag < 1 else f"{betrag:.2f}".replace(".", ",")


def teile_block(block: Block, n: int) -> tuple[Block, ...]:
    """Teilt `block` an Satzgrenzen in hoechstens `n` Teile gleicher Groessenordnung.

    Hat der Text weniger Saetze als `n`, gibt es weniger Teile; ein einzelner Satz bleibt
    ungeteilt (dann ist `(block,)` die Antwort). Die Teile tragen Kapitel, Rolle und Nummer des
    Blocks -- sie sind nur Sprecheinheiten, der Block bleibt die Einheit des Berichts.
    """
    teile = _SATZENDE.split(block.text)
    saetze, trenner = teile[0::2], teile[1::2]
    n = min(n, len(saetze))
    if n < 2:
        return (block,)
    gesamt = sum(len(satz) for satz in saetze)
    gruppen: list[list[int]] = [[]]
    erreicht = 0
    for i, satz in enumerate(saetze):
        gruppen[-1].append(i)
        erreicht += len(satz)
        uebrig_saetze = len(saetze) - i - 1
        uebrig_gruppen = n - len(gruppen)
        if uebrig_gruppen and (
            erreicht >= gesamt * len(gruppen) / n or uebrig_saetze == uebrig_gruppen
        ):
            gruppen.append([])
    texte = []
    for gruppe in gruppen:
        text = "".join(saetze[i] + (trenner[i] if i < len(trenner) else "") for i in gruppe)
        texte.append(text.strip())
    return tuple(
        Block(block.nr, block.stueck_nrs, text, block.kapitel, block.ansage) for text in texte
    )


def schaetze_kosten_usd(zeichen: int, konfig: WegKonfig) -> float | None:
    """Kosten fuer `zeichen` Text bei den Preisen der `WegKonfig`; ohne Preise `None`.

    Eingabe: Zeichen/4 Text-Token; Ausgabe: Zeichen bei 16 Zeichen/s und 25 Audio-Token/s.
    """
    pt, pa = konfig.preis_usd_je_1m_text_token, konfig.preis_usd_je_1m_audio_token
    if pt is None or pa is None:
        return None
    return zeichen / ERSATZ_ZEICHEN_JE_S * AUDIO_TOKEN_JE_S / 1e6 * pa + zeichen / 4 / 1e6 * pt


class _Schranke:
    """Die Vergabe: wie viele Anfragen gleichzeitig laufen duerfen und wann keine hinausgeht.

    Jede Anfrage nimmt ein Permit (`nimm`) und gibt es zurueck (`gib`). Ein 429 (`drossle`)
    gibt das Permit zurueck UND schliesst die Schranke: keine Anfrage geht hinaus, bis jede
    laufende Antwort angekommen ist und der Wartende `entdrossle` ruft. Nach `DREI_429` solchen
    Antworten gibt die Schranke dauerhaft nur noch `parallel // 2` Permits (mindestens 1) frei.
    """

    def __init__(self, parallel: int) -> None:
        self._bed = threading.Condition()
        self._parallel = max(1, parallel)
        self.zuruecksetzen()

    def zuruecksetzen(self) -> None:
        with self._bed:
            self._erlaubt = self._parallel
            self._aktiv = 0
            self._gedrosselt = 0
            self._anzahl_429 = 0

    def wecke(self) -> None:
        with self._bed:
            self._bed.notify_all()

    def nimm(self, abbruch: threading.Event) -> None:
        with self._bed:
            while self._gedrosselt or self._aktiv >= self._erlaubt:
                if abbruch.is_set():
                    raise _Abbruch
                self._bed.wait()
            if abbruch.is_set():
                raise _Abbruch
            self._aktiv += 1

    def gib(self) -> None:
        with self._bed:
            self._aktiv -= 1
            self._bed.notify_all()

    def drossle(self) -> bool:
        """Permit zurueck, Schranke zu, warten bis nichts mehr laeuft; wahr bei Halbierung."""
        with self._bed:
            self._aktiv -= 1
            self._gedrosselt += 1
            self._anzahl_429 += 1
            halbiert = False
            if self._anzahl_429 == DREI_429 and self._erlaubt > max(1, self._parallel // 2):
                self._erlaubt = max(1, self._parallel // 2)
                halbiert = True
            self._bed.notify_all()
            while self._aktiv > 0:
                self._bed.wait()
            return halbiert

    def entdrossle(self) -> None:
        with self._bed:
            self._gedrosselt -= 1
            self._bed.notify_all()

    @property
    def erlaubt(self) -> int:
        return self._erlaubt


def _tokens(nutzung: Any, feld: str, modalitaet: str) -> int | None:
    """Die Token einer Modalitaet aus `usage.<feld>`; fehlt etwas, `None` (nie 0)."""
    if not isinstance(nutzung, dict):
        return None
    for eintrag in nutzung.get(feld) or ():
        if isinstance(eintrag, dict) and eintrag.get("modality") == modalitaet:
            wert = eintrag.get("tokens")
            return wert if isinstance(wert, int) and not isinstance(wert, bool) else None
    return None


def _mime_teile(mime_type: str) -> tuple[str, dict[str, str]]:
    """`(Typ, Parameter)` ohne Gross-/Kleinschreibung, z. B. `audio/L16;codec=pcm;rate=24000`."""
    typ, *rest = (teil.strip() for teil in mime_type.lower().split(";"))
    parameter = {}
    for teil in rest:
        name, _, wert = teil.partition("=")
        parameter[name.strip()] = wert.strip()
    return typ, parameter


class SprecherGemini:
    """Gemini-TTS hinter der Sprecher-Schnittstelle (`sprecher.Sprecher`)."""

    weg = "gemini"

    def __init__(
        self,
        *,
        schluessel: str,
        konfig: WegKonfig,
        modell: str | None = None,
        transport: Transport | None = None,
        uhr: Callable[[], float] = time.monotonic,
        schlaf: Callable[[float], None] = time.sleep,
        arbeiter: Arbeiter | None = None,
        verbrauch: Callable[[str, int | None, int | None], None] | None = None,
    ) -> None:
        self._schluessel = schluessel
        self.konfig = konfig
        self.modell = modell or konfig.modell
        self._transport = transport
        self._uhr = uhr
        self._schlaf = schlaf
        self.arbeiter = arbeiter
        self._verbrauch_ruf = verbrauch
        self._schranke = _Schranke(konfig.parallel)
        self._nie = threading.Event()  # nie gesetzt: fuer Einzelaufrufe ausserhalb von sprich_viele
        self._ereignisse: queue.SimpleQueue[tuple[Any, ...]] = queue.SimpleQueue()
        self._sperre = threading.Lock()
        self._anfragen = 0
        self._tokens_text = 0
        self._tokens_audio = 0
        self._token_fehlen = False
        self._wiederholt = 0
        self._sperren_wiederholung = 0
        self._sperren_teilen = 0
        self._token_abweichung: list[str] = []

    # -- Buendeln ---------------------------------------------------------------------

    def buendle(self, stuecke: Sequence[Stueck]) -> tuple[Block, ...]:
        """Bloecke aus ganzen Stuecken bis `block_zeichen` (Spec 6.4).

        Nie ueber ein Kapitel, nie ueber einen Wechsel der Stimme (Ansage/Text) und nie mit einem
        Titel oder einer Zwischenueberschrift: die stehen allein, damit die Pause danach (Mastern)
        an einer Blockgrenze liegt. Absatzgrenzen werden Leerzeilen, Stuecke desselben Absatzes
        stehen mit einem Leerzeichen hintereinander. Ein Stueck ueber der Grenze wird allein ein
        Block. Die Eingabegrenze des Modells (Zeichen/3 gegen 8.192) deckelt `block_zeichen`.
        """
        grenze = min(self.konfig.block_zeichen, EINGABE_TOKEN_MAX * ZEICHEN_JE_TOKEN)
        bloecke: list[Block] = []
        offen: list[Stueck] = []
        text = ""

        def schliesse() -> None:
            nonlocal offen, text
            if offen:
                bloecke.append(
                    Block(
                        nr=offen[0].nr,
                        stueck_nrs=tuple(s.nr for s in offen),
                        text=text,
                        kapitel=offen[0].kapitel,
                        ansage=offen[0].ansage,
                    )
                )
            offen, text = [], ""

        for s in stuecke:
            trenn = "\n\n" if offen and s.absatz != offen[-1].absatz else " "
            if offen and not (
                s.art == "text"
                and offen[-1].art == "text"
                and s.kapitel == offen[0].kapitel
                and s.ansage == offen[0].ansage
                and len(text) + len(trenn) + len(s.text) <= grenze
            ):
                schliesse()
            text = text + trenn + s.text if offen else s.text
            offen.append(s)
            if s.art != "text":
                schliesse()
        schliesse()
        return tuple(bloecke)

    def ton_schluessel(self, block: Block, stimme: Stimme) -> str:
        """Blocktext, Weg, Modell, Zeilenname, Fassung, Google-Stimme, Stil und Sprache."""
        return fingerabdruck(
            "ton",
            block.text,
            "gemini",
            self.modell,
            stimme.name,
            stimme.version,
            stimme.stimme,
            stimme.stil,
            stimme.sprache,
        )[:16]

    # -- Anfrage und Antwort ------------------------------------------------------------

    def baue_rumpf(self, block: Block, stimme: Stimme) -> dict[str, Any]:
        """Der Rumpf der Anfrage, genau die Form aus Spec 8.1."""
        if not stimme.stimme:
            raise Mp4Fehler(f"Stimme '{stimme.name}' hat keinen Google-Stimmennamen (Weg gemini)")
        inhalt: dict[str, Any] = {"type": "text", "text": block.text}
        if stimme.stil:
            inhalt["annotations"] = [{"type": "speech_metadata", "style": stimme.stil}]
        return {
            "model": self.modell,
            "input": [{"type": "user_input", "content": [inhalt]}],
            "response_format": {"type": "audio"},
            "generation_config": {"speech_config": [{"voice": stimme.stimme}]},
        }

    def lies_antwort(self, antwort: dict[str, Any]) -> tuple[bytes, str, Token]:
        """`(Daten, mime_type, Token)` aus dem letzten Audio-Eintrag in `steps[].content[]`."""
        audio = None
        for schritt in antwort.get("steps") or ():
            for inhalt in (schritt.get("content") or ()) if isinstance(schritt, dict) else ():
                if isinstance(inhalt, dict) and inhalt.get("type") == "audio":
                    audio = inhalt
        if audio is None or not audio.get("data"):
            raise SprecherFehler("Antwort ohne Audio in steps[].content[]", "Fehlerantwort")
        try:
            daten = base64.b64decode(audio["data"], validate=True)
        except (binascii.Error, ValueError, TypeError) as fehler:
            raise SprecherFehler(
                f"Audio nicht als Base64 lesbar ({fehler})", "Fehlerantwort"
            ) from (fehler)
        nutzung = antwort.get("usage")
        token: Token = {
            "tokens_text": _tokens(nutzung, "input_tokens_by_modality", MODALITAET_TEXT),
            "tokens_audio": _tokens(nutzung, "output_tokens_by_modality", MODALITAET_AUDIO),
        }
        return daten, str(audio.get("mime_type") or ""), token

    def schreibe_ton(self, daten: bytes, mime_type: str, ziel: Path) -> float:
        """Schreibt den Ton als WAV im Paketmass (24 kHz, mono, PCM16) atomar; gibt die Dauer (s).

        Der MIME-Typ muss ein bekannter sein (PCM `audio/L16` oder WAV), sonst `Mp4Fehler`; ob es
        RIFF oder kopfloses PCM ist, sagen die ersten vier Bytes (Spec 8.1).
        """
        typ, parameter = _mime_teile(mime_type)
        if typ not in _PCM_TYPEN and typ not in _WAV_TYPEN:
            raise Mp4Fehler(
                f"Unbekannter Audio-Typ der Antwort: {mime_type!r} "
                "(erwartet audio/L16 oder audio/wav)"
            )
        ist_riff = daten[:4] == b"RIFF"
        if ist_riff != (typ in _WAV_TYPEN):
            _LOG.warning(
                "mime_type %r widerspricht den Bytes (%s): die Bytes gelten",
                mime_type,
                "RIFF" if ist_riff else "kopfloses PCM",
            )
        if not daten:
            raise SprecherFehler("Audio ohne Daten", "Fehlerantwort")
        with atomar(ziel) as tmp:
            if ist_riff:
                frames = self._schreibe_riff(daten, tmp)
            else:
                rate = self._pcm_rate(parameter, mime_type, typ in _WAV_TYPEN)
                frames = self._schreibe_pcm(daten, rate, tmp)
            if frames <= 0:  # vor dem Ersetzen: eine vorhandene Aufnahme bleibt
                raise SprecherFehler("Audio ohne Länge", "Fehlerantwort")
        return frames / SAMPLERATE

    @staticmethod
    def _pcm_rate(parameter: dict[str, str], mime_type: str, wav_typ: bool) -> int:
        """Die Rate aus dem Typ; ein WAV-Typ ohne Rate meint das Paketmass."""
        if wav_typ and "rate" not in parameter:
            return SAMPLERATE
        try:
            return int(parameter["rate"])
        except (KeyError, ValueError):
            raise Mp4Fehler(f"PCM-Antwort ohne lesbare Rate im Typ {mime_type!r}") from None

    @staticmethod
    def _konvertiere(daten: bytes, vor_eingabe: list[str], tmp: Path) -> int:
        """ffmpeg bringt `daten` auf das Paketmass; gibt die Frames der Ausgabe."""
        ffmpeg(
            *vor_eingabe,
            "-i",
            "-",
            "-ar",
            SAMPLERATE,
            "-ac",
            1,
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            tmp,
            zeit_s=120,
            eingabe=daten,
        )
        with wave.open(str(tmp), "rb") as w:
            return w.getnframes()

    def _schreibe_pcm(self, daten: bytes, rate: int, tmp: Path) -> int:
        if len(daten) % 2:
            raise SprecherFehler("PCM-Daten mit ungerader Bytezahl", "Fehlerantwort")
        if rate == SAMPLERATE:
            with wave.open(str(tmp), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SAMPLERATE)
                w.writeframes(daten)
            return len(daten) // 2
        return self._konvertiere(daten, ["-f", "s16le", "-ar", str(rate), "-ac", "1"], tmp)

    def _schreibe_riff(self, daten: bytes, tmp: Path) -> int:
        try:
            with wave.open(io.BytesIO(daten), "rb") as w:
                kopf = (w.getframerate(), w.getnchannels(), w.getsampwidth())
                frames = w.readframes(w.getnframes())
        except (wave.Error, EOFError) as fehler:
            raise SprecherFehler(
                f"WAV-Antwort nicht lesbar ({fehler})", "Fehlerantwort"
            ) from fehler
        if kopf == (SAMPLERATE, 1, 2):
            with wave.open(str(tmp), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SAMPLERATE)
                w.writeframes(frames)
            return len(frames) // 2
        return self._konvertiere(daten, [], tmp)

    # -- Sprechen -----------------------------------------------------------------------

    def _melde(self, text: str) -> None:
        self._ereignisse.put(("meldung", text))

    def _fehler_aus(self, fehler: anfrage.AnfrageFehler) -> SprecherFehler:
        """Die Klasse (Spec 8.3) zu einem Fehler der Anfrage."""
        status, code = fehler.status, (fehler.code or "").lower()
        if status == 400 and code in SPERRCODES:
            return SprecherFehler(f"Google sperrt den Inhalt: {fehler}", "Sperre")
        if status == 429:
            return SprecherFehler(f"Limit erreicht: {fehler}", "Limit")
        if status is None:
            return _Wartend(f"Keine Antwort von Google: {fehler}", WARTEN_NETZ_S)
        if status >= 500:
            return _Wartend(f"Fehlerantwort von Google: {fehler}", WARTEN_SERVER_S)
        return SprecherFehler(f"Zugang abgelehnt oder Anfrage falsch: {fehler}", "Zugang")

    def _anfrage(
        self, rumpf: dict[str, Any], abbruch: threading.Event
    ) -> tuple[dict[str, Any] | None, SprecherFehler | None]:
        """Eine Anfrage unter Permit: `(Antwort, None)` oder `(None, Fehler)`.

        Bei Klasse `Limit` ist die Schranke zu (der Aufrufer wartet und ruft `entdrossle`).
        """
        self._schranke.nimm(abbruch)
        freigegeben = False
        try:
            return (
                anfrage.sende(
                    URL,
                    rumpf,
                    {"x-goog-api-key": self._schluessel},
                    zeitgrenze=self.konfig.zeitgrenze_s,
                    transport=self._transport,
                ),
                None,
            )
        except anfrage.AnfrageFehler as ursache:
            fehler = self._fehler_aus(ursache)
            fehler.__cause__ = ursache
            if fehler.klasse == "Limit":
                freigegeben = True
                if self._schranke.drossle():
                    self._melde(
                        f"parallel-halbiert: nach {DREI_429} Limit-Antworten höchstens "
                        f"{self._schranke.erlaubt} Anfragen gleichzeitig"
                    )
            return None, fehler
        finally:
            if not freigegeben:
                self._schranke.gib()

    def _buche(self, token: Token) -> None:
        """Eine Antwort mit Audio ist verbraucht: zaehlen und dem Aufrufer melden."""
        with self._sperre:
            self._anfragen += 1
            if token.get("tokens_text") is None or token.get("tokens_audio") is None:
                self._token_fehlen = True
            self._tokens_text += token.get("tokens_text") or 0
            self._tokens_audio += token.get("tokens_audio") or 0
            if self._verbrauch_ruf is not None:
                self._verbrauch_ruf(
                    self.modell, token.get("tokens_text"), token.get("tokens_audio")
                )

    def _hole_ton(
        self, block: Block, stimme: Stimme, ziel: Path, abbruch: threading.Event
    ) -> Messwerte:
        """Spricht `block` nach `ziel`: Anfragen mit den Wartezeiten je Fehlerklasse (Spec 8.3).

        Eine Sperre kommt unveraendert als `SprecherFehler` heraus (die Leiter steht in `sprich`).
        """
        rumpf = self.baue_rumpf(block, stimme)
        anfragen = 0
        limit_stufe = 0
        fehlversuche = 0
        while True:
            antwort, fehler = self._anfrage(rumpf, abbruch)
            anfragen += 1
            if fehler is None:
                try:
                    daten, mime, token = self.lies_antwort(antwort or {})
                    self._buche(token)
                    dauer = self.schreibe_ton(daten, mime, ziel)
                    if dauer <= 0:
                        raise SprecherFehler("Audio ohne Länge", "Fehlerantwort")
                except SprecherFehler as ursache:
                    fehler = ursache
                else:
                    self._pruefe_token(block, token, dauer)
                    return {
                        "dauer": dauer,
                        "sprechrate": len(block.text) / dauer,
                        "versuche": anfragen,
                        "tokens_text": token.get("tokens_text"),
                        "tokens_audio": token.get("tokens_audio"),
                    }
            if fehler.klasse == "Limit":
                try:
                    if limit_stufe >= len(WARTEN_429):
                        raise fehler
                    warten = WARTEN_429[limit_stufe]
                    limit_stufe += 1
                    self._melde(
                        f"gedrosselt: Limit erreicht, warte {warten} s "
                        f"(Versuch {limit_stufe}/{len(WARTEN_429)})"
                    )
                    self._schlaf(warten)
                finally:
                    self._schranke.entdrossle()
                continue
            if fehler.klasse == "Fehlerantwort":
                fehlversuche += 1
                if fehlversuche >= VERSUCHE_FEHLERANTWORT:
                    raise fehler
                with self._sperre:
                    self._wiederholt += 1
                self._schlaf(getattr(fehler, "warten_s", WARTEN_OHNE_AUDIO_S))
                continue
            raise fehler

    def _pruefe_token(self, block: Block, token: Token, dauer: float) -> None:
        """Gegenprobe: Audio-Token / 25 muss der gemessenen Dauer auf +-5 % entsprechen."""
        audio = token.get("tokens_audio")
        if audio is None:
            return
        erwartet = audio / AUDIO_TOKEN_JE_S
        if abs(erwartet - dauer) > TOKEN_TOLERANZ * dauer:
            with self._sperre:
                self._token_abweichung.append(
                    f"Block {block.nr}: {audio} Audio-Token = {erwartet:.1f} s, "
                    f"gemessen {dauer:.1f} s"
                )

    def _sperre_fehler(self, block: Block, teil: Block) -> SprecherFehler:
        return SprecherFehler(
            f"Google sperrt den Text auch geteilt (Kapitel {block.kapitel + 1}, Block {block.nr}), "
            f"Stelle »{erste_woerter(teil.text)}«; selbes Modell, kein Ersatz",
            "Sperre",
        )

    def sprich(self, block: Block, stimme: Stimme, ziel: Path) -> Messwerte:
        """Spricht `block` nach `ziel` (WAV 24 kHz mono PCM16, atomar).

        Eine Sperre (nicht deterministisch) wird einmal wiederholt, dann an Satzgrenzen in 2,
        schliesslich in 4 Teile geteilt (immer das selbe Modell); bleibt auch ein Einzelsatz
        gesperrt, ist das ein `SprecherFehler` der Klasse `Sperre` mit der Stelle.
        """
        return self._sprich(block, stimme, ziel, self._nie)

    def _sprich(
        self, block: Block, stimme: Stimme, ziel: Path, abbruch: threading.Event
    ) -> Messwerte:
        try:
            return self._hole_ton(block, stimme, ziel, abbruch)
        except SprecherFehler as fehler:
            if fehler.klasse != "Sperre":
                raise
        try:
            messwerte = self._hole_ton(block, stimme, ziel, abbruch)
        except SprecherFehler as fehler:
            if fehler.klasse != "Sperre":
                raise
        else:
            with self._sperre:
                self._sperren_wiederholung += 1
            return messwerte
        return self._sprich_geteilt(block, stimme, ziel, abbruch)

    def _sprich_geteilt(
        self, block: Block, stimme: Stimme, ziel: Path, abbruch: threading.Event
    ) -> Messwerte:
        """Zwei Teile, ein weiterhin gesperrter Teil nochmals in zwei; dann zusammenlegen.

        Die Teile liegen in einem Arbeitsordner neben dem Ziel, der mit dem Zusammenlegen oder
        dem Abbruch verschwindet: ihre inhaltsadressierten Namen koennten sonst die Aufnahme
        eines anderen Blocks gleichen Textes treffen.
        """
        haelften = teile_block(block, 2)
        if len(haelften) < 2:
            raise self._sperre_fehler(block, block)
        gesprochen: list[tuple[Path, Messwerte]] = []
        with temp_ordner(ziel.parent) as arbeit:

            def teil_ton(teil: Block) -> Messwerte:
                wav = Path(arbeit) / f"{self.ton_schluessel(teil, stimme)}.wav"
                messwerte = self._hole_ton(teil, stimme, wav, abbruch)
                gesprochen.append((wav, messwerte))
                return messwerte

            for haelfte in haelften:
                try:
                    teil_ton(haelfte)
                except SprecherFehler as fehler:
                    if fehler.klasse != "Sperre":
                        raise
                    viertel = teile_block(haelfte, 2)
                    if len(viertel) < 2:
                        raise self._sperre_fehler(block, haelfte) from fehler
                    for stueck in viertel:
                        try:
                            teil_ton(stueck)
                        except SprecherFehler as tief:
                            if tief.klasse != "Sperre":
                                raise
                            raise self._sperre_fehler(block, stueck) from tief
            pause = stimme.pause_stueck
            with atomar(ziel) as tmp, wave.open(str(tmp), "wb") as aus:
                aus.setnchannels(1)
                aus.setsampwidth(2)
                aus.setframerate(SAMPLERATE)
                for i, (wav, _) in enumerate(gesprochen):
                    if i:
                        aus.writeframes(b"\x00\x00" * round(pause * SAMPLERATE))
                    with wave.open(str(wav), "rb") as ein:
                        aus.writeframes(ein.readframes(ein.getnframes()))
        with self._sperre:
            self._sperren_teilen += 1
        dauer = sum(m["dauer"] for _, m in gesprochen) + pause * (len(gesprochen) - 1)
        texte = [m["tokens_text"] for _, m in gesprochen]
        audios = [m["tokens_audio"] for _, m in gesprochen]
        return {
            "dauer": dauer,
            "sprechrate": len(block.text) / dauer,
            "versuche": sum(m["versuche"] for _, m in gesprochen),
            "tokens_text": None if None in texte else sum(texte),
            "tokens_audio": None if None in audios else sum(audios),
        }

    def sprich_viele(
        self,
        auftraege: Sequence[Auftrag],
        *,
        soll_weichen: Callable[[], bool],
        fortschritt: Callable[[str], None],
    ) -> Iterator[tuple[Block, Messwerte | SprecherFehler]]:
        """Spricht die Bloecke mit hoechstens `parallel` Anfragen gleichzeitig (Spec 8.5).

        Die Reihenfolge der Ergebnisse ist die der Fertigstellung. Vor jeder neuen Vergabe fragt
        `soll_weichen`; wahr beendet die Vergabe (laufende Bloecke werden zu Ende gesprochen).
        Eine Klasse ausser `Fehlerantwort` (Sperre, Limit, Zugang) beendet die Vergabe ebenfalls:
        jeder weitere Block scheiterte gleich. Jede Meldung geht durch `fortschritt` im Faden des
        Aufrufers, nie aus einem Arbeitsfaden.
        """
        vorrat: deque[Auftrag] = deque(auftraege)
        gesamt = len(vorrat)
        abbruch = threading.Event()
        self._schranke.zuruecksetzen()
        while not self._ereignisse.empty():
            self._ereignisse.get_nowait()
        vergabe = threading.Lock()
        beendet = False

        def naechster() -> Auftrag | None:
            nonlocal beendet
            with vergabe:
                if beendet or abbruch.is_set() or not vorrat:
                    return None
                if soll_weichen():
                    beendet = True
                    return None
                return vorrat.popleft()

        def faden() -> None:
            try:
                while (auftrag := naechster()) is not None:
                    try:
                        ergebnis: Messwerte | SprecherFehler = self._sprich(
                            auftrag.block, auftrag.stimme, auftrag.ziel, abbruch
                        )
                    except SprecherFehler as fehler:
                        ergebnis = fehler
                        if fehler.klasse != "Fehlerantwort":
                            abbruch.set()  # keine neue Vergabe: der Lauf bricht ab
                            self._schranke.wecke()
                    self._ereignisse.put(("ergebnis", auftrag.block, ergebnis))
            except _Abbruch:
                pass
            except BaseException as ausnahme:  # nie leise sterben: der Aufrufer sieht es
                abbruch.set()
                self._schranke.wecke()
                self._ereignisse.put(("ausnahme", ausnahme))
            finally:
                self._ereignisse.put(("ende",))

        faeden = [
            threading.Thread(target=faden, name=f"gemini-{i}", daemon=True)
            for i in range(min(self.konfig.parallel, gesamt))
        ]
        for f in faeden:
            f.start()
        offen = len(faeden)
        erledigt = 0
        try:
            while offen:
                ereignis = self._ereignisse.get()
                if ereignis[0] == "meldung":
                    fortschritt(ereignis[1])
                elif ereignis[0] == "ausnahme":
                    raise ereignis[1]
                elif ereignis[0] == "ende":
                    offen -= 1
                else:
                    erledigt += 1
                    yield ereignis[1], ereignis[2]
                    if erledigt % STAND_ALLE == 0:
                        fortschritt(f"Gemini: {erledigt}/{gesamt} Blöcke gesprochen")
        finally:
            abbruch.set()
            self._schranke.wecke()

    def startprobe(self, stimmen: Sequence[Stimme]) -> None:
        """Spricht den Probesatz je Stimme; ein Fehler (Zugang, Modell, Stimmenname) bricht ab."""
        with tempfile.TemporaryDirectory(prefix="probe-") as tmp:
            for stimme in stimmen:
                self.sprich(Block(0, (), PROBE_SATZ, 0, False), stimme, Path(tmp) / "probe.wav")

    def kann_hoeren(self) -> bool:
        return self.arbeiter is not None

    # -- Verbrauch, Kosten, Ausweis -------------------------------------------------------

    def verbrauch(self) -> Verbrauch:
        """Antworten mit Audio dieses Sprechers; Token `None`, wenn eine sie nicht meldete."""
        with self._sperre:
            if self._anfragen and self._token_fehlen:
                return Verbrauch(self._anfragen, None, None)
            return Verbrauch(self._anfragen, self._tokens_text, self._tokens_audio)

    def _kosten(self, verbrauch: Verbrauch) -> str:
        k = self.konfig
        if k.preis_usd_je_1m_text_token is None or k.preis_usd_je_1m_audio_token is None:
            return "Preise nicht konfiguriert"
        if verbrauch.tokens_text is None or verbrauch.tokens_audio is None:
            return "nicht berechenbar (Token nicht gemeldet)"
        usd = (
            verbrauch.tokens_text * k.preis_usd_je_1m_text_token
            + verbrauch.tokens_audio * k.preis_usd_je_1m_audio_token
        ) / 1e6
        stand = k.preisstand.isoformat() if k.preisstand else "Preisstand unbekannt"
        return f"{_usd(usd)} USD (Preisstand {stand})"

    def schaetzung(self, zeichen: int) -> str | None:
        """Die Kostenschaetzung vor dem Sprechen (Zeichen offener Bloecke)."""
        usd = schaetze_kosten_usd(zeichen, self.konfig)
        if usd is None:
            return f"Kosten-Schätzung: Preise nicht konfiguriert ({zeichen} Zeichen, {self.modell})"
        return f"Kosten-Schätzung: etwa {_usd(usd)} USD für {zeichen} Zeichen ({self.modell})"

    def ausweis(self) -> Ausweis:
        """Modell, Token, Kosten, Sperren und Wiederholungen dieses Sprechers fuer den Bericht."""
        v = self.verbrauch()
        with self._sperre:
            wdh, teilen, wiederholt = (
                self._sperren_wiederholung,
                self._sperren_teilen,
                self._wiederholt,
            )
            abweichungen = tuple(self._token_abweichung)
        if v.tokens_text is None or v.tokens_audio is None:
            token = "Token nicht gemeldet"
        else:
            token = f"Token: {v.tokens_text} Text, {v.tokens_audio} Audio"
        loesungen = []
        if wdh:
            loesungen.append("durch Wiederholung" if not teilen else f"{wdh} durch Wiederholung")
        if teilen:
            loesungen.append("durch Teilen" if not wdh else f"{teilen} durch Teilen")
        sperren = f"Sperren: {wdh + teilen}" + (
            f" ({', '.join(loesungen)} gelöst)" if loesungen else ""
        )
        zeilen = (
            f"Modell: {self.modell}",
            f"Anfragen mit Audio: {v.anfragen}",
            token,
            f"Kosten: {self._kosten(v)}",
            sperren,
            f"Wiederholungen nach Fehlerantwort: {wiederholt}",
        )
        warnungen = ()
        if abweichungen:
            warnungen = (
                f"Token gegen Dauer: {len(abweichungen)} Block/Blöcke weichen um mehr als 5 % "
                f"von 25 Audio-Token je Sekunde ab (zuerst {abweichungen[0]})",
            )
        return Ausweis(zeilen, warnungen)
