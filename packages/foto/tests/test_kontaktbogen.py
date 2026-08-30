"""Ein Bild statt fuenfzehn — der Kontaktbogen.

Spec § 4a: *"Alle Bilder der Serie als ein Bild, nummeriert, im Raster. Reines
Pillow, kein LLM-Aufruf. Er ist zugleich das Werkzeug, mit dem Stufe 3 urteilt —
statt fuenfzehn Einzelbildern ein Blick. Firsthand erprobt: am Kontaktbogen der
Zugspitzen-Serie war die Reihenstruktur sofort lesbar, an den Einzelbildern
nicht."*

Er ist auch der Grund, warum die Bildanalyse bezahlbar bleibt: eine Serie ist per
Definition EIN Motiv. 630 Aufrufe statt 1.293, rund 7 € statt 13.

**Die Nummern sind kein Schmuck.** Das Modell soll sagen koennen „Bild 3 bis 7
gehoeren nicht dazu" — ohne Nummern kann es die Stelle nicht benennen, und die
Antwort ist unbrauchbar.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mkn_foto import kontaktbogen

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def _bilder(ordner: Path, anzahl: int, breite: int = 400, hoehe: int = 300) -> list[Path]:
    ordner.mkdir(parents=True, exist_ok=True)
    pfade = []
    for i in range(anzahl):
        p = ordner / f"b{i:03d}.jpg"
        # Unterscheidbare Farben, damit ein Vertauschen sichtbar waere.
        Image.new("RGB", (breite, hoehe), (i * 20 % 256, 100, 200)).save(p)
        pfade.append(p)
    return pfade


def test_alle_bilder_landen_auf_einem_bogen(tmp_path):
    pfade = _bilder(tmp_path / "q", 6)

    bogen = kontaktbogen.baue(pfade, tmp_path / "bogen.jpg")

    assert bogen.exists()
    with Image.open(bogen) as bild:
        assert bild.width > 0 and bild.height > 0


def test_die_reihenfolge_bleibt_erhalten(tmp_path):
    """Ohne sie kann das Modell nicht sagen, WELCHES Bild aus der Reihe faellt.

    Geprueft ueber die Farben: das erste Kaechelchen oben links muss die Farbe
    des ersten Bildes tragen.
    """
    pfade = _bilder(tmp_path / "q", 4)
    with Image.open(pfade[0]) as erstes:
        farbe_erstes = erstes.getpixel((10, 10))

    bogen = kontaktbogen.baue(pfade, tmp_path / "bogen.jpg", rand=0, beschriftung=False)

    with Image.open(bogen) as b:
        # Ein Stueck innerhalb der ersten Kachel, jenseits moeglicher Kanten.
        ecke = b.getpixel((20, 20))
    assert abs(ecke[0] - farbe_erstes[0]) < 30, (
        f"oben links steht nicht das erste Bild: {ecke} gegen {farbe_erstes}"
    )


def test_bei_vielen_bildern_wird_gesampelt(tmp_path):
    """Ein Bogen mit hundert Kacheln ist unlesbar — und teuer, weil er als Bild
    an das Modell geht."""
    pfade = _bilder(tmp_path / "q", 40)

    bogen = kontaktbogen.baue(pfade, tmp_path / "bogen.jpg")

    # Die AUSWAHL pruefen, nicht die Rechenfunktion daneben: `gezeigte()` ist
    # reines `min()` und bleibt richtig, auch wenn `auswahl` gar nicht sampelt.
    # Genau so blieb die erste Fassung gruen.
    assert len(kontaktbogen.auswahl(pfade)) == kontaktbogen.MAX_KACHELN, (
        f"nicht gesampelt: {len(kontaktbogen.auswahl(pfade))} von {len(pfade)}"
    )
    assert bogen.exists()
    # Und der Bogen darf nicht so gross sein, dass vierzig Kacheln daraufpassen.
    with Image.open(bogen) as b:
        flaeche = b.width * b.height
    assert flaeche < 25 * (kontaktbogen.KACHEL_PX + kontaktbogen.RAND_PX) ** 2, (
        f"der Bogen ist {b.width}x{b.height} gross — da passen mehr als "
        f"{kontaktbogen.MAX_KACHELN} Kacheln drauf"
    )


def test_beim_sampeln_bleiben_erstes_und_letztes_bild_drin(tmp_path):
    """Sie tragen den Anfang und das Ende der Reihe — genau das, was beim
    Beurteilen einer Serie zaehlt."""
    pfade = _bilder(tmp_path / "q", 40)

    gewaehlt = kontaktbogen.auswahl(pfade)

    assert gewaehlt[0] == pfade[0], "das erste Bild fehlt"
    assert gewaehlt[-1] == pfade[-1], "das letzte Bild fehlt"
    assert len(gewaehlt) == kontaktbogen.MAX_KACHELN


def test_wenige_bilder_werden_nicht_gesampelt(tmp_path):
    """Untergrenze: sonst waere ein Sampling, das immer greift, genauso gruen —
    und eine Dreier-Serie verlore Bilder ohne Not."""
    pfade = _bilder(tmp_path / "q", 3)

    assert kontaktbogen.auswahl(pfade) == pfade


def test_ein_unlesbares_bild_reisst_den_bogen_nicht_ab(tmp_path):
    """Bei 1.293 Aufnahmen ist eine kaputte Datei normal. Der Bogen entsteht
    trotzdem, mit den ueberigen."""
    pfade = _bilder(tmp_path / "q", 4)
    kaputt = tmp_path / "q" / "kaputt.jpg"
    kaputt.write_bytes(b"kein bild")
    pfade.insert(2, kaputt)

    bogen = kontaktbogen.baue(pfade, tmp_path / "bogen.jpg")

    assert bogen is not None and bogen.exists()


def test_ohne_ein_einziges_lesbares_bild_entsteht_kein_bogen(tmp_path):
    """Untergrenze zum Fall darueber: ein leerer Bogen waere ein Bild ohne
    Inhalt, das trotzdem Geld kostet, wenn es an das Modell geht."""
    kaputt = tmp_path / "kaputt.jpg"
    kaputt.write_bytes(b"kein bild")

    assert kontaktbogen.baue([kaputt], tmp_path / "bogen.jpg") is None
