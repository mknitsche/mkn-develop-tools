"""Die Pruefung ohne Menschen: was das Sprachmodell nicht aendern darf."""

from __future__ import annotations

import pytest

from mkn_audio.hoertext.pruefen import GRENZE, pruefe, zahlwoerter

# Ein Absatz mit rund 100 Woertern: ein einzelnes Wort liegt dann unter der Grenze von
# 3 %, sodass nur die eigene Zahlen-Regel anschlagen kann, nicht die Wort-Bilanz.
FUELLER = "Die Hunde liefen am Morgen über die Weide und der Hirte folgte ihnen langsam. "
LANG = FUELLER * 7 + "Dabei zählte er vier Hunde und einen Esel."


def test_unveraenderter_text_besteht():
    assert pruefe(LANG, LANG) is None


def test_umformung_mit_gleichen_woertern_besteht():
    vorher = "Das Auto (ein roter Wagen) fuhr los."
    nachher = "Das Auto, ein roter Wagen, fuhr los."
    assert pruefe(vorher, nachher) is None


@pytest.mark.parametrize(
    "wort",
    [
        "vier",
        "null",
        "zwölf",
        "dreißig",
        "zweiundzwanzig",
        "hundertachtundfünfzigtausend",
        "neunzehnhundertneunzig",
        "tausendneunhundertneunzig",
    ],
)
def test_zahlwoerter_werden_erkannt(wort):
    assert zahlwoerter([wort]) == {wort: 1}


@pytest.mark.parametrize(
    "wort",
    ["zwölften", "dritte", "ersten", "zwanzigsten", "siebten", "zweite", "hundertste"],
)
def test_ordnungszahlen_werden_erkannt(wort):
    assert zahlwoerter([wort]) == {wort: 1}


@pytest.mark.parametrize(
    "wort", ["ein", "eine", "einen", "einem", "einer", "eines", "und", "Hund", "Zeit", "Weide"]
)
def test_gewoehnliche_woerter_sind_keine_zahlwoerter(wort):
    assert not zahlwoerter([wort])


def test_ziffern_gelten_als_zahl():
    assert zahlwoerter(["3a", "Haus"]) == {"3a": 1}


def test_gross_und_kleinschreibung_ist_egal():
    assert zahlwoerter(["Vier"]) == {"vier": 1}


def test_zahl_geaendert_wird_auch_unter_der_wortgrenze_erkannt():
    nachher = LANG.replace("vier", "fünf")
    grund = pruefe(LANG, nachher)
    assert grund is not None
    assert "Zahl" in grund
    assert "vier" in grund
    assert "fünf" in grund


def test_zahl_entfernt_oder_hinzugefuegt_wird_erkannt():
    assert pruefe(LANG, LANG.replace("vier ", "")) is not None
    assert pruefe(LANG, LANG + " Es waren zehn.") is not None


def test_ausgelassener_satz_ueber_der_grenze():
    vorher = "Er kam. Sie ging. Wir blieben. Es regnete lange. Dann war Ruhe."
    nachher = "Er kam. Sie ging. Wir blieben. Dann war Ruhe."
    grund = pruefe(vorher, nachher)
    assert grund is not None
    assert "fehlt" in grund


def test_hinzugefuegter_satz_ueber_der_grenze():
    vorher = "Er kam. Sie ging. Wir blieben. Dann war Ruhe."
    nachher = vorher + " Plötzlich erschien ein Fremder."
    grund = pruefe(vorher, nachher)
    assert grund is not None
    assert "neu" in grund


def test_wiederholter_satz_aus_bekannten_woertern_ist_ein_zugewinn():
    # Eine Menge allein sähe das nicht: alle Wörter kommen schon vor.
    vorher = "Er kam. Sie ging. Wir blieben. Dann war Ruhe."
    assert pruefe(vorher, vorher + " Er kam. Sie ging.") is not None


def test_ein_wort_in_langem_absatz_liegt_unter_der_grenze():
    nachher = LANG.replace("Esel", "Maulesel")
    assert pruefe(LANG, nachher) is None
    assert 0 < GRENZE < 0.1


def test_ein_wort_in_kurzem_absatz_liegt_ueber_der_grenze():
    assert pruefe("Er kam gestern.", "Er kam heute.") is not None


def test_leerer_ausgangstext_laesst_kein_neues_wort_zu():
    assert pruefe("", "") is None
    assert pruefe("", "Etwas.") is not None
