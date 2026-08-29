"""Zusicherungen zur Kandidaten-Heuristik (Stufe 2).

Stufe 2 raet — und sie soll grosszuegig raten, weil ueber ihre Treffer erst
der Blick auf das Bild entscheidet. Der teure Fehler ist deshalb NICHT der
falsche Verdacht, sondern der uebersehene Fall: was Stufe 2 nicht vorschlaegt,
sieht nie jemand an.

Die Grenzwerte stammen aus gemessenen Reihen, nicht aus einer Schaetzung.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from mkn_foto import serien
from mkn_foto.modell import Aufnahme, Serie

_START = datetime(2026, 8, 26, 20, 15, 19)


def _bild(
    nr: int,
    *,
    brennweite: float = 34.0,
    blende: float = 8.0,
    zeit_s: float = 1 / 300,
    abstand: float = 2,
    kamera: str = "D850",
) -> Aufnahme:
    return Aufnahme(
        zeitpunkt=_START + timedelta(seconds=nr * abstand),
        kamera=kamera,
        stamm=f"D85_{2560 + nr}",
        dateien={},
        exif={
            "EXIF:Model": "NIKON D850",
            "EXIF:FocalLength": brennweite,
            "EXIF:FNumber": blende,
            "EXIF:ExposureTime": zeit_s,
        },
    )


def test_driftende_belichtungszeit_zerreisst_den_kandidaten_nicht():
    """Bei Zeitautomatik misst die Kamera jedes Bild neu. Ein Kriterium
    „alles konstant" verpasst genau die Panoramen — firsthand gemessen an
    einer Reihe mit f/8 und 34 mm konstant, waehrend die Zeit von 1/300 auf
    1/240 wanderte."""
    zeiten = [1 / 300, 1 / 280, 1 / 260, 1 / 250, 1 / 240]
    aufnahmen = [_bild(nr, zeit_s=z) for nr, z in enumerate(zeiten)]

    (kandidat,) = serien.kandidaten(aufnahmen, schon_erkannt=[])

    assert len(kandidat.aufnahmen) == 5


def test_wechselnde_brennweite_beendet_den_kandidaten():
    """Wer zoomt, schwenkt kein Panorama."""
    aufnahmen = [_bild(0), _bild(1), _bild(2), _bild(3), _bild(4, brennweite=70.0)]

    (kandidat,) = serien.kandidaten(aufnahmen, schon_erkannt=[])

    assert len(kandidat.aufnahmen) == 4


def test_wechselnde_blende_beendet_den_kandidaten():
    """Untergrenze zur Brennweite: ohne diesen Fall wuerde ein Merkmalspaar,
    das nur die Brennweite prueft, unbemerkt durchgehen."""
    aufnahmen = [_bild(0), _bild(1), _bild(2), _bild(3), _bild(4, blende=11.0)]

    (kandidat,) = serien.kandidaten(aufnahmen, schon_erkannt=[])

    assert len(kandidat.aufnahmen) == 4


def test_eine_lange_pause_beendet_den_kandidaten():
    """Zwei Motive nacheinander mit derselben Einstellung sind kein Schwenk."""
    aufnahmen = [_bild(nr) for nr in range(4)] + [_bild(nr, abstand=2) for nr in range(30, 34)]

    ergebnis = serien.kandidaten(aufnahmen, schon_erkannt=[])

    assert [len(k.aufnahmen) for k in ergebnis] == [4, 4]


def test_ein_kamerawechsel_beendet_den_kandidaten():
    """Zwei Kameras koennen dieselbe Sekunde belegen — ohne diese Grenze
    liefe eine Fuji-Aufnahme mitten in eine Nikon-Reihe."""
    aufnahmen = [_bild(nr) for nr in range(4)] + [_bild(nr, kamera="XE5") for nr in range(4, 8)]

    ergebnis = serien.kandidaten(aufnahmen, schon_erkannt=[])

    assert [len(k.aufnahmen) for k in ergebnis] == [4, 4]


def test_drei_bilder_sind_noch_kein_kandidat():
    """Darunter ist es keine Reihe, sondern eine Wiederholung."""
    assert serien.kandidaten([_bild(0), _bild(1), _bild(2)], schon_erkannt=[]) == []


def test_was_die_kamera_schon_bezeugt_hat_wird_nicht_nochmal_geraten():
    """Sonst traegt dieselbe Aufnahme zwei Serienzuordnungen — und der
    Dateiname kann nur eine tragen."""
    aufnahmen = [_bild(nr) for nr in range(5)]
    bekannt = Serie(typ="hdr", nummer=1, aufnahmen=tuple(aufnahmen), quelle="kamera", sicher=True)

    assert serien.kandidaten(aufnahmen, schon_erkannt=[bekannt]) == []


def test_eine_bereits_belegte_aufnahme_verbindet_nicht_ueber_sich_hinweg():
    """Untergrenze zur Zeile darueber: die belegte Aufnahme darf nicht
    einfach uebersprungen werden, sonst waechst ein Kandidat quer durch eine
    bezeugte Serie hindurch zusammen."""
    aufnahmen = [_bild(nr) for nr in range(9)]
    bekannt = Serie(typ="hdr", nummer=1, aufnahmen=(aufnahmen[4],), quelle="kamera", sicher=True)

    ergebnis = serien.kandidaten(aufnahmen, schon_erkannt=[bekannt])

    assert [len(k.aufnahmen) for k in ergebnis] == [4, 4]


def test_kandidaten_sind_ausdruecklich_unsicher():
    """`sicher=False` ist das Signal an Stufe 3, das Bild anzusehen — und an
    den Bericht, den Punkt auf die Nacharbeits-Liste zu setzen."""
    (kandidat,) = serien.kandidaten([_bild(nr) for nr in range(5)], schon_erkannt=[])

    assert kandidat.sicher is False
    assert kandidat.quelle == "heuristik"
    assert kandidat.typ == "pan"


def test_gleiche_zeitstempel_bringen_die_gruppierung_nicht_durcheinander():
    """Die Kamera schreibt nur Sekunden — bei einem schnellen Schwenk teilen
    sich mehrere Bilder eine. Haengt die Reihenfolge dann an der Eingabe,
    schwankt auch das Ergebnis."""
    aufnahmen = [_bild(nr, abstand=0) for nr in range(6)]
    verdreht = [aufnahmen[3], aufnahmen[5], aufnahmen[0], aufnahmen[4], aufnahmen[1], aufnahmen[2]]

    (kandidat,) = serien.kandidaten(verdreht, schon_erkannt=[])

    assert [a.stamm for a in kandidat.aufnahmen] == [a.stamm for a in aufnahmen]
