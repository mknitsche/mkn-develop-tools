"""Manifest: das gelesene Dokument in der gemeinsamen Schnittstelle (Bereichs-Manifest).

Der Fall, der zaehlt: das Manifest zeigt ALLES mit Art und aendert keinen Buchstaben. Ein
Manifest, das Text umformuliert oder stillschweigend weglaesst, machte den Abnehmer blind
fuer genau das, was er beurteilen soll.
"""

from __future__ import annotations

import json

import pytest

from mkn_audio.manifest import ART_VON_ROLLE, als_manifest, schreibe_manifest
from mkn_audio.regie import ROLLEN, Rollenbild
from mkn_audio.typen import Dokument, Kapitel, Mp4Fehler

DOK = Dokument(
    titel="Größe & Maß",
    autor="Erika Muster",
    sprache="de",
    kapitel=(
        Kapitel("Eins", ("Das ist der erste Absatz.", "Und ein zweiter, etwas länger.")),
        Kapitel("", ("Dritter Absatz.",)),
        Kapitel("Leer", ()),
    ),
)
ROLLEN_BILD = Rollenbild(
    "Zeitschriftenartikel",
    {(0, 0): "ueberschrift", (0, 1): "haupttext", (1, 0): "fussnote"},
)
KW = {"quelle": "/wo/auch/immer/Artikel.pdf", "sha256": "ab" * 32, "herkunft": "textschicht"}


def _manifest(dok=DOK, rollenbild=ROLLEN_BILD, **zusatz):
    return als_manifest(dok, rollenbild, leser="mkn-audio", **{**KW, **zusatz})


def _bereiche(manifest):
    return [b for a in manifest["abschnitte"] for b in a["bereiche"]]


def test_manifest_struktur_nach_schnittstelle():
    m = _manifest()

    assert set(m) == {"quelle", "abschnitte", "text_bilanz"}
    assert set(m["quelle"]) == {
        "pfad",
        "sha256",
        "dokumentart",
        "titel",
        "autor",
        "datum",
        "sprache",
        "seiten_gesamt",
    }
    assert m["quelle"]["dokumentart"] == "Zeitschriftenartikel"
    assert m["quelle"]["titel"] == "Größe & Maß"
    assert m["quelle"]["autor"] == "Erika Muster"
    assert m["quelle"]["datum"] == ""
    assert m["quelle"]["sprache"] == "de"
    assert m["quelle"]["seiten_gesamt"] is None
    assert m["quelle"]["sha256"] == "ab" * 32

    assert [a["nr"] for a in m["abschnitte"]] == [1, 2, 3]
    assert [a["titel"] for a in m["abschnitte"]] == ["Eins", "", "Leer"]
    for abschnitt in m["abschnitte"]:
        assert set(abschnitt) == {"nr", "titel", "seite_von", "seite_bis", "bereiche"}
        assert abschnitt["seite_von"] is None and abschnitt["seite_bis"] is None
    assert m["abschnitte"][2]["bereiche"] == []

    for bereich in _bereiche(m):
        assert set(bereich) == {
            "nr",
            "reihenfolge",
            "art",
            "titel",
            "seite",
            "text",
            "handschrift",
            "herkunft",
            "lage",
            "leser",
        }
        assert bereich["handschrift"] is False
        assert bereich["herkunft"] == "textschicht"
        assert bereich["seite"] is None and bereich["lage"] is None
        assert bereich["leser"] == "mkn-audio"
    # Es muss als JSON ausgebbar sein, ohne Sonderbehandlung.
    assert json.loads(json.dumps(m, ensure_ascii=False)) == m


def test_autor_und_unbekanntes_bleiben_ehrlich():
    dok = Dokument("T", None, "en", (Kapitel("K", ("a",)),))

    m = als_manifest(dok, None, **KW, leser="x")

    assert m["quelle"]["autor"] is None
    assert m["quelle"]["sprache"] == "en"
    assert m["quelle"]["dokumentart"] == ""


def test_rollen_werden_arten():
    assert set(ART_VON_ROLLE) == set(ROLLEN), "jede Rolle der Regie braucht eine Art"
    kapitel = tuple(Kapitel(f"K{i}", (f"Text {rolle}.",)) for i, rolle in enumerate(ROLLEN))
    dok = Dokument("T", None, "de", kapitel)
    bild = Rollenbild("", {(i, 0): rolle for i, rolle in enumerate(ROLLEN)})

    arten = [b["art"] for b in _bereiche(_manifest(dok, bild))]

    assert arten == [ART_VON_ROLLE[rolle] for rolle in ROLLEN]
    assert ART_VON_ROLLE["haupttext"] == "fliesstext"
    assert ART_VON_ROLLE["metadaten"] == "kopf"
    assert ART_VON_ROLLE["tabelle"] == "wert_tabelle"
    assert ART_VON_ROLLE["bedienelement"] == "bedienelement"
    assert ART_VON_ROLLE["fussnote"] == "fussnote"


def test_absatz_ohne_eintrag_im_rollenbild_ist_fliesstext():
    bereiche = _bereiche(_manifest())

    assert [b["art"] for b in bereiche] == ["ueberschrift", "fliesstext", "fussnote"]


def test_unbekannte_rolle_bricht_laut():
    bild = Rollenbild("", {(0, 0): "erfunden"})

    with pytest.raises(Mp4Fehler, match="erfunden"):
        _manifest(DOK, bild)


def test_ohne_rollenbild_alles_fliesstext():
    arten = {b["art"] for b in _bereiche(_manifest(DOK, None))}

    assert arten == {"fliesstext"}


def test_text_unveraendert():
    seltsam = "  Zwei  Leerzeichen,\u00a0Umlaute äöü ß \u2013 \u201eZitat\u201c \t ende "
    dok = Dokument("T", None, "de", (Kapitel("K", (seltsam, "ᛟ Fremdschrift")),))

    texte = [b["text"] for b in _bereiche(_manifest(dok, None))]

    assert texte == [seltsam, "ᛟ Fremdschrift"]


def test_reihenfolge_laufend_ueber_abschnitte():
    m = _manifest()

    bereiche = _bereiche(m)
    assert [b["reihenfolge"] for b in bereiche] == [1, 2, 3]
    assert [b["nr"] for b in m["abschnitte"][0]["bereiche"]] == [1, 2]
    assert [b["nr"] for b in m["abschnitte"][1]["bereiche"]] == [1]
    assert [b["text"] for b in bereiche] == [
        "Das ist der erste Absatz.",
        "Und ein zweiter, etwas länger.",
        "Dritter Absatz.",
    ]


def test_herkunft_ist_dokumentweit_und_geprueft():
    assert {b["herkunft"] for b in _bereiche(_manifest(herkunft="ocr"))} == {"ocr"}
    with pytest.raises(Mp4Fehler, match="herkunft"):
        _manifest(herkunft="geraten")


def test_text_bilanz_ohne_rest():
    bilanz = _manifest()["text_bilanz"]

    # 5 + 5 + 2 Woerter
    assert bilanz == {"woerter_gesamt": 12, "woerter_zugeordnet": 12, "rest": []}


def test_text_bilanz_mit_rest():
    bilanz = _manifest(weggelassen_vor_rollen=7)["text_bilanz"]

    assert bilanz["woerter_zugeordnet"] == 12
    assert bilanz["woerter_gesamt"] == 19
    assert bilanz["rest"] == [{"grund": "vom Leser vor den Rollen entfernt", "woerter": 7}]


def test_kein_absoluter_pfad(tmp_path):
    quelle = tmp_path / "geheim" / "Befund Nr 1.pdf"

    m = _manifest(quelle=quelle)

    assert m["quelle"]["pfad"] == "Befund Nr 1.pdf"
    assert str(tmp_path) not in json.dumps(m)


def test_schreiben_atomar_utf8(tmp_path):
    ziel = tmp_path / "tief" / "manifest.json"

    pfad = schreibe_manifest(_manifest(), ziel)

    assert pfad == ziel
    roh = ziel.read_bytes()
    assert "Größe & Maß".encode() in roh, "UTF-8 im Klartext, kein \\u-Escape"
    assert json.loads(roh.decode("utf-8")) == _manifest()
    assert [p.name for p in ziel.parent.iterdir()] == ["manifest.json"], "keine .tmp-Reste"


def test_schreiben_laesst_alte_datei_bei_fehler_ganz(tmp_path):
    ziel = tmp_path / "manifest.json"
    schreibe_manifest(_manifest(), ziel)
    vorher = ziel.read_bytes()

    with pytest.raises(TypeError):
        schreibe_manifest({"kaputt": object()}, ziel)

    assert ziel.read_bytes() == vorher
    assert [p.name for p in tmp_path.iterdir()] == ["manifest.json"]


def test_leser_heisst_mkn_audio(tmp_path):
    """Das Manifest des Laufs nennt als Leser den Paketnamen `mkn-audio` (Cluster D1).

    Seit 0.3.0 gibt es zwei Befehle (`mkn-mp4-local`, `mkn-mp4-gemini`), aber EINEN Leser:
    die Lesestufe gehoert dem Paket, nicht einem Befehl. Der alte Befehlsname `mkn-mp4`
    entfaellt ohne Alias und darf auch im Manifest nicht mehr erscheinen.
    """
    from types import SimpleNamespace

    from mkn_audio import lauf

    verz = SimpleNamespace(quelle_hash="cd" * 32, wurzel=tmp_path)
    lauf._schreibe_manifest(
        verz, DOK, ROLLEN_BILD, quelle=tmp_path / "Artikel.pdf", bildquelle=False
    )

    bereiche = _bereiche(json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8")))
    assert bereiche  # Untergrenze (LP-36): es gibt Bereiche, die einen Leser nennen
    assert {b["leser"] for b in bereiche} == {"mkn-audio"}
