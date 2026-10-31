"""Die Konfiguration: Fundort, Vorgaben, und laut scheitern, wenn sie nicht stimmt."""

from __future__ import annotations

from pathlib import Path

import pytest
from mkn_kern.anfrage import AnfrageFehler

from mkn_audio import konfig
from mkn_audio.konfig import Konfig, lade
from mkn_audio.typen import Mp4Fehler


def _schreibe(pfad: Path, text: str) -> Path:
    pfad.write_text(text, encoding="utf-8")
    return pfad


MINIMAL = 'stimmen_tabelle = "/t/stimmen.toml"\narbeiter_python = "/a/bin/python"\n'


def test_konfig_umgebung_ueberschreibt_pfad(tmp_path, monkeypatch):
    standard = _schreibe(tmp_path / "standard.toml", MINIMAL.replace("/t/", "/standard/"))
    eigene = _schreibe(tmp_path / "eigene.toml", MINIMAL.replace("/t/", "/eigene/"))
    monkeypatch.setattr(konfig, "STANDARD_ORT", standard)
    monkeypatch.setenv("MKN_MP4_KONFIG", str(eigene))

    ergebnis = lade()

    assert ergebnis.stimmen_tabelle == Path("/eigene/stimmen.toml")


def test_ohne_umgebung_gilt_der_standardort(tmp_path, monkeypatch):
    standard = _schreibe(tmp_path / "standard.toml", MINIMAL)
    monkeypatch.setattr(konfig, "STANDARD_ORT", standard)
    monkeypatch.delenv("MKN_MP4_KONFIG")

    assert lade().stimmen_tabelle == Path("/t/stimmen.toml")


def test_aufruf_pfad_schlaegt_umgebung(tmp_path, monkeypatch):
    _schreibe(tmp_path / "env.toml", MINIMAL.replace("/t/", "/env/"))
    monkeypatch.setenv("MKN_MP4_KONFIG", str(tmp_path / "env.toml"))
    direkt = _schreibe(tmp_path / "direkt.toml", MINIMAL.replace("/t/", "/direkt/"))

    assert lade(direkt).stimmen_tabelle == Path("/direkt/stimmen.toml")


def test_vorgaben(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "heim"))
    pfad = _schreibe(tmp_path / "k.toml", MINIMAL)

    ergebnis = lade(pfad)

    assert isinstance(ergebnis, Konfig)
    assert ergebnis.arbeitsort == tmp_path / "heim" / ".cache" / "mkn-mp4"
    assert ergebnis.arbeiter_python == Path("/a/bin/python")
    assert ergebnis.whisper_modell == "small"


def test_werte_und_tilde_und_relative_pfade(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "heim"))
    pfad = _schreibe(
        tmp_path / "k.toml",
        'stimmen_tabelle = "stimmen.toml"\narbeiter_python = "~/arbeiter/bin/python"\n'
        'arbeitsort = "~/arbeit"\nwhisper_modell = "medium"\n',
    )

    ergebnis = lade(pfad)

    # Relativ heisst: relativ zur Konfigurationsdatei, nicht zum Aufrufer.
    assert ergebnis.stimmen_tabelle == tmp_path / "stimmen.toml"
    assert ergebnis.arbeiter_python == tmp_path / "heim" / "arbeiter" / "bin" / "python"
    assert ergebnis.arbeitsort == tmp_path / "heim" / "arbeit"
    assert ergebnis.whisper_modell == "medium"


def test_fehlende_datei_bricht_mit_ort(tmp_path):
    with pytest.raises(Mp4Fehler, match=r"gibtsnicht\.toml"):
        lade(tmp_path / "gibtsnicht.toml")


def test_fehlende_datei_ueber_umgebung_bricht_mit_ort():
    """Die Fixture zeigt auf einen Pfad, den es nicht gibt: kein stiller Ersatz."""
    with pytest.raises(Mp4Fehler, match=r"gibtsnicht\.toml"):
        lade()


def test_pflichtschluessel_fehlt_bricht(tmp_path):
    """`stimmen_tabelle` ist Pflicht; `arbeiter_python` seit Plan C4 nicht mehr."""
    pfad = _schreibe(tmp_path / "k.toml", 'arbeiter_python = "/a/bin/python"\n')

    with pytest.raises(Mp4Fehler, match="stimmen_tabelle"):
        lade(pfad)


def test_unbekannter_schluessel_bricht(tmp_path):
    pfad = _schreibe(tmp_path / "k.toml", MINIMAL + 'whisper_model = "small"\n')

    with pytest.raises(Mp4Fehler, match="whisper_model"):
        lade(pfad)


def test_kaputtes_toml_bricht_mit_ort(tmp_path):
    pfad = _schreibe(tmp_path / "k.toml", "stimmen_tabelle = [")

    with pytest.raises(Mp4Fehler, match=r"k\.toml"):
        lade(pfad)


def test_falscher_typ_bricht(tmp_path):
    pfad = _schreibe(tmp_path / "k.toml", MINIMAL + "whisper_modell = 3\n")

    with pytest.raises(Mp4Fehler, match="whisper_modell"):
        lade(pfad)


def test_mkn_kern_fehler_hat_status():
    """Das Paket braucht mkn-kern >= 0.3: `AnfrageFehler` traegt den HTTP-Status (Plan B0.2).

    Ohne Status kann der Gemini-Sprecher Sperre, Limit und Zugang nicht unterscheiden.
    """
    assert AnfrageFehler("x", status=400).status == 400


def test_konfig_ohne_arbeiter_python_fuer_gemini_ok(tmp_path):
    """Wer nur den Weg gemini nutzt, braucht keinen Arbeiter: `arbeiter_python` ist optional
    (dann keine Whisper-Stichprobe, Spec 14.2) und fehlt als `None`, nie als Ersatzpfad."""
    pfad = _schreibe(tmp_path / "k.toml", 'stimmen_tabelle = "/t/stimmen.toml"\n')

    ergebnis = lade(pfad)

    assert ergebnis.stimmen_tabelle == Path("/t/stimmen.toml")
    assert ergebnis.arbeiter_python is None
