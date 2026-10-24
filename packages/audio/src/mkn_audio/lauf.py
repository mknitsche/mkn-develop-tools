"""Der Lauf: von der Quelle zur Hoerdatei, Stufe fuer Stufe, fortsetzbar.

Die Stufen (Spec 6, § 18): Lesen, Regie, Hoertext, Gliedern, Sprechen, Pruefen, Mastern,
Verpacken, Bericht. Dieses Modul verbindet nur; jede Stufe steht in ihrem eigenen Modul. Was es
selbst entscheidet, ist die Reihenfolge und -- wichtiger -- **was nicht neu gerechnet
werden muss** (`arbeitsverzeichnis`).

**Wiederaufnahme ohne Doppelrechnung.** Sprechen ist die teure Stufe, und sie ist
stueckweise: jede Aufnahme wird gleich nach dem Sprechen mit ihren Messwerten abgelegt.
Bricht der Lauf ab (Neustart, Strom, `Gewichen`), findet der naechste jede fertige
Aufnahme wieder und spricht nur den Rest. Eine halbe Aufnahme gilt nie als fertig: dafuer
braucht es WAV *und* Messwerte, und beide entstehen atomar.

**Weichen.** Ein langes Buch macht einer kurzen Quelle Platz (Spec 9). `soll_weichen`
wird vor jedem noch zu sprechenden Stueck gefragt; `Gewichen` ist kein Fehler des Laufs,
sondern seine Unterbrechung -- der Aufrufer legt ihn zurueck in die Warteschlange.

**Bewusste Entscheidungen**

- Die *Sprache* der Aufnahme bestimmt die Stimme (`stimme.sprache`), nicht die Quelle.
  Widerspricht ihr die Quelle, steht das im Bericht; erkannt wird nichts.
- Die Kapitelmarken der M4B tragen die Titel der *Quelle*, nicht den ausgeschriebenen
  Hoertext: im Player soll "Kapitel 3" stehen, nicht "Kapitel drei".
- Das Cover wird VOR dem Sprechen geprueft. Ein kaputtes Cover wuerde sonst erst beim
  Verpacken scheitern, nach Stunden Sprechen; es kostet das Hoerstueck nichts, also wird
  es mit Warnung weggelassen.
- Die Stimmqualitaet im Bericht (Tonlage, Melodie) misst `miss` an einem Ausschnitt des
  ersten Kapitels, nicht an dessen ganzer Laenge: die Messung braucht Minuten je Stunde
  Ton, und der Bericht ist es nicht wert, einen Lauf am Ende zu verzoegern oder an der
  Zeitgrenze des Arbeiters scheitern zu lassen.
- Zeitstempel auffaelliger Stellen sind aus den Dauern der Stuecke auf die fertige
  Kapitellaenge umgerechnet: auf wenige Sekunden genau, nicht auf das Bild.
- Ohne Sprachmodell wird der Hoertext nur nach Regeln aufbereitet; das steht im Bericht.
- **Die Regie** entscheidet zwischen Lesen und Hoertext, was gesprochen wird und
  was nur Beiwerk ist, und schreibt Vorspann, Ueberleitungen und Abspann. Diese Ansagen
  spricht, wenn die Stimme eine `ansage_stimme` nennt, diese zweite Stimme (Vorlage und
  Regler) und wird mit deren Klang und Tempo gemastert -- in einem Kapitel mit Ueberleitung
  jeder Lauf gleicher Stimme fuer sich, danach aneinandergefuegt. Die Kapitelmarken
  heissen "Einleitung" und "Abspann", und die Zaehlung "Kapitel N" kennt sie nicht.
  Wie weit die Regie eingreift, bestimmt `regie_modus`: ein EPUB bekommt `buch` (nur
  Unhoerbares entfaellt), alles andere `voll`; `aus` liest unveraendert.
- **Ein Arbeiter-Ausfall kostet ein Stueck, nicht das Buch.** Scheitert das Sprechen eines
  Stuecks (Tod, Zeitgrenze, Fehlerantwort), gibt es EINEN neuen Versuch -- der Client
  startet nach Tod und Zeitgrenze ohnehin frisch (Spec 7). Scheitert auch der, steht fuer
  dieses Stueck Stille der erwarteten Dauer im Hoerstueck, und der Bericht nennt es als
  Befund. Die Stille ist eine WAV ohne Messwerte und gilt deshalb nie als gesprochen: der
  erneute Lauf derselben Quelle versucht dieses Stueck noch einmal, und die Pruefung
  rechnet dann neu (die Menge der ersetzten Stuecke steht im Fingerabdruck). Das gilt nur,
  solange das Arbeitsverzeichnis der Quelle noch da ist. Gift-Stueck und kaputter Arbeiter
  sehen sich anfangs gleich; mehr als `MAX_AUSFAELLE_FOLGE` Stuecke hintereinander sind
  kein Gift-Stueck mehr, dann bricht der Lauf laut ab (der Dienst meldet einen Defekt).
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

from mkn_audio import __version__
from mkn_audio.arbeiter_client import Arbeiter, ArbeiterFehler
from mkn_audio.arbeitsverzeichnis import (
    Arbeitsverzeichnis,
    datei_hash,
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
)
from mkn_audio.pruefen import ZEICHEN_JE_SEKUNDE, pruefe, sprich_zweimal
from mkn_audio.regie import WARNUNG_AUS, inszeniere, pruefe_modus, verstehe
from mkn_audio.stimmen import Stimme, lade_tabelle
from mkn_audio.typen import Dokument, Kapitel, Mp4Fehler, Stueck, Textmodell
from mkn_audio.verpacken import _cover_datei, ausgabe_name, m4b, mp3


def _laeufe(
    stuecke: list[Stueck], sprecher: Callable[[Stueck], Stimme]
) -> list[tuple[Stimme, list[Stueck]]]:
    """Die Stuecke eines Kapitels in Laeufe gleicher Stimme, in Reihenfolge."""
    laeufe: list[tuple[Stimme, list[Stueck]]] = []
    for stueck in stuecke:
        wer = sprecher(stueck)
        if laeufe and laeufe[-1][0] == wer:
            laeufe[-1][1].append(stueck)
        else:
            laeufe.append((wer, [stueck]))
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
"""Alle so viele Stuecke meldet das Sprechen einen Stand."""

MAX_AUSFAELLE_FOLGE = 3
"""So viele Stuecke hintereinander darf das Sprechen scheitern (je zwei Versuche), bevor der
Lauf es nicht mehr fuer Gift-Stuecke, sondern fuer einen kaputten Arbeiter haelt."""

_WORT = re.compile(r"\w+")


class Gewichen(Mp4Fehler):
    """Der Lauf hat an einer Stueckgrenze Platz gemacht (`soll_weichen()` war wahr).

    Der Zustand ist im Arbeitsverzeichnis gesichert; derselbe Aufruf setzt fort.
    """


@dataclass(frozen=True)
class Ergebnis:
    """Was ein Lauf geliefert hat.

    `warnungen` sind alle Hinweise des Berichts (Quelle, Hoertext, Lauf), ohne Doppelte.
    `dauer_s` ist die Spieldauer des Hoerstuecks.
    """

    dateien: tuple[Path, ...]
    bericht: Path
    warnungen: tuple[str, ...]
    dauer_s: float


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


def _stille_statt_ton(stueck: Stueck, ziel: Path) -> dict:
    """Legt Stille der erwarteten Dauer nach `ziel` und gibt Messwerte dafuer.

    Die Messwerte gehen NICHT ins Arbeitsverzeichnis (`schreibe_ton`): ohne sie gilt die
    Aufnahme dort als nicht gesprochen. Die Sprechrate ist der Erwartungswert der
    Pruefung, damit das Tempo-Angleichen die Stille nicht als Ausreisser behandelt.
    """
    dauer = len(stueck.text) / ZEICHEN_JE_SEKUNDE
    with atomar(ziel) as tmp, wave.open(str(tmp), "wb") as aus:
        aus.setnchannels(1)
        aus.setsampwidth(2)
        aus.setframerate(SAMPLERATE)
        schreibe_stille(aus, dauer)
    return {"dauer": dauer, "sprechrate": ZEICHEN_JE_SEKUNDE, "versuche": 0, "zu_kurz": False}


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
    return bool(kapitel.arten) and not kapitel.titel.strip() and "wortlaut" not in kapitel.arten


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
        leser="mkn-mp4",
    )
    entfernt = [w for w in dok.warnungen if w.startswith("weggelassen:")]
    manifest["text_bilanz"]["rest"].extend({"grund": w, "woerter": None} for w in entfernt)
    schreibe_manifest(manifest, verz.wurzel / "manifest.json")


def konvertiere(
    quelle: Path,
    ziel: Path,
    stimme: Stimme,
    *,
    arbeiter: Arbeiter,
    textmodell: Textmodell | None,
    konfig: Konfig,
    auswahl: str | None = None,
    format: Literal["m4b", "mp3"] = "m4b",
    soll_weichen: Callable[[], bool] = lambda: False,
    fortschritt: Callable[[str], None] = lambda _: None,
    heute: date | None = None,
    regie_modus: Literal["voll", "buch", "aus"] | None = None,
) -> Ergebnis:
    """Macht aus `quelle` eine Hoerdatei (oder MP3 je Kapitel) in `ziel`.

    `heute` ist das Datum im Dateinamen; ohne Angabe fragt der Lauf die Uhr (`date.today()`).
    `regie_modus` (siehe `regie`): ohne Angabe `buch` fuer ein EPUB, sonst `voll`. Ein Buch
    besteht aus seinem Text, und eine falsch erkannte Rolle darf darin nichts Hoerbares
    kosten; Zusammenfassungen, Artikel und Programmseiten bestehen dagegen zu grossen Teilen
    aus Beiwerk, das die Regie weglassen soll.
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

    # Alles, was fehlen kann, bevor Stunden vergehen: die Vorlage, die Ausspracheliste.
    try:
        vorlage_hash = datei_hash(stimme.vorlage)
    except Mp4Fehler as fehler:
        raise Mp4Fehler(f"Vorlage der Stimme '{stimme.name}': {fehler}") from fehler
    aussprache = _lade_aussprache(quelle)
    tabellen_stand = lade_tabelle(konfig.stimmen_tabelle).fingerabdruck
    verz = Arbeitsverzeichnis.fuer_quelle(konfig.arbeitsort, quelle)

    # -- Lesen ------------------------------------------------------------------------
    fp_lesen = fingerabdruck(
        "lesen", verz.quelle_hash, textmodell is not None, __version__, STAND_LESEN
    )
    gespeichert = verz.lies_stufe("lesetext", fp_lesen)
    if gespeichert is None:
        fortschritt("Lesen")
        gelesen = lies(quelle, textmodell=textmodell)
        verz.schreibe_stufe("lesetext", fp_lesen, dokument_zu_json(gelesen))
    else:
        fortschritt("Lesen (vorhanden)")
        gelesen = dokument_aus_json(gespeichert)
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

    gruppen: dict[int, list[Stueck]] = {}
    for s in stuecke:
        gruppen.setdefault(s.kapitel, []).append(s)
    for k in range(len(hoer.kapitel)):
        if k not in gruppen:
            warnungen.append(f"Kapitel »{dok.kapitel[k].titel or k + 1}« ohne Text übersprungen")

    # -- Sprechen -----------------------------------------------------------------------
    # Wer spricht die Ansagen? Nennt die Stimme keine zweite (oder sich selbst), die Hauptstimme.
    # Die Vorlage der zweiten wird wie die der ersten VOR dem Sprechen geprueft.
    ansagen = any(s.ansage for s in stuecke)
    ansager = stimme
    if ansagen and stimme.ansage_stimme not in (None, stimme.name):
        ansager = lade_tabelle(konfig.stimmen_tabelle).hole(stimme.ansage_stimme)
    try:
        ansage_hash = vorlage_hash if ansager is stimme else datei_hash(ansager.vorlage)
    except Mp4Fehler as fehler:
        raise Mp4Fehler(f"Vorlage der Ansage-Stimme '{ansager.name}': {fehler}") from fehler

    def sprecher(stueck: Stueck) -> Stimme:
        return ansager if stueck.ansage else stimme

    def ton_schluessel(stueck: Stueck) -> str:
        wer = sprecher(stueck)
        return fingerabdruck(
            "ton",
            stueck.text,
            wer.modell,
            wer.sprache,
            ansage_hash if wer is ansager else vorlage_hash,
            wer.exaggeration,
            wer.cfg_weight,
            wer.temperature,
            wer.pausen_kuerzen,
        )[:16]

    schluessel = {s.nr: ton_schluessel(s) for s in stuecke}
    offen = sum(1 for s in stuecke if verz.lies_ton(schluessel[s.nr]) is None)
    fortschritt(f"Sprechen: {offen} von {len(stuecke)} Stücken offen")
    ton: dict[int, dict] = {}
    nicht_gesprochen: dict[int, str] = {}  # Stueck-Nr -> Fehlerklasse, mit Stille ersetzt
    ausfaelle_folge = 0
    for i, s in enumerate(stuecke, start=1):
        antwort = verz.lies_ton(schluessel[s.nr])
        if antwort is None:
            if soll_weichen():
                raise Gewichen(f"Lauf weicht vor Stück {s.nr} von {len(stuecke)}")
            wav = verz.ton_wav(schluessel[s.nr])
            try:
                antwort = sprich_zweimal(
                    arbeiter, s.text, sprache=sprecher(s).sprache, stimme=sprecher(s), ziel=wav
                )
            except ArbeiterFehler as fehler:
                ausfaelle_folge += 1
                if ausfaelle_folge > MAX_AUSFAELLE_FOLGE:
                    raise ArbeiterFehler(
                        f"{ausfaelle_folge} Stücke hintereinander nicht gesprochen "
                        f"(zuletzt Stück {s.nr}): kein Gift-Stück, der Arbeiter ist "
                        f"defekt (zuletzt {fehler.klasse})\n{fehler}",
                        "Folge",
                    ) from fehler
                antwort = _stille_statt_ton(s, wav)
                nicht_gesprochen[s.nr] = fehler.klasse
                fortschritt(f"Stück {s.nr} nicht gesprochen ({fehler.klasse}): Stille eingesetzt")
            else:
                ausfaelle_folge = 0
                verz.schreibe_ton(schluessel[s.nr], antwort)
        ton[s.nr] = antwort
        if i % FORTSCHRITT_ALLE == 0 or i == len(stuecke):
            fortschritt(f"Sprechen {i}/{len(stuecke)}")

    if nicht_gesprochen:
        warnungen.append(
            f"{len(nicht_gesprochen)} Stück(e) nicht gesprochen, Stille eingesetzt "
            "(Stellen im Bericht); ein erneuter Lauf derselben Quelle versucht sie noch einmal"
        )

    def wav_von(stueck: Stueck) -> Path:
        return verz.ton_wav(schluessel[stueck.nr])

    # -- Pruefen ------------------------------------------------------------------------
    # Ersetzte Stuecke gibt es nichts zu hoeren, und ihre Menge gehoert in den Fingerabdruck:
    # ist eines beim naechsten Lauf gesprochen, muss die Pruefung dieses Stueck sehen.
    pruef_stuecke = [s for s in stuecke if s.nr not in nicht_gesprochen]
    fp_pruef = fingerabdruck(
        "pruefen",
        fp_stuecke,
        [schluessel[s.nr] for s in stuecke],
        sorted(nicht_gesprochen),
        STICHPROBE,
        __version__,
    )
    gespeichert = verz.lies_stufe("pruefung", fp_pruef)
    if gespeichert is None:
        fortschritt("Prüfen")
        pruefung = pruefe(
            pruef_stuecke,
            ton,
            arbeiter=arbeiter,
            sprache=stimme.sprache,
            stimme=stimme,
            wav_pfad=wav_von,
            stichprobe=STICHPROBE,
            zufall=random.Random(int(fp_pruef, 16)),
            ansage_stimme=ansager if ansagen else None,
        )
        # Neu gesprochene Stuecke ersetzen ihre Messwerte, BEVOR gemastert wird: die
        # Sprechrate der alten Aufnahme wuerde das Tempo-Angleichen verfaelschen.
        for nr, antwort in pruefung.neuer_ton.items():
            ton[nr] = antwort
            verz.schreibe_ton(schluessel[nr], antwort)
        befunde = [[b.stueck_nr, b.grund, b.zeit_s] for b in pruefung.auffaellig]
        verz.schreibe_stufe("pruefung", fp_pruef, {"befunde": befunde})
    else:
        fortschritt("Prüfen (vorhanden)")
        befunde = gespeichert["befunde"]
        for s in stuecke:  # die Messwerte der ersetzten Aufnahmen stehen schon in den Dateien
            ton[s.nr] = verz.lies_ton(schluessel[s.nr]) or ton[s.nr]

    # Die ersetzten Stuecke stehen frisch im Bericht, nie aus dem Zwischenstand der Pruefung:
    # ihre Fehlerklasse ist die dieses Laufs.
    befunde = sorted(
        [*befunde, *([nr, f"nicht gesprochen ({k})", 0.0] for nr, k in nicht_gesprochen.items())],
        key=lambda b: b[0],
    )

    # -- Mastern ------------------------------------------------------------------------
    kapitel_nummern = sorted(gruppen)
    kapitel_wavs: list[tuple[str, Path]] = []
    # Jeder Lauf gleicher Stimme klingt und laeuft wie seine Stimme: ein Kapitel nur aus Ansagen
    # (Vorspann, Abspann) wie die Ansage-Stimme, eine Ueberleitung mitten im Kapitel ebenso --
    # die Klangkorrektur der einen Stimme verschlechtert die andere (Stimmfindung P29).
    for n, k in enumerate(kapitel_nummern, start=1):
        fortschritt(f"Mastern {n}/{len(kapitel_nummern)}")
        wav = verz.kapitel_wav(k)
        laeufe = _laeufe(gruppen[k], sprecher)
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
                kapitel_ton(teil, ton, ks, wav_von, roh)
                master(roh, ks, gemastert)
                roh.unlink()
                teile.append(gemastert)
            if len(laeufe) > 1:
                pausen = [
                    _pause_nach(vorne[-1], hinten[0], stimme)
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
    erstes = kapitel_nummern[0]
    messung = arbeiter.miss(
        _ausschnitt(kapitel_wavs[0][1], verz.wurzel / "messung.wav", MESS_AUSSCHNITT_S)
    )
    woerter = sum(len(_WORT.findall(s.text)) for s in gruppen[erstes])
    messwerte = {
        "f0_median": float(messung["f0_median"]),
        "streuung_ht": float(messung["streuung_ht"]),
        "woerter_je_minute": woerter / (dauern[0] / 60),
    }

    stueck_nach_nr = {s.nr: s for s in stuecke}
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
        for i, s in enumerate(gruppe):
            roh_start[s.nr] = lauf_s
            lauf_s += wav_info(wav_von(s))[3] / SAMPLERATE
            if i + 1 < len(gruppe):
                folgt = gruppe[i + 1]
                wer = sprecher(s) if sprecher(s) == sprecher(folgt) else stimme
                lauf_s += _pause_nach(s, folgt, wer)
        umrechnung[k] = d / lauf_s  # die Kapitel-WAV ist gemastert: Tempo, Angleich ...
    bericht_befunde = []
    for nr, grund, zeit in befunde:
        if nr not in stueck_nach_nr:
            raise Mp4Fehler(f"Befund zu unbekanntem Stück {nr}")
        k = stueck_nach_nr[nr].kapitel
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
    else:
        dateien = mp3(kapitel_wavs, dok, ziel, datum=datum)

    # -- Bericht --------------------------------------------------------------------------
    fortschritt("Bericht")
    gesprochen = replace(hoer, kapitel=tuple(hoer.kapitel[k] for k in kapitel_nummern))
    alle_warnungen = _eindeutig(hoer.warnungen, warnungen)
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
        ansage_stimme=ansager if ansagen else None,
    )
    return Ergebnis(dateien=dateien, bericht=bericht, warnungen=alle_warnungen, dauer_s=dauer_s)
