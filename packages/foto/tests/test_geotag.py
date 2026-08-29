"""Position je BILD statt je Session — echtes Geotagging.

KT-1 am 2026-08-30: *"eigentlich hatte ich gehofft, du machst sinnvolle gpx (gps)
informationen, die man auf einer karte sieht"*.

Er hat recht, und die Messung zeigt, wie sehr: die Spur hat einen Median von
**63 Sekunden** zwischen zwei Punkten. Damit laesst sich fuer jedes Bild die
Position zum Aufnahmezeitpunkt interpolieren, auf wenige Meter genau. Die erste
Fassung gab stattdessen ganzen Sessions eine Sammelkoordinate — 141 Bilder mit
demselben Punkt und 25 m Radius. Auf einer Karte ist das ein Punkt, keine Route.

**Die Genauigkeit kommt aus dem zeitlichen Abstand**, nicht aus einer Annahme:
liegt der naechste Anker 30 Sekunden entfernt, ist die Position auf wenige Meter
sicher; liegt er eine halbe Stunde entfernt, ist sie grob; liegen Stunden
dazwischen, wird **gar nichts** geschrieben. Eine Koordinate, die ihre eigene
Unsicherheit nicht mitfuehrt, behauptet Genauigkeit, die sie nicht hat.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from mkn_foto import geotag
from mkn_foto.modell import Anker, Aufnahme

#: Alle Zeiten als Versatz zu diesem Punkt -- die erste Fassung addierte auf das
#: Minutenfeld und lief bei `_anker(40)` in "minute must be in 0..59".
_START = datetime(2026, 8, 26, 6, 0)


def _anker(minute: float, lat: float, lon: float) -> Anker:
    return Anker(zeit=_START + timedelta(minutes=minute), lat=lat, lon=lon, name=None)


def _aufnahme(minute: float, sekunde: int = 0) -> Aufnahme:
    return Aufnahme(
        zeitpunkt=_START + timedelta(minutes=minute, seconds=sekunde),
        kamera="XE5",
        stamm="X0001",
        dateien={},
        exif={},
    )


def test_position_wird_zwischen_zwei_ankern_interpoliert():
    """Der Kern: ein Bild genau in der Mitte liegt auf der Mitte der Strecke."""
    anker = [_anker(0, 47.5000, 11.4000), _anker(2, 47.5020, 11.4020)]

    ort = geotag.fuer_aufnahme(_aufnahme(1), anker)

    assert ort is not None
    assert ort.lat == pytest.approx(47.5010, abs=1e-5), f"nicht interpoliert: {ort}"
    assert ort.lon == pytest.approx(11.4010, abs=1e-5)


def test_jedes_bild_bekommt_seine_eigene_position():
    """Ohne diese Zusicherung waere ein Geotagger, der allen Bildern denselben
    naechsten Ankerpunkt gibt, genauso gruen — und genau das war die erste
    Fassung."""
    anker = [_anker(0, 47.5000, 11.4000), _anker(10, 47.5100, 11.4100)]

    orte = [geotag.fuer_aufnahme(_aufnahme(m), anker) for m in (2, 5, 8)]

    breiten = [o.lat for o in orte]
    assert len(set(breiten)) == 3, f"alle Bilder auf demselben Punkt: {breiten}"
    assert breiten == sorted(breiten), "die Positionen laufen nicht mit der Zeit"


def test_der_radius_waechst_mit_dem_zeitlichen_abstand():
    """Die Genauigkeit ist keine Annahme, sondern eine Messung."""
    nah = [_anker(0, 47.5, 11.4), _anker(1, 47.5001, 11.4001)]
    # 10 Minuten Luecke, Aufnahme in der Mitte: 300 s Abstand zum naechsten
    # Anker, also 420 m Zeitschranke. Noch innerhalb der Obergrenze -- eine
    # groessere Luecke faellt bewusst ganz heraus, das prueft der Test darunter.
    fern = [_anker(0, 47.5, 11.4), _anker(10, 47.6, 11.5)]

    ort_nah = geotag.fuer_aufnahme(_aufnahme(0, 30), nah)
    ort_fern = geotag.fuer_aufnahme(_aufnahme(5), fern)

    assert ort_nah.radius_m < ort_fern.radius_m, (
        f"der Radius folgt dem Abstand nicht: nah {ort_nah.radius_m} m, fern {ort_fern.radius_m} m"
    )
    assert ort_nah.radius_m <= 50, f"bei 30 s Abstand zu grob: {ort_nah.radius_m} m"


def test_zu_grosse_luecke_liefert_gar_nichts():
    """Die oberste Regel. Am 25.08. gibt es NULL Spurpunkte — dort darf nichts
    erfunden werden, auch nicht aus zwei Ankern, die Stunden entfernt liegen."""
    weit = [_anker(-360, 47.5, 11.4), _anker(360, 47.9, 11.9)]

    assert geotag.fuer_aufnahme(_aufnahme(0), weit) is None


def test_ein_bild_vor_dem_ersten_anker_wird_nicht_extrapoliert():
    """Vor dem Spurbeginn ist die Position unbekannt, nicht "wie der erste Punkt".
    Am 24.08. fing die Aufzeichnung mitten am Tag an."""
    anker = [_anker(30, 47.5, 11.4), _anker(32, 47.51, 11.41)]

    # Zwei Stunden vor dem ersten Anker.
    assert geotag.fuer_aufnahme(_aufnahme(-120), anker) is None


def test_ein_bild_direkt_auf_einem_anker_uebernimmt_ihn():
    """Der haeufigste Fall bei Handybildern: das Bild IST der Anker."""
    anker = [_anker(0, 47.5000, 11.4000), _anker(5, 47.5050, 11.4050)]

    ort = geotag.fuer_aufnahme(_aufnahme(0), anker)

    assert ort.lat == pytest.approx(47.5000, abs=1e-6)
    assert ort.radius_m <= geotag.RADIUS_MIN_M


def test_ohne_anker_gibt_es_keine_position():
    """Untergrenze: sonst bestuende der Geotagger auch ueber einer leeren Liste."""
    assert geotag.fuer_aufnahme(_aufnahme(0), []) is None


def test_die_quelle_sagt_woher_die_position_stammt():
    """`vorschlag` heisst "nicht schreiben". Eine interpolierte Position ist aber
    belegt — sie muss sich davon unterscheiden, sonst landet sie nie in einer
    Datei."""
    anker = [_anker(0, 47.5, 11.4), _anker(2, 47.502, 11.402)]

    ort = geotag.fuer_aufnahme(_aufnahme(1), anker)

    assert ort.quelle != "vorschlag", "eine belegte Position gilt als Vorschlag"
    assert ort.quelle == geotag.QUELLE


def test_die_zeitschranke_gilt_auch_bei_gleicher_strecke():
    """Die eigentliche Regel der Spec § 5: die Grundschranke ist die ZEIT.

    Der Test darueber liess sich auch mit einem festen Radius bestehen — er mass
    in Wahrheit nur die raeumliche Verengung. Hier ist die Strecke zwischen den
    Ankern in beiden Faellen GLEICH und weit; nur der zeitliche Abstand
    unterscheidet sich. Wer den Radius nicht aus der Zeit ableitet, liefert
    zweimal denselben Wert.
    """
    kurz = [_anker(0, 47.5, 11.4), _anker(2, 47.6, 11.5)]
    lang = [_anker(0, 47.5, 11.4), _anker(8, 47.6, 11.5)]

    ort_kurz = geotag.fuer_aufnahme(_aufnahme(1), kurz)
    ort_lang = geotag.fuer_aufnahme(_aufnahme(4), lang)

    assert ort_kurz.radius_m < ort_lang.radius_m, (
        f"der Radius folgt der Zeit nicht: 1 min Abstand -> {ort_kurz.radius_m} m, "
        f"4 min Abstand -> {ort_lang.radius_m} m"
    )
    # 60 s Gehzeit sind rund 84 m, 240 s rund 336 m.
    assert 60 <= ort_kurz.radius_m <= 110, f"unerwartet: {ort_kurz.radius_m} m"
    assert 300 <= ort_lang.radius_m <= 380, f"unerwartet: {ort_lang.radius_m} m"


def test_knapp_vor_der_spur_wird_trotz_enger_schranke_nichts_geliefert():
    """Die Extrapolations-Sperre muss eigenstaendig tragen.

    Der Test darueber lag zwei Stunden vor der Spur — dort haette auch die
    Radius-Obergrenze gegriffen, und die Sperre blieb unbewiesen. Hier liegt die
    Aufnahme nur eine Minute vor dem ersten Anker: die Zeitschranke waere eng,
    die Position trotzdem unbekannt.
    """
    anker = [_anker(10, 47.5, 11.4), _anker(12, 47.5010, 11.4010)]

    assert geotag.fuer_aufnahme(_aufnahme(9), anker) is None, (
        "vor dem ersten Anker wurde extrapoliert"
    )
    assert geotag.fuer_aufnahme(_aufnahme(13), anker) is None, (
        "nach dem letzten Anker wurde extrapoliert"
    )


def test_ohne_anker_gibt_es_keine_position_auch_ohne_eigenen_riegel():
    """Untergrenze, jetzt ohne den ueberfluessigen Vorab-Riegel: die leere Liste
    faellt in denselben Zweig wie "vor der Spur"."""
    assert geotag.fuer_aufnahme(_aufnahme(0), []) is None


def test_raeumliche_naehe_verengt_nur_bei_zeitlich_dichten_ankern():
    """Die Regel der Spec § 5, und ich hatte sie halb gebaut.

    Wörtlich dort: *"Räumliche Information darf nur verengen, nie ersetzen — und
    nur, wenn DICHTE Anker im Intervall liegen. Zwei weit auseinanderliegende
    Anker sagen über den Weg dazwischen nichts."*

    "Dicht" heisst ZEITLICH dicht. Zwei Anker, die 40 Minuten auseinanderliegen
    und zufaellig am selben Punkt stehen, sagen ueber die Zwischenzeit nichts —
    das ist die Rundwanderung aus der Gate-Runde: losgehen, zurueckkommen,
    derselbe Punkt. Meine erste Fassung verengte allein nach der raeumlichen
    Distanz und gab einem Bild aus der Mitte 27 m Radius, obwohl 20 Minuten
    Gehzeit rund 1,7 km zulassen.
    """
    # Zwei Anker, raeumlich 22 m auseinander, zeitlich 40 Minuten.
    rundweg = [_anker(0, 47.6500, 11.3700), _anker(40, 47.6502, 11.3702)]

    ort = geotag.fuer_aufnahme(_aufnahme(20), rundweg)

    assert ort is None or ort.radius_m > 500, (
        f"raeumliche Naehe hat ueber 40 Minuten hinweg verengt: {ort} — "
        "in der Zwischenzeit kann jemand weggegangen und zurueckgekommen sein"
    )


def test_bei_dichten_ankern_verengt_die_naehe_weiterhin():
    """Untergrenze: sonst waere die Verengung ganz abgeschaltet, und jede
    Position bekaeme den vollen Zeitradius — bei dichter Spur deutlich zu grob."""
    dicht = [_anker(0, 47.6500, 11.3700), _anker(1, 47.6502, 11.3702)]

    ort = geotag.fuer_aufnahme(_aufnahme(0, 30), dicht)

    assert ort is not None
    # 30 s Gehzeit waeren 42 m; die Anker liegen 22 m auseinander.
    assert ort.radius_m <= 42, f"die Verengung greift nicht mehr: {ort.radius_m} m"
