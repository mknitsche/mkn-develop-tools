"""Verpacken: M4B mit Kapitelmarken, MP3 je Kapitel und die Namen der Ausgabedateien.

**Warum M4B der Standard ist.** Eine Datei je Quelle mit Kapitelmarken, Titel, Autor und
Cover: Apple Books und BookPlayer setzen genau dort fort, wo man aufgehoert hat. MP3 je
Kapitel bleibt fuer Geraete ohne M4B. AAC mono, weil das Modell mono spricht -- Stereo
braechte nur kuenstlichen Raumklang.

**Kapitel ohne Riesen-WAV.** Die Kapitel-WAVs werden nicht zu einer Datei zusammengelegt
(ein 40-Stunden-Hoerbuch waere 7 GB, ueber dem 4-GB-Limit des WAV-Formats), sondern ffmpeg
liest sie ueber seine Konkatenations-Liste hintereinander. Die Kapitelzeiten stammen aus
den exakten Frame-Zahlen der WAVs, nicht aus einer Schaetzung.

**Namen.** `JJJJ-MM-TT <Titel>_vNN<Endung>`: der Titel in NFC (ein Name in NFD sieht auf
einem Mac gleich aus, ist aber ein anderer Name -- und unsichtbar fuer den Finder am NAS),
die Nummer zaehlt bestehende Dateien, damit ein zweiter Lauf nie ein Ergebnis ueberschreibt.
"""

from __future__ import annotations

import re
import unicodedata
import wave
from collections.abc import Sequence
from pathlib import Path

from mkn_audio.mastern import (
    SAMPLERATE,
    atomar,
    existiert,
    ffmpeg,
    pruefe_format,
    schreibe_stille,
    temp_ordner,
    zeitgrenze,
)
from mkn_audio.typen import Dokument, Mp4Fehler

GENRE = "H\u00f6rbuch"
"""Das Genre-Tag; Apple Books sortiert danach (Umlaut als Escape: ASCII-Quelltext)."""

_STRICH = "\N{EN DASH}"
"""Gedankenstrich im MP3-Namen: `<Titel> - NN <Kapiteltitel>`."""

_TITEL_ZEICHEN = 120
_TITEL_BYTES = 140
_NAME_BYTES = 240
"""Dateinamen sind auf 255 Bytes begrenzt (ext4 auf einem Linux-Server); 15 bleiben fuer die
Temporaer-Endung `.teil` und Reserve. Umlaute zaehlen 2 Bytes, Titel 3."""

_SPITZE = (
    f"aresample={4 * SAMPLERATE},alimiter=limit=0.7079:level=false:latency=true,"
    f"aresample={SAMPLERATE}"
)
"""Spitzen vor der verlustbehafteten Kodierung auf -3 dBFS, vierfach ueberabgetastet (nahe am
True Peak), ohne Pegelausgleich und ohne Versatz (die Kapitelmarken bleiben). Der Kodierer
setzt Ueberschwinger auf die gemasterten Kapitel (True Peak -1,1 bis -1,5 dBTP): gemessen
an echten Hoerbuechern AAC 64 kbit/s bis +4,4 dBTP, MP3 64 kbit/s bis +0,3 dBTP."""

_AAC = ("-c:a", "aac", "-b:a", "80k", "-aac_pns", 0)
"""AAC fuer die M4B. Gegen die Ueberschwinger reicht `_SPITZE` allein nicht: die
Rausch-Ersetzung (PNS) machte aus Hochton-Stoessen Spitzen von +6 dB ueber der Quelle, und
64 kbit/s blies harte Einsaetze auf. Mit allen drei Massnahmen blieben drei echte Hoerbuecher
bei -2,0 bis -2,4 dBTP und -16,2 bis -16,5 LUFS (64 kbit/s ohne PNS: harte Stoesse +2,7)."""

_DATUM = re.compile(r"\d{4}-\d{2}-\d{2}")
_VERBOTEN = re.compile(r"[/:\x00-\x1f\x7f]")


# -- Namen ----------------------------------------------------------------------------


def _kuerze(text: str, zeichen: int, bytes_: int) -> str:
    """Kuerzt auf `zeichen` Zeichen und `bytes_` UTF-8-Bytes (nie mitten im Zeichen)."""
    text = text[:zeichen]
    while len(text.encode()) > bytes_:
        text = text[:-1]
    return text.rstrip()


def _sauber(text: str) -> str:
    """NFC, ohne `/` `:` und Steuerzeichen (zu Leerzeichen), Leerraum zusammengezogen."""
    text = _VERBOTEN.sub(" ", unicodedata.normalize("NFC", text))
    return " ".join(text.split())


def ausgabe_name(ordner: Path, datum: str, titel: str, endung: str, zusatz: str = "") -> Path:
    """`JJJJ-MM-TT <Titel>[ <zusatz>]_vNN<endung>` -- die erste Nummer, die es noch nicht gibt.

    Titel auf 120 Zeichen gekuerzt; der Zusatz (etwa Kapitelnummer und -titel im MP3-Namen)
    bekommt den Rest bis zur Byte-Grenze des Dateisystems. `datum` reicht der Aufrufer aus
    einem Werkzeug herein (HC-11), hier wird nur seine Form geprueft.
    """
    if not _DATUM.fullmatch(datum):
        raise Mp4Fehler(f"Datum muss JJJJ-MM-TT sein (ist {datum!r})")
    if not endung.startswith(".") or len(endung) < 2:
        raise Mp4Fehler(f"Endung muss mit Punkt beginnen (ist {endung!r})")
    titel = _kuerze(_sauber(titel), _TITEL_ZEICHEN, _TITEL_BYTES)
    if not titel:
        raise Mp4Fehler("Titel fuer den Dateinamen ist leer")
    zusatz = _sauber(zusatz)
    rest = _NAME_BYTES - len(f"{datum} {titel} _v99{endung}".encode())
    zusatz = _kuerze(zusatz, 10_000, rest)
    stamm = f"{datum} {titel}" + (f" {zusatz}" if zusatz else "")
    nr = 1
    while existiert(ordner / f"{stamm}_v{nr:02d}{endung}"):
        nr += 1
    return ordner / f"{stamm}_v{nr:02d}{endung}"


# -- Cover und Metadaten --------------------------------------------------------------


def _bild_endung(daten: bytes) -> str:
    """Dateiendung nach dem Kopf der Bilddaten; was ffmpeg nicht als Cover einbetten kann,
    bricht laut (ein Hoerbuch ohne das Cover, das die Quelle hatte, soll nicht still
    entstehen)."""
    if daten.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if daten.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if daten.startswith((b"GIF87a", b"GIF89a")) or daten[8:12] == b"WEBP":
        return ".konv"  # wird nach JPEG gewandelt
    raise Mp4Fehler("Cover: kein JPEG, PNG, GIF oder WebP")


def _cover_datei(cover: bytes | None, werk: Path) -> Path | None:
    """Schreibt das Cover als JPEG/PNG in `werk`; GIF und WebP werden nach JPEG gewandelt
    (MP4 und ID3 betten nur diese beiden Bildarten ein)."""
    if cover is None:
        return None
    endung = _bild_endung(cover)
    if endung != ".konv":
        pfad = werk / f"cover{endung}"
        pfad.write_bytes(cover)
        return pfad
    roh = werk / "cover-roh"
    roh.write_bytes(cover)
    jpg = werk / "cover.jpg"
    ffmpeg("-i", roh, "-frames:v", 1, "-q:v", 2, jpg, zeit_s=60)
    return jpg


def _einzeilig(text: str) -> str:
    return " ".join(text.split())


def _meta_wert(text: str) -> str:
    """Maskiert einen Wert fuer ffmetadata (`=`, `;`, `#`, `\\` und Zeilenumbruch)."""
    return re.sub(r"([=;#\\])", r"\\\1", _einzeilig(text))


def _tags(dok: Dokument) -> list[tuple[str, str]]:
    tags = [("title", dok.titel)]
    if dok.autor:
        tags.append(("artist", dok.autor))
    tags += [("album", dok.titel), ("genre", GENRE)]
    return tags


# -- M4B ------------------------------------------------------------------------------


def _kapitel_zeiten(
    kapitel: Sequence[tuple[str, Path]], pause_kapitel: float
) -> tuple[list[tuple[int, int]], float]:
    """((Start, Ende) in ms je Kapitel, Gesamtdauer in s).

    Das Ende eines Kapitels ist der Start des naechsten: die Pause gehoert zum
    vorigen Kapitel, so liegt jede Kapitelmarke genau auf dem ersten gesprochenen Wort.
    """
    dauern = [pruefe_format(wav) / SAMPLERATE for _, wav in kapitel]
    starts, t = [], 0.0
    for d in dauern:
        starts.append(t)
        t += d + pause_kapitel
    gesamt = t - pause_kapitel
    ms = [round(s * 1000) for s in starts]
    enden = [*ms[1:], round(gesamt * 1000)]
    return list(zip(ms, enden, strict=True)), gesamt


def _liste_zeile(pfad: Path) -> str:
    return "file '" + str(pfad.resolve()).replace("'", "'\\''") + "'\n"


def m4b(
    kapitel: Sequence[tuple[str, Path]],
    dok: Dokument,
    ziel: Path,
    *,
    pause_kapitel: float,
) -> Path:
    """Packt die Kapitel-WAVs in eine `.m4b` (AAC mono 80 kbit/s, 24 kHz) mit Kapitelmarken.

    `kapitel` sind `(Titel, WAV)` in Lesereihenfolge; zwischen ihnen liegen
    `pause_kapitel` Sekunden Stille. Titel, Autor, Album und Genre kommen als Tags, das
    Cover (falls vorhanden) als `attached_pic`; `faststart` legt den Index nach vorn,
    damit ein Player die Datei schon beim Laden bedienen kann.
    """
    if not kapitel:
        raise Mp4Fehler("M4B ohne Kapitel kann nicht gepackt werden")
    zeiten, gesamt = _kapitel_zeiten(kapitel, pause_kapitel)
    with temp_ordner(ziel.parent) as werk_name:
        werk = Path(werk_name)
        cover = _cover_datei(dok.cover, werk)
        zeilen = []
        stille = werk / "stille.wav"
        if len(kapitel) > 1 and pause_kapitel > 0:
            with wave.open(str(stille), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SAMPLERATE)
                schreibe_stille(w, pause_kapitel)
        for i, (_, wav) in enumerate(kapitel):
            if i and pause_kapitel > 0:
                zeilen.append(_liste_zeile(stille))
            zeilen.append(_liste_zeile(wav))
        liste = werk / "liste.txt"
        liste.write_text("".join(zeilen), encoding="utf-8")

        meta = [";FFMETADATA1\n"]
        meta += [f"{schluessel}={_meta_wert(wert)}\n" for schluessel, wert in _tags(dok)]
        for (titel, _), (start, ende) in zip(kapitel, zeiten, strict=True):
            meta.append(
                f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={start}\nEND={ende}\n"
                f"title={_meta_wert(titel)}\n"
            )
        metadatei = werk / "meta.txt"
        metadatei.write_text("".join(meta), encoding="utf-8")

        eingaben = ["-f", "concat", "-safe", "0", "-i", liste, "-i", metadatei]
        zuordnung = ["-map", "0:a", "-map_metadata", "1", "-map_chapters", "1"]
        bild: list[str | Path] = []
        if cover is not None:
            eingaben += ["-i", cover]
            zuordnung += ["-map", "2:v"]
            bild = ["-c:v", "copy", "-disposition:v", "attached_pic"]
        with atomar(ziel) as tmp:
            ffmpeg(
                *eingaben, *zuordnung,
                *("-af", _SPITZE), *_AAC, *("-ac", 1, "-ar", SAMPLERATE),
                *bild, *("-movflags", "+faststart", "-f", "ipod", tmp),
                zeit_s=zeitgrenze(gesamt),
            )  # fmt: skip
    return ziel


# -- MP3 ------------------------------------------------------------------------------


def mp3(
    kapitel: Sequence[tuple[str, Path]],
    dok: Dokument,
    ziel_ordner: Path,
    *,
    datum: str,
) -> tuple[Path, ...]:
    """Eine MP3 je Kapitel (64 kbit/s mono, ID3v2.3) mit Titel, Album, Autor, Track, Cover.

    Name: `JJJJ-MM-TT <Titel> - NN <Kapiteltitel>_vNN.mp3`. Die Reihenfolge der Dateien im
    Ergebnis ist die der Kapitel.
    """
    if not kapitel:
        raise Mp4Fehler("MP3 ohne Kapitel kann nicht gepackt werden")
    ergebnis = []
    with temp_ordner(ziel_ordner) as werk_name:
        cover = _cover_datei(dok.cover, Path(werk_name))
        for nr, (titel, wav) in enumerate(kapitel, 1):
            ziel = ausgabe_name(
                ziel_ordner, datum, dok.titel, ".mp3", zusatz=f"{_STRICH} {nr:02d} {titel}"
            )
            tags = {
                "title": titel,
                "album": dok.titel,
                "genre": GENRE,
                "track": f"{nr}/{len(kapitel)}",
            }
            if dok.autor:
                tags["artist"] = dok.autor
            eingaben: list[str | Path] = ["-i", wav]
            zuordnung: list[str | Path] = ["-map", "0:a"]
            bild: list[str | Path] = []
            if cover is not None:
                eingaben += ["-i", cover]
                zuordnung += ["-map", "1:v"]
                bild = [
                    *("-c:v", "copy", "-metadata:s:v", "title=Album cover"),
                    *("-disposition:v", "attached_pic"),
                ]
            meta = [arg for k, v in tags.items() for arg in ("-metadata", f"{k}={_einzeilig(v)}")]
            with atomar(ziel) as tmp:
                ffmpeg(
                    *eingaben, *zuordnung, *meta,
                    *("-af", _SPITZE),
                    *("-c:a", "libmp3lame", "-b:a", "64k", "-ac", 1, "-ar", SAMPLERATE),
                    *bild, *("-id3v2_version", 3, "-f", "mp3", tmp),
                    zeit_s=zeitgrenze(pruefe_format(wav) / SAMPLERATE),
                )  # fmt: skip
            ergebnis.append(ziel)
    return tuple(ergebnis)
