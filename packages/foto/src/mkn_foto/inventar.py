"""Liest einen Bild-Baum und fasst RAW und JPEG zu Aufnahmen zusammen.

Die Einheit ist die Belichtung, nicht die Datei: eine Aufnahme kann als RAW,
als JPEG oder als beides vorliegen und wird durchgehend gleich behandelt.
Anwender ist die Pipeline.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from mkn_foto import exif
from mkn_foto.modell import Aufnahme

_LOG = logging.getLogger(__name__)

BILD_ENDUNGEN = frozenset({".NEF", ".RAF", ".JPG", ".JPEG", ".HEIC", ".MOV"})

# Ordner, die im Zielbaum neben den Tagen liegen und keine Aufnahmen enthalten.
UEBERSPRUNGEN = frozenset({"_bericht", "_Rejected"})

# Endungen, deren EXIF die Aufnahme fuehrt: die MakerNotes des RAW tragen die
# Serienangabe der Kamera, das beigelegte JPEG nicht.
_ROHFORMATE = frozenset({".NEF", ".RAF"})

_ZEITFORMAT = "%Y:%m:%d %H:%M:%S"

_Schluessel = tuple[datetime, str, str]


def lies_baum(wurzel: Path) -> list[Aufnahme]:
    """Sammelt alle Aufnahmen unterhalb von `wurzel`, chronologisch sortiert.

    Gepaart wird ueber (Aufnahmezeitpunkt, Kamera, Stamm) — NICHT ueber den
    Stamm allein. Kameras zaehlen vierstellig und beginnen nach 9999 wieder
    bei 0001; ueber einen laengeren Bestand ist der Stamm damit nicht
    eindeutig, und zwei fremde Belichtungen fielen zusammen.
    """
    pfade = sorted(_bilddateien(wurzel))
    dateien_je_schluessel: dict[_Schluessel, dict[str, Path]] = {}
    exif_je_schluessel: dict[_Schluessel, dict[str, Any]] = {}

    for pfad, felder in zip(pfade, exif.lies(pfade), strict=True):
        roh = felder.get("EXIF:DateTimeOriginal")
        if not roh:
            # Laut, nicht leise: ohne Zeitpunkt faellt die Datei aus dem
            # gesamten Lauf — sie wird nicht falsch benannt, sie fehlt.
            _LOG.warning("ohne DateTimeOriginal, uebersprungen: %s", pfad)
            continue
        zeitpunkt = datetime.strptime(roh, _ZEITFORMAT)
        kuerzel = exif.kamera_kuerzel(felder["EXIF:Model"])
        endung = pfad.suffix.upper()

        schluessel = (zeitpunkt, kuerzel, pfad.stem)
        dateien_je_schluessel.setdefault(schluessel, {})[endung] = pfad
        if schluessel not in exif_je_schluessel or endung in _ROHFORMATE:
            exif_je_schluessel[schluessel] = felder

    aufnahmen = [
        Aufnahme(
            zeitpunkt=zeitpunkt,
            kamera=kamera,
            stamm=stamm,
            dateien=dateien,
            exif=exif_je_schluessel[(zeitpunkt, kamera, stamm)],
        )
        for (zeitpunkt, kamera, stamm), dateien in dateien_je_schluessel.items()
    ]
    return sorted(aufnahmen, key=lambda a: (a.zeitpunkt, a.stamm))


def _bilddateien(wurzel: Path) -> list[Path]:
    gefunden: list[Path] = []
    for pfad in wurzel.rglob("*"):
        if not pfad.is_file() or pfad.suffix.upper() not in BILD_ENDUNGEN:
            continue
        if pfad.name.startswith("."):
            continue
        if any(teil.name in UEBERSPRUNGEN for teil in pfad.parents):
            continue
        gefunden.append(pfad)
    return gefunden
