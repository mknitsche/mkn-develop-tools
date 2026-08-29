"""Zusicherungen zur Entscheidungsvorlage.

Was das Werkzeug nicht belegen kann, entscheidet der Mensch — aber nur, wenn
er es ANSEHEN kann. Diese Vorlage legt je offener Session eine Handvoll
Bilder ab und schreibt daneben, was bekannt ist und was fehlt.

Zwei Dinge duerfen hier nicht passieren:

- Ein Original darf nicht angefasst werden. Kopiert wird, nie verschoben,
  nie geschrieben — die Kamerabilder sind das Einzige, was es nur einmal gibt.
- Die Auswahl darf nicht vom Anfang der Session stammen. Wer die ersten fuenf
  Bilder zeigt, zeigt fuenfmal dasselbe Motiv; die Session soll sich in der
  Auswahl wiedererkennen lassen.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from itertools import pairwise

import pytest
from mkn_foto import entscheidung
from mkn_foto.modell import Aufnahme, Ort, Spot

_START = datetime(2026, 8, 26, 17, 0, 0)


def _bild(nr: int, tmp_path=None, *, endungen=(".JPG",)) -> Aufnahme:
    dateien = {}
    for e in endungen:
        p = (tmp_path / f"DSCF{3500 + nr}{e}") if tmp_path else None
        if p is not None:
            p.write_bytes(b"nicht wirklich ein Bild")
        dateien[e] = p
    return Aufnahme(
        zeitpunkt=_START + timedelta(minutes=nr),
        kamera="XE5",
        stamm=f"DSCF{3500 + nr}",
        dateien=dateien,
        exif={},
    )


def test_die_auswahl_ist_ueber_die_session_verteilt():
    """Die ersten fuenf Bilder einer Session zeigen fuenfmal dasselbe Motiv.
    Verteilt zeigen sie, wo die Session anfaengt, wohin sie geht und wo sie
    endet — nur so ist sie wiederzuerkennen.

    Geprueft wird die EIGENSCHAFT, nicht eine ausgerechnete Liste: die erste
    Fassung dieses Tests trug von Hand gerechnete Namen und lag daneben — sie
    haette meine Kopfrechnung geprueft, nicht die Verteilung."""
    spot = Spot(aufnahmen=tuple(_bild(n) for n in range(20)))

    auswahl = entscheidung.waehle(spot, anzahl=5)

    stellen = [spot.aufnahmen.index(a) for a in auswahl]
    abstaende = [b - a for a, b in pairwise(stellen)]
    assert stellen[0] == 0
    assert stellen[-1] == len(spot.aufnahmen) - 1
    assert len(set(stellen)) == 5
    assert max(abstaende) - min(abstaende) <= 1, f"ungleich verteilt: {stellen}"


def test_das_erste_und_das_letzte_bild_sind_immer_dabei():
    """Sie zeigen, wo die Session begann und wo sie endete — der Anfang traegt
    oft die Wegmarke, das Ende den Aufbruch."""
    spot = Spot(aufnahmen=tuple(_bild(n) for n in range(20)))

    auswahl = entscheidung.waehle(spot, anzahl=3)

    assert auswahl[0].stamm == "DSCF3500"
    assert auswahl[-1].stamm == "DSCF3519"


def test_eine_kurze_session_wird_vollstaendig_gezeigt():
    """Untergrenze: bei weniger Bildern als gewuenscht darf nichts doppelt
    erscheinen — sonst sieht die Vorlage nach mehr Material aus, als es gibt."""
    spot = Spot(aufnahmen=tuple(_bild(n) for n in range(3)))

    auswahl = entscheidung.waehle(spot, anzahl=5)

    assert [a.stamm for a in auswahl] == ["DSCF3500", "DSCF3501", "DSCF3502"]


def test_originale_werden_kopiert_nicht_verschoben(tmp_path):
    """Die Kamerabilder sind das Einzige, was es nur einmal gibt."""
    quelle = tmp_path / "quelle"
    quelle.mkdir()
    spot = Spot(aufnahmen=tuple(_bild(n, quelle) for n in range(3)))
    ziel = tmp_path / "vorlage"

    entscheidung.bereite_vor([(spot, None)], ziel)

    assert all(a.dateien[".JPG"].exists() for a in spot.aufnahmen), "Original verschwunden"
    assert len(list(ziel.rglob("*.JPG"))) == 3


def test_nur_jpeg_wird_kopiert(tmp_path):
    """Eine RAW-Datei waere vierzigmal so gross und in keinem Vorschauprogramm
    schneller anzusehen. Fuer eine Ortsentscheidung reicht das JPEG."""
    quelle = tmp_path / "quelle"
    quelle.mkdir()
    spot = Spot(aufnahmen=(_bild(0, quelle, endungen=(".JPG", ".RAF")),))
    ziel = tmp_path / "vorlage"

    entscheidung.bereite_vor([(spot, None)], ziel)

    assert len(list(ziel.rglob("*.JPG"))) == 1
    assert list(ziel.rglob("*.RAF")) == []


def test_eine_session_ohne_jpeg_wird_gemeldet_statt_uebergangen(tmp_path):
    """Sonst fehlt in der Vorlage ein Ordner, und niemand weiss warum."""
    quelle = tmp_path / "quelle"
    quelle.mkdir()
    spot = Spot(aufnahmen=(_bild(0, quelle, endungen=(".RAF",)),))
    ziel = tmp_path / "vorlage"

    entscheidung.bereite_vor([(spot, None)], ziel)

    assert "kein JPEG" in (ziel / "liste.md").read_text()


def test_die_liste_nennt_was_bekannt_ist(tmp_path):
    """Ein Vorschlag mit Namen und Radius ist eine Frage, die sich mit Ja
    beantworten laesst — eine leere Zeile ist Arbeit."""
    quelle = tmp_path / "quelle"
    quelle.mkdir()
    spot = Spot(aufnahmen=tuple(_bild(n, quelle) for n in range(3)))
    vorschlag = Ort(lat=47.5, lon=11.3, radius_m=25, name="Kunstort", quelle="vorschlag")

    entscheidung.bereite_vor([(spot, vorschlag)], tmp_path / "vorlage")

    text = (tmp_path / "vorlage" / "liste.md").read_text()
    assert "Kunstort" in text
    assert "25" in text
    assert "47.5" in text


def test_die_liste_nennt_die_bildzahl_der_ganzen_session(tmp_path):
    """Nicht die Zahl der gezeigten Bilder: an einer Entscheidung fuer eine
    Session mit 141 Aufnahmen haengt anderes Gewicht als an einer mit zwei."""
    quelle = tmp_path / "quelle"
    quelle.mkdir()
    spot = Spot(aufnahmen=tuple(_bild(n, quelle) for n in range(12)))

    entscheidung.bereite_vor([(spot, None)], tmp_path / "vorlage", anzahl=3)

    assert "12 Aufnahmen" in (tmp_path / "vorlage" / "liste.md").read_text()


def test_die_liste_beginnt_mit_der_schwersten_entscheidung(tmp_path):
    """An einer Session mit 141 Aufnahmen haengt anderes Gewicht als an einer
    mit zwei. Wer die Liste chronologisch abarbeitet, faengt bei den
    Streubildern an und gibt vielleicht auf, bevor die Spots kommen.

    Gemessen am echten Bestand: von 20 offenen Sessions sind elf Streubilder
    mit zusammen 26 Aufnahmen — die neun echten Spots tragen die restlichen
    410."""
    quelle = tmp_path / "quelle"
    quelle.mkdir()
    klein = Spot(aufnahmen=(_bild(0, quelle),))
    gross = Spot(aufnahmen=tuple(_bild(n, quelle) for n in range(10, 20)))
    mittel = Spot(aufnahmen=tuple(_bild(n, quelle) for n in range(30, 34)))

    entscheidung.bereite_vor([(klein, None), (gross, None), (mittel, None)], tmp_path / "v")

    ordner = sorted(p.name for p in (tmp_path / "v").iterdir() if p.is_dir())
    # Erwartung aus den Daten abgeleitet, nicht getippt: eine von Hand
    # geschriebene Zeitangabe prueft die Kopfrechnung des Autors mit.
    assert f"{gross.von:%H%M}" in ordner[0], ordner
    assert f"{mittel.von:%H%M}" in ordner[1], ordner
    assert f"{klein.von:%H%M}" in ordner[2], ordner


def test_ein_zweiter_lauf_laesst_keine_alten_ordner_stehen(tmp_path):
    """Firsthand aufgefallen: der zweite Lauf legte neben die zwanzig neuen
    Ordner die zwanzig alten — vierzig Eintraege fuer zwanzig Sessions, und
    einem alten Ordner ist nicht anzusehen, dass er von gestern ist.

    Besonders tueckisch, weil die Nummerierung sich zwischen den Laeufen
    aendern darf: dann kollidieren die Namen nicht einmal."""
    quelle = tmp_path / "quelle"
    quelle.mkdir()
    ziel = tmp_path / "vorlage"
    zwei = Spot(aufnahmen=tuple(_bild(n, quelle) for n in range(2)))
    drei = Spot(aufnahmen=tuple(_bild(n, quelle) for n in range(10, 13)))

    entscheidung.bereite_vor([(zwei, None), (drei, None)], ziel)
    entscheidung.bereite_vor([(drei, None)], ziel)

    assert len([p for p in ziel.iterdir() if p.is_dir()]) == 1


def test_ein_fremder_ordner_wird_nicht_ueberschrieben(tmp_path):
    """Untergrenze zur Zeile darueber: das Aufraeumen darf nur die eigenen
    Spuren betreffen. Zeigt jemand versehentlich auf einen Ordner mit eigenen
    Dateien, muss es KNALLEN statt aufzuraeumen."""
    quelle = tmp_path / "quelle"
    quelle.mkdir()
    fremd = tmp_path / "fremd"
    fremd.mkdir()
    (fremd / "wichtig.txt").write_text("nicht anfassen")
    spot = Spot(aufnahmen=(_bild(0, quelle),))

    with pytest.raises(entscheidung.ZielNichtLeer):
        entscheidung.bereite_vor([(spot, None)], fremd)

    assert (fremd / "wichtig.txt").exists()


def test_die_ordner_tragen_zeit_und_nummer(tmp_path):
    """Der Ordnername muss ohne die Liste lesbar sein — sonst muss man beim
    Durchsehen staendig hin und her springen."""
    quelle = tmp_path / "quelle"
    quelle.mkdir()
    spot = Spot(aufnahmen=tuple(_bild(n, quelle) for n in range(3)))

    entscheidung.bereite_vor([(spot, None)], tmp_path / "vorlage")

    ordner = [p.name for p in (tmp_path / "vorlage").iterdir() if p.is_dir()]
    assert ordner == ["01_2026-08-26_1700-1702"]
