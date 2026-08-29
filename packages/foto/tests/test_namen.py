"""Zusicherungen zur Dateinotation und zur Existenzpruefung.

Der Name ist das Ergebnis des ganzen Werkzeugs — er traegt Datum, Zeit,
Kamera, Serienzugehoerigkeit und den Originalnamen. Zwei Dinge muessen
darum sitzen:

- Ein Zaehler, der nicht mehr in zwei Stellen passt, wuerde die Abschnitte
  verschieben und den Namen unlesbar machen.
- Die Suche nach einer schon vorhandenen Aufnahme darf NICHT auf dem
  Typ-Abschnitt bestehen: genau dort steht eine Korrektur von Hand, und ein
  zweiter Lauf wuerde sie sonst rueckgaengig machen.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from mkn_foto import namen
from mkn_foto.modell import Aufnahme


def _aufnahme(
    stamm="DSCF3541",
    zeit=datetime(2026, 8, 27, 10, 31, 22),
    kamera="XE5",
    dateien=None,
):
    return Aufnahme(zeitpunkt=zeit, kamera=kamera, stamm=stamm, dateien=dateien or {}, exif={})


def test_einzelaufnahme_traegt_std_ohne_serienteil():
    assert namen.archiv_name(_aufnahme(), ".RAF") == "2026-08-27_103122_XE5_std_DSCF3541.RAF"


def test_serienaufnahme_traegt_typ_nummer_position_und_gesamtzahl():
    a = _aufnahme(stamm="D85_2560", zeit=datetime(2026, 8, 26, 20, 15, 19), kamera="D850")
    assert (
        namen.archiv_name(a, ".NEF", typ="pan", serie=1, pos=1, gesamt=15)
        == "2026-08-26_201519_D850_pan01-01v15_D85_2560.NEF"
    )


def test_einstellige_zaehler_werden_auf_zwei_stellen_aufgefuellt():
    """Die drei Belichtungen einer HDR-Reihe sind der haeufigste Fall — und
    genau dort faellt fehlendes Auffuellen auf: `v3` statt `v03` bringt die
    Namensfolge im Ordner durcheinander, sobald eine Reihe zehn Bilder hat.

    Die erste Fassung dieser Zusicherung prueste `gesamt=15`, wo beide
    Schreibweisen dasselbe ergeben — die Mutation hat sie ueberlebt."""
    a = _aufnahme(stamm="D85_2560", zeit=datetime(2026, 8, 26, 20, 15, 19), kamera="D850")
    assert (
        namen.archiv_name(a, ".NEF", typ="hdr", serie=2, pos=3, gesamt=3)
        == "2026-08-26_201519_D850_hdr02-03v03_D85_2560.NEF"
    )


def test_serie_ueber_99_bricht_laut_ab_statt_still_zu_ueberlaufen():
    """Ein dreistelliger Zaehler wuerde die Positionsstellen verschieben und
    den Namen unlesbar machen — lieber lauter Abbruch."""
    with pytest.raises(namen.NotationUeberlauf, match="100"):
        namen.archiv_name(_aufnahme(), ".RAF", typ="hdr", serie=1, pos=1, gesamt=100)


def test_unbekannter_typ_wird_abgewiesen():
    with pytest.raises(ValueError, match="hdrx"):
        namen.archiv_name(_aufnahme(), ".RAF", typ="hdrx", serie=1, pos=1, gesamt=3)


def test_serientyp_ohne_zaehler_wird_abgewiesen():
    """Sonst faellt es erst in der Formatierung auf — mit einer Meldung, die
    nicht sagt, was fehlt."""
    with pytest.raises(ValueError, match="pan"):
        namen.archiv_name(_aufnahme(), ".RAF", typ="pan")


def test_das_stabile_muster_laesst_den_typ_abschnitt_offen():
    """Genau dort steht eine Korrektur von Hand — danach darf nicht gesucht
    werden, sonst legt ein zweiter Lauf die korrigierte Aufnahme neu an."""
    assert namen.stabiles_muster(_aufnahme(), ".RAF") == "2026-08-27_103122_XE5_*_DSCF3541.RAF"


def test_eine_umbenannte_datei_gilt_als_vorhanden(tmp_path):
    """Aus `pan01` wurde von Hand `std`. Der naechste Lauf muss sie trotzdem
    finden und in Ruhe lassen."""
    (tmp_path / "2026-08-27_103122_XE5_std_DSCF3541.RAF").write_bytes(b"x")
    a = _aufnahme(dateien={".RAF": Path("egal.RAF")})

    assert namen.ist_schon_da(tmp_path, a) is True


def test_eine_fremde_datei_im_ordner_gilt_nicht_als_diese_aufnahme(tmp_path):
    """Untergrenze zur Zeile darueber: ohne diesen Fall bestuende die
    Existenzpruefung auch dann, wenn sie schlicht jede nichtleere Ablage
    bejahte."""
    (tmp_path / "2026-08-27_103125_XE5_std_DSCF3542.RAF").write_bytes(b"x")
    a = _aufnahme(dateien={".RAF": Path("egal.RAF")})

    assert namen.ist_schon_da(tmp_path, a) is False


def test_eine_fehlende_aufnahme_gilt_als_nicht_vorhanden(tmp_path):
    a = _aufnahme(dateien={".RAF": Path("egal.RAF")})

    assert namen.ist_schon_da(tmp_path, a) is False


def test_ein_fehlender_zielordner_ist_kein_fehler(tmp_path):
    """Beim ersten Lauf eines Tages gibt es den Ordner noch nicht."""
    a = _aufnahme(dateien={".RAF": Path("egal.RAF")})

    assert namen.ist_schon_da(tmp_path / "gibt-es-nicht", a) is False
