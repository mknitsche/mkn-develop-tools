"""Zusicherungen zum exiftool-Wrapper.

Der Wrapper ist die einzige Stelle im Paket, die exiftool aufruft. Zwei Dinge
koennen hier still schiefgehen und beide sind teuer:

- Ein GERATENES Kamerakuerzel landet im Dateinamen und ist danach nicht mehr
  von einem echten zu unterscheiden.
- Ein FEHLENDES exiftool wuerde ohne Pruefung erst tief im Lauf auffallen,
  mitten im Schreiben.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mkn_foto import exif


def test_kamerakuerzel_kommt_aus_der_hinterlegten_zuordnung():
    assert exif.kamera_kuerzel("NIKON D850") == "D850"
    assert exif.kamera_kuerzel("X-E5") == "XE5"
    assert exif.kamera_kuerzel("iPhone 16 Pro") == "iP16Pro"


def test_unbekannte_kamera_bricht_laut_ab_statt_zu_raten():
    """Abbruch statt Heuristik: ein falsches Kuerzel im Dateinamen ist nicht
    mehr erkennbar, sobald es geschrieben ist."""
    with pytest.raises(exif.UnbekannteKamera, match="Sony"):
        exif.kamera_kuerzel("Sony ILCE-7M4")


def test_fehlermeldung_nennt_den_ort_der_eintragung():
    """Wer ueber eine neue Kamera stolpert, soll nicht suchen muessen."""
    with pytest.raises(exif.UnbekannteKamera, match="KAMERA_KUERZEL"):
        exif.kamera_kuerzel("Canon EOS R5")


def test_leere_pfadliste_ruft_exiftool_gar_nicht_auf(monkeypatch):
    """Untergrenze zu den Lese-Tests: ohne diesen Fall wuerde ein Wrapper, der
    bei leerer Liste exiftool mit NULL Pfaden aufruft, unbemerkt den gesamten
    Baum lesen."""

    def platzt(*_a, **_k):
        raise AssertionError("exiftool wurde trotz leerer Pfadliste aufgerufen")

    monkeypatch.setattr(exif, "_ruf_exiftool", platzt)
    assert exif.lies([]) == []


def test_lies_liefert_genau_einen_eintrag_je_pfad(tmp_path: Path):
    """Auch fuer Dateien, zu denen exiftool nichts sagt.

    Der Aufrufer paart die Ergebnisse strikt mit den Eingabepfaden; eine
    gekuerzte Liste wuerde dort brechen — oder, schlimmer, still verrutschen.
    """
    echt = tmp_path / "a.jpg"
    echt.write_bytes(_MINI_JPEG)
    fehlt = tmp_path / "gibt-es-nicht.jpg"

    ergebnis = exif.lies([echt, fehlt])

    assert len(ergebnis) == 2
    assert ergebnis[0]["SourceFile"] == str(echt)
    assert ergebnis[1]["SourceFile"] == str(fehlt)


def test_fehlendes_exiftool_wird_beim_aufruf_laut(monkeypatch, tmp_path: Path):
    """Nicht gefunden heisst Abbruch mit Installationshinweis - nicht ein
    leeres Ergebnis, das wie 'keine Metadaten' aussieht."""
    monkeypatch.setattr(exif, "_exiftool_pfad", lambda: None)
    with pytest.raises(exif.ExiftoolFehlt, match="exiftool"):
        exif.lies([tmp_path / "x.jpg"])


# Kleinstes gueltiges JPEG (SOI, APP0/JFIF, EOI) - exiftool liest es, Pillow nicht noetig.
_MINI_JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")
