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

import datetime as dt
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

# Wie weit ueber die Sessiongrenze hinaus Anker noch zaehlen. Die Grenze ist
# der letzte Ausloeser, nicht der Moment des Aufbruchs: ein Anker wenige
# Minuten davor oder danach sagt sehr wohl, wo jemand waehrend der Session war.
# An der echten Woche gemessen liegen solche Randanker 18 bis 200 m vom
# Sessionmittelpunkt entfernt, und sie holen sechs Sessions mit 472 Bildern von
# der Entscheidungsliste zurueck.
#
# Der Wert ist KEINE gedrehte Schraube, sondern eine Bedingung: er muss
# schmaler sein als die halbe Session-Pause (`spots.PAUSE_S`), sonst koennen
# sich zwei benachbarte Sessions denselben Anker teilen. Firsthand: bei 15
# Minuten Rand faellt die Zahl belegter Bilder von 840 auf 669, weil Anker der
# Nachbarsession den Radius aufblaehen.
RAND_S = 300.0

# Ein Anker gilt als widerlegt, wenn der Umweg ueber ihn um dieses Vielfache
# laenger ist als der direkte Weg zwischen seinen Nachbarn. An der echten
# Woche gemessen: Faktor 10 verwirft 6 von 732 Ankern, alle offensichtlich
# falsch (935 bis 3383 m abseits bei Nachbarn 1 bis 79 m auseinander). Faktor
# 5 faengt bereits echte Bewegung ein.
_WIDERSPRUCH_FAKTOR = 10.0

_ERDRADIUS_M = 6_371_000.0


def fuer_spot(spot: Spot, anker: Sequence[Anker], *, rand_s: float = RAND_S) -> Ort | None:
    """Ort einer Session, oder None wenn kein Anker in ihrer Naehe liegt.

    Beruecksichtigt werden Anker der Session UND eines schmalen Randstreifens
    davor und danach — siehe `RAND_S`.
    """
    rand = dt.timedelta(seconds=rand_s)
    drin = sorted(
        (a for a in anker if spot.von - rand <= gpx.in_kamerazeit(a) <= spot.bis + rand),
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


def fasse_gleichen_ort_zusammen(
    sessions: Sequence[Spot], anker: Sequence[Anker], *, rand_s: float = RAND_S
) -> list[Spot]:
    """Fuegt zeitlich benachbarte Sessions zusammen, die am selben Ort liegen.

    Die Pause gehoert zum Ort. Wer an einem Spot ankommt, sich umsieht,
    ueberlegt und dann weiterfotografiert, erzeugt eine Luecke, die groesser
    ist als die Sessionschwelle — und trotzdem ist es EIN Spot. Die Zeit allein
    kann das nicht sehen; die Anker sehen es.

    Gemessen am 28.08.: zwei Sessions lagen 5 m auseinander, getrennt durch 19
    Minuten Pause. Der einzige solche Fall einer ganzen Fotowoche — die
    Zeitschwelle sitzt also gut, aber nicht perfekt.

    „Derselbe Ort" braucht keine eigene Zahl: er ist es, wenn die Mittelpunkte
    naeher beieinander liegen als der groessere der beiden Radien. Damit
    skaliert die Regel mit der Genauigkeit, die die Anker hergeben, statt eine
    Entfernung zu behaupten.
    """
    ergebnis: list[Spot] = []
    for spot in sessions:
        if ergebnis and _gleicher_ort(ergebnis[-1], spot, anker, rand_s):
            vereint = sorted(
                [*ergebnis[-1].aufnahmen, *spot.aufnahmen],
                key=lambda a: (a.zeitpunkt, a.stamm),
            )
            ergebnis[-1] = Spot(aufnahmen=tuple(vereint))
        else:
            ergebnis.append(spot)
    return ergebnis


def _gleicher_ort(a: Spot, b: Spot, anker: Sequence[Anker], rand_s: float) -> bool:
    """Beide Orte bestimmbar UND naeher als der groessere ihrer Radien?"""
    ort_a = fuer_spot(a, anker, rand_s=rand_s)
    ort_b = fuer_spot(b, anker, rand_s=rand_s)
    if ort_a is None or ort_b is None:
        return False
    abstand = _entfernung_m(
        Anker(zeit=a.von, lat=ort_a.lat, lon=ort_a.lon, name=None),
        Anker(zeit=b.von, lat=ort_b.lat, lon=ort_b.lon, name=None),
    )
    return abstand <= max(ort_a.radius_m, ort_b.radius_m)


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

    **Auch die RAENDER werden geprueft.** Ein Ausreisser ganz vorn oder ganz
    hinten hat nur einen Nachbarn, aber er ist deshalb nicht unverdaechtig: er
    wird gegen die beiden folgenden (bzw. vorangehenden) gehalten. Firsthand am
    28.08. gefunden — der erste Anker einer Session lag 935 m von allen
    dreizehn anderen entfernt, die untereinander auf 13 m uebereinstimmten. Die
    erste Fassung behielt ihn ungeprueft, und ein klar bestimmter Spot wurde
    dadurch zum Vorschlag.
    """
    if len(anker) < 3:
        return list(anker)
    behalten = []
    if not _rand_widerlegt(anker[0], anker[1], anker[2], faktor):
        behalten.append(anker[0])
    for vorher, verdaechtig, nachher in zip(anker, anker[1:], anker[2:], strict=False):
        umweg = _entfernung_m(vorher, verdaechtig) + _entfernung_m(verdaechtig, nachher)
        direkt = max(_entfernung_m(vorher, nachher), _RADIUS_MIN_M)
        if umweg <= faktor * direkt:
            behalten.append(verdaechtig)
    if not _rand_widerlegt(anker[-1], anker[-2], anker[-3], faktor):
        behalten.append(anker[-1])
    return behalten


def _rand_widerlegt(rand: Anker, nachbar: Anker, uebernaechster: Anker, faktor: float) -> bool:
    """Widerspricht das Paar hinter dem Randanker diesem Randanker?

    Der Randanker ist widerlegt, wenn er von seinem Nachbarn viel weiter weg
    ist, als dieser Nachbar von SEINEM Nachbarn — dann sind sich die beiden
    einig und der Rand steht allein. Wer sich wirklich fortbewegt, erzeugt
    dieses Bild nicht: dort liegen alle drei aehnlich weit auseinander.
    """
    schritt = _entfernung_m(rand, nachbar)
    folge = max(_entfernung_m(nachbar, uebernaechster), _RADIUS_MIN_M)
    return schritt > faktor * folge


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
