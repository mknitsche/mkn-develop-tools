"""Zusicherungen zur Serienerkennung aus der Kameraaussage.

Hier entscheidet sich, welche Bilder einen gemeinsamen Namen bekommen. Ein
Fehler faellt danach kaum noch auf: aus zwei Reihen wird eine, die Positionen
verschieben sich, und die Dateinamen behaupten eine Zusammengehoerigkeit, die
es nie gab.

Die Testdaten bilden den gemessenen Bestand vom 2026-08-27 nach — nicht
ausgedachte Faelle. Beide Kameras haben dort genau die Falle gestellt, gegen
die hier geprueft wird.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from mkn_foto import serien
from mkn_foto.modell import Aufnahme

_START = datetime(2026, 8, 27, 10, 30, 0)


def _fuji(nr: int, sequenz: int, *, bracketing: int = 1, sekunden: float | None = None) -> Aufnahme:
    versatz = nr * 2 if sekunden is None else sekunden
    return Aufnahme(
        zeitpunkt=_START + timedelta(seconds=versatz),
        kamera="XE5",
        stamm=f"DSCF{3500 + nr}",
        dateien={},
        exif={
            "EXIF:Model": "X-E5",
            "MakerNotes:AutoBracketing": bracketing,
            "MakerNotes:SequenceNumber": sequenz,
        },
    )


def _nikon(
    nr: int, ev: float, *, sekunden: float, modus: str = "Single-Frame, Exposure Bracketing"
) -> Aufnahme:
    return Aufnahme(
        zeitpunkt=_START + timedelta(seconds=sekunden),
        kamera="D850",
        stamm=f"D85_{2580 + nr}",
        dateien={},
        exif={
            "EXIF:Model": "NIKON D850",
            "MakerNotes:ShootingMode": modus,
            "MakerNotes:ExposureBracketValue": ev,
        },
    )


# --------------------------------------------------------------------------
# Fujifilm — die Kamera zaehlt die Bilder einer Reihe selbst
# --------------------------------------------------------------------------


def test_zwei_direkt_aufeinanderfolgende_reihen_bleiben_getrennt():
    """Der Neustart der Sequenznummer ist die Grenze, nicht der Zeitabstand.

    Im Bestand vom 27.08. liegen zwischen dem letzten Bild einer Reihe und dem
    ersten der naechsten zweimal nur ZWEI bis DREI Sekunden — weniger als
    innerhalb mancher Reihe. Eine Zeitlueckenregel haette dort verschmolzen.
    """
    aufnahmen = [
        _fuji(0, 1, sekunden=0),
        _fuji(1, 2, sekunden=1),
        _fuji(2, 3, sekunden=1),
        _fuji(3, 1, sekunden=3),
        _fuji(4, 2, sekunden=4),
        _fuji(5, 3, sekunden=4),
    ]

    ergebnis = serien.aus_kamera(aufnahmen)

    assert [len(s.aufnahmen) for s in ergebnis] == [3, 3]
    assert [s.nummer for s in ergebnis] == [1, 2]


def test_gleiche_zeitstempel_innerhalb_einer_reihe_bringen_die_folge_nicht_durcheinander():
    """Die Kamera schreibt nur Sekunden. Im echten Bestand tragen SECHS Bilder
    einer Reihe denselben Zeitstempel — die Reihenfolge kann dort nicht aus der
    Zeit kommen. Sortiert die Erkennung nur nach Zeit, haengt das Ergebnis an
    der Eingabereihenfolge, und ein scheinbarer Sequenz-Rueckfall zerschneidet
    die Reihe."""
    aufnahmen = [
        _fuji(nr, sequenz, sekunden=0) for nr, sequenz in enumerate([1, 2, 3, 4, 5], start=1)
    ]
    verdreht = [aufnahmen[3], aufnahmen[0], aufnahmen[4], aufnahmen[1], aufnahmen[2]]

    ergebnis = serien.aus_kamera(verdreht)

    assert len(ergebnis) == 1
    assert [a.exif["MakerNotes:SequenceNumber"] for a in ergebnis[0].aufnahmen] == [1, 2, 3, 4, 5]


def test_ohne_bracketing_entsteht_keine_serie():
    aufnahmen = [_fuji(nr, sequenz, bracketing=0) for nr, sequenz in enumerate([1, 2, 3])]

    assert serien.aus_kamera(aufnahmen) == []


def test_die_kamerareihe_der_fuji_gilt_als_sicher():
    """Die X-E5 nummeriert die Bilder einer Reihe selbst durch — das ist eine
    Aussage der Kamera, keine Ableitung. Nur dafuer gilt `sicher`, und nur
    `sicher` entscheidet spaeter, dass niemand mehr auf das Bild schauen muss."""
    aufnahmen = [_fuji(nr, sequenz) for nr, sequenz in enumerate([1, 2, 3])]

    (serie,) = serien.aus_kamera(aufnahmen)

    assert serie.sicher is True
    assert serie.quelle == "kamera"
    assert serie.typ == "hdr"


# --------------------------------------------------------------------------
# Nikon — die Kamera zaehlt NICHT; die Reihe steht im Belichtungswert
# --------------------------------------------------------------------------


def test_nikon_reihe_wird_am_wiederkehrenden_belichtungswert_getrennt_nicht_an_der_zeit():
    """Der gemessene Fall vom 27.08., Bild fuer Bild nachgebaut.

    Die sieben Bilder D85_2584 bis 2590 sind EINE Reihe in 2/3-EV-Schritten,
    von Hand ueber dreieinhalb Minuten belichtet — mit einer Lucke von 130
    Sekunden mittendrin. Eine Zeitlueckenregel zerreisst sie; die Rueckkehr
    des Belichtungswerts auf einen schon benutzten Wert trennt sie richtig.
    """
    aufnahmen = [
        _nikon(3, 0.0, sekunden=0),  # einzeln, davor
        _nikon(4, 0.0, sekunden=19),  # Reihe beginnt: Wert 0 kehrt wieder
        _nikon(5, -2.0, sekunden=55),
        _nikon(6, -1.333, sekunden=57),
        _nikon(7, -0.667, sekunden=187),  # 130 s Lucke MITTEN in der Reihe
        _nikon(8, 0.667, sekunden=188),
        _nikon(9, 1.333, sekunden=193),
        _nikon(10, 2.0, sekunden=195),
        _nikon(11, 0.0, sekunden=275),  # neue Reihe
        _nikon(12, -2.0, sekunden=307),
    ]

    ergebnis = serien.aus_kamera(aufnahmen)

    assert [len(s.aufnahmen) for s in ergebnis] == [7, 2]
    assert [a.stamm for a in ergebnis[0].aufnahmen] == [
        "D85_2584",
        "D85_2585",
        "D85_2586",
        "D85_2587",
        "D85_2588",
        "D85_2589",
        "D85_2590",
    ]


def test_die_nikon_reihe_gilt_NICHT_als_sicher():
    """Die D850 schreibt keinen Reihenzaehler — nachgesehen, nicht vermutet:
    ihre MakerNotes kennen nur `AutoBracketOrder` und den Belichtungswert je
    Bild. Die Gruppierung ist damit eine Ableitung aus Kameradaten, keine
    Aussage der Kamera. Sie als `sicher` auszuweisen hiesse, eine Vermutung
    als Tatsache zu fuehren — und genau diese Serien wuerden dann nie wieder
    angesehen."""
    aufnahmen = [
        _nikon(4, 0.0, sekunden=0),
        _nikon(5, -2.0, sekunden=2),
        _nikon(6, 2.0, sekunden=4),
    ]

    (serie,) = serien.aus_kamera(aufnahmen)

    assert serie.sicher is False
    assert serie.quelle == "kamera"


def test_ohne_reihenmodus_entsteht_keine_nikon_serie():
    aufnahmen = [
        _nikon(4, 0.0, sekunden=0, modus="Single-Frame"),
        _nikon(5, -2.0, sekunden=2, modus="Single-Frame"),
    ]

    assert serien.aus_kamera(aufnahmen) == []


def test_eine_einzelne_aufnahme_im_reihenmodus_ist_keine_serie():
    """Untergrenze: ohne sie wuerde jedes versehentlich im Reihenmodus
    ausgeloeste Einzelbild eine `Serie` bilden — im echten Bestand ist
    D85_2583 genau so ein Fall."""
    assert serien.aus_kamera([_nikon(3, 0.0, sekunden=0)]) == []


def test_serien_beider_kameras_werden_chronologisch_durchnummeriert():
    """Die Nummer steht im Dateinamen. Zwei Serien mit derselben Nummer waeren
    zwei verschiedene Reihen unter einem Namen."""
    aufnahmen = [
        _nikon(4, 0.0, sekunden=0),
        _nikon(5, -2.0, sekunden=2),
        _fuji(0, 1, sekunden=100),
        _fuji(1, 2, sekunden=101),
    ]

    ergebnis = serien.aus_kamera(aufnahmen)

    assert [s.nummer for s in ergebnis] == [1, 2]
    assert [s.aufnahmen[0].kamera for s in ergebnis] == ["D850", "XE5"]
