"""Zusicherungen zum Lesen der GPX-Spur.

Alle Koordinaten in dieser Datei sind ERFUNDEN. Echte Werte aus gefahrenen
Reisen sagen, wo jemand wann war — sie gehoeren nicht in ein oeffentliches
Repository, auch nicht als Testdaten.

Der teure Fehler hier ist die Zeit, nicht der Ort: liegt die Umrechnung eine
Stunde daneben, bekommt jedes Bild eine Koordinate, die plausibel aussieht
und falsch ist.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from mkn_foto import gpx

_GPX = """<?xml version="1.0" encoding="UTF-8" standalone="no" ?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1" creator="Test">
  <wpt lat="1.5" lon="2.5"><name>Kunstort</name><time>2026-08-27T07:00:00+00:00</time></wpt>
  <trk><trkseg>
    <trkpt lat="1.0" lon="2.0"><time>2026-08-27T08:30:00+00:00</time></trkpt>
    <trkpt lat="1.1" lon="2.1"><time>2026-08-27T08:00:00+00:00</time></trkpt>
  </trkseg></trk>
</gpx>
"""


@pytest.fixture
def spurdatei(tmp_path):
    pfad = tmp_path / "spur.gpx"
    pfad.write_text(_GPX)
    return pfad


def test_trackpunkte_kommen_chronologisch_zurueck(spurdatei):
    """Die Datei enthaelt sie absichtlich verkehrt herum — die Ortssuche
    setzt Sortierung voraus."""
    track, _ = gpx.lies(spurdatei)

    assert [p.lat for p in track] == [1.1, 1.0]


def test_wegpunkte_werden_getrennt_von_der_spur_zurueckgegeben(spurdatei):
    """Ein benannter Wegpunkt schlaegt spaeter jede berechnete Koordinate —
    er BENENNT den Ort, statt ihn zu vermessen. Landete er in der Spur,
    ginge diese Unterscheidung verloren."""
    track, wege = gpx.lies(spurdatei)

    assert [w.name for w in wege] == ["Kunstort"]
    assert len(track) == 2
    assert all(p.name is None for p in track)


def test_kamerazeit_wird_ueber_die_zeitzone_aufgeloest_nicht_addiert():
    """Ein fester Versatz waere ueber einen Zeitumstellungs-Tag hinweg falsch.
    Deshalb ein Winter- UND ein Sommerdatum: im Winter gilt CET (+1), im
    Sommer CEST (+2). Ein Test mit nur einem der beiden bestuende auch mit
    einer fest eingebauten Stundenzahl."""
    winter = gpx.Anker(
        zeit=datetime.fromisoformat("2026-01-15T08:00:00+00:00"), lat=1.0, lon=2.0, name=None
    )
    sommer = gpx.Anker(
        zeit=datetime.fromisoformat("2026-08-27T08:00:00+00:00"), lat=1.0, lon=2.0, name=None
    )

    assert gpx.in_kamerazeit(winter) == datetime(2026, 1, 15, 9, 0, 0)
    assert gpx.in_kamerazeit(sommer) == datetime(2026, 8, 27, 10, 0, 0)


def test_kamerazeit_ist_zonenlos_und_damit_direkt_vergleichbar():
    """`Aufnahme.zeitpunkt` ist tz-naiv, so wie es im EXIF steht. Ein
    tz-bewusstes Ergebnis liesse sich damit nicht vergleichen — Python
    verweigert den Vergleich von naiv und bewusst."""
    p = gpx.Anker(
        zeit=datetime.fromisoformat("2026-08-27T08:00:00+00:00"), lat=1.0, lon=2.0, name=None
    )

    assert gpx.in_kamerazeit(p).tzinfo is None


def test_eine_andere_zeitzone_wird_auch_genutzt():
    """Untergrenze zur Zeile darueber: ohne diesen Fall koennte die Zone
    fest verdrahtet sein und beide Tests bestuenden trotzdem. Reisen finden
    nicht nur in Mitteleuropa statt."""
    p = gpx.Anker(
        zeit=datetime.fromisoformat("2026-08-27T08:00:00+00:00"), lat=1.0, lon=2.0, name=None
    )

    assert gpx.in_kamerazeit(p, zone="Asia/Tokyo") == datetime(2026, 8, 27, 17, 0, 0)


def test_ein_punkt_ohne_zeit_wird_uebergangen_statt_zu_stuerzen(tmp_path, caplog):
    """Er ist fuer die Zeitzuordnung wertlos — aber er darf nicht den ganzen
    Lauf abbrechen. Gemeldet wird er trotzdem: eine Spur, die still
    schrumpft, faellt erst auf, wenn Bilder ohne Ort dastehen."""
    import logging

    pfad = tmp_path / "luecke.gpx"
    pfad.write_text(
        '<?xml version="1.0"?><gpx version="1.1" '
        'xmlns="http://www.topografix.com/GPX/1/1">'
        '<trk><trkseg><trkpt lat="1.0" lon="2.0"/></trkseg></trk></gpx>'
    )

    with caplog.at_level(logging.WARNING, logger="mkn_foto.gpx"):
        track, _ = gpx.lies(pfad)

    assert track == []
    assert "ohne Zeit" in caplog.text


def test_eine_zonenlose_zeit_bleibt_unveraendert(monkeypatch) -> None:
    """**Der Fehler, den erst eine funktionierende CI gefunden hat.**

    `astimezone()` auf einer ZONENLOSEN Zeit nimmt still die Zone des Rechners
    an. In Europe/Berlin faellt das nicht auf, weil Quelle und Ziel dieselbe
    Zone sind; auf einem Runner in UTC verschiebt sich jeder Anker um zwei
    Stunden und findet seine Session nicht mehr. Drei Pipeline-Tests waren
    deshalb hier gruen und dort rot -- und niemand hat es gesehen, weil die CI
    seit dem ersten Commit an einer fehlenden Abhaengigkeit scheiterte.

    Das Bittere: `pipeline._in_kamerazeit` schuetzt genau davor, mit einem
    Kommentar, der den Fehler beschreibt. Zwei Funktionen fuer dieselbe
    Aufgabe, eine mit Schutz, eine ohne.

    **Die Bedingung wird HERGESTELLT, nicht vorausgesetzt** (LP-40): der Test
    setzt die Zone selbst, sonst prueft er die Maschine und nicht den Code.
    """
    import os
    import time

    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    try:
        zonenlos = datetime(2026, 8, 27, 10, 30, 0)
        anker = gpx.Anker(zeit=zonenlos, lat=47.5, lon=11.4, name=None)

        assert gpx.in_kamerazeit(anker) == zonenlos
    finally:
        os.environ.pop("TZ", None)
        time.tzset()


def test_eine_zonenbehaftete_zeit_wird_umgerechnet(monkeypatch) -> None:
    """Der andere Fall bleibt, wie er war: eine UTC-Zeit wird in Kamerazeit
    gebracht. Ohne diese Zusicherung koennte man den Fehler oben 'beheben',
    indem man gar nicht mehr umrechnet."""
    import time

    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    anker = gpx.Anker(
        zeit=datetime(2026, 8, 27, 8, 30, 0, tzinfo=UTC), lat=47.5, lon=11.4, name=None
    )

    # Sommerzeit: Berlin ist UTC+2.
    assert gpx.in_kamerazeit(anker) == datetime(2026, 8, 27, 10, 30, 0)
