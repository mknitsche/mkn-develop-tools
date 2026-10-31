"""Der Lauf: von der Quelle zur Hoerdatei, Stufe fuer Stufe, fortsetzbar.

Die Stufen (Spec 6, § 18): Lesen, Regie, Hoertext, Gliedern, Buendeln, Sprechen, Pruefen,
Mastern, Verpacken, Bericht. Dieses Modul verbindet nur; jede Stufe steht in ihrem eigenen
Modul. Was es selbst entscheidet, ist die Reihenfolge und -- wichtiger -- **was nicht neu
gerechnet werden muss** (`arbeitsverzeichnis`).

**Wiederaufnahme ohne Doppelrechnung.** Sprechen ist die teure Stufe, und sie ist
blockweise (ein Block ist lokal ein Stueck, bei Gemini mehrere Saetze): jede Aufnahme wird
gleich nach dem Sprechen mit ihren Messwerten abgelegt.
Bricht der Lauf ab (Neustart, Strom, `Gewichen`), findet der naechste jede fertige
Aufnahme wieder und spricht nur den Rest. Eine halbe Aufnahme gilt nie als fertig: dafuer
braucht es WAV *und* Messwerte, und beide entstehen atomar.

**Weichen.** Ein langes Buch macht einer kurzen Quelle Platz (Spec 9). `soll_weichen`
wird vor jedem noch zu sprechenden Block gefragt (der Sprecher fragt, der Lauf erkennt die
unvollstaendige Folge); `Gewichen` ist kein Fehler des Laufs,
sondern seine Unterbrechung -- der Aufrufer legt ihn zurueck in die Warteschlange.

**Bewusste Entscheidungen**

- **Der Weg ist ein `Sprecher`** (`sprecher.py`): er buendelt, nennt den Ton-Schluessel,
  spricht und startet die Probe. Der Lauf kennt keine Engine; Stimmen eines anderen Wegs sind
  ein Bedienfehler.
- Die *Sprache* der Aufnahme bestimmt die Stimme (`stimme.sprache`), nicht die Quelle.
  Widerspricht ihr die Quelle, steht das im Bericht; erkannt wird nichts.
- Die Kapitelmarken der M4B tragen die Titel der *Quelle*, nicht den ausgeschriebenen
  Hoertext: im Player soll "Kapitel 3" stehen, nicht "Kapitel drei".
- Das Cover wird VOR dem Sprechen geprueft. Ein kaputtes Cover wuerde sonst erst beim
  Verpacken scheitern, nach Stunden Sprechen; es kostet das Hoerstueck nichts, also wird
  es mit Warnung weggelassen.
- Die Stimmqualitaet im Bericht (Tonlage, Melodie) misst `miss` an einem Ausschnitt des
  ersten Kapitels mit Fliesstext der Text-Stimme (nicht der Einleitung, die die Ansage-Stimme
  spricht; dasselbe Kapitel liefert das Sprechtempo), nicht an dessen ganzer Laenge: die
  Messung braucht Minuten je Stunde Ton, und der Bericht ist es nicht wert, einen Lauf am
  Ende zu verzoegern oder an der Zeitgrenze des Arbeiters scheitern zu lassen.
- Zeitstempel auffaelliger Stellen sind aus den Dauern der Stuecke auf die fertige
  Kapitellaenge umgerechnet: auf wenige Sekunden genau, nicht auf das Bild.
- Ohne Sprachmodell wird der Hoertext nur nach Regeln aufbereitet; das steht im Bericht.
- **Die Regie** entscheidet zwischen Lesen und Hoertext, was gesprochen wird und
  was nur Beiwerk ist, und schreibt Vorspann, Ueberleitungen und Abspann. Diese Ansagen
  (und die Titel) spricht die Ansage-Stimme `ansage` (Rolle der Tabelle), mit deren Klang
  und Tempo gemastert -- in einem Kapitel mit Ueberleitung
  jeder Lauf gleicher Stimme fuer sich, danach aneinandergefuegt. Die Kapitelmarken
  heissen "Einleitung" und "Abspann", und die Zaehlung "Kapitel N" kennt sie nicht.
  Wie weit die Regie eingreift, bestimmt `regie_modus`: ein EPUB bekommt `buch` (nur
  Unhoerbares entfaellt), alles andere `voll`; `aus` liest unveraendert.
- **Ein Ausfall kostet einen Block, nicht das Buch.** Scheitert das Sprechen eines
  Blocks (lokal: Tod, Zeitgrenze, Fehlerantwort), gibt es EINEN neuen Versuch -- der Client
  startet nach Tod und Zeitgrenze ohnehin frisch (Spec 7). Scheitert auch der, steht fuer
  diesen Block Stille der erwarteten Dauer im Hoerstueck, und der Bericht nennt es als
  Befund. Die Stille ist eine WAV ohne Messwerte und gilt deshalb nie als gesprochen: der
  erneute Lauf derselben Quelle versucht diesen Block noch einmal, und die Pruefung
  rechnet dann neu (die Menge der ersetzten Bloecke steht im Fingerabdruck). Das gilt nur,
  solange das Arbeitsverzeichnis der Quelle noch da ist. Gift-Block und kaputter Arbeiter
  sehen sich anfangs gleich; mehr als `MAX_AUSFAELLE_FOLGE` Bloecke hintereinander sind
  kein Gift-Block mehr, dann bricht der Lauf laut ab (der Dienst meldet einen Defekt).
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
import wave
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Literal

import pymupdf

from mkn_audio import __version__
from mkn_audio.arbeiter_client import ArbeiterFehler
from mkn_audio.arbeitsverzeichnis import (
    Arbeitsverzeichnis,
    dokument_aus_json,
    dokument_zu_json,
    fingerabdruck,
    stuecke_aus_json,
    stuecke_zu_json,
)
from mkn_audio.bericht import schreibe_bericht
from mkn_audio.gliedern import gliedere, waehle
from mkn_audio.hoertext import hoertext
from mkn_audio.konfig import Konfig
from mkn_audio.lesen import KeinText, ist_bildquelle, lies
from mkn_audio.lesen.bild import lade_bild
from mkn_audio.manifest import als_manifest, schreibe_manifest
from mkn_audio.mastern import (
    SAMPLERATE,
    _pause_nach,
    atomar,
    ffmpeg,
    kapitel_ton,
    master,
    schreibe_stille,
    temp_ordner,
    wav_info,
    zeitgrenze,
)
from mkn_audio.pruefen import (
    ZEICHEN_JE_SEKUNDE,
    lies_kapitelmarken,
    pruefe,
    pruefe_kapitelmarken,
    sprechraten_median,
)
from mkn_audio.regie import WARNUNG_AUS, inszeniere, pruefe_modus, verstehe
from mkn_audio.sprecher import (
    ERSATZ_ZEICHEN_JE_S,
    Auftrag,
    Block,
    Sprecher,
    SprecherFehler,
    Verbrauch,
)
from mkn_audio.stimmen import WEGE, Stimme, lade_tabelle
from mkn_audio.typen import QUELL_ARTEN, Dokument, Kapitel, Mp4Fehler, Textmodell
from mkn_audio.verpacken import _cover_datei, ausgabe_name, m4b, mp3
from mkn_audio.vertraulich import Hinweis, RueckfrageNoetig, pruefe_vertraulich


def _laeufe(
    bloecke: list[Block], sprecher: Callable[[Block], Stimme]
) -> list[tuple[Stimme, list[Block]]]:
    """Die Bloecke eines Kapitels in Laeufe gleicher Stimme, in Reihenfolge."""
    laeufe: list[tuple[Stimme, list[Block]]] = []
    for block in bloecke:
        wer = sprecher(block)
        if laeufe and laeufe[-1][0] == wer:
            laeufe[-1][1].append(block)
        else:
            laeufe.append((wer, [block]))
    return laeufe


def _fuege_zusammen(teile: list[Path], pausen: list[float], ziel: Path) -> None:
    """Haengt gemasterte Teile (PCM16, mono, 24 kHz) mit den Pausen dazwischen aneinander."""
    with atomar(ziel) as tmp, wave.open(str(tmp), "wb") as aus:
        aus.setnchannels(1)
        aus.setsampwidth(2)
        aus.setframerate(SAMPLERATE)
        for i, teil in enumerate(teile):
            if i:
                schreibe_stille(aus, pausen[i - 1])
            with wave.open(str(teil), "rb") as ein:
                aus.writeframes(ein.readframes(ein.getnframes()))


def _code_stand(wurzel: Path, teile: tuple[str, ...]) -> str:
    """Hash ueber den Code einer Textstufe (Dateien oder Ordner unter `wurzel`, .py und .toml).

    Die Textstufen haengen daran, nicht nur an der Version: ein Fix im Leser wirkt sonst erst
    nach einem Versionssprung (Kapitel-1-Abnahme 24.10.). Je Stufe nur ihr eigener Code: eine
    Aenderung an Verpacken oder Kommandozeile darf Lesen und Regie nicht neu ausloesen -- die
    Regie kostet ein Sprachmodell, und neue Ansagen verschieben Stueckgrenzen und damit Ton.
    """
    h = hashlib.sha256()
    for teil in teile:
        pfad = wurzel / teil
        dateien = sorted(pfad.rglob("*")) if pfad.is_dir() else [pfad]
        for datei in dateien:
            if datei.suffix in {".py", ".toml"}:
                h.update(datei.relative_to(wurzel).as_posix().encode())
                h.update(datei.read_bytes())
    return h.hexdigest()[:16]


_PAKET = Path(__file__).parent
#: Code-Stand je Textstufe, einmal beim Laden berechnet (`_code_stand`); `typen.py` traegt das
#: Datenmodell aller Stufen. Die Stufen bauen aufeinander auf: wer Lesen aendert, rechnet alles neu.
STAND_LESEN = _code_stand(_PAKET, ("lesen", "sprache.py", "typen.py", "_toml.py"))
STAND_REGIE = _code_stand(_PAKET, ("regie.py", "manifest.py", "hoertext"))
STAND_HOERTEXT = _code_stand(_PAKET, ("hoertext",))
STAND_GLIEDERN = _code_stand(_PAKET, ("gliedern.py",))

STICHPROBE = 0.05
"""Anteil der unauffaelligen Stuecke, die trotzdem gehoert werden (Spec 6, Punkt 6)."""

MAX_ZEICHEN = 400
"""Hoechstlaenge eines Stuecks (Prototyp, Spec 6 Punkt 5)."""

MESS_AUSSCHNITT_S = 300
"""So viele Sekunden vom Anfang des ersten Kapitels misst der Bericht."""

FORTSCHRITT_ALLE = 20
"""Alle so viele Bloecke meldet das Sprechen einen Stand."""

MAX_AUSFAELLE_FOLGE = 3
"""So viele Bloecke hintereinander darf das Sprechen scheitern (lokal je zwei Versuche), bevor
der Lauf es nicht mehr fuer Gift-Bloecke, sondern fuer einen kaputten Sprecher haelt."""

LAUTE_KLASSEN = frozenset({"Sperre", "Limit", "Zugang"})
"""Fehlerklassen des Sprechers, bei denen der Lauf sofort laut abbricht, statt den Block durch
Stille zu ersetzen: der Inhalt wird gesperrt, das Konto ist am Limit, der Zugang ist falsch."""

_WORT = re.compile(r"\w+")


class Gewichen(Mp4Fehler):
    """Der Lauf hat an einer Stueckgrenze Platz gemacht (`soll_weichen()` war wahr).

    Der Zustand ist im Arbeitsverzeichnis gesichert; derselbe Aufruf setzt fort.
    """


@dataclass(frozen=True)
class Ergebnis:
    """Was ein Lauf geliefert hat.

    `warnungen` sind alle Hinweise des Berichts (Quelle, Hoertext, Lauf), ohne Doppelte.
    `dauer_s` ist die Spieldauer des Hoerstuecks. `weg` und `modell` nennen, womit
    gesprochen wurde; `verbrauch` zaehlt die Anfragen eines bezahlten Wegs (nur dieser Aufruf:
    Treffer im Zwischenstand kosten nichts), sonst `None`. `datenschutz` sind die Hinweise vor dem
    Versand an Google (leer, wo nichts gesendet wird oder nichts auffiel).
    """

    dateien: tuple[Path, ...]
    bericht: Path
    warnungen: tuple[str, ...]
    dauer_s: float
    weg: str
    modell: str
    verbrauch: Verbrauch | None
    datenschutz: tuple[Hinweis, ...] = ()


def _mit_titel(dok: Dokument, quelle: Path) -> Dokument:
    """Ein leerer Titel wird der Dateiname ohne Endung (NFC) -- der Name der Ausgabe."""
    if dok.titel.strip():
        return dok
    return replace(dok, titel=unicodedata.normalize("NFC", quelle.stem))


def _lade_aussprache(quelle: Path) -> dict[str, str] | None:
    """`aussprache.json` neben der Quelle: `{"Wort": "Ersatz"}`; ohne Datei keine Tabelle."""
    pfad = quelle.with_name("aussprache.json")
    if not pfad.is_file():
        return None
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError) as fehler:
        raise Mp4Fehler(f"aussprache.json unlesbar: {pfad} ({fehler})") from fehler
    if not isinstance(daten, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in daten.items()
    ):
        raise Mp4Fehler(f'aussprache.json muss ein Objekt {{"Wort": "Ersatz"}} sein: {pfad}')
    return daten


def _pruefe_cover(dok: Dokument, wurzel: Path) -> tuple[Dokument, str | None]:
    """Prueft, ob das Cover sich einbetten laesst; sonst Dokument ohne Cover und Warnung.

    Dieselbe Aufbereitung wie beim Verpacken (`_cover_datei`) und danach ein echtes
    Dekodieren: ein Bildkopf allein sagt nicht, dass ffmpeg das Bild lesen kann.
    """
    if dok.cover is None:
        return dok, None
    try:
        with temp_ordner(wurzel) as werk:
            datei = _cover_datei(dok.cover, Path(werk))
            assert datei is not None
            ffmpeg("-i", datei, "-frames:v", 1, "-f", "null", "-", zeit_s=60)
    except Mp4Fehler as fehler:
        grund = str(fehler).splitlines()[0][:200]
        return replace(dok, cover=None), f"Cover unbrauchbar, ohne Cover verpackt ({grund})"
    return dok, None


def _ausschnitt(wav: Path, ziel: Path, sekunden: float) -> Path:
    """Die ersten `sekunden` einer WAV (PCM, ohne numpy)."""
    with wave.open(str(wav), "rb") as ein:
        frames = min(ein.getnframes(), round(sekunden * ein.getframerate()))
        daten = ein.readframes(frames)
        with atomar(ziel) as tmp, wave.open(str(tmp), "wb") as aus:
            aus.setparams(ein.getparams())
            aus.writeframes(daten)
    return ziel


def _stille_statt_ton(block: Block, ziel: Path, zeichen_je_s: float = ZEICHEN_JE_SEKUNDE) -> dict:
    """Legt Stille der erwarteten Dauer nach `ziel` und gibt Messwerte dafuer.

    Die Messwerte gehen NICHT ins Arbeitsverzeichnis (`schreibe_ton`): ohne sie gilt die
    Aufnahme dort als nicht gesprochen. Die Sprechrate ist der Erwartungswert der
    Pruefung, damit das Tempo-Angleichen die Stille nicht als Ausreisser behandelt.
    """
    dauer = len(block.text) / zeichen_je_s
    with atomar(ziel) as tmp, wave.open(str(tmp), "wb") as aus:
        aus.setnchannels(1)
        aus.setsampwidth(2)
        aus.setframerate(SAMPLERATE)
        schreibe_stille(aus, dauer)
    return {"dauer": dauer, "sprechrate": zeichen_je_s, "versuche": 0, "zu_kurz": False}


ANSAGE_KAPITEL = {"vorspann": "Einleitung", "abspann": "Abspann"}
"""Wie ein Kapitel nur aus Ansagen in der Kapitelliste des Players heisst (nach seiner Art)."""


def _kapitelname(dok: Dokument, k: int) -> str:
    """Der Name eines Kapitels in der Kapitelliste des Players.

    Titel der Quelle; ein Ansage-Kapitel der Regie (kein Titel, Art `vorspann`/`abspann`)
    heisst `ANSAGE_KAPITEL` -- die Kopfseite "Einleitung", weil ein Hoerer sie so kennt und
    ueberspringen kann, der Schluss "Abspann"; sonst "Kapitel N", wobei die Ansage-Kapitel
    nicht mitzaehlen -- sie stehen nicht in der Quelle, und "Kapitel 2" soll das zweite
    Kapitel des Buches sein.
    """
    kapitel = dok.kapitel[k]
    if kapitel.titel.strip():
        return kapitel.titel.strip()
    if _nur_ansagen(kapitel):
        return ANSAGE_KAPITEL[kapitel.arten[0]]
    davor = sum(1 for v in dok.kapitel[:k] if _nur_ansagen(v))
    return f"Kapitel {k + 1 - davor}"


def _nur_ansagen(kapitel: Kapitel) -> bool:
    return (
        bool(kapitel.arten)
        and not kapitel.titel.strip()
        and not any(art in QUELL_ARTEN for art in kapitel.arten)
    )


def _eindeutig(*listen: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(w for liste in listen for w in liste))


def _schreibe_manifest(verz, dok, rollenbild, *, quelle: Path, bildquelle: bool) -> None:
    """Legt das Gelesene im gemeinsamen Bereichs-Manifest neben die Stufen ab.

    Das Manifest ist die gemeinsame Schnittstelle "Quelle erschliessen" (Format: README); es
    zeigt ALLES mit Art, das Weglassen ist Sache der Regie. Was der Leser
    schon vor den Rollen entfernt hat (Kopf- und Fusszeilen, Webadressen ...), steht als Rest
    in der Text-Bilanz -- mit seiner Warnung, weil der Leser die Woerter nicht zaehlt; ein
    leerer Rest wuerde sonst Vollstaendigkeit behaupten, die es nicht gibt.
    """
    herkunft = (
        "bildmodell"
        if bildquelle
        else ("ocr" if any("Texterkennung" in w for w in dok.warnungen) else "textschicht")
    )
    manifest = als_manifest(
        dok,
        rollenbild,
        quelle=quelle,
        sha256=verz.quelle_hash,
        herkunft=herkunft,
        leser="mkn-audio",
    )
    entfernt = [w for w in dok.warnungen if w.startswith("weggelassen:")]
    manifest["text_bilanz"]["rest"].extend({"grund": w, "woerter": None} for w in entfernt)
    schreibe_manifest(manifest, verz.wurzel / "manifest.json")


def _dokumentart(wurzel: Path) -> str | None:
    """Die Dokumentart der Regie aus dem Manifest des Arbeitsverzeichnisses, sonst `None`."""
    pfad = wurzel / "manifest.json"
    if not pfad.is_file():
        return None
    try:
        art = json.loads(pfad.read_text(encoding="utf-8"))["quelle"]["dokumentart"]
    except (OSError, ValueError, KeyError, TypeError) as fehler:
        raise Mp4Fehler(f"manifest.json unlesbar: {pfad} ({fehler})") from fehler
    return art or None


def _seitenzahl(quelle: Path) -> int | None:
    """Die Seitenzahl eines PDFs, sonst `None` (andere Formate haben keine feste Seitenzahl)."""
    if quelle.suffix.lower() != ".pdf":
        return None
    with pymupdf.open(str(quelle)) as pdf:
        return pdf.page_count


def _fp_lesen(quelle: Path, verz: Arbeitsverzeichnis, textmodell: Textmodell | None) -> str:
    """Fingerabdruck der Lesestufe. Der Dateiname gehoert hinein: jeder Leser nimmt ihn als
    Titel, wenn die Quelle keinen nennt -- sonst bekaeme gleicher Inhalt unter neuem Namen den
    alten Titel."""
    return fingerabdruck(
        "lesen",
        verz.quelle_hash,
        unicodedata.normalize("NFC", quelle.name),
        textmodell is not None,
        __version__,
        STAND_LESEN,
    )


def lies_mit_zwischenstand(
    quelle: Path,
    verz: Arbeitsverzeichnis,
    textmodell: Textmodell | None,
    fortschritt: Callable[[str], None] = lambda _: None,
) -> Dokument:
    """Liest `quelle` oder nimmt den Zwischenstand `lesetext` des Arbeitsverzeichnisses.

    Der eine Weg zum gelesenen Dokument: `konvertiere` und die Kommandozeile (Sprachwahl vor dem
    Lauf) rufen ihn beide, damit ein Bildmodell eine Quelle nie zweimal liest.
    """
    fp_lesen = _fp_lesen(quelle, verz, textmodell)
    gespeichert = verz.lies_stufe("lesetext", fp_lesen)
    if gespeichert is None:
        fortschritt("Lesen")
        gelesen = lies(quelle, textmodell=textmodell)
        verz.schreibe_stufe("lesetext", fp_lesen, dokument_zu_json(gelesen))
        return gelesen
    fortschritt("Lesen (vorhanden)")
    return dokument_aus_json(gespeichert)


def konvertiere(
    quelle: Path,
    ziel: Path,
    stimme: Stimme,
    *,
    sprecher: Sprecher,
    ansage: Stimme,
    textmodell: Textmodell | None,
    konfig: Konfig,
    auswahl: str | None = None,
    format: Literal["m4b", "mp3"] = "m4b",
    soll_weichen: Callable[[], bool] = lambda: False,
    fortschritt: Callable[[str], None] = lambda _: None,
    heute: date | None = None,
    regie_modus: Literal["voll", "buch", "aus"] | None = None,
    cloud_ok: bool | Callable[[tuple[Hinweis, ...]], bool] = False,
) -> Ergebnis:
    """Macht aus `quelle` eine Hoerdatei (oder MP3 je Kapitel) in `ziel`.

    `stimme` spricht den Fliesstext, `ansage` Titel, Zwischenueberschriften, Vorspann,
    Ueberleitungen und Abspann (dieselbe Stimme ist erlaubt); beide gehoeren dem Weg des
    `sprecher`s, sonst ist es ein Bedienfehler.
    `heute` ist das Datum im Dateinamen; ohne Angabe fragt der Lauf die Uhr (`date.today()`).
    `regie_modus` (siehe `regie`): ohne Angabe `buch` fuer ein EPUB, sonst `voll`. Ein Buch
    besteht aus seinem Text, und eine falsch erkannte Rolle darf darin nichts Hoerbares
    kosten; Zusammenfassungen, Artikel und Programmseiten bestehen dagegen zu grossen Teilen
    aus Beiwerk, das die Regie weglassen soll.
    `cloud_ok` gilt nur fuer Wege, die Text ins Netz senden (gemini): gibt es Datenschutz-Hinweise
    (`vertraulich`), entscheidet `cloud_ok` -- ein Wahrheitswert oder eine Funktion, die die
    Hinweise bekommt (die Kommandozeile fragt). Ohne Freigabe bricht der Lauf mit
    `RueckfrageNoetig` ab, bevor die erste Anfrage hinausgeht.
    Fehler brechen laut ab; `KeinText` heisst: die Quelle ist unbrauchbar (kein Defekt der
    Umgebung), `Gewichen`: der Lauf wurde unterbrochen und setzt mit demselben Aufruf fort.
    """
    if format not in ("m4b", "mp3"):
        raise Mp4Fehler(f"unbekanntes Format '{format}' (moeglich: m4b, mp3)")
    if regie_modus is not None:
        pruefe_modus(regie_modus)
    quelle = Path(quelle)
    modus = regie_modus or ("buch" if quelle.suffix.lower() == ".epub" else "voll")
    ziel = Path(ziel)
    datum = (heute or date.today()).isoformat()
    warnungen: list[str] = []
    if textmodell is None:
        warnungen.append(
            "Ohne Sprachmodell gelesen: Hörtext nur nach Regeln, Bilder und Scans per Texterkennung"
        )

    # Alles, was fehlen kann, bevor Stunden vergehen: Weg und Vorlagen der Stimmen, die
    # Ausspracheliste. Ein Ton-Schluessel laesst sich nur bilden, wenn die Stimme benutzbar ist
    # (lokal: Vorlage da) -- die Probe mit einem leeren Block deckt das ohne Sprechen auf.
    for rolle, wer in (("Stimme", stimme), ("Ansage-Stimme", ansage)):
        if wer.weg != sprecher.weg:
            raise Mp4Fehler(
                f"{rolle} '{wer.name}' gehört zum Weg '{wer.weg}', gesprochen wird mit "
                f"'{sprecher.weg}'"
            )
        sprecher.ton_schluessel(Block(-1, (), "", -1, False), wer)
    aussprache = _lade_aussprache(quelle)
    tabelle = lade_tabelle(konfig.stimmen_tabelle)
    tabellen_stand = tabelle.fingerabdruck
    for hinweis in tabelle.hinweise:
        warnungen.append(hinweis)
        fortschritt(hinweis)
    verz = Arbeitsverzeichnis.fuer_quelle(konfig.arbeitsort, quelle)

    # -- Lesen ------------------------------------------------------------------------
    fp_lesen = _fp_lesen(quelle, verz, textmodell)
    gelesen = lies_mit_zwischenstand(quelle, verz, textmodell, fortschritt)
    dok = waehle(_mit_titel(gelesen, quelle), auswahl)

    dok, cover_warnung = _pruefe_cover(dok, verz.wurzel)
    if cover_warnung:
        warnungen.append(cover_warnung)
        fortschritt(cover_warnung)
    if dok.sprache and dok.sprache[:2].lower() != stimme.sprache[:2].lower():
        warnungen.append(
            f"Quelle ist »{dok.sprache}«, die Stimme spricht »{stimme.sprache}«: "
            "das Hörstück klingt wie ein Ausländer"
        )

    # -- Regie ------------------------------------------------------------------------
    # Die Regie sieht die gewaehlten Kapitel und den Titel (steht im Vorspann): beides gehoert
    # in den Fingerabdruck, sonst gaelte eine Regie fuer ein anderes Dokument. Die Bilder der
    # Vorlage gehen nur bei einer Bildquelle mit -- sie zeigen Spalten und Kaesten, die der
    # Text nicht mehr hat.
    fp_regie = fingerabdruck(
        "regie",
        fp_lesen,
        auswahl,
        dok.titel,
        textmodell is not None,
        modus,
        __version__,
        STAND_REGIE,
    )
    gespeichert = verz.lies_stufe("regie", fp_regie)
    if gespeichert is None:
        fortschritt("Regie")
        bilder = ()
        if textmodell is not None and modus != "aus" and ist_bildquelle(quelle):
            daten, mime = lade_bild(quelle)
            bilder = ((mime, daten),)
        if modus == "aus" or textmodell is None:
            rollenbild = None
            regie_warnungen = (
                (WARNUNG_AUS,) if modus == "aus" else ("Ohne Sprachmodell: keine Regie",)
            )
            gelesen = dok
        else:
            rollenbild = verstehe(dok, textmodell=textmodell, bilder=bilder)
            gelesen = dok
            dok, regie_warnungen = inszeniere(dok, rollenbild, textmodell=textmodell, modus=modus)
        _schreibe_manifest(verz, gelesen, rollenbild, quelle=quelle, bildquelle=bool(bilder))
        # Die Warnungen reisen im Dokument, damit sie auch aus dem Arbeitsverzeichnis in den
        # Bericht kommen (wie bei Lesen und Hoertext).
        dok = replace(dok, warnungen=(*dok.warnungen, *regie_warnungen))
        verz.schreibe_stufe("regie", fp_regie, dokument_zu_json(dok))
    else:
        fortschritt("Regie (vorhanden)")
        dok = dokument_aus_json(gespeichert)

    # -- Hoertext -----------------------------------------------------------------------
    fp_hoer = fingerabdruck(
        "hoertext",
        fp_regie,
        auswahl,
        aussprache,
        textmodell is not None,
        __version__,
        STAND_HOERTEXT,
    )
    gespeichert = verz.lies_stufe("hoertext", fp_hoer)
    if gespeichert is None:
        fortschritt("Hörtext")
        hoer, _ = hoertext(dok, textmodell=textmodell, aussprache=aussprache)
        verz.schreibe_stufe("hoertext", fp_hoer, dokument_zu_json(hoer))
    else:
        fortschritt("Hörtext (vorhanden)")
        hoer = dokument_aus_json(gespeichert)
    hoer = _mit_titel(hoer, quelle)

    # -- Gliedern ---------------------------------------------------------------------
    fp_stuecke = fingerabdruck("gliedern", fp_hoer, MAX_ZEICHEN, __version__, STAND_GLIEDERN)
    gespeichert = verz.lies_stufe("stuecke", fp_stuecke)
    if gespeichert is None:
        stuecke = gliedere(hoer, max_zeichen=MAX_ZEICHEN)
        verz.schreibe_stufe("stuecke", fp_stuecke, stuecke_zu_json(stuecke))
    else:
        stuecke = stuecke_aus_json(gespeichert)
    if not stuecke:
        raise KeinText(f"Aus {quelle.name} bleibt nach der Aufbereitung nichts zu sprechen")
    fortschritt(f"Gliedern: {len(stuecke)} Stücke")

    stueck_nach_nr = {s.nr: s for s in stuecke}

    # -- Buendeln ---------------------------------------------------------------------
    bloecke = sprecher.buendle(stuecke)
    gruppen: dict[int, list[Block]] = {}
    for b in bloecke:
        gruppen.setdefault(b.kapitel, []).append(b)
    for k in range(len(hoer.kapitel)):
        if k not in gruppen:
            warnungen.append(f"Kapitel »{dok.kapitel[k].titel or k + 1}« ohne Text übersprungen")

    # -- Datenschutz ------------------------------------------------------------------
    # Nur ein Weg, der Text ins Netz sendet, prueft (lokal bleibt alles auf dem Rechner). Geprueft
    # wird der Lesetext nach der Regie, nicht der Hoertext: dort sind Zahlen schon ausgeschrieben.
    hinweise: tuple[Hinweis, ...] = ()
    if sprecher.weg == "gemini":
        hinweise = pruefe_vertraulich(
            dok, dokumentart=_dokumentart(verz.wurzel), seiten=_seitenzahl(quelle)
        )
        if hinweise:
            freigabe = cloud_ok(hinweise) if callable(cloud_ok) else cloud_ok
            if not freigabe:
                raise RueckfrageNoetig(
                    "Datenschutz-Hinweise vor dem Versand an Google: "
                    + "; ".join(f"{h.klasse} {h.anzahl} ({h.beispiel})" for h in hinweise)
                )

    # -- Sprechen -----------------------------------------------------------------------
    # Wer spricht die Ansagen? Die Ansage-Stimme (Rolle der Tabelle); ist es dieselbe wie die
    # Hauptstimme, spricht die Hauptstimme.
    ansagen = any(b.ansage for b in bloecke)

    def sprecher_von(block: Block) -> Stimme:
        return ansage if block.ansage else stimme

    schluessel = {b.nr: sprecher.ton_schluessel(b, sprecher_von(b)) for b in bloecke}
    ton: dict[int, dict] = {}
    for b in bloecke:
        gespeichert_ton = verz.lies_ton(schluessel[b.nr])
        if gespeichert_ton is not None:
            ton[b.nr] = gespeichert_ton
    offen = [b for b in bloecke if b.nr not in ton]
    fortschritt(f"Sprechen: {len(offen)} von {len(bloecke)} Blöcken offen")
    if offen and (schaetzung := sprecher.schaetzung(sum(len(b.text) for b in offen))):
        fortschritt(schaetzung)
    nicht_gesprochen: dict[int, str] = {}  # Block-Nr -> Fehlerklasse, mit Stille ersetzt
    ausfaelle_folge = 0
    fertig = len(ton)
    # Textgleiche Bloecke derselben Stimme teilen den inhaltsadressierten Ton-Schluessel, also
    # eine Datei: EIN Auftrag je Schluessel (sonst sprechen parallele Faeden dieselbe Datei und
    # bezahlen doppelt), das Ergebnis gilt fuer alle Bloecke des Schluessels.
    gleiche: dict[str, list[Block]] = {}
    for b in bloecke:
        gleiche.setdefault(schluessel[b.nr], []).append(b)
    auftraege = [
        Auftrag(geschwister[0], sprecher_von(geschwister[0]), verz.ton_wav(schl))
        for schl, geschwister in gleiche.items()
        if geschwister[0].nr not in ton
    ]
    gewichen = False

    def weiche() -> bool:
        """Einmal wahr, bleibt wahr: der Lauf erkennt am Ende, dass der Sprecher gewichen ist."""
        nonlocal gewichen
        gewichen = gewichen or soll_weichen()
        return gewichen

    ausgefallen: list[Block] = []  # Fehlerantwort nach allen Versuchen: Stille nach dem Sprechen
    for block, ergebnis in sprecher.sprich_viele(
        auftraege, soll_weichen=weiche, fortschritt=fortschritt
    ):
        if isinstance(ergebnis, SprecherFehler):
            if ergebnis.klasse in LAUTE_KLASSEN:
                # Sperre, Limit, Zugang: kein Ausfall dieses Blocks, sondern der Lauf selbst ist
                # am Ende -- laut abbrechen, mit der Stelle (Zwischenstand bleibt).
                raise SprecherFehler(
                    f"Kapitel »{_kapitelname(dok, block.kapitel)}«: {ergebnis}", ergebnis.klasse
                ) from ergebnis
            ausfaelle_folge += 1  # ein Ausfall je Anfrage, auch wenn mehrere Bloecke daran haengen
            if ausfaelle_folge > MAX_AUSFAELLE_FOLGE:
                ursache = ergebnis.__cause__ if ergebnis.__cause__ is not None else ergebnis
                art = ArbeiterFehler if isinstance(ursache, ArbeiterFehler) else SprecherFehler
                raise art(
                    f"{ausfaelle_folge} Blöcke hintereinander nicht gesprochen "
                    f"(zuletzt Block {block.nr}): kein Gift-Block, der Sprecher ist "
                    f"defekt (zuletzt {ergebnis.klasse})\n{ergebnis}",
                    "Folge",
                ) from ursache
            for gleich in gleiche[schluessel[block.nr]]:
                ausgefallen.append(gleich)
                nicht_gesprochen[gleich.nr] = ergebnis.klasse
            fortschritt(f"Block {block.nr} nicht gesprochen ({ergebnis.klasse}): Stille eingesetzt")
        else:
            ausfaelle_folge = 0
            for gleich in gleiche[schluessel[block.nr]]:
                ton[gleich.nr] = ergebnis
            verz.schreibe_ton(schluessel[block.nr], ergebnis)
        fertig += len(gleiche[schluessel[block.nr]])
        if fertig % FORTSCHRITT_ALLE == 0 or fertig == len(bloecke):
            fortschritt(f"Sprechen {fertig}/{len(bloecke)}")
    if len(ton) + len(ausgefallen) < len(bloecke):
        naechster = next(b for b in bloecke if b.nr not in ton and b not in ausgefallen)
        if not gewichen:
            raise Mp4Fehler(
                f"Der Sprecher hat Block {naechster.nr} von {len(bloecke)} nicht geliefert, "
                "ohne zu weichen"
            )
        raise Gewichen(f"Lauf weicht vor Block {naechster.nr} von {len(bloecke)}")

    # Die Stille eines ausgefallenen Blocks dauert, was der Lauf von ihm erwartet haette: bei
    # Gemini `len(text) / Median seiner Stimme` (erst jetzt bekannt, nach dem Sprechen aller),
    # sonst 16 Zeichen/s; lokal die feste Rate des Wegs.
    if ausgefallen:
        medianraten = sprechraten_median(bloecke, ton, sprecher_von)
        for block in ausgefallen:
            if WEGE[sprecher.weg].band_relativ:
                median = medianraten.get(sprecher_von(block).name)
                rate = median[0] if median is not None else ERSATZ_ZEICHEN_JE_S
            else:
                rate = ZEICHEN_JE_SEKUNDE
            ton[block.nr] = _stille_statt_ton(block, verz.ton_wav(schluessel[block.nr]), rate)

    if nicht_gesprochen:
        warnungen.append(
            f"{len(nicht_gesprochen)} Block/Blöcke nicht gesprochen, Stille eingesetzt "
            "(Stellen im Bericht); ein erneuter Lauf derselben Quelle versucht sie noch einmal"
        )

    def wav_von(block: Block) -> Path:
        return verz.ton_wav(schluessel[block.nr])

    weg = WEGE[sprecher.weg]

    # -- Pruefen ------------------------------------------------------------------------
    # Ersetzte Bloecke gibt es nichts zu hoeren, und ihre Menge gehoert in den Fingerabdruck:
    # ist einer beim naechsten Lauf gesprochen, muss die Pruefung diesen Block sehen. Auch
    # das Band des Wegs und die Frage, ob gehoert werden kann, bestimmen das Ergebnis.
    # Textgleiche Bloecke sind eine Aufnahme: sie wird einmal geprueft und hoechstens einmal
    # neu gesprochen; der Befund steht beim ersten Block.
    pruef_bloecke = [
        b for b in bloecke if b.nr not in nicht_gesprochen and gleiche[schluessel[b.nr]][0] is b
    ]
    fp_pruef = fingerabdruck(
        "pruefen",
        fp_stuecke,
        [schluessel[b.nr] for b in bloecke],
        sorted(nicht_gesprochen),
        STICHPROBE,
        sprecher.kann_hoeren(),
        weg.pruefband,
        weg.band_relativ,
        __version__,
    )
    gespeichert = verz.lies_stufe("pruefung", fp_pruef)
    if gespeichert is None:
        fortschritt("Prüfen")
        pruefung = pruefe(
            pruef_bloecke,
            ton,
            sprecher=sprecher,
            sprache=stimme.sprache,
            stimme=stimme,
            wav_pfad=wav_von,
            stichprobe=STICHPROBE,
            zufall=random.Random(int(fp_pruef, 16)),
            ansage_stimme=ansage if ansagen else None,
            band=weg.pruefband,
            band_relativ=weg.band_relativ,
            verwirf=lambda block: verz.verwirf_ton(schluessel[block.nr]),
        )
        # Neu gesprochene Bloecke ersetzen ihre Messwerte, BEVOR gemastert wird: die
        # Sprechrate der alten Aufnahme wuerde das Tempo-Angleichen verfaelschen.
        for nr, neue_messwerte in pruefung.neuer_ton.items():
            for gleich in gleiche[schluessel[nr]]:
                ton[gleich.nr] = neue_messwerte
            verz.schreibe_ton(schluessel[nr], neue_messwerte)
        befunde = [[b.block_nr, b.grund, b.zeit_s] for b in pruefung.auffaellig]
        pruef_warnungen = list(pruefung.warnungen)
        neu_gesprochen = pruefung.neu_gesprochen
        verz.schreibe_stufe(
            "pruefung",
            fp_pruef,
            {"befunde": befunde, "warnungen": pruef_warnungen, "neu": neu_gesprochen},
        )
    else:
        fortschritt("Prüfen (vorhanden)")
        befunde = gespeichert["befunde"]
        pruef_warnungen = gespeichert["warnungen"]
        neu_gesprochen = gespeichert.get("neu", 0)
        for b in bloecke:  # die Messwerte der ersetzten Aufnahmen stehen schon in den Dateien
            ton[b.nr] = verz.lies_ton(schluessel[b.nr]) or ton[b.nr]
    warnungen.extend(pruef_warnungen)

    # Die ersetzten Bloecke stehen frisch im Bericht, nie aus dem Zwischenstand der Pruefung:
    # ihre Fehlerklasse ist die dieses Laufs.
    befunde = sorted(
        [*befunde, *([nr, f"nicht gesprochen ({k})", 0.0] for nr, k in nicht_gesprochen.items())],
        key=lambda b: b[0],
    )

    # -- Mastern ------------------------------------------------------------------------
    def pause_zwischen(vorne: Block, hinten: Block, wer: Stimme) -> float:
        """Pause hinter dem letzten Stueck von `vorne` gegenueber dem ersten von `hinten`."""
        return _pause_nach(
            stueck_nach_nr[vorne.stueck_nrs[-1]], stueck_nach_nr[hinten.stueck_nrs[0]], wer
        )

    kapitel_nummern = sorted(gruppen)
    kapitel_wavs: list[tuple[str, Path]] = []
    # Jeder Lauf gleicher Stimme klingt und laeuft wie seine Stimme: ein Kapitel nur aus Ansagen
    # (Vorspann, Abspann) wie die Ansage-Stimme, eine Ueberleitung mitten im Kapitel ebenso --
    # die Klangkorrektur der einen Stimme verschlechtert die andere (Stimmfindung P29).
    for n, k in enumerate(kapitel_nummern, start=1):
        fortschritt(f"Mastern {n}/{len(kapitel_nummern)}")
        wav = verz.kapitel_wav(k)
        laeufe = _laeufe(gruppen[k], sprecher_von)
        fp_kapitel = fingerabdruck(
            "kapitel",
            fp_pruef,
            k,
            [
                (
                    len(teil),
                    ks.pause_stueck,
                    ks.pause_absatz,
                    ks.pause_titel,
                    ks.pause_vor_ueberschrift,
                    ks.pause_nach_ueberschrift,
                    ks.tempo_angleich,
                    list(ks.klang),
                    ks.tempo,
                    ks.tonhoehe_ht,
                )
                for ks, teil in laeufe
            ],
        )
        if verz.lies_stufe(verz.kapitel_stufe(k), fp_kapitel) is None or not wav.is_file():
            roh = verz.kapitel_roh(k)
            teile: list[Path] = []
            for i, (ks, teil) in enumerate(laeufe):
                gemastert = wav if len(laeufe) == 1 else wav.with_name(f"{wav.stem}-{i}.wav")
                kapitel_ton(
                    teil,
                    ton,
                    ks,
                    wav_von,
                    roh,
                    pause_nach=lambda vorne, hinten, ks=ks: pause_zwischen(vorne, hinten, ks),
                )
                if all(b.nr in nicht_gesprochen for b in teil):
                    # Ein Lauf nur aus ersetzten Bloecken ist Stille: es gibt nichts zu messen
                    # (loudnorm bricht bei "stumm" ab), und die Stille bleibt, wie sie ist.
                    roh.replace(gemastert)
                else:
                    master(roh, ks, gemastert)
                    roh.unlink()
                teile.append(gemastert)
            if len(laeufe) > 1:
                pausen = [
                    pause_zwischen(vorne[-1], hinten[0], stimme)
                    for (_, vorne), (_, hinten) in pairwise(laeufe)
                ]
                _fuege_zusammen(teile, pausen, wav)
                for teil_wav in teile:
                    teil_wav.unlink()
            verz.schreibe_stufe(verz.kapitel_stufe(k), fp_kapitel, {})
        kapitel_wavs.append((_kapitelname(dok, k), wav))

    dauern = [wav_info(w)[3] / SAMPLERATE for _, w in kapitel_wavs]
    dauer_s = sum(dauern) + stimme.pause_kapitel * (len(dauern) - 1)

    # -- Messwerte und Zeitstempel fuer den Bericht -------------------------------------
    # Gemessen wird das erste Kapitel mit Fliesstext der Text-Stimme: davor stehen Kapitel nur
    # aus Ansagen (Einleitung), die die Ansage-Stimme spricht.
    i = next((i for i, k in enumerate(kapitel_nummern) if any(not b.ansage for b in gruppen[k])), 0)
    woerter = sum(len(_WORT.findall(b.text)) for b in gruppen[kapitel_nummern[i]])
    messwerte = {"woerter_je_minute": woerter / (dauern[i] / 60)}
    if sprecher.arbeiter is not None:  # Tonlage und Melodie misst nur der Arbeiter
        messung = sprecher.arbeiter.miss(
            _ausschnitt(kapitel_wavs[i][1], verz.wurzel / "messung.wav", MESS_AUSSCHNITT_S)
        )
        messwerte = {
            "f0_median": float(messung["f0_median"]),
            "streuung_ht": float(messung["streuung_ht"]),
            **messwerte,
        }

    block_nach_nr = {b.nr: b for b in bloecke}
    kapitel_start = {}
    t = 0.0
    for k, d in zip(kapitel_nummern, dauern, strict=True):
        kapitel_start[k] = t if format == "m4b" else 0.0
        t += d + stimme.pause_kapitel
    roh_start: dict[int, float] = {}
    umrechnung: dict[int, float] = {}
    for k, d in zip(kapitel_nummern, dauern, strict=True):
        gruppe = gruppen[k]
        lauf_s = 0.0
        for i, b in enumerate(gruppe):
            roh_start[b.nr] = lauf_s
            lauf_s += wav_info(wav_von(b))[3] / SAMPLERATE
            if i + 1 < len(gruppe):
                folgt = gruppe[i + 1]
                wer = sprecher_von(b) if sprecher_von(b) == sprecher_von(folgt) else stimme
                lauf_s += pause_zwischen(b, folgt, wer)
        umrechnung[k] = d / lauf_s  # die Kapitel-WAV ist gemastert: Tempo, Angleich ...
    bericht_befunde = []
    for nr, grund, zeit in befunde:
        if nr not in block_nach_nr:
            raise Mp4Fehler(f"Befund zu unbekanntem Block {nr}")
        k = block_nach_nr[nr].kapitel
        stelle = kapitel_start[k] + (roh_start[nr] + (zeit or 0.0)) * umrechnung[k]
        titel = _kapitelname(dok, k)
        bericht_befunde.append((nr, f"{grund} (Kapitel »{titel}«)", stelle))

    # -- Verpacken ------------------------------------------------------------------------
    fortschritt("Verpacken")
    ziel.mkdir(parents=True, exist_ok=True)
    if format == "m4b":
        datei = ausgabe_name(ziel, datum, dok.titel, ".m4b")
        m4b(kapitel_wavs, dok, datei, pause_kapitel=stimme.pause_kapitel)
        dateien: tuple[Path, ...] = (datei,)
        # Jede Kapitelmarke muss in einer Pause liegen, sonst springt der Player mitten in ein
        # Wort. Die Marken kommen aus der fertigen M4B (ffprobe), nicht aus der Rechnung des
        # Laufs: nur so faellt auf, wenn das Verpacken sie anders setzt. Befunde sind Hinweise;
        # was nicht gelesen werden konnte, steht als ungeprueft da, nie still als in Ordnung.
        fortschritt("Kapitelmarken prüfen")
        marken = lies_kapitelmarken(datei, zeit_s=zeitgrenze(dauer_s))
        if len(marken) != len(kapitel_nummern):
            warnungen.append(
                f"Kapitelmarken: ungeprüft (Datei trägt {len(marken)} Kapitel, "
                f"erwartet {len(kapitel_nummern)})"
            )
        else:
            warnungen.extend(
                pruefe_kapitelmarken(
                    datei,
                    marken,
                    pause_kapitel=stimme.pause_kapitel,
                    zeit_s=zeitgrenze(dauer_s),
                )
            )
    else:
        dateien = mp3(kapitel_wavs, dok, ziel, datum=datum)
        warnungen.append("Kapitelmarken: ungeprüft (Format ohne Kapitel)")

    # -- Bericht --------------------------------------------------------------------------
    fortschritt("Bericht")
    gesprochen = replace(hoer, kapitel=tuple(hoer.kapitel[k] for k in kapitel_nummern))
    ausweis = sprecher.ausweis()
    warnungen.extend(ausweis.warnungen)
    alle_warnungen = _eindeutig(hoer.warnungen, warnungen)
    verbrauch = sprecher.verbrauch()
    weg_zeilen = (
        (
            f"Blöcke: {len(offen)} neu gesprochen, "
            f"{len(bloecke) - len(offen)} aus dem Zwischenstand",
            *ausweis.zeilen,
            f"Neu gesprochen nach der Prüfung (Ausreißer): {neu_gesprochen}",
        )
        if ausweis.zeilen
        else ()
    )
    bericht = schreibe_bericht(
        ausgabe_name(ziel, datum, f"{dok.titel} Bericht", ".md"),
        quelle=quelle,
        stimme=stimme,
        tabellen_stand=tabellen_stand,
        dok=gesprochen,
        dateien=dateien,
        dauer_s=dauer_s,
        warnungen=warnungen,
        befunde=bericht_befunde,
        messwerte=messwerte,
        ansage_stimme=ansage if ansagen else None,
        weg=sprecher.weg,
        modell=sprecher.modell,
        bloecke=len(bloecke),
        verbrauch=verbrauch,
        weg_zeilen=weg_zeilen,
        datenschutz=hinweise,
    )
    return Ergebnis(
        dateien=dateien,
        bericht=bericht,
        warnungen=alle_warnungen,
        dauer_s=dauer_s,
        weg=sprecher.weg,
        modell=sprecher.modell,
        verbrauch=verbrauch,
        datenschutz=hinweise,
    )
