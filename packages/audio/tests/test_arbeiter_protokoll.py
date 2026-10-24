"""Das Zeilenprotokoll von `arbeiter.py` im Schein-Modus (`--schein`).

Der Schein-Pfad laedt weder Chatterbox noch Whisper und braucht nur die
Standardbibliothek -- die Paket-Umgebung hat weder numpy noch torch. Bewiesen wird hier
das Protokoll und die Regeln (3 Versuche, atomares Schreiben), nicht die Stimme.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import wave
from pathlib import Path

import pytest

ARBEITER = Path(__file__).parents[1] / "src" / "mkn_audio" / "arbeiter.py"
TEXT = "x" * 140  # erwartet 140 / 14 = 10 s; Grenze 55 % = 5,5 s


def frage(anfragen, *args: str) -> list[dict]:
    """Startet den Arbeiter mit `--schein`, schickt Zeilen, liest die Antwortzeilen."""
    zeilen = "".join((a if isinstance(a, str) else json.dumps(a)) + "\n" for a in anfragen)
    lauf = subprocess.run(
        [sys.executable, str(ARBEITER), "--schein", *args],
        input=zeilen,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert lauf.returncode == 0, lauf.stderr
    return [json.loads(z) for z in lauf.stdout.splitlines()]


def sprich(tmp_path: Path, name: str = "a.wav", text: str = TEXT) -> dict:
    vorlage = tmp_path / "vorlage.wav"
    vorlage.write_bytes(b"")
    return {
        "befehl": "sprich",
        "text": text,
        "sprache": "de",
        "vorlage": str(vorlage),
        "exaggeration": 0.45,
        "cfg_weight": 0.45,
        "temperature": 0.75,
        "pausen_kuerzen": True,
        "ziel": str(tmp_path / name),
    }


def dauer_der_datei(pfad: Path) -> float:
    with wave.open(str(pfad), "rb") as w:
        return w.getnframes() / w.getframerate()


@pytest.mark.parametrize(
    ("dauern", "erwartet_anteil"),
    [("0.2,0.3,0.45", 0.45), ("0.3,0.5,0.2", 0.5)],
)
def test_drei_versuche_laengster_gewinnt(tmp_path, dauern, erwartet_anteil):
    # Alle drei Versuche unter 55 %: das LAENGSTE gewinnt, nicht das letzte.
    [antwort] = frage([sprich(tmp_path)], "--schein-dauern", dauern)
    assert antwort["versuche"] == 3
    assert antwort["zu_kurz"] is True
    assert antwort["dauer"] == pytest.approx(10 * erwartet_anteil, abs=0.01)
    assert dauer_der_datei(tmp_path / "a.wav") == pytest.approx(10 * erwartet_anteil, abs=0.01)


def test_hoert_beim_ersten_ausreichenden_versuch_auf(tmp_path):
    [antwort] = frage([sprich(tmp_path)], "--schein-dauern", "0.3,0.9,0.1")
    assert antwort["versuche"] == 2
    assert antwort["zu_kurz"] is False
    assert antwort["dauer"] == pytest.approx(9.0, abs=0.01)


def test_sprechrate_ist_zeichen_je_sekunde(tmp_path):
    [antwort] = frage([sprich(tmp_path)])
    assert antwort["versuche"] == 1
    assert antwort["sprechrate"] == pytest.approx(14.0, abs=0.1)


def test_fehler_bleiben_in_der_leitung_und_der_arbeiter_lebt_weiter(tmp_path):
    fehlende_vorlage = sprich(tmp_path, "b.wav") | {"vorlage": str(tmp_path / "fehlt.wav")}
    antworten = frage(
        [
            fehlende_vorlage,
            "das ist kein json",
            {"befehl": "tanze"},
            {"befehl": "sprich", "text": "ohne Rest"},
            sprich(tmp_path, "c.wav"),
        ]
    )
    assert "Vorlage fehlt" in antworten[0]["fehler"]
    assert "fehler" in antworten[1]
    assert "tanze" in antworten[2]["fehler"]
    assert "fehler" in antworten[3]
    assert antworten[4]["dauer"] == pytest.approx(10.0, abs=0.01)
    # Die Fehlerfaelle haben keine Datei hinterlassen.
    assert not (tmp_path / "b.wav").exists()


def lade_arbeiter_modul():
    spec = importlib.util.spec_from_file_location("arbeiter_unter_test", ARBEITER)
    modul = importlib.util.module_from_spec(spec)
    # Kein Bytecode neben das Skript: ein zweites Zwischenlager wuerde bei Aenderungen
    # in derselben Sekunde den alten Stand beweisen statt des neuen.
    vorher, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(modul)
    finally:
        sys.dont_write_bytecode = vorher
    return modul


def test_atomar_kein_halbes_wav(tmp_path, monkeypatch):
    arbeiter = lade_arbeiter_modul()
    alt = tmp_path / "a.wav"
    alt.write_bytes(b"ALT")

    def schreibe_halb_und_stirb(self, w, pfad):
        Path(pfad).write_bytes(b"RIFF-halb")
        raise OSError("Strom weg")

    monkeypatch.setattr(arbeiter.ScheinWerk, "schreibe", schreibe_halb_und_stirb)
    with pytest.raises(OSError, match="Strom weg"):
        arbeiter.sprich(arbeiter.ScheinWerk(), sprich(tmp_path))
    # Weder ist eine vorhandene Aufnahme angetastet noch bleibt ein Rest liegen.
    assert alt.read_bytes() == b"ALT"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.wav", "vorlage.wav"]


def test_atomar_erfolg_hinterlaesst_keinen_rest(tmp_path):
    [antwort] = frage([sprich(tmp_path)])
    assert antwort["dauer"] > 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.wav", "vorlage.wav"]
