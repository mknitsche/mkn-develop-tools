"""Der Client gegen einen echten Kindprozess (Schein-Arbeiter, gleiches Protokoll).

Kein Test braucht Chatterbox: `schein_arbeiter.py` spricht dasselbe Zeilenprotokoll und
loest Fehlfaelle (Fehlerantwort, Absturz, Haengen) auf Zuruf im Text aus.
"""

from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

import pytest

from mkn_audio.arbeiter_client import Arbeiter, ArbeiterFehler
from mkn_audio.typen import Mp4Fehler

SCHEIN = Path(__file__).with_name("schein_arbeiter.py")
SATZ = "Das ist ein kurzer Test der neuen Stimme, 70 Zeichen lang."


def neuer(**kw) -> Arbeiter:
    return Arbeiter(Path(sys.executable), skript=SCHEIN, **kw)


def sprich(a: Arbeiter, text: str, ziel: Path) -> dict:
    return a.sprich(
        text,
        sprache="de",
        vorlage=Path("vorlage.wav"),
        exaggeration=0.45,
        cfg_weight=0.45,
        temperature=0.75,
        ziel=ziel,
    )


def test_client_sprich_rundreise(tmp_path):
    ziel = tmp_path / "a.wav"
    with neuer() as a:
        antwort = sprich(a, SATZ, ziel)
    assert antwort["dauer"] == pytest.approx(len(SATZ) / 14)
    with wave.open(str(ziel), "rb") as w:
        assert w.getframerate() == 24_000
        assert w.getnframes() / 24_000 == pytest.approx(len(SATZ) / 14, abs=0.01)


def test_client_miss_hoere_vorlage_rundreise(tmp_path):
    with neuer() as a:
        assert a.miss(tmp_path / "x.wav")["streuung_ht"] == 3.0
        assert a.hoere(tmp_path / "x.wav", "de") == "schein"
        antwort = a.vorlage(tmp_path / "roh.m4a", tmp_path / "v.wav", dauer=2)
    assert antwort["start"] == 0.0
    assert (tmp_path / "v.wav").exists()


def test_client_fehlerantwort_bricht_und_prozess_lebt_weiter(tmp_path):
    with neuer() as a:
        with pytest.raises(ArbeiterFehler, match="Schein-Fehler"):
            sprich(a, "[fehler]", tmp_path / "a.wav")
        # Eine Fehlerantwort ist kein Absturz: der naechste Auftrag laeuft im selben Prozess.
        assert sprich(a, SATZ, tmp_path / "b.wav")["dauer"] > 0


def test_client_toter_prozess_bricht_nennt_ursache_und_startet_neu(tmp_path):
    with neuer() as a:
        with pytest.raises(ArbeiterFehler, match="Schein-Absturz: Speicher voll") as roh:
            sprich(a, "[tod]", tmp_path / "a.wav")
        assert "Exit 3" in str(roh.value)
        # Spec 7: ein gestorbener Arbeiter wird neu gestartet, das Stueck gilt als nicht gerechnet.
        assert sprich(a, SATZ, tmp_path / "b.wav")["dauer"] > 0


def test_client_zeitgrenze(tmp_path):
    start = time.monotonic()
    with neuer(zeitgrenze_s=0.5) as a, pytest.raises(ArbeiterFehler, match="Zeitgrenze"):
        sprich(a, "[haengt]", tmp_path / "a.wav")
    assert time.monotonic() - start < 20


def test_client_startfehler_nennt_den_pfad(tmp_path):
    a = Arbeiter(tmp_path / "gibts-nicht", skript=SCHEIN)
    with pytest.raises(ArbeiterFehler, match="gibts-nicht"):
        a.__enter__()


def test_arbeiterfehler_ist_ein_paketfehler():
    assert issubclass(ArbeiterFehler, Mp4Fehler)


def test_speicherfehler_startet_den_arbeiter_neu(tmp_path):
    # Nach "out of memory" scheitert ein Neuversuch im selben Prozess sicher wieder.
    with neuer() as a:
        alt = a._prozess.pid
        with pytest.raises(ArbeiterFehler) as info:
            sprich(a, "[speicher]", tmp_path / "a.wav")
        assert info.value.klasse == "Speicher"
        assert sprich(a, SATZ, tmp_path / "b.wav")["dauer"] > 0
        assert a._prozess.pid != alt


def test_vorbeugender_neustart_nach_n_stuecken(tmp_path):
    with neuer(neustart_nach=2) as a:
        pids = []
        for i in range(5):
            sprich(a, SATZ, tmp_path / f"{i}.wav")
            pids.append(a._prozess.pid)
    # je zwei Stuecke ein Prozess: 1,1 | 2,2 | 3
    assert pids[0] == pids[1] != pids[2] == pids[3] != pids[4]
