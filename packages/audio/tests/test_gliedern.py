"""Tests der Stufe Gliedern: Dokument -> Stuecke, und die Kapitelauswahl."""

from __future__ import annotations

import pytest

from mkn_audio.gliedern import gliedere, waehle
from mkn_audio.typen import Dokument, Kapitel, Mp4Fehler


def _dok(*kapitel: Kapitel) -> Dokument:
    return Dokument(titel="T", autor=None, sprache="de", kapitel=tuple(kapitel))


def _texte(dok: Dokument, **kw) -> list[str]:
    return [s.text for s in gliedere(dok, **kw) if s.art == "text"]


def test_satzgrenzen():
    dok = _dok(Kapitel("K", ("Er sagte: Ja. Dann ging er.",)))
    assert _texte(dok) == ["Er sagte: Ja.", "Dann ging er."]


def test_ein_satz_je_stueck_nie_gebuendelt():
    dok = _dok(Kapitel("K", ("Eins. Zwei. Drei.",)))
    assert _texte(dok) == ["Eins.", "Zwei.", "Drei."]


def test_satzende_mit_anfuehrungszeichen_nach_dem_punkt():
    dok = _dok(Kapitel("K", ("Sie sagte „Ja.“ Dann ging sie.",)))
    assert _texte(dok) == ["Sie sagte „Ja.“", "Dann ging sie."]


def test_satzende_mit_fragezeichen_ausrufezeichen_und_auslassung():
    dok = _dok(Kapitel("K", ("Wirklich?! Ja. Warte... Dann los.",)))
    assert _texte(dok) == ["Wirklich?!", "Ja.", "Warte...", "Dann los."]


def test_dezimalzahl_und_komma_sind_kein_satzende():
    dok = _dok(Kapitel("K", ("Es kostet 3.5 Euro, glaube ich.",)))
    assert _texte(dok) == ["Es kostet 3.5 Euro, glaube ich."]


def test_zeilenumbrueche_im_absatz_werden_zu_leerzeichen():
    dok = _dok(Kapitel("K", ("Ein Satz\nueber zwei  Zeilen.",)))
    assert _texte(dok) == ["Ein Satz ueber zwei Zeilen."]


def test_ueberlanger_satz_mitte_an_semikolon():
    links = "a" * 100 + " " + "b" * 150 + ";"
    rechts = "c" * 100 + " " + "d" * 150 + "."
    # Kommas weiter aussen duerfen nicht gewinnen: Semikolon geht vor Komma.
    satz = "x, " + links + " " + rechts
    dok = _dok(Kapitel("K", (satz,)))
    teile = _texte(dok)
    assert teile == ["x, " + links, rechts]
    assert all(len(t) <= 400 for t in teile)


def test_ueberlanger_satz_ohne_semikolon_teilt_am_komma_nahe_der_mitte():
    satz = ("wort " * 40).strip() + ", " + ("zeit " * 40).strip() + "."
    assert len(satz) > 400
    teile = _texte(_dok(Kapitel("K", (satz,))))
    assert len(teile) == 2
    assert teile[0].endswith(",")
    assert all(len(t) <= 400 for t in teile)


def test_ueberlanger_absatz_ohne_satzzeichen():
    absatz = " ".join(f"eintrag{i}" for i in range(250))
    assert len(absatz) > 2000
    teile = _texte(_dok(Kapitel("K", (absatz,))))
    assert len(teile) >= 5
    assert all(len(t) <= 400 for t in teile)
    # Nichts geht verloren, nichts kommt dazu.
    assert " ".join(teile) == absatz


def test_wort_ohne_leerzeichen_wird_hart_geschnitten():
    url = "x" * 1000
    teile = _texte(_dok(Kapitel("K", (url,))))
    assert all(len(t) <= 400 for t in teile)
    assert "".join(teile) == url


def test_max_zeichen_ist_einstellbar():
    dok = _dok(Kapitel("K", ("eins zwei drei vier fuenf sechs",)))
    teile = _texte(dok, max_zeichen=15)
    assert all(len(t) <= 15 for t in teile)
    assert " ".join(teile) == "eins zwei drei vier fuenf sechs"


def test_titel_stueck_je_kapitel_und_nummerierung():
    dok = _dok(
        Kapitel("Erstes", ("Ah. Be.", "Ce.")),
        Kapitel("Zweites", ("De.",)),
    )
    stuecke = gliedere(dok)
    assert [(s.kapitel, s.absatz, s.nr, s.text, s.art) for s in stuecke] == [
        (0, -1, 0, "Erstes", "titel"),
        (0, 0, 1, "Ah.", "text"),
        (0, 0, 2, "Be.", "text"),
        (0, 1, 3, "Ce.", "text"),
        (1, -1, 4, "Zweites", "titel"),
        (1, 0, 5, "De.", "text"),
    ]


def test_leerer_absatz_faellt_weg_aber_der_index_bleibt():
    dok = _dok(Kapitel("K", ("Eins.", "   ", "Drei.")))
    stuecke = [s for s in gliedere(dok) if s.art == "text"]
    assert [(s.absatz, s.text) for s in stuecke] == [(0, "Eins."), (2, "Drei.")]


def test_kapitel_ohne_titel_hat_kein_titelstueck():
    dok = _dok(Kapitel("  ", ("Nur Text.",)))
    stuecke = gliedere(dok)
    assert [(s.art, s.nr) for s in stuecke] == [("text", 0)]


def test_max_zeichen_unsinn_bricht_laut():
    with pytest.raises(Mp4Fehler):
        gliedere(_dok(Kapitel("K", ("Text.",))), max_zeichen=0)


@pytest.fixture
def vier_kapitel() -> Dokument:
    return _dok(*(Kapitel(f"K{i}", (f"Text {i}.",)) for i in range(1, 5)))


def _titel(dok: Dokument) -> list[str]:
    return [k.titel for k in dok.kapitel]


def test_auswahl_bereiche(vier_kapitel):
    assert waehle(vier_kapitel, None) is vier_kapitel
    assert _titel(waehle(vier_kapitel, "3")) == ["K3"]
    assert _titel(waehle(vier_kapitel, "1-3")) == ["K1", "K2", "K3"]
    assert _titel(waehle(vier_kapitel, "2,4")) == ["K2", "K4"]
    assert _titel(waehle(vier_kapitel, "1-2, 4")) == ["K1", "K2", "K4"]


def test_auswahl_behaelt_dokumentreihenfolge_und_ueberschneidungen_zaehlen_einmal(vier_kapitel):
    assert _titel(waehle(vier_kapitel, "4,1-3,2")) == ["K1", "K2", "K3", "K4"]


def test_auswahl_behaelt_titel_autor_und_cover():
    kapitel = (Kapitel("K1", ("x.",)), Kapitel("K2", ("y.",)))
    neu = waehle(Dokument("T", "A", "de", kapitel, ("w",), b"c"), "2")
    assert (neu.titel, neu.autor, neu.sprache) == ("T", "A", "de")
    assert (neu.warnungen, neu.cover) == (("w",), b"c")


@pytest.mark.parametrize(
    "auswahl", ["", " ", "0", "5", "1-5", "3-1", "a", "1-", "-2", "1,,2", "1.5", "\u00b2"]
)
def test_auswahl_ungueltig_bricht_laut(vier_kapitel, auswahl):
    with pytest.raises(Mp4Fehler):
        waehle(vier_kapitel, auswahl)


def test_ansage_stuecke_markiert():
    """Absaetze mit Art ausser `wortlaut` sind Ansagen; Titel und Wortlaut nie."""
    dok = Dokument(
        "T",
        None,
        "de",
        (
            Kapitel("", ("Sie hören ein Buch. Viel Freude.",), ("vorspann",)),
            Kapitel(
                "Eins",
                ("Erster Satz hier.", "Weiter geht es."),
                ("wortlaut", "ueberleitung"),
            ),
            Kapitel("Zwei", ("Ohne Regie.",)),
        ),
    )

    stuecke = gliedere(dok)

    assert [(s.kapitel, s.art, s.ansage) for s in stuecke] == [
        (0, "text", True),  # Vorspann, zwei Saetze
        (0, "text", True),
        (1, "titel", False),
        (1, "text", False),
        (1, "text", True),  # Ueberleitung
        (2, "titel", False),
        (2, "text", False),  # Kapitel ohne Arten: alles Wortlaut
    ]
    assert not any(s.art == "titel" for s in stuecke if s.kapitel == 0)  # leerer Titel


def test_initialen_sind_kein_satzende():
    # Kapitel 1 des Hoerbuchs (24.10.): "C. G. Jung" zerfiel in die Stuecke "C." und "G.",
    # an denen die Stimme scheiterte.
    dok = _dok(Kapitel("K", ("Schon C. G. Jung schrieb davon. Dann kam Freud.",)))
    assert _texte(dok) == ["Schon C. G. Jung schrieb davon.", "Dann kam Freud."]
    dok = _dok(Kapitel("K", ("Schon C.G. Jung schrieb davon. Dann kam Freud.",)))
    assert _texte(dok) == ["Schon C.G. Jung schrieb davon.", "Dann kam Freud."]


def test_klein_weiter_ist_kein_satzende():
    # "Pius IX. zum Dogma" (roemische Zahl), "ca. zehn": geht es klein weiter, endet kein Satz.
    dok = _dok(Kapitel("K", ("Es war Pius IX. zum Dogma erklärt worden. Dann kam mehr.",)))
    assert _texte(dok) == ["Es war Pius IX. zum Dogma erklärt worden.", "Dann kam mehr."]
