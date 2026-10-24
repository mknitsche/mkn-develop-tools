"""Fotos und Screenshots: Bildmodell, Texterkennung, und die Hilfsprogramme."""

from __future__ import annotations

import subprocess

import pytest

from mkn_audio.lesen import bild, lies
from mkn_audio.typen import Mp4Fehler
from muster_quellen import muster_png

PNG = b"\x89PNG\r\n\x1a\n"


def test_bild_geht_ans_bildmodell(tmp_path):
    aufrufe = []

    def modell(prompt, bilder):
        aufrufe.append((prompt, bilder))
        return "Die Ueberschrift\n\nErster Absatz des Artikels,\nüber zwei Zeilen.\n\nZweiter."

    dok = lies(muster_png(tmp_path / "Artikel.png"), textmodell=modell)

    ((prompt, bilder),) = aufrufe
    assert bilder[0][0] == "image/png" and bilder[0][1].startswith(PNG)
    for pflicht in ("Lesereihenfolge", "Spalten", "Überschriften", "Erfinde"):
        assert pflicht in prompt
    assert dok.kapitel[0].absaetze == (
        "Die Ueberschrift",
        "Erster Absatz des Artikels, über zwei Zeilen.",
        "Zweiter.",
    )
    assert dok.titel == "Artikel"
    assert dok.sprache == "de"


def test_bild_ohne_modell_geht_an_tesseract_und_sagt_es(tmp_path, monkeypatch):
    monkeypatch.setattr(bild, "ocr", lambda png, sprache: f"Erkannt ({sprache}).")

    dok = lies(muster_png(tmp_path / "x.png"), textmodell=None)

    assert dok.kapitel[0].absaetze == ("Erkannt (deu).",)
    assert any("kein Bildmodell" in w and "Texterkennung" in w for w in dok.warnungen)


def test_bild_jpeg_wird_am_kopf_erkannt_nicht_an_der_endung(tmp_path):
    png = muster_png(tmp_path / "echt.png")
    falsch = tmp_path / "falsch.jpg"  # PNG-Inhalt mit JPG-Endung
    falsch.write_bytes(png.read_bytes())
    gesehen = []

    lies(falsch, textmodell=lambda p, b: gesehen.append(b[0][0]) or "Text.")

    assert gesehen == ["image/png"]


def test_bild_das_keins_ist_bricht(tmp_path):
    kein_bild = tmp_path / "x.png"
    kein_bild.write_bytes(b"Text, kein Bild")
    with pytest.raises(Mp4Fehler, match="Bild"):
        lies(kein_bild, textmodell=lambda p, b: "x")


def test_bild_grosses_foto_wird_verkleinert(tmp_path, monkeypatch):
    monkeypatch.setattr(bild, "MAX_BILD_BYTES", 500)
    gesehen = []

    lies(
        muster_png(tmp_path / "gross.png"),
        textmodell=lambda p, b: gesehen.append(b[0]) or "Text.",
    )

    mime, daten = gesehen[0]
    assert mime == "image/jpeg" and daten.startswith(b"\xff\xd8\xff")


def test_heic_ohne_umwandler_bricht_und_mit_umwandler_geht_es(tmp_path, monkeypatch):
    heic = tmp_path / "foto.heic"
    heic.write_bytes(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 20)

    monkeypatch.setattr(bild.shutil, "which", lambda _name: None)
    with pytest.raises(Mp4Fehler, match="HEIC"):
        lies(heic, textmodell=lambda p, b: "x")

    def umwandeln(befehl, **_k):
        ziel = befehl[befehl.index("--out") + 1]
        with open(ziel, "wb") as f:
            f.write(b"\xff\xd8\xff-jpeg")
        return subprocess.CompletedProcess(befehl, 0, b"", b"")

    monkeypatch.setattr(bild.shutil, "which", lambda name: "/bin/sips" if name == "sips" else None)
    monkeypatch.setattr(bild.subprocess, "run", umwandeln)
    gesehen = []
    lies(heic, textmodell=lambda p, b: gesehen.append(b[0]) or "Text.")
    assert gesehen[0][0] == "image/jpeg"


def test_ocr_ruft_tesseract_mit_sprache_und_zeitgrenze(monkeypatch):
    gesehen = {}

    def lauf(befehl, **kwargs):
        gesehen.update(befehl=befehl, **kwargs)
        return subprocess.CompletedProcess(befehl, 0, b"Erkannter Text", b"")

    monkeypatch.setattr(bild.subprocess, "run", lauf)

    assert bild.ocr(b"png", "deu") == "Erkannter Text"
    assert gesehen["befehl"][:2] == ["tesseract", "stdin"]
    assert gesehen["befehl"][gesehen["befehl"].index("-l") + 1] == "deu"
    assert gesehen["input"] == b"png"
    assert gesehen["timeout"] == 120


def test_ocr_fehlerfaelle_brechen_laut(monkeypatch):
    def zeit(*_a, **kw):
        raise subprocess.TimeoutExpired("tesseract", kw["timeout"])

    monkeypatch.setattr(bild.subprocess, "run", zeit)
    with pytest.raises(Mp4Fehler, match="Zeitgrenze"):
        bild.ocr(b"png", "deu")

    def fehler(befehl, **_k):
        return subprocess.CompletedProcess(befehl, 1, b"", b"Failed loading language 'deu'")

    monkeypatch.setattr(bild.subprocess, "run", fehler)
    with pytest.raises(Mp4Fehler, match="Failed loading language"):
        bild.ocr(b"png", "deu")


def _heic(tmp_path):
    heic = tmp_path / "foto.heic"
    heic.write_bytes(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 20)
    return heic


def _wandler(monkeypatch, vorhanden, schreibt):
    """Stellt her, welche Programme es gibt und welche davon ein JPEG schreiben.

    `vorhanden` und `schreibt` sind Programmnamen; das Ziel ist jeweils das letzte
    Argument (`heif-convert`, `ffmpeg`) bzw. das nach `--out` (`sips`).
    """
    gerufen = []

    def finde(name):
        return f"/bin/{name}" if name in vorhanden else None

    def lauf(befehl, **_k):
        gerufen.append(list(befehl))
        if befehl[0] in schreibt:
            ziel = befehl[befehl.index("--out") + 1] if "--out" in befehl else befehl[-1]
            with open(ziel, "wb") as f:
                f.write(b"\xff\xd8\xff-jpeg")
        return subprocess.CompletedProcess(befehl, 0, b"", b"")

    monkeypatch.setattr(bild.shutil, "which", finde)
    monkeypatch.setattr(bild.subprocess, "run", lauf)
    return gerufen


def test_heic_ueber_heif_convert_wenn_kein_sips(tmp_path, monkeypatch):
    gerufen = _wandler(monkeypatch, {"heif-convert", "ffmpeg"}, {"heif-convert"})
    gesehen = []

    lies(_heic(tmp_path), textmodell=lambda p, b: gesehen.append(b[0]) or "Text.")

    assert gesehen[0][0] == "image/jpeg"
    ((befehl,),) = [(b,) for b in gerufen]
    assert befehl[:3] == ["heif-convert", "-q", "90"]
    assert befehl[3].endswith("in.heic") and befehl[4].endswith("aus.jpg")


def test_heic_reihenfolge_sips_dann_heif_convert_dann_ffmpeg(tmp_path, monkeypatch):
    gerufen = _wandler(monkeypatch, {"sips", "heif-convert", "ffmpeg"}, {"ffmpeg"})

    daten, mime = bild.lade_bild(_heic(tmp_path))

    assert [b[0] for b in gerufen] == ["sips", "heif-convert", "ffmpeg"]
    assert mime == "image/jpeg" and daten.startswith(b"\xff\xd8\xff")


def test_heic_ohne_wandler_nennt_alle_wege(tmp_path, monkeypatch):
    _wandler(monkeypatch, set(), set())

    with pytest.raises(Mp4Fehler) as fehler:
        lies(_heic(tmp_path), textmodell=lambda p, b: "x")

    for weg in ("HEIC", "sips", "heif-convert", "ffmpeg", "libheif-examples"):
        assert weg in str(fehler.value)
