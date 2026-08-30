"""Aus gemessenen Schritten werden Gruppen mit einer Klasse.

Das ist die Klammer zwischen Messung und Urteil: `deckung` liefert Zahlen ueber
Bildpaare, `serien.vermesse` macht daraus Gruppen und entscheidet, welche davon
ueberhaupt ans Modell gehen. Die Entscheidung ist billig und folgt einer Regel
aus dem Design (§ 3): **eine Gruppe mit mindestens einem Schwenk-Schritt ist ein
Kandidat.**

Was hier NICHT entschieden wird, ist die Panorama-Frage selbst -- die kann die
Messung nachweislich nicht beantworten (§ 3a: eine Gehsequenz sieht panoramiger
aus als ein echtes Panorama). Die Klassifikation bereitet vor; das Urteil faellt
am Bild.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from mkn_foto import serien
from mkn_foto.deckung import Deckung, Schritt
from mkn_foto.modell import Aufnahme, Serie

_START = datetime(2026, 8, 30, 15, 54, 9)


def _a(nr: int) -> Aufnahme:
    return Aufnahme(
        zeitpunkt=_START + timedelta(seconds=nr * 5),
        kamera="XE5",
        stamm=f"DSCF{3894 + nr}",
        dateien={},
        exif={},
    )


def _fenster(anzahl: int) -> Serie:
    return Serie(
        typ="",
        nummer=0,
        aufnahmen=tuple(_a(n) for n in range(anzahl)),
        quelle="heuristik",
        sicher=False,
    )


def _schritt(von: int, nach: int, art: str, dx: float = 0.0, dy: float = 0.35) -> Schritt:
    return Schritt(
        von=von,
        nach=nach,
        art=art,
        deckung=Deckung(korrelation=0.9, dx=dx, dy=dy if art == "schwenk" else 0.02, k0=0.3),
    )


def test_eine_gruppe_mit_einem_schwenk_ist_kandidat():
    """**Die Regel des Designs, und sie ist bewusst grosszuegig.**

    Ein Kandidat kostet einen Modellaufruf (~2 ct); ein uebersehener Fall kostet
    das Panorama. Der Prueffall ist genau so ein Mischfall -- ein Schwenk-Schritt
    (3894→3895) plus ein Wiederholungs-Schritt (3895→3896, die zweite Aufnahme
    derselben Zelle) -- und bleibt EIN Kandidat.
    """
    gruppen = serien.vermesse(
        [_fenster(3)],
        {0: [_schritt(0, 1, "schwenk"), _schritt(1, 2, "wiederholung")]},
    )

    assert len(gruppen) == 1
    assert gruppen[0].klasse == "kandidat", gruppen[0].klasse
    assert len(gruppen[0].aufnahmen) == 3


def test_nur_wiederholungen_sind_kein_kandidat():
    """Zwei Anlaeufe auf dasselbe Motiv gehen nicht als Panorama ans Modell.

    Sie werden trotzdem als Gruppe gefuehrt: der Motiv-Lauf fragt sie mit EINEM
    Kontaktbogen statt je Mitglied einzeln, was Aufrufe spart und an den Namen
    nichts aendert. Belegt am Bestand: `DSCF3917`/`3918`, Egidienkirche, Versatz
    0,05.
    """
    gruppen = serien.vermesse([_fenster(2)], {0: [_schritt(0, 1, "wiederholung")]})

    assert gruppen[0].klasse == "wiederholung"


def test_ohne_verbindung_zerfaellt_das_fenster():
    """Ein Fenster ist noch keine Aussage.

    Die Zeitfenster sind bewusst grosszuegig geschnitten (60 s); was die Messung
    darin nicht verbindet, sind Einzelbilder und geht denselben Weg wie bisher.
    Ueber die ganze Fotorunde zerfallen vier von sechs Fenstern genau so.
    """
    gruppen = serien.vermesse([_fenster(3)], {0: []})

    assert all(g.klasse == "einzeln" for g in gruppen), [g.klasse for g in gruppen]
    assert len(gruppen) == 3, "drei unverbundene Aufnahmen sind drei Einzelbilder"


def test_eine_gruppe_endet_wo_die_kette_reisst():
    """Ein Fenster kann mehrere Gruppen enthalten.

    Die Zeitgrenze schneidet grob, die Deckung fein: reisst die Kette in der
    Mitte, entstehen zwei Gruppen -- und nur die mit einem Schwenk-Schritt geht
    ans Modell.
    """
    gruppen = serien.vermesse(
        [_fenster(4)],
        {0: [_schritt(0, 1, "schwenk"), _schritt(2, 3, "wiederholung")]},
    )

    klassen = [g.klasse for g in gruppen]
    assert klassen.count("kandidat") == 1, klassen
    assert klassen.count("wiederholung") == 1, klassen


def test_das_raster_wird_je_kandidat_abgeleitet():
    """`m x n` steht am Kandidaten, nicht erst nach dem Urteil.

    Das Modell bekommt die Rastervermutung mitgeliefert; sie stammt aus der
    Messung, nicht aus dem Bild (Design § 5, am Pruefstein `D85_2560`-`2574`
    bewiesen).
    """
    gruppen = serien.vermesse(
        [_fenster(3)],
        {0: [_schritt(0, 1, "schwenk"), _schritt(1, 2, "schwenk", dx=0.25, dy=0.02)]},
    )

    assert gruppen[0].reihen, "kein Raster abgeleitet"
    assert sum(gruppen[0].reihen) == 3, gruppen[0].reihen
