"""Bestimmt den Ort einer Foto-Session und wie belastbar er ist.

Die Einheit ist der SPOT, nicht das einzelne Bild. An einem Fleck koennen
Stunden vergehen; wer jedes Bild einzeln fragt „wo warst du in dieser
Sekunde", laesst mitten in einer langen Session Bilder unbestimmt, die von
hundert anderen mit demselben Ort umgeben sind.

Der teure Fehler ist nicht die fehlende Ortsangabe, sondern die zu GENAUE.
Eine Koordinate mit engem Radius sieht aus wie eine Messung; steht sie erst in
der Datei, ist ihr nicht mehr anzusehen, dass sie geraten war. Deshalb traegt
jeder Ort seinen Radius mit, und was nicht belegt ist, wird VORGESCHLAGEN
statt geschrieben (`quelle="vorschlag"`).

**Der Abgleich ist das Signal, nicht die Geschwindigkeit.** Zwei unabhaengige
Quellen — die GPS-Spur und die Handybilder — koennen einander widersprechen,
und genau dort sitzen die Fehler. Gemessen am 26.08.: ein Spurpunkt 3383 m
abseits, zwischen zwei Handybildern, die 3 m auseinanderliegen. Eine Regel
ueber Geschwindigkeit haette ihn durchgelassen, denn 3,4 km in dreieinhalb
Minuten sind mit dem Auto moeglich.

Anwender ist die Pipeline.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from mkn_foto import gpx
from mkn_foto.modell import Anker, Ort, Spot

# Feiner als das ist eine erfundene Praezision: GPS selbst liegt bei rund 10 m,
# und ein Anker beschreibt den Standort des Geraets, nicht den des Motivs.
_RADIUS_MIN_M = 25

# Darueber benennt eine Koordinate keinen Ort mehr, sondern eine Fahrt. Sie
# sieht trotzdem aus wie eine Messung — also nur Vorschlag.
_RADIUS_MAX_M = 500

# Wie viel von der Session die Anker zeitlich abdecken muessen. Gemessen: bei
# der Haelfte trennen sich die Faelle sauber — der Wasserfall-Spot vom 28.08.
# (119 Bilder ueber 26 Minuten, Anker nur in einem Moment davon) faellt
# heraus, die durchgehend begleiteten Sessions bleiben.
_ABDECKUNG_MIN = 0.5

# Ein Anker gilt als widerlegt, wenn der Umweg ueber ihn um dieses Vielfache
# laenger ist als der direkte Weg zwischen seinen Nachbarn. An der echten
# Woche gemessen: Faktor 10 verwirft 6 von 732 Ankern, alle offensichtlich
# falsch (935 bis 3383 m abseits bei Nachbarn 1 bis 79 m auseinander). Faktor
# 5 faengt bereits echte Bewegung ein.
_WIDERSPRUCH_FAKTOR = 10.0

_ERDRADIUS_M = 6_371_000.0


def fuer_spot(spot: Spot, anker: Sequence[Anker]) -> Ort | None:
    """Ort einer Session, oder None wenn kein Anker in ihr liegt."""
    drin = sorted(
        (a for a in anker if spot.von <= gpx.in_kamerazeit(a) <= spot.bis),
        key=lambda a: a.zeit,
    )
    if not drin:
        return None

    rein = verwirf_widerlegte(drin)
    lat = sum(a.lat for a in rein) / len(rein)
    lon = sum(a.lon for a in rein) / len(rein)
    mitte = Anker(zeit=rein[0].zeit, lat=lat, lon=lon, name=None)
    radius = max(_entfernung_m(mitte, a) for a in rein)
    radius = round(max(radius, _RADIUS_MIN_M))

    benannt = min((a for a in rein if a.name), key=lambda a: _entfernung_m(mitte, a), default=None)
    belegt = radius <= _RADIUS_MAX_M and _abdeckung(spot, rein) >= _ABDECKUNG_MIN
    return Ort(
        lat=lat,
        lon=lon,
        radius_m=radius,
        name=benannt.name if benannt else None,
        quelle=("gpx" if benannt else "anker") if belegt else "vorschlag",
    )


def verwirf_widerlegte(
    anker: Sequence[Anker], *, faktor: float = _WIDERSPRUCH_FAKTOR
) -> list[Anker]:
    """Wirft Anker weg, denen ihre beiden Nachbarn widersprechen.

    Ein Anker ist widerlegt, wenn der Umweg ueber ihn um ein Vielfaches
    laenger ist als der direkte Weg zwischen seinen zeitlichen Nachbarn. Wer
    sich wirklich fortbewegt, erzeugt keinen Umweg — dort liegen auch die
    Nachbarn weit auseinander.

    Unter drei Ankern kann nichts widerlegt werden: ein Widerspruch braucht
    einen Verdaechtigen UND zwei Nachbarn, die sich einig sind.
    """
    if len(anker) < 3:
        return list(anker)
    behalten = [anker[0]]
    for vorher, verdaechtig, nachher in zip(anker, anker[1:], anker[2:], strict=False):
        umweg = _entfernung_m(vorher, verdaechtig) + _entfernung_m(verdaechtig, nachher)
        direkt = max(_entfernung_m(vorher, nachher), _RADIUS_MIN_M)
        if umweg <= faktor * direkt:
            behalten.append(verdaechtig)
    behalten.append(anker[-1])
    return behalten


def _abdeckung(spot: Spot, anker: Sequence[Anker]) -> float:
    """Anteil der Session, den die Anker zeitlich umspannen.

    Drei Anker in einem einzigen Moment sagen ueber die uebrige Stunde nichts
    — und ein Fussmarsch zu einem Wasserfall fuehrt weg vom beobachteten Punkt.
    """
    dauer = (spot.bis - spot.von).total_seconds()
    if dauer <= 0:
        return 1.0
    spanne = (gpx.in_kamerazeit(anker[-1]) - gpx.in_kamerazeit(anker[0])).total_seconds()
    return spanne / dauer


def _entfernung_m(a: Anker, b: Anker) -> float:
    """Haversine — auf diesen Entfernungen genau genug."""
    phi1, phi2 = math.radians(a.lat), math.radians(b.lat)
    dphi = math.radians(b.lat - a.lat)
    dlam = math.radians(b.lon - a.lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * _ERDRADIUS_M * math.asin(math.sqrt(h))
