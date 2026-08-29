"""Zusicherungen zum Lesen der GPX-Spur.

Alle Koordinaten in dieser Datei sind ERFUNDEN. Echte Werte aus gefahrenen
Reisen sagen, wo jemand wann war — sie gehoeren nicht in ein oeffentliches
Repository, auch nicht als Testdaten.

Der teure Fehler hier ist die Zeit, nicht der Ort: liegt die Umrechnung eine
Stunde daneben, bekommt jedes Bild eine Koordinate, die plausibel aussieht
und falsch ist.
"""

from __future__ import annotations

from datetime import datetime

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
    winter = gpx.Punkt(
        zeit=datetime.fromisoformat("2026-01-15T08:00:00+00:00"), lat=1.0, lon=2.0, name=None
    )
    sommer = gpx.Punkt(
        zeit=datetime.fromisoformat("2026-08-27T08:00:00+00:00"), lat=1.0, lon=2.0, name=None
    )

    assert gpx.in_kamerazeit(winter) == datetime(2026, 1, 15, 9, 0, 0)
    assert gpx.in_kamerazeit(sommer) == datetime(2026, 8, 27, 10, 0, 0)


def test_kamerazeit_ist_zonenlos_und_damit_direkt_vergleichbar():
    """`Aufnahme.zeitpunkt` ist tz-naiv, so wie es im EXIF steht. Ein
    tz-bewusstes Ergebnis liesse sich damit nicht vergleichen — Python
    verweigert den Vergleich von naiv und bewusst."""
    p = gpx.Punkt(
        zeit=datetime.fromisoformat("2026-08-27T08:00:00+00:00"), lat=1.0, lon=2.0, name=None
    )

    assert gpx.in_kamerazeit(p).tzinfo is None


def test_eine_andere_zeitzone_wird_auch_genutzt():
    """Untergrenze zur Zeile darueber: ohne diesen Fall koennte die Zone
    fest verdrahtet sein und beide Tests bestuenden trotzdem. Reisen finden
    nicht nur in Mitteleuropa statt."""
    p = gpx.Punkt(
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
