"""Position je BILD, interpoliert aus allen Ankerquellen — echtes Geotagging.

KT-1 am 2026-08-30: *"eigentlich hatte ich gehofft, du machst sinnvolle gpx (gps)
informationen, die man auf einer karte sieht"*.

Die erste Fassung gab ganzen Sessions eine Sammelkoordinate: 141 Bilder mit
demselben Punkt. Auf einer Karte ist das ein Punkt, keine Route. Dabei gibt die
Spur weit mehr her — gemessen an der echten Reise liegt der Median zwischen zwei
Spurpunkten bei **63 Sekunden**.

**Der Radius folgt der Spec § 5, nicht einer Annahme.** Die dortige Regel ist
ausdruecklich korrigiert worden, und die Korrektur ist der Kern:

- **Grundschranke ist die ZEIT.** Weiter als Gehgeschwindigkeit mal verstrichener
  Zeit kann niemand gekommen sein. Diese Schranke gilt immer.
- **Raeumliche Information darf nur verengen, nie ersetzen.** Der Gegenbeleg aus
  der Gate-Runde: bei einer Rundwanderung stehen Anfangs- und Endanker am selben
  Punkt. Wer den Radius aus ihrer Entfernung ableitet, gibt dem Bild vom
  entferntesten Punkt der Route die Startkoordinate mit einem Radius nahe null —
  exakt die erfundene Praezision, gegen die die Regel gebaut ist.
- Daraus folgt: **je dichter die Spur, desto enger jeder Radius.**

**Nicht extrapoliert.** Vor dem ersten und nach dem letzten Anker ist die Position
unbekannt, nicht "wie der naechste Punkt". Am 24.08. begann die Aufzeichnung
mitten am Tag, am 25.08. gibt es NULL Spurpunkte.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from datetime import datetime

from mkn_foto.modell import Anker, Aufnahme, Ort

QUELLE = "gpx"
"""Herkunft einer interpolierten Position. Nicht `vorschlag` — sie ist belegt."""

RADIUS_MIN_M = 15
"""Untergrenze. Auch ein Bild genau auf einem Spurpunkt steht nicht metergenau:
Handy-GPS streut, und die Kamerauhr geht nicht sekundengleich."""

RADIUS_MAX_M = 500
"""Darueber ist die Angabe wertlos -- dann lieber gar keine (Spec § 0a).

Diese Schranke traegt ALLEIN die Zusicherung "zu unsicher wird nicht
geschrieben". Eine fruehere Fassung hatte zusaetzlich eine Obergrenze fuer die
zeitliche Luecke; die sagte dasselbe, nur ungenauer, und machte beide
unfalsifizierbar -- keine Einzel-Mutation konnte die Zusicherung brechen, weil
die jeweils andere Pruefung einsprang. Dasselbe galt fuer einen `if not anker`
am Anfang, den der i==0-Zweig ohnehin abfaengt."""

DICHT_S = 180.0
"""Bis zu dieser Luecke gelten zwei Anker als zeitlich dicht -- nur dann darf
ihre raeumliche Naehe den Radius verengen. Drei Minuten Gehzeit sind rund 250 m;
darueber kann die Strecke dazwischen beliebig verlaufen sein, auch im Kreis.

Gemessen an der echten Spur liegt der Median-Abstand bei 63 s, das 75-Prozent-
Quantil bei 157 s -- die Verengung greift damit im Regelfall und faellt nur in
den Luecken aus, fuer die sie ohnehin nichts aussagt."""

GEHTEMPO_M_S = 1.4
"""Rund 5 km/h. Die Zeitschranke rechnet damit, wie weit jemand in der Luecke
gekommen sein KANN. Bewusst Gehtempo und nicht Autotempo: die Schranke soll die
Regel fuer den haeufigen Fall sein. Fuer Autofahrten wird sie zu eng und liefert
deshalb GAR KEINE Position statt einer falsch-engen -- das ist die richtige
Richtung (Spec § 0a: im Zweifel nicht schreiben)."""


def fuer_aufnahme(aufnahme: Aufnahme, anker: Sequence[Anker]) -> Ort | None:
    """Die Position zum Aufnahmezeitpunkt, oder None.

    `anker` muss chronologisch sortiert sein (`pipeline.anker_sammeln` liefert
    das so).
    """
    zeiten = [a.zeit for a in anker]
    i = bisect.bisect_left(zeiten, aufnahme.zeitpunkt)

    if i < len(anker) and anker[i].zeit == aufnahme.zeitpunkt:
        treffer = anker[i]
        return Ort(
            lat=treffer.lat,
            lon=treffer.lon,
            radius_m=RADIUS_MIN_M,
            name=treffer.name,
            quelle=QUELLE,
        )

    # Kein Extrapolieren: ausserhalb der Spur ist die Position unbekannt.
    if i == 0 or i >= len(anker):
        return None

    vorher, nachher = anker[i - 1], anker[i]
    luecke = (nachher.zeit - vorher.zeit).total_seconds()
    anteil = (aufnahme.zeitpunkt - vorher.zeit).total_seconds() / luecke
    lat = vorher.lat + (nachher.lat - vorher.lat) * anteil
    lon = vorher.lon + (nachher.lon - vorher.lon) * anteil

    radius = _radius(aufnahme.zeitpunkt, vorher, nachher)
    if radius > RADIUS_MAX_M:
        return None

    return Ort(lat=lat, lon=lon, radius_m=radius, name=None, quelle=QUELLE)


def _radius(zeitpunkt: datetime, vorher: Anker, nachher: Anker) -> int:
    """Zeitschranke, durch raeumliche Information nur VERENGT.

    Der naehere der beiden Nachbarn bestimmt die Schranke: weiter als von ihm
    aus in der verstrichenen Zeit erreichbar kann die Aufnahme nicht liegen.
    """
    abstand_s = min(
        abs((zeitpunkt - vorher.zeit).total_seconds()),
        abs((nachher.zeit - zeitpunkt).total_seconds()),
    )
    schranke = abstand_s * GEHTEMPO_M_S

    # Verengen, nie ersetzen -- und NUR bei zeitlich dichten Ankern.
    #
    # "Dicht" heisst ZEITLICH dicht, nicht raeumlich. Zwei Anker, die eine
    # Dreiviertelstunde auseinanderliegen und zufaellig am selben Punkt stehen,
    # sagen ueber die Zwischenzeit nichts: das ist die Rundwanderung aus der
    # Gate-Runde -- losgehen, zurueckkommen, derselbe Punkt. Meine erste Fassung
    # verengte allein nach der raeumlichen Distanz und gab einem Bild aus der
    # Mitte einer 40-Minuten-Luecke 27 m Radius, obwohl 20 Minuten Gehzeit rund
    # 1,7 km zulassen. Genau davor warnt Spec Paragraf 5.
    luecke_s = (nachher.zeit - vorher.zeit).total_seconds()
    if luecke_s <= DICHT_S:
        strecke = _entfernung_m(vorher, nachher)
        if strecke < schranke:
            schranke = max(strecke, RADIUS_MIN_M)

    return max(RADIUS_MIN_M, round(schranke))


def _entfernung_m(a: Anker, b: Anker) -> float:
    """Haversine, in Metern."""
    from math import asin, cos, radians, sin, sqrt

    r = 6371000.0
    dlat = radians(b.lat - a.lat)
    dlon = radians(b.lon - a.lon)
    h = sin(dlat / 2) ** 2 + cos(radians(a.lat)) * cos(radians(b.lat)) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(h))
