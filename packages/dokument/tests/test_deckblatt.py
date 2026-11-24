"""Deckblatt setzen, abnehmen, lesen: eine Seite vorn dazu und wieder weg, ohne das Original zu beschaedigen.

Risiken: Daten verloren (ein Ziel wird ueberschrieben, eine echte Seite verschwindet, Lesezeichen, Verweise, Anhaenge
oder Formularfelder gehen beim Einfuegen verloren, eine Signatur wird entwertet) und falsche Information (ein fremdes
Blatt wird als Deckblatt abgenommen, ein Infofeld wird mit einem veralteten Wert zurueckgesetzt). Alle PDFs entstehen
im Test; keine Datei wird eingecheckt.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest

from mkn_dokument import deckblatt, kommandozeile
from mkn_dokument.deckblatt import Angaben, DeckblattFehler

ANGABEN = Angaben(
    titel="Probebericht Messung",
    datum="2026-11",
    quelle="Scan Probeablage",
    tags=("probe", "messung"),
    links=(("Vorgang", "https://example.org/vorgang"),),
    status=(("Original", "Papier im Ordner"),),
    weitere=(("Seitenformat", "A4"),),
)


def _quelle(pfad: Path, seiten: int = 3) -> Path:
    """Ein PDF mit allem, was bleiben muss: Lesezeichen, interner und externer Verweis, Anhang, Formularfeld."""
    d = pymupdf.open()
    for nr in range(seiten):
        d.new_page(width=595, height=842).insert_text((72, 100), f"Probeseite {nr + 1} Inhalt Nummer {nr + 1}")
    d[0].insert_link(
        {"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(72, 200, 200, 220), "page": seiten - 1, "to": pymupdf.Point()}
    )
    d[min(1, seiten - 1)].insert_link(
        {"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(72, 240, 200, 260), "uri": "https://example.org/a"}
    )
    d.set_toc([[1, "Anfang", 1], [2, "Ende", seiten]])
    d.embfile_add("anhang.txt", b"Anhang der Quelle")
    feld = pymupdf.Widget()
    feld.field_name, feld.field_type, feld.field_value = "name", pymupdf.PDF_WIDGET_TYPE_TEXT, "Eingetragen"
    feld.rect = pymupdf.Rect(72, 300, 300, 320)
    d[seiten - 1].add_widget(feld)
    d.set_metadata({"title": "Alter Titel", "author": "Probeautor", "keywords": "alt"})
    d.save(pfad)
    d.close()
    return pfad


def _abdruck(pdf: Path, erste: int = 0) -> dict:
    """Unabhaengig vom Modul: was ein Leser von Seite ``erste`` an sieht, Seitenzahlen auf ``erste`` bezogen."""
    with pymupdf.open(pdf) as d:
        return {
            "texte": [" ".join(w[4] for w in d[n].get_text("words")) for n in range(erste, d.page_count)],
            "toc": [[ebene, titel, seite - erste] for ebene, titel, seite in d.get_toc()],
            "verweise": [
                [
                    (v["kind"], v.get("uri"), v.get("page", -1) - erste if "page" in v else None)
                    for v in d[n].get_links()
                ]
                for n in range(erste, d.page_count)
            ],
            "anhaenge": {n: d.embfile_get(n) for n in d.embfile_names() if n != deckblatt.KENNUNG},
            "felder": [[(f.field_name, f.field_value) for f in d[n].widgets()] for n in range(erste, d.page_count)],
        }


def _inhalt(ordner: Path) -> list[str]:
    return sorted(p.name for p in ordner.iterdir())


def _setzen(tmp_path: Path, **mehr) -> tuple[Path, Path]:
    quelle = _quelle(tmp_path / "quelle.pdf")
    return quelle, deckblatt.setzen(quelle, tmp_path / "mit.pdf", ANGABEN, **mehr)


# --- hin und zurueck -----------------------------------------------------------------------------------------------


def test_setzen_stellt_eine_seite_vor_die_unveraenderte_quelle(tmp_path):
    quelle, mit = _setzen(tmp_path)
    assert _abdruck(mit, erste=1) == _abdruck(quelle)
    with pymupdf.open(mit) as d:
        assert d.page_count == 4
        kopf = " ".join(w[4] for w in d[0].get_text("words"))
        assert d.metadata["title"] == "Probebericht Messung" and d.metadata["keywords"] == "probe, messung"
        assert d.metadata["author"] == "Probeautor"
        assert deckblatt.KENNUNG in d.embfile_names()
    for teil in ("Probebericht Messung", "2026-11", "Scan Probeablage", "quelle.pdf", "probe", "Papier im Ordner"):
        assert teil in kopf
    assert _inhalt(tmp_path) == ["mit.pdf", "quelle.pdf"]


def test_hin_und_zurueck_gleicht_der_quelle(tmp_path):
    quelle, mit = _setzen(tmp_path)
    ohne = deckblatt.abnehmen(mit, tmp_path / "ohne.pdf")
    assert _abdruck(ohne) == _abdruck(quelle)
    with pymupdf.open(ohne) as d:
        assert deckblatt.KENNUNG not in d.embfile_names()
        assert (d.metadata["title"], d.metadata["author"], d.metadata["keywords"]) == (
            "Alter Titel",
            "Probeautor",
            "alt",
        )
    assert _inhalt(tmp_path) == ["mit.pdf", "ohne.pdf", "quelle.pdf"]


def test_lesen_gibt_die_kennung_mit_quelle_und_pruefsumme(tmp_path):
    quelle, mit = _setzen(tmp_path)
    kennung = deckblatt.lesen(mit)
    assert kennung["schema"] == 1
    assert kennung["angaben"]["titel"] == "Probebericht Messung"
    assert kennung["angaben"]["links"] == [["Vorgang", "https://example.org/vorgang"]]
    assert kennung["quelle"]["datei"] == "quelle.pdf" and kennung["quelle"]["seiten"] == 3
    assert kennung["quelle"]["sha256"] == hashlib.sha256(quelle.read_bytes()).hexdigest()
    with pymupdf.open(mit) as d:
        text = " ".join(w[4] for w in d[0].get_text("words"))
    assert kennung["deckblatt"]["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()


def test_angaben_werden_maskiert_und_adressen_verweisen(tmp_path):
    quelle = _quelle(tmp_path / "quelle.pdf")
    angaben = Angaben(titel="<b>Fett</b> & Co", datum="2026", links=(("Seite", "https://example.org/x"),))
    mit = deckblatt.setzen(quelle, tmp_path / "mit.pdf", angaben)
    with pymupdf.open(mit) as d:
        assert "<b>Fett</b> & Co" in " ".join(w[4] for w in d[0].get_text("words"))
        assert any(v.get("uri") == "https://example.org/x" for v in d[0].get_links())


def test_kopfseite_von_aussen_wird_gesetzt(tmp_path):
    def eigene(angaben: Angaben, ziel: Path) -> None:
        d = pymupdf.open()
        d.new_page().insert_text((72, 100), f"Eigene Gestaltung {angaben.titel}")
        d.save(ziel)
        d.close()

    _, mit = _setzen(tmp_path, kopfseite=eigene)
    with pymupdf.open(mit) as d:
        assert d[0].get_text().startswith("Eigene Gestaltung Probebericht Messung")
    assert deckblatt.lesen(mit)["angaben"]["titel"] == "Probebericht Messung"


def test_eigenes_css_wird_angewandt(tmp_path):
    _, mit = _setzen(tmp_path, stil=deckblatt.Stil(css="h1 { font-size: 40px; }"))
    assert deckblatt.lesen(mit)["schema"] == 1


# --- Schutzregeln beim Setzen --------------------------------------------------------------------------------------


@pytest.mark.parametrize("befehl", ["setzen", "abnehmen"])
def test_vorhandenes_ziel_wird_nie_ueberschrieben(tmp_path, befehl):
    quelle, mit = _setzen(tmp_path)
    ziel = tmp_path / "ziel.pdf"
    ziel.write_bytes(b"schon da")
    with pytest.raises(DeckblattFehler, match="existiert"):
        if befehl == "setzen":
            deckblatt.setzen(quelle, ziel, ANGABEN)
        else:
            deckblatt.abnehmen(mit, ziel)
    assert ziel.read_bytes() == b"schon da"
    assert _inhalt(tmp_path) == ["mit.pdf", "quelle.pdf", "ziel.pdf"]


def test_ziel_als_verweis_wird_nie_beschrieben(tmp_path):
    quelle = _quelle(tmp_path / "quelle.pdf")
    anderes = tmp_path / "anderes.pdf"
    anderes.write_bytes(b"fremd")
    (tmp_path / "ziel.pdf").symlink_to(anderes)
    with pytest.raises(DeckblattFehler, match="existiert"):
        deckblatt.setzen(quelle, tmp_path / "ziel.pdf", ANGABEN)
    assert anderes.read_bytes() == b"fremd"


def test_ziel_das_waehrend_des_laufs_entsteht_wird_nicht_ueberschrieben(tmp_path, monkeypatch):
    """Zwischen Vorpruefung und Veroeffentlichen legt ein anderer das Ziel an: es bleibt, wie er es schrieb."""
    quelle = _quelle(tmp_path / "quelle.pdf")
    ziel = tmp_path / "mit.pdf"
    echt = os.link

    def zuvorgekommen(quelle_pfad, ziel_pfad):
        Path(ziel_pfad).write_bytes(b"von anderswo")
        echt(quelle_pfad, ziel_pfad)

    monkeypatch.setattr(deckblatt.os, "link", zuvorgekommen)
    with pytest.raises(DeckblattFehler, match="existiert"):
        deckblatt.setzen(quelle, ziel, ANGABEN)
    assert ziel.read_bytes() == b"von anderswo"
    assert _inhalt(tmp_path) == ["mit.pdf", "quelle.pdf"]


def test_ohne_harte_verweise_wird_exklusiv_kopiert(tmp_path, monkeypatch):
    def kein_link(quelle_pfad, ziel_pfad):
        raise PermissionError("keine harten Verweise")

    monkeypatch.setattr(deckblatt.os, "link", kein_link)
    quelle, mit = _setzen(tmp_path)
    assert _abdruck(mit, erste=1) == _abdruck(quelle)
    assert _inhalt(tmp_path) == ["mit.pdf", "quelle.pdf"]


def test_ohne_harte_verweise_bleibt_ein_entstandenes_ziel_unberuehrt(tmp_path, monkeypatch):
    quelle = _quelle(tmp_path / "quelle.pdf")
    ziel = tmp_path / "mit.pdf"

    def kein_link(quelle_pfad, ziel_pfad):
        Path(ziel_pfad).write_bytes(b"von anderswo")
        raise PermissionError("keine harten Verweise")

    monkeypatch.setattr(deckblatt.os, "link", kein_link)
    with pytest.raises(DeckblattFehler, match="existiert"):
        deckblatt.setzen(quelle, ziel, ANGABEN)
    assert ziel.read_bytes() == b"von anderswo"


def test_zielordner_fehlt(tmp_path):
    quelle = _quelle(tmp_path / "quelle.pdf")
    with pytest.raises(DeckblattFehler, match="Zielordner"):
        deckblatt.setzen(quelle, tmp_path / "fehlt" / "mit.pdf", ANGABEN)
    assert not (tmp_path / "fehlt").exists()


def _schreibe(pfad: Path, daten: bytes) -> Path:
    pfad.write_bytes(daten)
    return pfad


def _leeres_pdf(pfad: Path) -> Path:
    pfad.write_bytes(
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )
    return pfad


def _verschluesselt(pfad: Path, **schutz) -> Path:
    d = pymupdf.open()
    d.new_page().insert_text((72, 100), "Geheim")
    d.save(pfad, encryption=pymupdf.PDF_ENCRYPT_AES_256, **schutz)
    d.close()
    return pfad


@pytest.mark.parametrize(
    ("baue", "satz"),
    [
        (lambda p: p, "fehlt"),
        (lambda p: _schreibe(p, b"kein pdf"), "kein lesbares PDF"),
        (lambda p: _schreibe(p, b""), "kein lesbares PDF"),
        (_leeres_pdf, "ohne Seite"),
        (lambda p: _verschluesselt(p, user_pw="u", owner_pw="o"), "verschluesselt"),
        (lambda p: _verschluesselt(p, owner_pw="o", permissions=0), "verschluesselt"),
    ],
    ids=["fehlt", "kein-pdf", "leer", "ohne-seite", "passwort", "nur-rechte"],
)
@pytest.mark.parametrize("befehl", ["setzen", "abnehmen", "lesen"])
def test_unbrauchbare_quelle_bricht_ab(tmp_path, baue, satz, befehl):
    quelle = baue(tmp_path / "quelle.pdf")
    with pytest.raises(DeckblattFehler, match=satz):
        if befehl == "setzen":
            deckblatt.setzen(quelle, tmp_path / "ziel.pdf", ANGABEN)
        elif befehl == "abnehmen":
            deckblatt.abnehmen(quelle, tmp_path / "ziel.pdf")
        else:
            deckblatt.lesen(quelle)
    assert not (tmp_path / "ziel.pdf").exists()


def _mit_signaturfeld(pfad: Path) -> None:
    d = pymupdf.open(pfad)
    feld = pymupdf.Widget()
    feld.field_name, feld.field_type = "unterschrift", pymupdf.PDF_WIDGET_TYPE_SIGNATURE
    feld.rect = pymupdf.Rect(72, 500, 300, 540)
    d[0].add_widget(feld)
    d.xref_set_key(d.pdf_catalog(), "AcroForm/SigFlags", "0")  # nur das Feld zeigt die Signatur an
    d.saveIncr()
    d.close()


def _mit_sigflags(pfad: Path) -> None:
    d = pymupdf.open(pfad)
    d.xref_set_key(d.pdf_catalog(), "AcroForm/SigFlags", "3")
    d.saveIncr()
    d.close()


def _mit_bytebereich(pfad: Path) -> None:
    d = pymupdf.open(pfad)
    nr = d.get_new_xref()
    d.update_object(nr, "<</Type/Sig/Filter/Adobe.PPKLite/ByteRange[0 10 20 30]>>")
    d.saveIncr()
    d.close()


@pytest.mark.parametrize(
    "zeichen", [_mit_signaturfeld, _mit_sigflags, _mit_bytebereich], ids=["feld", "flags", "bytes"]
)
def test_signiertes_pdf_wird_abgewiesen(tmp_path, zeichen):
    quelle = _quelle(tmp_path / "quelle.pdf")
    zeichen(quelle)
    with pytest.raises(DeckblattFehler, match="Signatur"):
        deckblatt.setzen(quelle, tmp_path / "mit.pdf", ANGABEN)
    assert _inhalt(tmp_path) == ["quelle.pdf"]


def test_nach_dem_setzen_signiert_wird_nicht_abgenommen(tmp_path):
    _, mit = _setzen(tmp_path)
    _mit_bytebereich(mit)
    with pytest.raises(DeckblattFehler, match="Signatur"):
        deckblatt.abnehmen(mit, tmp_path / "ohne.pdf")
    assert not (tmp_path / "ohne.pdf").exists()


def test_zweites_deckblatt_wird_verweigert(tmp_path):
    _, mit = _setzen(tmp_path)
    with pytest.raises(DeckblattFehler, match="schon ein Deckblatt"):
        deckblatt.setzen(mit, tmp_path / "doppelt.pdf", ANGABEN)
    assert not (tmp_path / "doppelt.pdf").exists()


def test_fremde_kennungsdatei_wird_nicht_ueberschrieben(tmp_path):
    quelle = _quelle(tmp_path / "quelle.pdf")
    with pymupdf.open(quelle) as d:
        d.embfile_add(deckblatt.KENNUNG, b"etwas anderes")
        d.saveIncr()
    with pytest.raises(DeckblattFehler, match="schon eingebettet"):
        deckblatt.setzen(quelle, tmp_path / "mit.pdf", ANGABEN)
    assert not (tmp_path / "mit.pdf").exists()


@pytest.mark.parametrize("datum", ["2026-13", "2026-02-30", "26-01-01", "heute", "2026-1", ""])
def test_ungueltiges_datum_bricht_ab(tmp_path, datum):
    quelle = _quelle(tmp_path / "quelle.pdf")
    with pytest.raises(DeckblattFehler, match="Datum"):
        deckblatt.setzen(quelle, tmp_path / "mit.pdf", Angaben(titel="T", datum=datum))
    assert not (tmp_path / "mit.pdf").exists()


@pytest.mark.parametrize("datum", ["2026", "2026-02", "2024-02-29"])
def test_gueltiges_datum_wird_angenommen(tmp_path, datum):
    quelle = _quelle(tmp_path / "quelle.pdf")
    deckblatt.setzen(quelle, tmp_path / "mit.pdf", Angaben(titel="T", datum=datum))
    assert deckblatt.lesen(tmp_path / "mit.pdf")["angaben"]["datum"] == datum


def test_leerer_titel_bricht_ab(tmp_path):
    quelle = _quelle(tmp_path / "quelle.pdf")
    with pytest.raises(DeckblattFehler, match="Titel"):
        deckblatt.setzen(quelle, tmp_path / "mit.pdf", Angaben(titel="  ", datum="2026"))


def test_kopfseite_ueber_ein_blatt_hinaus_bricht_ab(tmp_path):
    quelle = _quelle(tmp_path / "quelle.pdf")
    angaben = Angaben(titel="Lang", datum="2026", tags=tuple(f"schlagwort-{n}" for n in range(400)))
    with pytest.raises(DeckblattFehler, match="mehr als ein Blatt"):
        deckblatt.setzen(quelle, tmp_path / "mit.pdf", angaben)
    assert _inhalt(tmp_path) == ["quelle.pdf"]


def _zwei_blaetter(angaben: Angaben, ziel: Path) -> None:
    d = pymupdf.open()
    for n in range(2):
        d.new_page().insert_text((72, 100), f"Blatt {n}")
    d.save(ziel)
    d.close()


def _ohne_text(angaben: Angaben, ziel: Path) -> None:
    d = pymupdf.open()
    d.new_page()
    d.save(ziel)
    d.close()


def _nichts(angaben: Angaben, ziel: Path) -> None:
    return None


def _kein_pdf(angaben: Angaben, ziel: Path) -> None:
    ziel.write_text("kein pdf")


@pytest.mark.parametrize(
    "kopfseite", [_zwei_blaetter, _ohne_text, _nichts, _kein_pdf], ids=["zwei", "ohne-text", "nichts", "kein-pdf"]
)
def test_kopfseite_von_aussen_muss_genau_eine_seite_liefern(tmp_path, kopfseite):
    quelle = _quelle(tmp_path / "quelle.pdf")
    with pytest.raises(DeckblattFehler, match="Kopfseite"):
        deckblatt.setzen(quelle, tmp_path / "mit.pdf", ANGABEN, kopfseite=kopfseite)
    assert _inhalt(tmp_path) == ["quelle.pdf"]


def test_fehler_der_kopfseite_von_aussen_hinterlaesst_nichts(tmp_path):
    def kaputt(angaben: Angaben, ziel: Path) -> None:
        ziel.write_bytes(b"halb")
        raise RuntimeError("Satz gescheitert")

    quelle = _quelle(tmp_path / "quelle.pdf")
    with pytest.raises(RuntimeError, match="Satz gescheitert"):
        deckblatt.setzen(quelle, tmp_path / "mit.pdf", ANGABEN, kopfseite=kaputt)
    assert _inhalt(tmp_path) == ["quelle.pdf"]


def test_schriftenordner_muss_da_sein(tmp_path):
    quelle = _quelle(tmp_path / "quelle.pdf")
    with pytest.raises(DeckblattFehler, match="Schriften"):
        deckblatt.setzen(quelle, tmp_path / "mit.pdf", ANGABEN, stil=deckblatt.Stil(schriften=tmp_path / "fehlt"))
    assert _inhalt(tmp_path) == ["quelle.pdf"]


# --- Selbstpruefung: jeder Punkt faellt, wenn das Geschriebene abweicht ----------------------------------------------


def _verfaelsche(veraendern):
    """Ersetzt das Speichern: speichert wie das Modul und veraendert die gespeicherte Datei danach."""
    echt = deckblatt._speichern

    def speichern(d: pymupdf.Document, pfad: Path, *, garbage: int) -> None:
        echt(d, pfad, garbage=garbage)
        with pymupdf.open(pfad) as z:
            veraendern(z)
            z.saveIncr()

    return speichern


def _seite_mehr(d):
    d.new_page().insert_text((72, 100), "Angehaengt")


def _text_anders(d):
    d[d.page_count - 1].insert_text((72, 700), "Hinzugefuegt")


def _toc_anders(d):
    d.set_toc([[1, "Anfang", d.page_count]])


def _verweis_weg(d):
    for seite in d:
        for verweis in seite.get_links():
            if verweis.get("uri") == "https://example.org/a":
                seite.delete_link(verweis)
                return


def _anhang_weg(d):
    d.embfile_del("anhang.txt")


def _feld_anders(d):
    for seite in d:
        for feld in seite.widgets():
            feld.field_value = "Anders"
            feld.update()


def _kopf_anders(d):
    d[0].insert_text((72, 800), "Nachtrag")


def _kennung_weg(d):
    d.embfile_del(deckblatt.KENNUNG)


SETZEN_FEHLER = [_seite_mehr, _text_anders, _toc_anders, _verweis_weg, _anhang_weg, _feld_anders, _kopf_anders,
                 _kennung_weg]  # fmt: skip


@pytest.mark.parametrize("veraendern", SETZEN_FEHLER, ids=lambda f: f.__name__)
def test_selbstpruefung_beim_setzen(tmp_path, monkeypatch, veraendern):
    quelle = _quelle(tmp_path / "quelle.pdf")
    monkeypatch.setattr(deckblatt, "_speichern", _verfaelsche(veraendern))
    with pytest.raises(DeckblattFehler, match="Selbstpruefung"):
        deckblatt.setzen(quelle, tmp_path / "mit.pdf", ANGABEN)
    assert _inhalt(tmp_path) == ["quelle.pdf"]


def _kennung_wieder(d):
    d.embfile_add(deckblatt.KENNUNG, b"{}")


ABNEHMEN_FEHLER = [_seite_mehr, _text_anders, _toc_anders, _verweis_weg, _anhang_weg, _feld_anders, _kennung_wieder]


@pytest.mark.parametrize("veraendern", ABNEHMEN_FEHLER, ids=lambda f: f.__name__)
def test_selbstpruefung_beim_abnehmen(tmp_path, monkeypatch, veraendern):
    _, mit = _setzen(tmp_path)
    monkeypatch.setattr(deckblatt, "_speichern", _verfaelsche(veraendern))
    with pytest.raises(DeckblattFehler, match="Selbstpruefung"):
        deckblatt.abnehmen(mit, tmp_path / "ohne.pdf")
    assert _inhalt(tmp_path) == ["mit.pdf", "quelle.pdf"]


# --- abnehmen nur mit passender Kennung ----------------------------------------------------------------------------


def test_abnehmen_ohne_kennung_bricht_ab(tmp_path):
    quelle = _quelle(tmp_path / "quelle.pdf")
    with pytest.raises(DeckblattFehler, match="kein Deckblatt dieses Werkzeugs"):
        deckblatt.abnehmen(quelle, tmp_path / "ohne.pdf")
    assert _inhalt(tmp_path) == ["quelle.pdf"]


def test_abnehmen_bei_veraenderter_erster_seite_bricht_ab(tmp_path):
    _, mit = _setzen(tmp_path)
    with pymupdf.open(mit) as d:
        d[0].insert_text((72, 800), "Nachtrag")
        d.saveIncr()
    with pytest.raises(DeckblattFehler, match="Pruefsumme"):
        deckblatt.abnehmen(mit, tmp_path / "ohne.pdf")
    with pytest.raises(DeckblattFehler, match="Pruefsumme"):
        deckblatt.lesen(mit)
    assert not (tmp_path / "ohne.pdf").exists()


def test_abnehmen_wenn_fremde_seite_vorn_steht_bricht_ab(tmp_path):
    """Die Kennung ist da, aber vor das Deckblatt wurde ein anderes Blatt gesetzt: dieses bleibt."""
    _, mit = _setzen(tmp_path)
    with pymupdf.open(mit) as d:
        d.new_page(0).insert_text((72, 100), "Neues Anschreiben")
        d.saveIncr()
    with pytest.raises(DeckblattFehler, match="Pruefsumme"):
        deckblatt.abnehmen(mit, tmp_path / "ohne.pdf")


def _kennung_ersetzen(pdf: Path, aendern) -> None:
    """Schreibt den Inhalt der Kennung neu - ueber ihren Datenstrom, weil ``embfile_upd`` in PyMuPDF 1.27 fuer jeden
    Eintrag nach dem ersten den falschen trifft."""
    with pymupdf.open(pdf) as d:
        _, liste = d.xref_get_key(d.pdf_catalog(), "Names/EmbeddedFiles/Names")
        strom = int(re.search(rf"\({re.escape(deckblatt.KENNUNG)}\)<<.*?/EF<</F (\d+) 0 R>>", liste).group(1))
        d.update_stream(strom, aendern(d.embfile_get(deckblatt.KENNUNG)))
        d.saveIncr()


def _schema_2(daten: bytes) -> bytes:
    return json.dumps(json.loads(daten) | {"schema": 2}).encode()


def _ohne_pruefsumme(daten: bytes) -> bytes:
    kennung = json.loads(daten)
    del kennung["deckblatt"]
    return json.dumps(kennung).encode()


@pytest.mark.parametrize(
    "aendern",
    [
        lambda daten: b"kein json",
        lambda daten: b"[1, 2]",
        _schema_2,
        _ohne_pruefsumme,
        lambda daten: daten + b" " * 2**20,  # gueltiges JSON, nur zu gross
    ],
    ids=["kein-json", "keine-zuordnung", "schema-2", "unvollstaendig", "zu-gross"],
)
@pytest.mark.parametrize("befehl", ["abnehmen", "lesen", "setzen"])
def test_unbrauchbare_kennung_bricht_ab(tmp_path, aendern, befehl):
    _, mit = _setzen(tmp_path)
    _kennung_ersetzen(mit, aendern)
    with pytest.raises(DeckblattFehler, match=r"Kennung|schon eingebettet"):
        if befehl == "abnehmen":
            deckblatt.abnehmen(mit, tmp_path / "ohne.pdf")
        elif befehl == "lesen":
            deckblatt.lesen(mit)
        else:
            deckblatt.setzen(mit, tmp_path / "ohne.pdf", ANGABEN)
    assert not (tmp_path / "ohne.pdf").exists()


def test_abnehmen_ohne_seite_dahinter_bricht_ab(tmp_path):
    quelle = _quelle(tmp_path / "quelle.pdf", seiten=1)
    mit = deckblatt.setzen(quelle, tmp_path / "mit.pdf", ANGABEN)
    with pymupdf.open(mit) as d:
        d.delete_page(1)
        d.saveIncr()
    with pytest.raises(DeckblattFehler, match="keine Seite dahinter"):
        deckblatt.abnehmen(mit, tmp_path / "ohne.pdf")
    assert not (tmp_path / "ohne.pdf").exists()


# --- bearbeitete Dokumente -----------------------------------------------------------------------------------------


def test_infofeld_wird_nur_zurueckgesetzt_wenn_unveraendert(tmp_path):
    _, mit = _setzen(tmp_path)
    with pymupdf.open(mit) as d:
        d.set_metadata(d.metadata | {"title": "Spaeter umbenannt"})
        d.saveIncr()
    ohne = deckblatt.abnehmen(mit, tmp_path / "ohne.pdf")
    with pymupdf.open(ohne) as d:
        assert d.metadata["title"] == "Spaeter umbenannt"
        assert d.metadata["keywords"] == "alt"


def test_spaeter_angefuegte_seite_bleibt_mit_hinweis(tmp_path, capsys):
    quelle, mit = _setzen(tmp_path)
    with pymupdf.open(mit) as d:
        d.new_page().insert_text((72, 100), "Nachgereicht")
        d.saveIncr()
    assert deckblatt.lesen(mit)["quelle"]["seiten"] == 3
    assert "Hinweis" in capsys.readouterr().err
    ohne = deckblatt.abnehmen(mit, tmp_path / "ohne.pdf")
    assert "Hinweis" in capsys.readouterr().err
    texte = _abdruck(ohne)["texte"]
    assert texte[:3] == _abdruck(quelle)["texte"] and texte[3] == "Nachgereicht"


def test_lesen_ohne_kennung(tmp_path):
    quelle = _quelle(tmp_path / "quelle.pdf")
    with pytest.raises(DeckblattFehler, match="traegt kein Deckblatt dieses Werkzeugs"):
        deckblatt.lesen(quelle)


# --- Kommandozeile -------------------------------------------------------------------------------------------------


def _setzen_argv(quelle: Path, aus: Path, *mehr: str) -> list[str]:
    return ["deckblatt", "setzen", str(quelle), "--aus", str(aus), "--titel", "Probe", "--datum", "2026-11-24", *mehr]


def test_kommandozeile_hin_und_zurueck(tmp_path, capsys):
    quelle = _quelle(tmp_path / "quelle.pdf")
    mit, ohne = tmp_path / "mit.pdf", tmp_path / "ohne.pdf"
    argv = _setzen_argv(
        quelle, mit, "--quelle", "Scan", "--tag", "a", "--tag", "b", "--link", "Vorgang=https://example.org/v",
        "--status", "Stand=offen", "--angabe", "Format=A4", "--marke", "Probeablage",
    )  # fmt: skip
    assert kommandozeile.haupt(argv) == 0
    assert str(mit) in capsys.readouterr().out
    assert kommandozeile.haupt(["deckblatt", "lesen", str(mit)]) == 0
    kennung = json.loads(capsys.readouterr().out)
    assert kennung["angaben"]["tags"] == ["a", "b"] and kennung["angaben"]["weitere"] == [["Format", "A4"]]
    assert kennung["angaben"]["marke"] == "Probeablage" and kennung["angaben"]["status"] == [["Stand", "offen"]]
    assert kommandozeile.haupt(["deckblatt", "abnehmen", str(mit), "--aus", str(ohne)]) == 0
    assert _abdruck(ohne) == _abdruck(quelle)


@pytest.mark.parametrize("paar", ["--link=ohne-gleich", "--status==wert", "--angabe=Beschriftung="])
def test_kommandozeile_weist_halbe_paare_ab(tmp_path, capsys, paar):
    quelle = _quelle(tmp_path / "quelle.pdf")
    assert kommandozeile.haupt(_setzen_argv(quelle, tmp_path / "mit.pdf", paar)) == 1
    assert capsys.readouterr().err.startswith("mkn-dokument: ")
    assert not (tmp_path / "mit.pdf").exists()


def test_kommandozeile_abbruch_exit_1_mit_satz(tmp_path, capsys):
    quelle = _quelle(tmp_path / "quelle.pdf")
    assert kommandozeile.haupt(["deckblatt", "abnehmen", str(quelle), "--aus", str(tmp_path / "o.pdf")]) == 1
    fehler = capsys.readouterr().err
    assert fehler.startswith("mkn-dokument: ") and "kein Deckblatt dieses Werkzeugs" in fehler
    assert kommandozeile.haupt(["deckblatt", "lesen", str(quelle)]) == 1
    assert "kein Deckblatt dieses Werkzeugs" in capsys.readouterr().err


@pytest.mark.parametrize("schalter", [["--css", "fehlt.css"], ["--schriften", "fehlt"]])
def test_kommandozeile_fehlende_gestaltung_exit_1(tmp_path, capsys, schalter):
    quelle = _quelle(tmp_path / "quelle.pdf")
    schalter = [schalter[0], str(tmp_path / schalter[1])]
    assert kommandozeile.haupt(_setzen_argv(quelle, tmp_path / "mit.pdf", *schalter)) == 1
    assert capsys.readouterr().err.startswith("mkn-dokument: ")
    assert _inhalt(tmp_path) == ["quelle.pdf"]


def test_kommandozeile_braucht_kein_modellpaket(tmp_path):
    """Der Befehl laeuft auch dort, wo das Modellpaket fehlt: kein Leser, keine Anfrage, kein Schluessel."""
    quelle = _quelle(tmp_path / "quelle.pdf")
    programm = (
        "import sys; sys.modules['mkn_kern'] = None\n"
        "from mkn_dokument import kommandozeile\n"
        "raise SystemExit(kommandozeile.haupt(sys.argv[1:]))"
    )
    lauf = subprocess.run(
        [sys.executable, "-c", programm, *_setzen_argv(quelle, tmp_path / "mit.pdf")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert lauf.returncode == 0, lauf.stderr
    assert (tmp_path / "mit.pdf").is_file()


def _verzweigtes_anhangverzeichnis(pfad: Path) -> Path:
    """Anhang-Verzeichnis als Baum ueber /Kids (wie es manche Erzeuger bei vielen Anhaengen schreiben)."""
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), "Inhalt Seite eins")
    d.embfile_add("rechnung.xml", b"<xml>original</xml>")
    katalog = d.pdf_catalog()
    _, namen = d.xref_get_key(katalog, "Names/EmbeddedFiles/Names")
    blatt = d.get_new_xref()
    d.update_object(blatt, f"<</Names {namen} /Limits [(rechnung.xml)(rechnung.xml)]>>")
    wurzel = d.get_new_xref()
    d.update_object(wurzel, f"<</Kids [{blatt} 0 R]>>")
    d.xref_set_key(katalog, "Names", f"<</EmbeddedFiles {wurzel} 0 R>>")
    d.save(pfad, garbage=0)
    d.close()
    return pfad


def test_verzweigtes_anhangverzeichnis_wird_abgewiesen(tmp_path):
    """PyMuPDF sieht in einem verzweigten Verzeichnis keine Anhaenge; die Kennung daneben verdeckte das Original."""
    quelle = _verzweigtes_anhangverzeichnis(tmp_path / "quelle.pdf")
    vorher = quelle.read_bytes()
    with pytest.raises(DeckblattFehler, match="verzweigtes Anhang-Verzeichnis"):
        deckblatt.setzen(quelle, tmp_path / "mit.pdf", ANGABEN)
    assert _inhalt(tmp_path) == ["quelle.pdf"]
    assert quelle.read_bytes() == vorher


def _indirekte_flache_liste(pfad: Path, *, verzeichnis_indirekt: bool) -> Path:
    """Gueltige flache Anhangliste, deren ``/Names`` (und wahlweise ``EmbeddedFiles``) als eigenes Objekt steht."""
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), "Inhalt Seite eins")
    d.embfile_add("anhang.txt", b"Anhang der Quelle")
    katalog = d.pdf_catalog()
    _, namen = d.xref_get_key(katalog, "Names/EmbeddedFiles/Names")
    liste = d.get_new_xref()
    d.update_object(liste, namen)
    if verzeichnis_indirekt:
        verzeichnis = d.get_new_xref()
        d.update_object(verzeichnis, f"<</Names {liste} 0 R>>")
        d.xref_set_key(katalog, "Names", f"<</EmbeddedFiles {verzeichnis} 0 R>>")
    else:
        d.xref_set_key(katalog, "Names/EmbeddedFiles/Names", f"{liste} 0 R")
    d.save(pfad, garbage=0)
    d.close()
    return pfad


@pytest.mark.parametrize("verzeichnis_indirekt", [False, True], ids=["liste-indirekt", "beides-indirekt"])
def test_indirekt_gespeicherte_flache_anhangliste_wird_angenommen(tmp_path, verzeichnis_indirekt):
    quelle = _indirekte_flache_liste(tmp_path / "quelle.pdf", verzeichnis_indirekt=verzeichnis_indirekt)
    with pymupdf.open(quelle) as d:
        art, _ = d.xref_get_key(d.pdf_catalog(), "Names/EmbeddedFiles/Names")
    assert art == "xref"
    mit = deckblatt.setzen(quelle, tmp_path / "mit.pdf", ANGABEN)
    ohne = deckblatt.abnehmen(mit, tmp_path / "ohne.pdf")
    with pymupdf.open(mit) as d:
        assert d.embfile_get("anhang.txt") == b"Anhang der Quelle"
        assert sorted(d.embfile_names()) == sorted(["anhang.txt", deckblatt.KENNUNG])
    with pymupdf.open(ohne) as d:
        assert d.embfile_names() == ["anhang.txt"]
        assert d.embfile_get("anhang.txt") == b"Anhang der Quelle"
    assert _abdruck(ohne) == _abdruck(quelle)
