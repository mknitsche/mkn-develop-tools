"""Fotos, Screenshots und Seitenbilder lesen.

**Zwei Wege, ein Ergebnis.** Das Bildmodell liest ein Seitenbild in Lesereihenfolge
(Spalten, Kästen, Bildunterschriften) und ist der bessere Weg, kostet aber einen Aufruf
je Bild. Die lokale Texterkennung (tesseract) kostet nichts und bleibt auf dem Rechner,
liest aber nur Zeilen. Das Paket nimmt das Modell, solange es da ist und die Seitenzahl
klein bleibt, und die Texterkennung sonst -- ein Scan-Buch mit Hunderten Seiten soll
nicht Hunderte Bilder an ein Modell schicken.

**Erkannt wird am Dateikopf, nicht an der Endung.** Ein PNG mit der Endung `.jpg` würde
vom Modell-Dienst abgewiesen; die Endung wird nur gebraucht, um zu wissen, dass eine
Bilddatei gemeint ist.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pymupdf

from mkn_audio.lesen.text import (
    Befunde,
    absaetze_aus_text,
    baue_kapitel,
    normalisiere,
    pruefe_text_da,
)
from mkn_audio.typen import Dokument, Mp4Fehler, Textmodell

OCR_ZEITGRENZE_S = 120
"""Zeitgrenze je Aufruf von tesseract: eine fremde Datei darf den Lauf nicht festhalten."""

MAX_BILD_BYTES = 4_000_000
"""Groesser wird kein Bild an das Modell geschickt (Anbieter lehnen ab ca. 5 MB ab)."""

HOECHSTE_KANTE = 2000
"""Laengste Kante in Pixeln, auf die ein zu grosses Bild verkleinert wird."""

PROMPT = (
    "Lies den Text auf diesem Bild so, wie ein Mensch ihn vorlesen würde. "
    "Gib ihn in der Lesereihenfolge wieder: bei mehreren Spalten erst die ganze linke, "
    "dann die rechte Spalte; Überschriften stehen vor ihrem Text, Bildunterschriften "
    "nach dem Bild, Kästen nach dem Haupttext. "
    "Erfinde nichts, ergänze nichts, fasse nichts zusammen und ändere keine Zahl und "
    "keinen Namen; was nicht lesbar ist, lass weg. Zeilenumbrüche innerhalb eines "
    "Absatzes sind keine Absätze: trenne Absätze und Überschriften jeweils durch eine "
    "Leerzeile. Gib nur den Text aus, ohne Einleitung und ohne Anmerkung."
)

_ENDUNGEN_HEIC = (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1")


def ocr(png: bytes, sprache: str) -> str:
    """Liest ein Bild mit tesseract; fehlt das Programm, bricht es laut ab.

    Kein stiller Ersatz: ohne Texterkennung gaebe es fuer ein Scan-Buch gar keinen Text,
    und ein leeres Hoerstueck sieht nach Erfolg aus.
    """
    befehl = ["tesseract", "stdin", "stdout", "-l", sprache]
    try:
        ergebnis = subprocess.run(
            befehl, input=png, capture_output=True, timeout=OCR_ZEITGRENZE_S, check=False
        )
    except FileNotFoundError:
        raise Mp4Fehler(
            "tesseract nicht gefunden (Texterkennung noetig fuer Bilder ohne Bildmodell "
            "und fuer gescannte PDFs ueber der Seitengrenze)"
        ) from None
    except subprocess.TimeoutExpired:
        raise Mp4Fehler(f"tesseract: Zeitgrenze von {OCR_ZEITGRENZE_S} s ueberschritten") from None
    if ergebnis.returncode != 0:
        grund = ergebnis.stderr.decode("utf-8", "replace").strip()[-300:]
        raise Mp4Fehler(f"tesseract fehlgeschlagen (Exit {ergebnis.returncode}): {grund}")
    return ergebnis.stdout.decode("utf-8", "replace").strip()


def lies_mit_modell(textmodell: Textmodell, daten: bytes, mime: str) -> list[str]:
    """Laesst das Bildmodell ein Bild lesen; die Antwort wird zu Absaetzen."""
    return absaetze_aus_text(textmodell(PROMPT, ((mime, daten),)))


def lies_mit_ocr(png: bytes, sprache: str) -> list[str]:
    return absaetze_aus_text(ocr(png, sprache))


def seitenliste(nummern: list[int]) -> str:
    """`[1, 2, 3, 7]` -> `Seiten 1-3, 7` (Seitennummern ab 1)."""
    gruppen: list[str] = []
    i = 0
    while i < len(nummern):
        j = i
        while j + 1 < len(nummern) and nummern[j + 1] == nummern[j] + 1:
            j += 1
        gruppen.append(str(nummern[i]) if i == j else f"{nummern[i]}-{nummern[j]}")
        i = j + 1
    return ("Seite " if len(nummern) == 1 else "Seiten ") + ", ".join(gruppen)


# ---- Bilddateien --------------------------------------------------------------------


def _art(daten: bytes) -> str:
    """`png`, `jpeg` oder `heic` nach den ersten Bytes, sonst Fehler."""
    if daten.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if daten.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if daten[4:8] == b"ftyp" and daten[8:12] in _ENDUNGEN_HEIC:
        return "heic"
    raise Mp4Fehler("keine lesbare Bilddatei (weder PNG noch JPEG noch HEIC)")


def _heic_zu_jpeg(daten: bytes) -> bytes:
    """Wandelt HEIC mit einem vorhandenen Programm in JPEG: `sips`, `heif-convert`, `ffmpeg`.

    Modell-Dienste nehmen kein HEIC. Das Paket bringt keinen eigenen Decoder mit. Die
    Reihenfolge folgt der Verlaesslichkeit: `sips` (nur macOS) liest jedes iPhone-Foto;
    `heif-convert` (Paket `libheif-examples`) ist der Weg auf einem Linux-Server, weil das
    ffmpeg dort (6.1) HEIC aus iPhones nicht lesen kann; `ffmpeg` bleibt fuer Faelle, in
    denen es mit HEIF-Unterstuetzung gebaut ist. Liefert keiner ein Bild, nennt der Fehler
    alle drei Wege, statt dass das Foto unlesbar durchrutscht.
    """
    with tempfile.TemporaryDirectory() as ordner:
        quelle, ziel = Path(ordner, "in.heic"), Path(ordner, "aus.jpg")
        quelle.write_bytes(daten)
        versuche = {
            "sips": ["sips", "-s", "format", "jpeg", str(quelle), "--out", str(ziel)],
            "heif-convert": ["heif-convert", "-q", "90", str(quelle), str(ziel)],
            "ffmpeg": ["ffmpeg", "-v", "error", "-i", str(quelle), "-frames:v", "1", str(ziel)],
        }
        for name, befehl in versuche.items():
            if not shutil.which(name):
                continue
            try:
                subprocess.run(befehl, capture_output=True, timeout=OCR_ZEITGRENZE_S, check=False)
            except subprocess.TimeoutExpired:
                continue
            if ziel.is_file() and ziel.stat().st_size:
                return ziel.read_bytes()
    raise Mp4Fehler(
        "HEIC nicht lesbar: weder sips (macOS) noch heif-convert (Paket libheif-examples) "
        "noch ffmpeg mit HEIF-Unterstuetzung hat ein Bild geliefert"
    )


def _verkleinere(daten: bytes, art: str) -> tuple[bytes, str]:
    """Verkleinert ein zu grosses Bild als JPEG, damit der Modell-Dienst es annimmt."""
    with pymupdf.open(stream=daten, filetype=art) as doc:
        seite = doc[0]
        faktor = min(1.0, HOECHSTE_KANTE / max(seite.rect.width, seite.rect.height))
        bild = seite.get_pixmap(matrix=pymupdf.Matrix(faktor, faktor), alpha=False)
        return bild.tobytes("jpeg", jpg_quality=85), "jpeg"


def lade_bild(pfad: Path) -> tuple[bytes, str]:
    """Liest eine Bilddatei und gibt `(Bytes, MIME-Typ)` fuer das Modell zurueck."""
    daten = pfad.read_bytes()
    try:
        art = _art(daten)
    except Mp4Fehler as fehler:
        raise Mp4Fehler(f"{fehler}: {pfad.name}") from None
    if art == "heic":
        daten, art = _heic_zu_jpeg(daten), "jpeg"
    if len(daten) > MAX_BILD_BYTES:
        daten, art = _verkleinere(daten, art)
    return daten, f"image/{art}"


def lies_bild(pfad: Path, *, textmodell: Textmodell | None, ocr_sprache: str) -> Dokument:
    """Liest ein Foto oder einen Screenshot; ohne Bildmodell liest tesseract."""
    daten, mime = lade_bild(pfad)
    befunde = Befunde()
    if textmodell is not None:
        absaetze = lies_mit_modell(textmodell, daten, mime)
    else:
        befunde.warne(f"kein Bildmodell: lokale Texterkennung ({ocr_sprache}) statt dessen")
        absaetze = lies_mit_ocr(daten, ocr_sprache)
    titel = normalisiere(pfad.stem)
    dok = Dokument(
        titel=titel,
        autor=None,
        sprache="de",
        kapitel=baue_kapitel([(None, absaetze)], vorspann=titel, befunde=befunde),
        warnungen=befunde.alle(),
    )
    return pruefe_text_da(dok, pfad, "Bild")
