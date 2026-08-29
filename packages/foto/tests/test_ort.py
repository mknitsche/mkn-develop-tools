"""Zusicherungen zur Ortsbestimmung und zur Radius-Regel.

Alle Koordinaten sind ERFUNDEN. Gerechnet wird nahe (0,0); ein Grad Breite
entspricht rund 111.320 m, damit die Zahlen von Hand nachrechenbar sind.

Der teure Fehler ist hier nicht die fehlende Ortsangabe, sondern die zu
GENAUE. Eine Koordinate mit engem Radius sieht aus wie eine Messung; steht sie
erst in der Datei, ist ihr nicht mehr anzusehen, dass sie geraten war. Deshalb
gilt durchgehend: was nicht belegt ist, wird nicht geschrieben, sondern
vorgeschlagen — und ein Vorschlag geht auf die Entscheidungsliste.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mkn_foto import ort
from mkn_foto.gpx import Punkt
from mkn_foto.modell import Aufnahme

_AUFNAHME_ZEIT = datetime(2026, 8, 27, 12, 0, 0)
_METER_JE_GRAD = 111_320


def _aufnahme(zeit=_AUFNAHME_ZEIT):
    return Aufnahme(zeitpunkt=zeit, kamera="XE5", stamm="DSCF3541", dateien={}, exif={})


def _punkt(sekunden: float, nord_m: float = 0.0, name=None):
    """Anker `sekunden` relativ zur Aufnahme, `nord_m` Meter noerdlich von (0,0).

    Die Zeit wird als UTC gefuehrt (= lokale Sommerzeit minus zwei Stunden).
    """
    utc = _AUFNAHME_ZEIT - timedelta(hours=2) + timedelta(seconds=sekunden)
    return Punkt(zeit=utc.replace(tzinfo=UTC), lat=nord_m / _METER_JE_GRAD, lon=0.0, name=name)


# --- Das Tempo kommt aus der Spur, es wird nicht angenommen ----------------


def test_eine_schnelle_spur_ergibt_einen_weiten_radius():
    """Zwei Anker, 300 m in 30 s: die Spur belegt 10 m/s. Der naechste Anker
    liegt 30 s vor der Aufnahme, also sind 300 m Bewegungsspielraum belegt.

    Eine angenommene Gehgeschwindigkeit haette hier 42 m behauptet — bei einer
    Fahrt im Auto oder in der Seilbahn ist das eine erfundene Genauigkeit."""
    spur = [_punkt(-60, nord_m=0), _punkt(-30, nord_m=300)]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege=[])

    assert 250 <= ergebnis.radius_m <= 350
    assert ergebnis.quelle == "anker"


def test_dieselbe_geometrie_mit_langsamer_spur_ergibt_einen_engen_radius():
    """Gegenprobe zur Zeile darueber: gleiche Zeiten, gleicher Abstand zum
    Anker — nur die Spur selbst ist langsam. Der Radius faellt um den Faktor
    zehn. Genau das kann eine feste Konstante nicht."""
    spur = [_punkt(-60, nord_m=0), _punkt(-30, nord_m=30)]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege=[])

    assert ergebnis.radius_m < 60


# --- Was nicht belegt ist, wird nicht geschrieben --------------------------


def test_ohne_ein_kurzes_teilstueck_gibt_es_keinen_radius():
    """Ein einzelner Anker sagt nichts darueber, wie schnell man sich bewegt
    hat. Der Ort ist dann ein VORSCHLAG und geht auf die Entscheidungsliste."""
    ergebnis = ort.bestimme(_aufnahme(), [_punkt(-30, nord_m=100)], wege=[])

    assert ergebnis.radius_m is None
    assert ergebnis.quelle == "vorschlag"


def test_ein_langes_teilstueck_belegt_kein_tempo():
    """Die Rundwanderung, in ihrer schaerferen Form.

    Zwei Anker am selben Ort, zwoelf Minuten davor und danach: das
    Durchschnittstempo waere NULL, und daraus einen engen Radius abzuleiten
    hiesse zu behaupten, dazwischen sei niemand weggegangen. Ueber ein langes
    Teilstueck sagt der Durchschnitt nichts — also gibt es keinen Radius,
    sondern einen Vorschlag."""
    spur = [_punkt(-720, nord_m=0), _punkt(720, nord_m=0)]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege=[])

    assert ergebnis.radius_m is None
    assert ergebnis.quelle == "vorschlag"


def test_ein_zu_weiter_radius_wird_nicht_geschrieben():
    """3000 m in 30 s sind 360 km/h — was auch immer da passiert ist, der
    daraus folgende Radius von 3 km benennt keinen Ort mehr. Eine Koordinate,
    die nichts eingrenzt, sieht trotzdem aus wie eine Messung."""
    spur = [_punkt(-60, nord_m=0), _punkt(-30, nord_m=3000)]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege=[])

    assert ergebnis.radius_m is None
    assert ergebnis.quelle == "vorschlag"


def test_ohne_jeden_anker_im_fenster_kommt_gar_nichts_zurueck():
    """Kein Anker heisst kein Ort — nicht einmal ein Vorschlag, denn es gibt
    keine Koordinate, die man vorschlagen koennte."""
    assert ort.bestimme(_aufnahme(), spur=[], wege=[]) is None


def test_ein_anker_ausserhalb_des_fensters_zaehlt_nicht():
    """Vier Stunden Abstand sagen ueber den Aufnahmeort nichts mehr."""
    assert ort.bestimme(_aufnahme(), [_punkt(-14400)], wege=[]) is None


# --- Verengen, nie erweitern ----------------------------------------------


def test_der_radius_faellt_nie_unter_die_untergrenze():
    """Feiner als 25 m ist eine erfundene Praezision: GPS selbst liegt bei rund
    10 m, und der Anker beschreibt den Standort des Geraets, nicht den des
    Motivs."""
    spur = [_punkt(-60, nord_m=0), _punkt(-30, nord_m=1)]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege=[])

    assert ergebnis.radius_m == 25


def test_raeumliche_naehe_darf_nur_verengen_nie_erweitern():
    """Drei Anker, dicht in der Zeit: die Zeitschranke ergaebe 600 m, aber die
    Spur hat sich in diesem Fenster nur ueber 200 m bewegt. Der raeumliche
    Wert darf das verengen — ersetzen darf er die Schranke nie, sonst bekaeme
    die Rundwanderung wieder ihren falschen engen Radius."""
    spur = [_punkt(-60, nord_m=0), _punkt(-30, nord_m=30), _punkt(30, nord_m=900)]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege=[])

    assert ergebnis.radius_m is not None
    assert ergebnis.radius_m < 500


def test_das_hoechste_belegte_tempo_zaehlt_nicht_das_mittlere():
    """Zwei kurze Teilstuecke im Fenster: eines mit 10 m/s, eines mit 0,5 m/s.

    Der Radius muss die Bewegung ueberschaetzen duerfen, nur nicht
    unterschaetzen — ein Mittelwert glaettet genau die schnelle Strecke weg,
    auf die es ankommt. Ohne diesen Fall ist die Zusicherung hohl: in allen
    anderen Tests gibt es nur EIN kurzes Teilstueck, und dort sind Mittel und
    Maximum dasselbe."""
    spur = [
        _punkt(-800, nord_m=0),
        _punkt(-790, nord_m=100),  # 10 m/s
        _punkt(-780, nord_m=105),  # 0,5 m/s
        _punkt(-30, nord_m=105),  # lange Lucke: belegt kein Tempo, macht unstetig
    ]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege=[])

    assert 250 <= ergebnis.radius_m <= 350


def test_raeumliche_ausdehnung_zaehlt_nur_bei_dichter_spur():
    """Die Rundwanderung als Mutationsfall.

    Zwei Anker am selben Ort, ueber zwoelf Minuten auseinander — die
    raeumliche Ausdehnung des Fensters betraegt nur 100 m, die Zeitschranke
    300 m. Wuerde die Dichtepruefung entfallen, verengte die Ausdehnung den
    Radius auf 100 m und behauptete damit, dazwischen sei niemand weggegangen.
    """
    spur = [_punkt(-800, nord_m=0), _punkt(-790, nord_m=100), _punkt(-30, nord_m=100)]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege=[])

    assert ergebnis.radius_m > 200


# --- Welcher Punkt gemeldet wird ------------------------------------------


def test_der_zeitlich_naechste_anker_gewinnt_nicht_der_erste():
    """Sonst haengt das Ergebnis an der Reihenfolge in der Datei."""
    spur = [_punkt(-300, nord_m=0), _punkt(-280, nord_m=100), _punkt(-30, nord_m=200)]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege=[])

    assert round(ergebnis.lat * _METER_JE_GRAD) == 200


def test_ein_benannter_wegpunkt_liefert_den_ortsnamen_mit():
    """Der Name schlaegt die blosse Koordinate: er BENENNT das Motiv, statt den
    Standort des Fotografierenden zu vermessen."""
    spur = [_punkt(-60, nord_m=0), _punkt(-30, nord_m=30)]
    wege = [_punkt(-40, nord_m=15, name="Kunstort")]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege)

    assert ergebnis.name == "Kunstort"
    assert ergebnis.quelle == "gpx"


def test_der_zeitlich_naechste_wegpunkt_gewinnt():
    """Zwei benannte Orte im Fenster — der erste in der Datei ist nicht
    automatisch der richtige."""
    spur = [_punkt(-60, nord_m=0), _punkt(-30, nord_m=30)]
    wege = [_punkt(-600, nord_m=0, name="Fern"), _punkt(-40, nord_m=15, name="Nah")]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege)

    assert ergebnis.name == "Nah"


def test_der_radius_gehoert_zu_der_koordinate_die_gemeldet_wird():
    """Der eigentliche Fallstrick.

    Ein ferner benannter Wegpunkt und ein naher Spurpunkt: gemeldet wird der
    Wegpunkt, weil er den Ort BENENNT. Stammt der Radius dann vom nahen
    Spurpunkt, behauptet die Datei eine Genauigkeit, die fuer die gemeldete
    Koordinate nie galt — und das ist ihr hinterher nicht mehr anzusehen.

    Hier: der Wegpunkt liegt 300 s zurueck, der Spurpunkt 30 s. Bei belegten
    2 m/s sind das 600 m gegen 60 m — der weite Wert ist der richtige. Er wird
    anschliessend noch von der raeumlichen Ausdehnung des Fensters auf rund
    500 m verengt; entscheidend ist, dass er um ein Vielfaches ueber den 60 m
    liegt, die der nahe Spurpunkt ergeben haette.
    """
    spur = [_punkt(-60, nord_m=0), _punkt(-30, nord_m=60)]
    wege = [_punkt(-300, nord_m=500, name="Fern")]

    ergebnis = ort.bestimme(_aufnahme(), spur, wege)

    assert ergebnis.name == "Fern"
    assert ergebnis.radius_m > 300, "Radius stammt vom falschen Punkt"
