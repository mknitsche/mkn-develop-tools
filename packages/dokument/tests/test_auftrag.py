"""Die Antwort eines Lesers wird geprueft, bevor sie in den Abgleich geht."""

import pytest

from conftest import angabe
from mkn_dokument import auftrag


def test_auftrag_nennt_die_dokumentart_und_alle_felder():
    text = auftrag.auftrag("eines Kassenzettels")
    assert text.startswith("Du liest eine Seite eines Kassenzettels vom Seitenbild.")
    for feld in (*auftrag.FELDER, "lage", "unsicher"):
        assert f'"{feld}"' in text
    assert set(auftrag.SCHEMA["properties"]["angaben"]["items"]["required"]) == {
        *auftrag.FELDER,
        "lage",
        "unsicher",
    }


def test_gueltige_antwort_kommt_als_text_zurueck_fehlendes_leer():
    roh = {"angaben": [{"bezeichnung": "Druck", "wert": "72", "lage": [1, 2, 3, 4], "unsicher": True}]}
    (a,) = auftrag.pruefe_antwort(roh)
    assert a["wert"] == "72" and a["einheit"] == "" and a["lage"] == [1, 2, 3, 4] and a["unsicher"] is True


@pytest.mark.parametrize(
    "antwort",
    [
        None,
        [],
        {},
        {"angaben": "viele"},
        {"angaben": ["text"]},
        {"angaben": [angabe("1") | {"wert": ["1"]}]},
        {"angaben": [angabe("1") | {"wert": True}]},
    ],
)
def test_ungueltige_antwort_bricht_laut(antwort):
    with pytest.raises(auftrag.AntwortUngueltig):
        auftrag.pruefe_antwort(antwort)
