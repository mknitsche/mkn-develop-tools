"""Bestimmt den Ort einer Aufnahme und wie belastbar er ist.

Der teure Fehler ist hier nicht die fehlende Ortsangabe, sondern die zu
GENAUE. Eine Koordinate mit engem Radius sieht aus wie eine Messung; steht
sie erst in der Datei, ist ihr nicht mehr anzusehen, dass sie geraten war.
Deshalb fuehrt jeder Ort seinen eigenen Fehlerradius mit.

Die Grundschranke ist immer die ZEIT: weiter als Gehgeschwindigkeit mal
verstrichener Zeit kann niemand gekommen sein. Raeumliche Naehe darf diese
Schranke nur VERENGEN, nie ersetzen — bei einer Rundwanderung stehen Anfang
und Ende am selben Punkt, und eine rein raeumliche Regel gaebe dem Bild vom
entferntesten Punkt der Route die Startkoordinate mit einem Radius nahe null.

Anwender ist die Pipeline.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

from mkn_foto import gpx
from mkn_foto.gpx import Punkt
from mkn_foto.modell import Aufnahme, Ort

_GEHGESCHWINDIGKEIT_M_S = 1.4  # 5 km/h

# Ab wann eine Spur "dicht" ist und ihre raeumliche Ausdehnung mitreden darf.
_DICHT_MIN_PUNKTE = 3
_DICHT_MAX_LUECKE_S = 300

# Feiner als das ist eine erfundene Praezision: GPS selbst liegt bei rund 10 m,
# und der Anker beschreibt den Standort des Geraets, nicht den des Motivs.
_RADIUS_MIN_M = 25

# Die eigentliche Grenze der Aussage. Sie deckelt zugleich den Radius: mehr als
# _FENSTER_S * _GEHGESCHWINDIGKEIT_M_S kann nicht herauskommen. Eine zusaetzliche
# Radius-Obergrenze stand im Entwurf und waere toter Code gewesen — 15 Minuten
# ergeben hoechstens 1260 m, die vorgesehene Schranke lag bei 5000. Ihr Test
# bestand denn auch aus einem anderen Grund: sein Punkt lag ausserhalb des
# Fensters und fiel schon hier heraus.
_FENSTER_S = 900

_ERDRADIUS_M = 6_371_000.0


def bestimme(a: Aufnahme, spur: Sequence[Punkt], wege: Sequence[Punkt]) -> Ort | None:
    """Ort der Aufnahme, oder None wenn keine belastbare Aussage moeglich ist.

    Ein benannter Wegpunkt schlaegt die blosse Koordinate: er BENENNT den Ort,
    statt ihn zu vermessen. Der Radius gehoert dann aber auch zu IHM und nicht
    zu einem naeheren Spurpunkt — sonst behauptet die Datei eine Genauigkeit,
    die fuer die gemeldete Koordinate nie galt.
    """
    fenster = _im_fenster(a, [*spur, *wege])
    if not fenster:
        return None

    benannt = _zeitlich_naechster(a, [p for p in fenster if p.name])
    gewaehlt = benannt if benannt is not None else _zeitlich_naechster(a, fenster)

    radius = _radius_um(a, gewaehlt, fenster)
    return Ort(
        lat=gewaehlt.lat,
        lon=gewaehlt.lon,
        radius_m=radius,
        name=gewaehlt.name,
        quelle="gpx" if gewaehlt.name else "anker",
    )


def _radius_um(a: Aufnahme, gewaehlt: Punkt, fenster: Sequence[Punkt]) -> int:
    """Wie weit die Aufnahme vom gewaehlten Punkt entfernt sein kann."""
    zeitschranke = abs(_abstand_s(a, gewaehlt)) * _GEHGESCHWINDIGKEIT_M_S
    radius = zeitschranke
    if _ist_dicht(fenster):
        radius = min(zeitschranke, _spannweite_m(fenster))
    return round(max(radius, _RADIUS_MIN_M))


def _zeitlich_naechster(a: Aufnahme, punkte: Sequence[Punkt]) -> Punkt | None:
    """Der zeitlich naechste — nicht der erste in der Datei."""
    return min(punkte, key=lambda p: abs(_abstand_s(a, p))) if punkte else None


def _abstand_s(a: Aufnahme, p: Punkt) -> float:
    return (gpx.in_kamerazeit(p) - a.zeitpunkt).total_seconds()


def _im_fenster(a: Aufnahme, punkte: Sequence[Punkt]) -> list[Punkt]:
    return [p for p in punkte if abs(_abstand_s(a, p)) <= _FENSTER_S]


def _ist_dicht(fenster: Sequence[Punkt]) -> bool:
    """Genug Punkte UND keine grosse Lucke dazwischen.

    Beides ist noetig: drei Punkte, von denen zwei zusammenliegen und einer
    weit weg in der Zeit, beschreiben keinen engen Aufenthalt.
    """
    if len(fenster) < _DICHT_MIN_PUNKTE:
        return False
    zeiten = sorted(p.zeit for p in fenster)
    return all(
        (spaeter - frueher).total_seconds() <= _DICHT_MAX_LUECKE_S
        for frueher, spaeter in pairwise(zeiten)
    )


def _spannweite_m(fenster: Sequence[Punkt]) -> float:
    return max(_entfernung_m(a, b) for a in fenster for b in fenster)


def _entfernung_m(a: Punkt, b: Punkt) -> float:
    """Haversine — auf diesen Entfernungen genau genug."""
    phi1, phi2 = math.radians(a.lat), math.radians(b.lat)
    dphi = math.radians(b.lat - a.lat)
    dlam = math.radians(b.lon - a.lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * _ERDRADIUS_M * math.asin(math.sqrt(h))
