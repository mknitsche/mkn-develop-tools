"""Liest eine GPX-Spur und loest ihre Zeiten in Kamerazeit auf.

Quelle ist ein Export aus einem Reisetagebuch (Profil → Reise → Bearbeiten →
Route als GPX herunterladen). Das Werkzeug meldet sich an keinem Konto an: die
Datei legt der Anwender selbst ab. Anwender dieses Moduls ist `ort`.

Die Zeit ist hier der teure Teil, nicht der Ort. GPX traegt UTC, das Kamera-EXIF
traegt lokale Zeit ohne Zone. Liegt die Umrechnung eine Stunde daneben, bekommt
jedes Bild eine Koordinate, die plausibel aussieht und falsch ist.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from mkn_foto.modell import Anker

_LOG = logging.getLogger(__name__)

_NS = {"gpx": "http://www.topografix.com/GPX/1/1"}

# Aufgeloest wird ueber die Zonendatenbank, nicht ueber einen festen Versatz:
# der waere ueber einen Zeitumstellungs-Tag hinweg falsch — und zwar genau an
# dem Tag, an dem niemand damit rechnet.
_STANDARDZONE = "Europe/Berlin"


def lies(pfad: Path) -> tuple[list[Anker], list[Anker]]:
    """Gibt (Spurpunkte, Wegpunkte) zurueck, je chronologisch sortiert."""
    wurzel = ElementTree.parse(pfad).getroot()
    spur = [p for kind in wurzel.findall(".//gpx:trkpt", _NS) if (p := _zu_punkt(kind)) is not None]
    wege = [p for kind in wurzel.findall("gpx:wpt", _NS) if (p := _zu_punkt(kind)) is not None]
    return sorted(spur, key=_nach_zeit), sorted(wege, key=_nach_zeit)


def in_kamerazeit(p: Anker, zone: str = _STANDARDZONE) -> datetime:
    """Rechnet die UTC-Zeit eines Punkts in zonenlose lokale Zeit um.

    Das Ergebnis ist direkt mit `Aufnahme.zeitpunkt` vergleichbar — der ist
    zonenlos, so wie die Zeit im EXIF steht.
    """
    return p.zeit.astimezone(ZoneInfo(zone)).replace(tzinfo=None)


def _zu_punkt(kind) -> Anker | None:
    zeit_text = _text(kind, "time")
    if zeit_text is None:
        # Fuer die Zeitzuordnung wertlos, aber kein Grund zum Abbruch. Gemeldet
        # wird er trotzdem: eine Spur, die still schrumpft, faellt erst auf,
        # wenn am Ende Bilder ohne Ort dastehen.
        _LOG.warning(
            "GPX-Anker ohne Zeit, uebergangen: lat=%s lon=%s", kind.get("lat"), kind.get("lon")
        )
        return None
    return Anker(
        zeit=datetime.fromisoformat(zeit_text),
        lat=float(kind.get("lat")),
        lon=float(kind.get("lon")),
        name=_text(kind, "name"),
    )


def _text(kind, tag: str) -> str | None:
    treffer = kind.find(f"gpx:{tag}", _NS)
    return treffer.text if treffer is not None else None


def _nach_zeit(p: Anker) -> datetime:
    return p.zeit
