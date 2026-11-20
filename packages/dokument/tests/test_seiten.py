"""Aus jeder Eingabe werden Seitenbilder in brauchbarer Groesse."""

import stat

import pymupdf
import pytest

from conftest import schreibe_pdf
from mkn_dokument import seiten


def _kante(bild):
    pixel = pymupdf.Pixmap(str(bild))
    return max(pixel.width, pixel.height)


def test_pdf_wird_je_seite_ein_bild_in_300_dpi(tmp_path):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf", seiten=3)
    bilder = seiten.seitenbilder(pdf, tmp_path / "aus")
    assert [b.name for b in bilder] == ["seite-001.png", "seite-002.png", "seite-003.png"]
    assert _kante(bilder[0]) == pytest.approx(842 * 300 / 72, abs=2)
    assert stat.S_IMODE(bilder[0].stat().st_mode) == 0o600


def test_bilddatei_ist_eine_seite_und_kleine_vorlagen_werden_vergroessert(tmp_path):
    klein = tmp_path / "foto.png"
    pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 300), False).save(klein)
    bilder = seiten.seitenbilder(klein, tmp_path / "aus")
    assert len(bilder) == 1
    assert _kante(bilder[0]) == pytest.approx(seiten.KANTE_MIN, abs=2)


def test_uebergrosse_vorlage_wird_auf_die_hoechstkante_begrenzt(tmp_path):
    gross = tmp_path / "scan.png"
    pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 5000, 3000), False).save(gross)
    assert _kante(seiten.seitenbilder(gross, tmp_path / "aus")[0]) == pytest.approx(seiten.KANTE_MAX, abs=2)


def test_fehlende_und_unlesbare_eingabe_brechen_laut(tmp_path):
    with pytest.raises(seiten.SeitenFehler, match="fehlt"):
        seiten.seitenbilder(tmp_path / "gibtsnicht.pdf", tmp_path / "aus")
    kaputt = tmp_path / "kaputt.pdf"
    kaputt.write_bytes(b"kein pdf")
    with pytest.raises(seiten.SeitenFehler):
        seiten.seitenbilder(kaputt, tmp_path / "aus")


def test_verkleinert_laesst_passendes_bild_unveraendert_und_haelt_sonst_die_grenzen(tmp_path):
    bild = seiten.seitenbilder(schreibe_pdf(tmp_path / "b.pdf"), tmp_path / "aus")[0]
    assert seiten.verkleinert(bild, None, None) == bild
    kleiner = seiten.verkleinert(bild, 1000, None)
    assert kleiner != bild and abs(_kante(kleiner) - 1000) <= 1
    assert bild.exists() and _kante(bild) > 1000
    winzig = seiten.verkleinert(bild, None, 20_000)
    assert winzig.stat().st_size <= 20_000
    assert stat.S_IMODE(winzig.stat().st_mode) == 0o600


def test_verkleinerte_fassung_gehoert_immer_zum_aktuellen_bild(tmp_path):
    # Zwei Dokumente nacheinander im selben Ordner: die verkleinerte Fassung des ersten darf nie fuer das zweite gelten.
    erstes = seiten.seitenbilder(schreibe_pdf(tmp_path / "a.pdf", text="Erstes Dokument"), tmp_path / "aus")[0]
    klein_1 = seiten.verkleinert(erstes, 1000, None).read_bytes()
    zweites = seiten.seitenbilder(schreibe_pdf(tmp_path / "b.pdf", text="Ganz anderes"), tmp_path / "aus")[0]
    klein_2 = seiten.verkleinert(zweites, 1000, None).read_bytes()
    assert klein_1 != klein_2


def test_gedrehtes_foto_wird_aufrecht_gerendert(tmp_path):
    from PIL import Image as bild_modul  # Dev-Abhaengigkeit; ohne sie soll der Test rot sein, nicht still fehlen

    foto = bild_modul.new("RGB", (400, 200), "white")
    exif = foto.getexif()
    exif[0x0112] = 6  # Kamera hochkant gehalten: 90 Grad
    foto.save(tmp_path / "foto.jpg", exif=exif)
    pixel = pymupdf.Pixmap(str(seiten.seitenbilder(tmp_path / "foto.jpg", tmp_path / "aus")[0]))
    assert pixel.height > pixel.width


def test_vorhandene_datei_mit_weiteren_rechten_wird_auf_besitzer_begrenzt(tmp_path):
    pdf = schreibe_pdf(tmp_path / "b.pdf")
    (tmp_path / "aus").mkdir()
    alt = tmp_path / "aus" / "seite-001.png"
    alt.write_bytes(b"alt")
    alt.chmod(0o644)
    bild = seiten.seitenbilder(pdf, tmp_path / "aus")[0]
    assert stat.S_IMODE(bild.stat().st_mode) == 0o600
    assert not list((tmp_path / "aus").glob("*.neu"))
