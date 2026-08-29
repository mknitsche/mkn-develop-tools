"""Zusicherungen zur Ortsbestimmung und zur Radius-Regel.

Alle Koordinaten sind ERFUNDEN. Gerechnet wird nahe (0,0), damit ein Grad
Laenge rund 111 km entspricht und die Zahlen von Hand nachrechenbar sind.

Der teure Fehler hier ist nicht die fehlende Ortsangabe, sondern die zu
GENAUE: eine Koordinate mit engem Radius sieht aus wie eine Messung. Steht
sie erst in der Datei, ist ihr nicht mehr anzusehen, dass sie geraten war.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mkn_foto import ort
from mkn_foto.gpx import Punkt
from mkn_foto.modell import Aufnahme

_AUFNAHME_ZEIT = datetime(2026, 8, 27, 12, 0, 0)


def _aufnahme(zeit=_AUFNAHME_ZEIT):
    return Aufnahme(zeitpunkt=zeit, kamera="XE5", stamm="DSCF3541", dateien={}, exif={})


def _punkt(minuten: float, lat=0.0, lon=0.0, name=None):
    """`minuten` relativ zur Aufnahme; die Zeit wird als UTC gefuehrt
    (= lokale Sommerzeit minus zwei Stunden)."""
    utc = _AUFNAHME_ZEIT - timedelta(hours=2) + timedelta(minutes=minuten)
    return Punkt(zeit=utc.replace(tzinfo=UTC), lat=lat, lon=lon, name=name)


# --- Die Radius-Regel -----------------------------------------------------


def test_ein_einzelner_ferner_anker_ergibt_einen_weiten_radius():
    """Zehn Minuten Abstand heissen 840 m Bewegungsspielraum. Die Ortsangabe
    muss das zugeben, statt Genauigkeit vorzutaeuschen."""
    ergebnis = ort.bestimme(_aufnahme(), [_punkt(-10.0)], wege=[])

    assert ergebnis is not None
    assert 800 <= ergebnis.radius_m <= 900
    assert ergebnis.quelle == "anker"


def test_eine_dichte_spur_verengt_den_radius():
    """Vier Punkte innerhalb weniger Minuten, alle nah beieinander: der
    raeumliche Wert darf die Zeitschranke unterbieten."""
    spur = [_punkt(m, lon=0.0001 * i) for i, m in enumerate([-3.0, -1.0, 1.0, 3.0])]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege=[])

    assert ergebnis.radius_m < 300


def test_die_rundwanderung_bekommt_keinen_falschen_engen_radius():
    """Anfang und Ende am selben Punkt, dazwischen eine weite Luecke. Der
    raeumliche Wert waere hier nahe null — die Zeitschranke muss gewinnen.
    Genau dieser Fall hat die erste, rein raeumliche Regel widerlegt."""
    spur = [_punkt(-12.0), _punkt(12.0)]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege=[])

    assert ergebnis.radius_m > 500


def test_raeumliche_naehe_verengt_nur_bei_dichter_spur():
    """Untergrenze zur Rundwanderung: drei Punkte am selben Ort, aber mit
    einer grossen Lucke dazwischen, sind KEINE dichte Spur. Ohne diese
    Zusicherung koennte die Dichtepruefung allein an der Punktzahl haengen
    und die Luecke ignorieren."""
    spur = [_punkt(-9.0), _punkt(-8.5), _punkt(9.0)]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege=[])

    assert ergebnis.radius_m > 500


def test_raeumliche_naehe_darf_nur_verengen_nie_erweitern():
    """Vier Punkte dicht in der ZEIT, aber weit auseinander im RAUM.

    Die raeumliche Spannweite betraegt hier ueber einen Kilometer, die
    Zeitschranke 84 m. Wuerde der raeumliche Wert die Schranke ersetzen statt
    sie zu verengen, wuechse der Radius um das Dreizehnfache — die Regel der
    Spec lautet ausdruecklich „nur verengen, nie ersetzen".

    Ohne diesen Fall ist die Zusicherung hohl: in allen anderen Tests liegt
    die Spannweite UNTER der Zeitschranke, dort liefern `min(a, b)` und `b`
    dasselbe Ergebnis."""
    spur = [_punkt(m, lat=0.01 * i) for i, m in enumerate([-2.0, -1.0, 1.0, 2.0])]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege=[])

    assert ergebnis.radius_m < 200


def test_der_radius_faellt_nie_unter_die_untergrenze():
    """Auch bei perfekt dichter Spur: feiner als 25 m ist eine erfundene
    Praezision. GPS selbst liegt bei rund 10 m, und der Anker beschreibt den
    Standort des Geraets, nicht den des Motivs."""
    spur = [_punkt(m) for m in (-0.5, -0.25, 0.25, 0.5)]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege=[])

    assert ergebnis.radius_m >= 25


# --- Was gemeldet wird, und was nicht --------------------------------------


def test_ohne_jeden_anker_im_fenster_kommt_nichts_zurueck():
    assert ort.bestimme(_aufnahme(), spur=[], wege=[]) is None


def test_ein_anker_ausserhalb_des_fensters_zaehlt_nicht():
    """Das Fenster ist die eigentliche Grenze der Aussage. Vier Stunden
    Abstand sagen ueber den Aufnahmeort nichts mehr."""
    assert ort.bestimme(_aufnahme(), [_punkt(-240.0)], wege=[]) is None


def test_der_zeitlich_naechste_anker_gewinnt_nicht_der_erste():
    """Sonst haengt das Ergebnis an der Reihenfolge in der Datei."""
    spur = [_punkt(-12.0, lat=1.0), _punkt(-1.0, lat=2.0), _punkt(11.0, lat=3.0)]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege=[])

    assert ergebnis.lat == 2.0


# --- Benannte Orte ---------------------------------------------------------


def test_ein_benannter_wegpunkt_liefert_den_ortsnamen_mit():
    """Der Name schlaegt die blosse Koordinate: er BENENNT das Motiv, statt
    den Standort des Fotografierenden zu vermessen."""
    wege = [_punkt(-2.0, name="Kunstort")]

    ergebnis = ort.bestimme(_aufnahme(), spur=[], wege=wege)

    assert ergebnis.name == "Kunstort"
    assert ergebnis.quelle == "gpx"


def test_der_zeitlich_naechste_wegpunkt_gewinnt():
    """Zwei benannte Orte im Fenster — der erste in der Datei ist nicht
    automatisch der richtige."""
    wege = [_punkt(-14.0, name="Fern"), _punkt(-2.0, name="Nah")]

    ergebnis = ort.bestimme(_aufnahme(), spur=[], wege=wege)

    assert ergebnis.name == "Nah"


def test_der_radius_gehoert_zu_der_koordinate_die_gemeldet_wird():
    """Der eigentliche Fallstrick.

    Ein ferner benannter Wegpunkt und ein naher Spurpunkt: gemeldet wird der
    Wegpunkt, weil er den Ort BENENNT. Stammt der Radius dann vom nahen
    Spurpunkt, behauptet die Datei 84 m Genauigkeit um eine Koordinate, die
    bis zu 1,2 km danebenliegen kann — und das ist einer Datei hinterher
    nicht mehr anzusehen.
    """
    wege = [_punkt(-14.0, lat=5.0, name="Fern")]
    spur = [_punkt(-1.0, lat=9.0)]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege)

    assert ergebnis.name == "Fern"
    assert ergebnis.lat == 5.0
    assert ergebnis.radius_m > 1000, "Radius stammt vom falschen Punkt"
