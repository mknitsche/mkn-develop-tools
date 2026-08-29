"""Zusicherungen zur Ortsbestimmung einer Foto-Session.

Alle Koordinaten sind ERFUNDEN. Gerechnet wird nahe (0,0); ein Grad Breite
entspricht rund 111.320 m, damit die Zahlen von Hand nachrechenbar sind.

Der teure Fehler ist nicht die fehlende Ortsangabe, sondern die zu GENAUE.
Eine Koordinate mit engem Radius sieht aus wie eine Messung; steht sie erst in
der Datei, ist ihr nicht mehr anzusehen, dass sie geraten war. Deshalb gilt
durchgehend: was nicht belegt ist, wird VORGESCHLAGEN, nicht geschrieben.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mkn_foto import ort, spots
from mkn_foto.modell import Anker, Aufnahme, Spot

_START = datetime(2026, 8, 27, 12, 0, 0)
_METER_JE_GRAD = 111_320


def _bild(minuten: float) -> Aufnahme:
    return Aufnahme(
        zeitpunkt=_START + timedelta(minutes=minuten),
        kamera="XE5",
        stamm=f"DSCF{3500 + int(minuten)}",
        dateien={},
        exif={},
    )


def _spot(*minuten: float) -> Spot:
    return Spot(aufnahmen=tuple(_bild(m) for m in minuten))


def _anker(minuten: float, nord_m: float = 0.0, ost_m: float = 0.0, name=None) -> Anker:
    """Anker `minuten` nach Sessionbeginn; die Zeit wird als UTC gefuehrt
    (= lokale Sommerzeit minus zwei Stunden)."""
    utc = _START - timedelta(hours=2) + timedelta(minutes=minuten)
    return Anker(
        zeit=utc.replace(tzinfo=UTC),
        lat=nord_m / _METER_JE_GRAD,
        lon=ost_m / _METER_JE_GRAD,
        name=name,
    )


# --- Der Ort einer Session ------------------------------------------------


def test_eine_session_mit_engen_ankern_bekommt_einen_engen_radius():
    spot = _spot(0, 20, 40, 60)
    anker = [_anker(0), _anker(20, nord_m=40), _anker(40, nord_m=80), _anker(60, nord_m=60)]

    ergebnis = ort.fuer_spot(spot, anker)

    assert ergebnis.quelle == "anker"
    assert ergebnis.radius_m < 100


def test_der_ort_ist_die_mitte_der_anker_nicht_der_erste():
    """Ein Spot hat eine Ausdehnung — genau die Wege, die waehrend der
    Kreativzeit zurueckgelegt werden. Sein Ort ist deren Mitte, nicht der
    zufaellig erste beobachtete Punkt."""
    spot = _spot(0, 60)
    anker = [_anker(0, nord_m=0), _anker(30, nord_m=100), _anker(60, nord_m=200)]

    ergebnis = ort.fuer_spot(spot, anker)

    assert round(ergebnis.lat * _METER_JE_GRAD) == 100


def test_der_radius_faellt_nie_unter_die_untergrenze():
    """Auch wenn alle Anker auf demselben Punkt liegen: feiner als 25 m ist
    eine erfundene Praezision. GPS selbst liegt bei rund 10 m."""
    spot = _spot(0, 60)
    anker = [_anker(0), _anker(30), _anker(60)]

    assert ort.fuer_spot(spot, anker).radius_m == 25


def test_ohne_anker_in_der_session_kommt_nichts_zurueck():
    assert ort.fuer_spot(_spot(0, 60), []) is None


def test_ein_anker_knapp_neben_der_session_zaehlt_mit():
    """Die Sessiongrenze ist der letzte Ausloeser, nicht der Moment des
    Aufbruchs. Ein Anker fuenf Minuten spaeter sagt sehr wohl, wo jemand
    waehrend der Session war — gemessen an der echten Woche liegen solche
    Randanker 18 bis 200 m vom Sessionmittelpunkt entfernt.

    Ohne den Randstreifen fielen sechs Sessions mit 472 Bildern auf die
    Entscheidungsliste, obwohl ihre Anker auf 25 m uebereinstimmen."""
    spot = _spot(0, 30)
    anker = [_anker(-3), _anker(15, nord_m=20), _anker(33, nord_m=10)]

    ergebnis = ort.fuer_spot(spot, anker)

    assert ergebnis is not None
    assert ergebnis.quelle == "anker"


def test_der_randstreifen_ist_schmaler_als_die_halbe_sessionpause():
    """Keine gedrehte Schraube, sondern eine Bedingung: waere der Rand breiter
    als die halbe Pause, koennten sich zwei benachbarte Sessions denselben
    Anker teilen — und der Ort der einen zoege den der anderen zu sich.

    Firsthand bestaetigt: bei 15 Minuten Rand faellt die Zahl belegter Bilder
    von 840 auf 669, weil Anker der Nachbarsession den Radius aufblaehen."""
    assert ort.RAND_S * 2 < spots.PAUSE_S


def test_anker_weit_ausserhalb_der_session_zaehlen_nicht():
    """Sonst zoege der Anker der naechsten Station den Ort dieser Session zu
    sich herueber."""
    spot = _spot(0, 60)
    anker = [_anker(-120, nord_m=5000), _anker(200, nord_m=5000)]

    assert ort.fuer_spot(spot, anker) is None


# --- Widerspruch zwischen Quellen: das eigentliche Signal ------------------


def test_ein_widerlegter_anker_wird_verworfen():
    """Der gemessene Fall vom 26.08.: ein Spurpunkt sass 3383 m abseits,
    zwischen zwei Handybildern, die 3 m auseinanderliegen.

    KEINE Regel ueber Geschwindigkeit haette ihn gefangen — 3,4 km in
    dreieinhalb Minuten sind mit dem Auto moeglich. Gefangen hat ihn der
    Widerspruch zwischen zwei unabhaengigen Quellen: der Umweg ueber ihn ist
    um ein Vielfaches laenger als der direkte Weg seiner Nachbarn."""
    spot = _spot(0, 60)
    anker = [
        _anker(10, nord_m=0),
        _anker(20, nord_m=0),
        _anker(30, nord_m=3383),  # der Ausreisser
        _anker(40, nord_m=3),
        _anker(50, nord_m=0),
    ]

    ergebnis = ort.fuer_spot(spot, anker)

    assert ergebnis.radius_m < 100, "der widerlegte Anker hat den Ort verzogen"


def test_eine_echte_bewegung_wird_nicht_verworfen():
    """Untergrenze zur Zeile darueber: wer sich wirklich fortbewegt, erzeugt
    keinen Umweg — seine Nachbarn liegen dann ebenso weit auseinander. Ohne
    diesen Fall koennte die Regel schlicht jeden entfernten Anker wegwerfen
    und saehe dabei aus wie Sorgfalt.

    Der Weg ist bewusst GEBOGEN: auf einer geraden Linie ist der Umweg immer
    genau so lang wie der direkte Weg, und dann bestuende der Test bei jeder
    Schwelle — er prueste die Regel gar nicht. Mit dem Knick liegt das
    Verhaeltnis bei 1,2, und eine zu enge Schwelle wirft die Bewegung weg."""
    anker = [
        _anker(10, nord_m=0),
        _anker(30, nord_m=300, ost_m=200),
        _anker(50, nord_m=600),
    ]

    behalten = ort.verwirf_widerlegte(anker)

    assert len(behalten) == 3


def test_auch_der_erste_anker_wird_geprueft():
    """Ein Ausreisser am RAND hat nur einen Nachbarn — geprueft werden muss er
    trotzdem, sonst kommt er ungehindert durch.

    Firsthand am 28.08. gefunden: der erste Anker einer Session lag 935 m von
    allen dreizehn anderen entfernt, die untereinander auf 13 m
    uebereinstimmten. Weil die erste Fassung den ersten Anker ungeprueft
    behielt, wuchs der Radius auf 868 m und ein klar bestimmter Spot wurde zum
    Vorschlag."""
    anker = [_anker(0, nord_m=935), _anker(10), _anker(20, nord_m=5), _anker(30)]

    behalten = ort.verwirf_widerlegte(anker)

    assert len(behalten) == 3
    assert all(a.lat * _METER_JE_GRAD < 100 for a in behalten)


def test_auch_der_letzte_anker_wird_geprueft():
    """Dieselbe Luecke am anderen Ende — und sie faellt getrennt auf, weil ein
    Riegel nur fuer den Anfang genauso aussieht wie einer fuer beide."""
    anker = [_anker(0), _anker(10, nord_m=5), _anker(20), _anker(30, nord_m=935)]

    behalten = ort.verwirf_widerlegte(anker)

    assert len(behalten) == 3
    assert all(a.lat * _METER_JE_GRAD < 100 for a in behalten)


def test_ein_randanker_auf_echter_bewegung_bleibt():
    """Untergrenze: wer am Anfang einer Wanderung steht, ist weit vom Ende
    entfernt — und trotzdem kein Ausreisser. Ohne diesen Fall wuerde die
    Randpruefung schlicht jeden entfernten Randanker wegwerfen."""
    anker = [_anker(0), _anker(10, nord_m=300), _anker(20, nord_m=600), _anker(30, nord_m=900)]

    assert len(ort.verwirf_widerlegte(anker)) == 4


def test_mit_zwei_ankern_kann_nichts_widerlegt_werden():
    """Ein Widerspruch braucht drei Punkte: einen Verdaechtigen und zwei
    Nachbarn, die sich einig sind. Bei zweien gibt es keine zweite Meinung."""
    anker = [_anker(10, nord_m=0), _anker(30, nord_m=5000)]

    assert len(ort.verwirf_widerlegte(anker)) == 2


def test_ein_einzelner_anker_kommt_nicht_doppelt_zurueck():
    """Die eigentliche Aufgabe des Riegels — bei zwei Ankern ist er
    wirkungslos, weil die Schleife ohnehin leer laeuft. Erst bei EINEM zeigt
    sich, wozu er da ist: ohne ihn steht der Anker zweimal in der Liste, als
    Anfang und als Ende, und der Radius saehe kleiner aus, als er ist."""
    assert len(ort.verwirf_widerlegte([_anker(10)])) == 1


def test_eine_leere_ankerliste_stuerzt_nicht():
    """Untergrenze: ohne den Riegel greift der Code auf das erste Element
    einer leeren Liste zu."""
    assert ort.verwirf_widerlegte([]) == []


# --- Was nicht belegt ist, wird vorgeschlagen ------------------------------


def test_duenne_zeitliche_abdeckung_ergibt_nur_einen_vorschlag():
    """Der gemessene Wasserfall-Fall vom 28.08.: 119 Bilder ueber 26 Minuten,
    aber die drei Anker decken davon einen einzigen Moment ab. Wo jemand die
    uebrige Zeit war, sagen sie nicht — und ein Fussmarsch fuehrt weg vom
    beobachteten Punkt."""
    spot = _spot(0, 60)
    anker = [_anker(0), _anker(1, nord_m=10), _anker(2, nord_m=20)]

    ergebnis = ort.fuer_spot(spot, anker)

    assert ergebnis.quelle == "vorschlag"


def test_ein_zu_weiter_radius_ergibt_nur_einen_vorschlag():
    """Der gemessene Seilbahn-Fall: 24 Bilder, deren Anker sich ueber einen
    Kilometer verteilen. Das ist kein Spot mehr, sondern eine Fahrt — und eine
    Koordinate, die nichts eingrenzt, sieht trotzdem aus wie eine Messung."""
    spot = _spot(0, 60)
    anker = [_anker(0), _anker(30, nord_m=1500), _anker(60, nord_m=3000)]

    assert ort.fuer_spot(spot, anker).quelle == "vorschlag"


def test_ein_benannter_anker_gibt_dem_spot_seinen_namen():
    """Ein benannter Ort schlaegt die blosse Koordinate: er BENENNT den Ort,
    statt ihn zu vermessen."""
    spot = _spot(0, 60)
    anker = [_anker(0), _anker(30, name="Kunstort"), _anker(60, nord_m=20)]

    ergebnis = ort.fuer_spot(spot, anker)

    assert ergebnis.name == "Kunstort"
    assert ergebnis.quelle == "gpx"


def test_ein_name_macht_aus_einem_vorschlag_keine_tatsache():
    """Sonst zoege ein zufaellig benannter Wegpunkt eine unbelegte Session in
    die Datei — und der Name klaenge dabei besonders glaubwuerdig."""
    spot = _spot(0, 60)
    anker = [_anker(0, name="Kunstort"), _anker(1, nord_m=10), _anker(2, nord_m=20)]

    assert ort.fuer_spot(spot, anker).quelle == "vorschlag"


# --- Sessions am selben Ort wieder zusammenfuegen --------------------------


def test_zwei_sessions_am_selben_ort_werden_zusammengefuegt():
    """Gemessen am 28.08.: zwei Sessions lagen 5 m auseinander, getrennt durch
    19 Minuten Pause. Das ist EIN Spot — die Pause gehoert zum Ort, so wie
    Ankommen und Ueberlegen dazugehoeren. Die Zeitschwelle allein kann das
    nicht sehen; die Anker sehen es."""
    eins = _spot(0, 10, 20)
    zwei = _spot(40, 50, 60)
    anker = [_anker(m, nord_m=n) for m, n in ((0, 0), (20, 10), (40, 5), (60, 0))]

    ergebnis = ort.fasse_gleichen_ort_zusammen([eins, zwei], anker)

    assert len(ergebnis) == 1
    assert len(ergebnis[0].aufnahmen) == 6


def test_zwei_sessions_an_verschiedenen_orten_bleiben_getrennt():
    """Untergrenze: sonst wuerde alles zu einem einzigen Spot verschmelzen."""
    eins = _spot(0, 10, 20)
    zwei = _spot(40, 50, 60)
    anker = [_anker(m, nord_m=n) for m, n in ((0, 0), (20, 10), (40, 3000), (60, 3010))]

    ergebnis = ort.fasse_gleichen_ort_zusammen([eins, zwei], anker)

    assert len(ergebnis) == 2


def test_nur_zeitlich_benachbarte_sessions_werden_zusammengefuegt():
    """Zwei Aufenthalte am selben Fleck mit einem anderen Ort dazwischen sind
    zwei Besuche, nicht einer — sonst schluckte der erste den zweiten mitsamt
    allem, was dazwischen liegt."""
    eins, mitte, drei = _spot(0, 10), _spot(30, 40), _spot(60, 70)
    anker = [
        _anker(0),
        _anker(10),
        _anker(30, nord_m=3000),
        _anker(40, nord_m=3000),
        _anker(60),
        _anker(70),
    ]

    ergebnis = ort.fasse_gleichen_ort_zusammen([eins, mitte, drei], anker)

    assert len(ergebnis) == 3


def test_eine_session_ohne_ort_verschmilzt_nicht():
    """Ohne Anker ist unbekannt, wo sie war — und Unbekanntes wird nicht
    stillschweigend einem Nachbarn zugeschlagen."""
    eins = _spot(0, 10)
    zwei = _spot(40, 50)
    anker = [_anker(0), _anker(10)]

    assert len(ort.fasse_gleichen_ort_zusammen([eins, zwei], anker)) == 2


def test_die_aufnahmen_bleiben_chronologisch():
    """Die Serienerkennung setzt die Reihenfolge voraus."""
    eins = _spot(0, 10, 20)
    zwei = _spot(40, 50, 60)
    anker = [_anker(m, nord_m=n) for m, n in ((0, 0), (20, 10), (40, 5), (60, 0))]

    (zusammen,) = ort.fasse_gleichen_ort_zusammen([eins, zwei], anker)

    zeiten = [a.zeitpunkt for a in zusammen.aufnahmen]
    assert zeiten == sorted(zeiten)
