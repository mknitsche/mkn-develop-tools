"""Der Lauf: Seiten lesen, abgleichen, Ergebnis ablegen — wiederholbar ueber die Mitschrift."""

import json
import stat

import pytest

from conftest import ScheinLeser, angabe, schreibe_pdf
from mkn_dokument import lesen
from mkn_dokument.auftrag import AntwortUngueltig
from mkn_dokument.leser import LeserFehler


def test_zwei_seiten_werden_gelesen_abgeglichen_und_abgelegt(tmp_path):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf", seiten=2)
    a = ScheinLeser(
        "a",
        [
            {"angaben": [angabe("6,25"), angabe("13", lage=(300, 100, 310, 140))]},
            {"angaben": [angabe("7")]},
        ],
    )
    b = ScheinLeser("b", [{"angaben": [angabe("(6,25)")]}, {"angaben": [angabe("9")]}])
    ergebnis = lesen.lies_dokument(pdf, tmp_path / "aus", a, b, dokumentart="eines Tests")
    assert [(x["seite"], x["wert"], x["ausgang"], x["grund"]) for x in ergebnis["angaben"]] == [
        (1, "6,25", "uebernommen", "zwei_leser"),
        (1, "13", "klaerliste", "nur_leser_a"),
        (2, None, "klaerliste", "leser_uneins"),
    ]
    assert ergebnis["quelle"]["seiten"] == 2 and ergebnis["leser"] == {"a": "a", "b": "b"}
    datei = tmp_path / "aus" / lesen.ERGEBNIS
    assert json.loads(datei.read_text()) == ergebnis
    assert stat.S_IMODE(datei.stat().st_mode) == 0o600
    assert lesen.zaehle(ergebnis) == {"uebernommen": 1, "nur_leser_a": 1, "leser_uneins": 1}
    for ordner in (tmp_path / "aus", tmp_path / "aus" / lesen.MITSCHRIFT, tmp_path / "aus" / lesen.SEITEN):
        assert stat.S_IMODE(ordner.stat().st_mode) == 0o700


def test_zweiter_lauf_liest_aus_der_mitschrift_ohne_aufruf(tmp_path):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf")
    antwort = [{"angaben": [angabe("6,25")]}]
    erstes = lesen.lies_dokument(pdf, tmp_path / "aus", ScheinLeser("a", antwort), ScheinLeser("b", antwort))
    a, b = ScheinLeser("a", []), ScheinLeser("b", [])
    assert lesen.lies_dokument(pdf, tmp_path / "aus", a, b) == erstes
    assert a.aufrufe == [] and b.aufrufe == []


def test_anderer_leser_oder_anderer_auftrag_ist_eine_neue_lesung(tmp_path):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf")
    antwort = [{"angaben": [angabe("6,25")]}]
    lesen.lies_dokument(pdf, tmp_path / "aus", ScheinLeser("a", antwort), ScheinLeser("b", antwort))
    neu = ScheinLeser("c", antwort)
    lesen.lies_dokument(pdf, tmp_path / "aus", ScheinLeser("a", []), neu)
    assert len(neu.aufrufe) == 1
    a, b = ScheinLeser("a", antwort), ScheinLeser("b", antwort)
    lesen.lies_dokument(pdf, tmp_path / "aus", a, b, dokumentart="eines anderen Fachs")
    assert len(a.aufrufe) == 1 and len(b.aufrufe) == 1


def test_ungueltige_antwort_bricht_laut_und_wird_nie_mitschrift(tmp_path):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf")
    gut = [{"angaben": [angabe("6,25")]}]
    with pytest.raises(AntwortUngueltig):
        lesen.lies_dokument(pdf, tmp_path / "aus", ScheinLeser("a", gut), ScheinLeser("b", [{"falsch": 1}]))
    assert not (tmp_path / "aus" / lesen.ERGEBNIS).exists()
    b = ScheinLeser("b", gut)
    a = ScheinLeser("a", [])
    ergebnis = lesen.lies_dokument(pdf, tmp_path / "aus", a, b)
    assert a.aufrufe == [] and len(b.aufrufe) == 1  # a aus der Mitschrift, b frisch
    assert ergebnis["angaben"][0]["ausgang"] == "uebernommen"


def test_fehler_eines_lesers_bricht_den_lauf(tmp_path):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf")
    with pytest.raises(LeserFehler):
        lesen.lies_dokument(pdf, tmp_path / "aus", ScheinLeser("a", [LeserFehler("aus")]), ScheinLeser("b", []))
    assert not (tmp_path / "aus" / lesen.ERGEBNIS).exists()


def test_zweimal_derselbe_leser_wird_abgewiesen(tmp_path):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf")
    with pytest.raises(ValueError, match="derselbe"):
        lesen.lies_dokument(pdf, tmp_path / "aus", ScheinLeser("a", []), ScheinLeser("a", []))


def test_quell_hash_gehoert_zum_gelesenen_stand(tmp_path):
    import hashlib

    pdf = schreibe_pdf(tmp_path / "beleg.pdf")
    erwartet = hashlib.sha256(pdf.read_bytes()).hexdigest()

    class Ersetzer(ScheinLeser):
        def lies(self, auftrag, bild):
            schreibe_pdf(pdf, text="Inzwischen ersetzt")  # die Eingabe aendert sich waehrend der Lesung
            return super().lies(auftrag, bild)

    antwort = [{"angaben": [angabe("6,25")]}]
    ergebnis = lesen.lies_dokument(pdf, tmp_path / "aus", Ersetzer("a", antwort), ScheinLeser("b", antwort))
    assert ergebnis["quelle"]["sha256"] == erwartet
