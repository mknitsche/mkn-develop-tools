"""Der Leser ueber mkn-kern: richtige Anfrage je Anbieter, laute Fehler."""

import json

import pytest
from mkn_kern import modelle

from conftest import angabe, schreibe_pdf
from mkn_dokument import leser, seiten


@pytest.fixture
def bild(tmp_path):
    return seiten.seitenbilder(schreibe_pdf(tmp_path / "b.pdf"), tmp_path / "aus")[0]


def transport_mit(antwort: dict, gesehen: list):
    def transport(url, roh, kopf, zeitgrenze):
        gesehen.append((url, json.loads(roh), kopf))
        return 200, json.dumps(antwort).encode()

    return transport


def test_anthropic_anfrage_traegt_bild_schluessel_und_liefert_das_json(bild, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "schluessel-a")
    gesehen: list = []
    inhalt = {"angaben": [angabe("6,25")]}
    antwort = {"content": [{"type": "text", "text": "```json\n" + json.dumps(inhalt) + "\n```"}]}
    lesender = leser.KernLeser(modelle.waehle("anthropic", "modell-x"), transport=transport_mit(antwort, gesehen))
    assert lesender.lies("Auftrag", bild) == inhalt
    _, koerper, kopf = gesehen[0]
    assert kopf["x-api-key"] == "schluessel-a"
    teile = koerper["messages"][0]["content"]
    assert teile[0]["text"] == "Auftrag" and teile[1]["type"] == "image"
    assert lesender.kennung == "anthropic:modell-x:32000"


def test_gemini_anfrage_verlangt_json_und_ueberspringt_denkteile(bild, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "schluessel-g")
    gesehen: list = []
    inhalt = {"angaben": []}
    antwort = {
        "candidates": [
            {
                "content": {"parts": [{"text": "ich denke", "thought": True}, {"text": json.dumps(inhalt)}]},
                "finishReason": "STOP",
            }
        ]
    }
    lesender = leser.KernLeser(modelle.waehle("gemini", "modell-y"), transport=transport_mit(antwort, gesehen))
    assert lesender.lies("Auftrag", bild) == inhalt
    url, koerper, kopf = gesehen[0]
    assert "modell-y" in url and kopf["x-goog-api-key"] == "schluessel-g"
    assert koerper["generationConfig"]["responseMimeType"] == "application/json"
    assert koerper["generationConfig"]["temperature"] == 0


@pytest.mark.parametrize(
    "antwort",
    [
        {"content": [{"type": "text", "text": '{"angaben": []}'}], "stop_reason": "max_tokens"},
        {"candidates": [{"content": {"parts": [{"text": '{"angaben": []}'}]}, "finishReason": "MAX_TOKENS"}]},
        {"content": [{"type": "text", "text": "kein json"}]},
        {"content": [{"type": "text", "text": "[1, 2]"}]},
        {"etwas": "anderes"},
    ],
)
def test_abgeschnittene_und_unverstaendliche_antwort_brechen_laut(bild, monkeypatch, antwort):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "s")
    lesender = leser.KernLeser(modelle.waehle("anthropic", "m"), transport=transport_mit(antwort, []))
    with pytest.raises(leser.LeserFehler):
        lesender.lies("Auftrag", bild)


def test_ohne_schluessel_geht_keine_anfrage_hinaus(bild):
    gesehen: list = []
    lesender = leser.KernLeser(modelle.waehle("anthropic", "m"), transport=transport_mit({}, gesehen))
    with pytest.raises(modelle.KeinSchluessel):
        lesender.lies("Auftrag", bild)
    assert gesehen == []
