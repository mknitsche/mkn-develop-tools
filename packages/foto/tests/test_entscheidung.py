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
from mkn_foto.modell import Aufnahme, Spot

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


def test_der_ordnername_traegt_nur_datum_und_zeit(tmp_path):
    """Keine laufende Nummer. Mit ihr kann niemand zwei Ordner zusammenfassen
    oder einen verschieben, ohne dass die Reihenfolge luegt — und weil die
    Liste nach Gewicht sortiert war, sprangen die Ordner zwischen den Tagen
    hin und her. Ohne Nummer sortieren sie sich von selbst chronologisch."""
    quelle = tmp_path / "quelle"
    quelle.mkdir()
    spot = Spot(aufnahmen=tuple(_bild(n, quelle) for n in range(3)))

    entscheidung.bereite_vor([(spot, None)], tmp_path / "v")

    ordner = [p.name for p in (tmp_path / "v").iterdir() if p.is_dir()]
    assert ordner == ["2026-08-26_1700-1702"]


def test_in_jedem_ordner_liegen_nur_noch_die_bilder(tmp_path):
    """Seit macb-S314 steht die Eingabe zentral in EINER Datei.

    Zwoelf Ordner mit je einem Formular waren genau die Form, bei der KT-1 nicht
    mehr wusste, was er tun soll — und zwei Wege fuer dieselbe Eingabe waeren
    ausserdem zwei Zustaende ueber eine Sache. Hier liegen deshalb nur noch die
    Bilder zum Ansehen; die Zusicherungen ueber das Eingabeformular leben in
    `test_bericht.py`.
    """
    quelle = tmp_path / "quelle"
    quelle.mkdir()
    spot = Spot(aufnahmen=tuple(_bild(n, quelle) for n in range(3)))

    ziel = entscheidung.bereite_vor([(spot, None)], tmp_path / "v")

    ordner = ziel / "2026-08-26_1700-1702"
    assert not (ordner / "ort.md").exists(), (
        "es entsteht wieder ein Formular je Ordner — die Eingabe gehoert an EINE Stelle"
    )
    assert list(ordner.glob("*.JPG")), f"keine Bilder zum Ansehen: {list(ordner.iterdir())}"


def test_ein_neuer_lauf_zerstoert_keine_geschriebene_notiz(tmp_path):
    """Der gefaehrlichste Fall des ganzen Moduls.

    Geprueft wird die ZENTRALE Eingabedatei — seit macb-S314 traegt sie die
    Antworten, nicht mehr eine Notiz je Ordner. Die vier Tests ueber den Inhalt
    einer Einzelnotiz sind mit ihrem Gegenstand nach `test_bericht.py` gewandert;
    hier bleibt der Schutz, weil er zum Raeumen gehoert und nicht zum Schreiben.

    Wer zwanzig Ordner durchgearbeitet und seine Orte eingetragen hat, verliert
    diese Arbeit unwiederbringlich, wenn der naechste Lauf das Ziel raeumt. Ein
    Warnsatz in einer Datei ist kein Schutz — er wird gelesen, nachdem es
    passiert ist. Also wird geprueft und angehalten."""
    quelle = tmp_path / "quelle"
    quelle.mkdir()
    ziel = tmp_path / "v"
    spot = Spot(aufnahmen=tuple(_bild(n, quelle) for n in range(3)))
    entscheidung.bereite_vor([(spot, None)], ziel)

    # Seit macb-S314 steht die Eingabe zentral: EINE Datei statt einer Notiz je
    # Ordner. Die Zusicherung ist dieselbe geblieben, nur ihr Gegenstand ist neu.
    zentral = ziel / entscheidung.SAMMELDATEI
    zentral.write_text(
        "# Offene Orte\n\n## 2026-08-26 · 17:00-17:02 · 3 Aufnahmen\n\n"
        "**Antwort:** Leutaschklamm\n",
        encoding="utf-8",
    )

    with pytest.raises(entscheidung.NotizenVorhanden) as fehler:
        entscheidung.bereite_vor([(spot, None)], ziel)

    # Die Meldung muss den betroffenen Ordner NENNEN — sonst weiss niemand,
    # welche Arbeit gerade auf dem Spiel steht.
    assert "2026-08-26" in str(fehler.value), (
        f"die Meldung nennt nicht, welche Arbeit auf dem Spiel steht: {fehler.value}"
    )
    assert "Leutaschklamm" in zentral.read_text(encoding="utf-8")


def test_ein_unberuehrter_lauf_darf_geraeumt_werden(tmp_path):
    """Untergrenze: waere jede vorhandene Notiz ein Hindernis, liesse sich der
    Lauf nie wiederholen — und genau das passiert oft, weil sich die Daten
    aendern."""
    quelle = tmp_path / "quelle"
    quelle.mkdir()
    ziel = tmp_path / "v"
    spot = Spot(aufnahmen=tuple(_bild(n, quelle) for n in range(3)))

    entscheidung.bereite_vor([(spot, None)], ziel)
    entscheidung.bereite_vor([(spot, None)], ziel)

    assert len([p for p in ziel.iterdir() if p.is_dir()]) == 1


def test_eine_unausgefuellte_sammeldatei_blockiert_nicht(tmp_path):
    """Untergrenze zum Schutz darueber: der zweite Lauf muss moeglich bleiben.

    Nach dem ERSTEN Lauf liegt die zentrale Datei bereits da, mit lauter leeren
    Feldern. Wer nur auf ihre Existenz prueft statt auf ihren Inhalt, sperrt
    damit jeden weiteren Lauf aus — und die Zusicherung darueber waere trotzdem
    gruen, weil sie nur den beschriebenen Fall kennt.
    """
    quelle = tmp_path / "quelle"
    quelle.mkdir()
    ziel = tmp_path / "v"
    spot = Spot(aufnahmen=tuple(_bild(n, quelle) for n in range(3)))
    entscheidung.bereite_vor([(spot, None)], ziel)

    (ziel / entscheidung.SAMMELDATEI).write_text(
        "# Offene Orte\n\n## 2026-08-26 · 17:00-17:02 · 3 Aufnahmen\n\n**Antwort:**\n",
        encoding="utf-8",
    )

    # Darf NICHT werfen.
    entscheidung.bereite_vor([(spot, None)], ziel)
