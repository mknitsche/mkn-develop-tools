"""Zusicherungen zum Lesen des Original-Baums.

Die Einheit ist die Belichtung, nicht die Datei. Zwei Fehler waeren hier
teuer und beide waeren still:

- Wuerden RAW und JPEG derselben Belichtung NICHT gepaart, bekaeme dieselbe
  Aufnahme zwei getrennte Namen und zwei Metadatensaetze, die auseinanderlaufen.
- Wuerde eine Datei ohne Aufnahmezeit einfach verschwinden, faellt sie aus dem
  gesamten Lauf heraus — sie wird nicht falsch benannt, sie fehlt.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pytest
from mkn_foto import inventar


def _lege_an(wurzel: Path, relativ: str) -> Path:
    pfad = wurzel / relativ
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(b"nicht wirklich ein Bild")
    return pfad


@pytest.fixture
def exif_stub(monkeypatch):
    """Ersetzt exiftool durch abgelegte Felder — geprueft wird die Paarung,
    nicht exiftool. Der Wrapper hat seine eigenen Tests."""
    felder = {
        "DSCF3541.RAF": ("2026:08:27 10:31:22", "X-E5"),
        "DSCF3541.JPG": ("2026:08:27 10:31:22", "X-E5"),
        "DSCF3542.RAF": ("2026:08:27 10:31:25", "X-E5"),
        "DSCF3540.RAF": ("2026:08:27 10:31:31", "X-E5"),  # spaeter als 3542!
        "DSCF9999.JPG": (None, "X-E5"),
    }

    def _lies(pfade):
        ergebnis = []
        for p in pfade:
            zeit, model = felder[Path(p).name]
            eintrag = {"SourceFile": str(p), "EXIF:Model": model}
            if zeit is not None:
                eintrag["EXIF:DateTimeOriginal"] = zeit
            ergebnis.append(eintrag)
        return ergebnis

    monkeypatch.setattr(inventar.exif, "lies", _lies)


def test_raw_und_jpeg_derselben_belichtung_sind_eine_aufnahme(tmp_path, exif_stub):
    _lege_an(tmp_path, "2026-08-27/X-E5/DSCF3541.RAF")
    _lege_an(tmp_path, "2026-08-27/X-E5/DSCF3541.JPG")

    aufnahmen = inventar.lies_baum(tmp_path)

    assert len(aufnahmen) == 1
    assert set(aufnahmen[0].dateien) == {".RAF", ".JPG"}
    assert aufnahmen[0].stamm == "DSCF3541"
    assert aufnahmen[0].kamera == "XE5"
    assert aufnahmen[0].zeitpunkt == datetime(2026, 8, 27, 10, 31, 22)


def test_das_raw_fuehrt_wo_es_eines_gibt(tmp_path, exif_stub):
    """Die MakerNotes des RAW tragen die Serieninformation der Kamera. Fuehrte
    stattdessen das JPEG, ginge genau die Angabe verloren, auf der Stufe 1 der
    Serienerkennung beruht — und die Erkennung fiele still auf Heuristik
    zurueck, ohne dass es jemandem auffiele."""
    raw = _lege_an(tmp_path, "2026-08-27/X-E5/DSCF3541.RAF")
    _lege_an(tmp_path, "2026-08-27/X-E5/DSCF3541.JPG")

    aufnahmen = inventar.lies_baum(tmp_path)

    assert aufnahmen[0].exif["SourceFile"] == str(raw)


def test_der_berichtsordner_wird_nicht_mitgelesen(tmp_path, exif_stub):
    """`_bericht` liegt im Zielbaum neben den Tagen. Wuerde er mitgelesen,
    liesse ein zweiter Lauf das Protokoll als Aufnahme durchgehen."""
    _lege_an(tmp_path, "2026-08-27/X-E5/DSCF3541.RAF")
    _lege_an(tmp_path, "_bericht/kontaktboegen/DSCF3542.RAF")

    aufnahmen = inventar.lies_baum(tmp_path)

    assert [a.stamm for a in aufnahmen] == ["DSCF3541"]


def test_aufnahmen_kommen_chronologisch_zurueck(tmp_path, exif_stub):
    """Die Serienerkennung setzt zeitliche Nachbarschaft voraus — die
    Reihenfolge ist Teil des Vertrags, nicht Zufall.

    DSCF3540 ist hier ABSICHTLICH die spaeteste Aufnahme: waeren Zeit- und
    Namensfolge deckungsgleich, bestuende dieser Test auch bei einer
    Sortierung nach dem Namen — und wuerde die Zusicherung nur behaupten.
    Genau so war die erste Fassung gebaut; die Mutation hat sie ueberlebt."""
    _lege_an(tmp_path, "2026-08-27/X-E5/DSCF3540.RAF")
    _lege_an(tmp_path, "2026-08-27/X-E5/DSCF3542.RAF")
    _lege_an(tmp_path, "2026-08-27/X-E5/DSCF3541.RAF")

    aufnahmen = inventar.lies_baum(tmp_path)

    assert [a.stamm for a in aufnahmen] == ["DSCF3541", "DSCF3542", "DSCF3540"]


def test_datei_ohne_aufnahmezeit_verschwindet_nicht_stillschweigend(tmp_path, exif_stub, caplog):
    """Ohne `DateTimeOriginal` kann die Aufnahme nicht eingeordnet werden — sie
    wird uebersprungen. Das darf nicht LEISE geschehen: die Datei faellt damit
    aus dem gesamten Lauf, sie wird nicht falsch benannt, sondern fehlt. Wer
    das erst am Ende an einer Stueckzahl merkt, sucht lange."""
    _lege_an(tmp_path, "2026-08-27/X-E5/DSCF3541.RAF")
    _lege_an(tmp_path, "2026-08-27/X-E5/DSCF9999.JPG")

    with caplog.at_level(logging.WARNING, logger="mkn_foto.inventar"):
        aufnahmen = inventar.lies_baum(tmp_path)

    assert [a.stamm for a in aufnahmen] == ["DSCF3541"]
    assert "DSCF9999.JPG" in caplog.text


def test_fremde_dateien_werden_exiftool_gar_nicht_erst_vorgelegt(tmp_path, monkeypatch):
    """Im echten Baum liegen Beistelldateien, Kataloge und `.DS_Store`. Wuerde
    der Endungsfilter sie durchlassen, bekaeme exiftool Muell vorgelegt und
    lieferte Eintraege, die als Aufnahmen durchgingen.

    Die urspruengliche Fassung dieses Tests prueste einen LEEREN Baum — dort
    ist die Zusicherung trivial erfuellt, weil schon `exif.lies` bei leerer
    Liste nichts tut (LP-34: ein Beweis muss seinen Gegenstand enthalten)."""
    _lege_an(tmp_path, "2026-08-27/X-E5/DSCF3541.xmp")
    _lege_an(tmp_path, "2026-08-27/X-E5/.DS_Store")
    _lege_an(tmp_path, "2026-08-27/Katalog.cosessiondb")

    def _darf_nicht_gerufen_werden(pfade):
        if pfade:
            raise AssertionError(f"exiftool bekam fremde Dateien: {[p.name for p in pfade]}")
        return []

    monkeypatch.setattr(inventar.exif, "lies", _darf_nicht_gerufen_werden)

    assert inventar.lies_baum(tmp_path) == []
