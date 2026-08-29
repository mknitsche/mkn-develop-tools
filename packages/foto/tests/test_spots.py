"""Zusicherungen zum Schneiden der Foto-Sessions.

Hier entsteht die Einheit, auf der die gesamte Ortsbestimmung beruht. Zwei
Fehler waeren teuer und beide unsichtbar:

- Zerschneidet der Schnitt eine Session, bekommen Teile davon getrennte Orte,
  obwohl sie an einem Fleck entstanden sind.
- Klebt er zwei Sessions zusammen, bekommt eine Fahrt oder ein Weg denselben
  Ort wie das Ziel.

Die Schwelle ist gemessen, nicht gewaehlt: von 1286 Abstaenden der
Messwoche liegen 95 % unter vier Minuten, das 99. Perzentil bei 56 Minuten.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from mkn_foto import spots
from mkn_foto.modell import Aufnahme

_START = datetime(2026, 8, 26, 17, 0, 0)


def _bild(sekunden: float, stamm="X", kamera="D850") -> Aufnahme:
    return Aufnahme(
        zeitpunkt=_START + timedelta(seconds=sekunden),
        kamera=kamera,
        stamm=f"{stamm}{int(sekunden)}",
        dateien={},
        exif={},
    )


def test_kurze_abstaende_bilden_eine_session():
    aufnahmen = [_bild(s) for s in (0, 5, 200, 400)]

    (spot,) = spots.schneide(aufnahmen)

    assert len(spot.aufnahmen) == 4
    assert spot.von == _START
    assert spot.bis == _START + timedelta(seconds=400)


def test_eine_lange_pause_beginnt_eine_neue_session():
    aufnahmen = [_bild(s) for s in (0, 60, 3000, 3060)]

    ergebnis = spots.schneide(aufnahmen)

    assert [len(s.aufnahmen) for s in ergebnis] == [2, 2]


def test_zwoelf_minuten_am_selben_ort_zerschneiden_nichts():
    """Der Fall, der die Regel gebaut hat: KT-1 war teils Stunden an einem
    Spot, und zwischen zwei Bildern koennen zwoelf Minuten liegen. Eine
    Schwelle unter dieser Dauer wuerde eine Session in Stuecke schneiden."""
    aufnahmen = [_bild(0), _bild(720), _bild(740)]

    (spot,) = spots.schneide(aufnahmen)

    assert len(spot.aufnahmen) == 3


def test_die_schwelle_selbst_trennt_noch_nicht():
    """Untergrenze zur Zeile darueber: genau auf der Schwelle bleibt es eine
    Session, erst darueber beginnt eine neue. Ohne diesen Fall waere unklar,
    ob die Grenze offen oder geschlossen gemeint ist."""
    genau = spots.PAUSE_S

    assert len(spots.schneide([_bild(0), _bild(genau)])) == 1
    assert len(spots.schneide([_bild(0), _bild(genau + 1)])) == 2


def test_beide_kameras_gehoeren_zur_selben_session():
    """Ein Spot ist ein Ort und eine Zeit, keine Kamera. Wer nach Kamera
    trennt, zerlegt jede Session, in der beide Gehaeuse im Einsatz waren — und
    das war die Regel, nicht die Ausnahme."""
    aufnahmen = [_bild(0, kamera="D850"), _bild(30, kamera="XE5"), _bild(60, kamera="D850")]

    (spot,) = spots.schneide(aufnahmen)

    assert len(spot.aufnahmen) == 3


def test_unsortierte_eingabe_wird_chronologisch_geschnitten():
    """Die Kamera schreibt nur Sekunden, und die Reihenfolge darf nicht an der
    Eingabe haengen — sonst wandern die Sessiongrenzen mit ihr."""
    aufnahmen = [_bild(3000), _bild(0), _bild(3060), _bild(60)]

    ergebnis = spots.schneide(aufnahmen)

    assert [len(s.aufnahmen) for s in ergebnis] == [2, 2]
    assert ergebnis[0].von == _START


def test_ohne_aufnahmen_gibt_es_keine_session():
    assert spots.schneide([]) == []
