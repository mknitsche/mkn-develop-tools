"""Mastern: Kapitel-Ton aus Stuecken, Tempo, Klang, Tonhoehe, Lautheit.

Die Aufnahmen entstehen im Test aus Sinus-Toenen (stdlib `wave` + `math`); geprueft wird
mit ffmpeg/ffprobe, dem Werkzeug, das auch die Produktion benutzt -- der Test haengt an
der WIRKUNG (Dauer, Lautheit, Frequenz), nicht an der Befehlszeile.
"""

from __future__ import annotations

import array
import itertools
import json
import math
import os
import re
import subprocess
import wave
from pathlib import Path

import pytest

from mkn_audio.mastern import _pause_nach, kapitel_ton, master
from mkn_audio.stimmen import Stimme
from mkn_audio.typen import Mp4Fehler, Stueck

RATE = 24_000


def schreibe_sinus(
    pfad: Path,
    sekunden: float,
    *,
    hz: float | tuple[float, ...] = 220.0,
    pegel: float = 0.05,
    moduliert: bool = False,
) -> Path:
    """Schreibt einen Sinus (oder eine Summe) als WAV PCM16, 24 kHz, mono."""
    toene = (hz,) if isinstance(hz, float | int) else hz
    n = int(sekunden * RATE)
    werte = array.array("h")
    for i in range(n):
        t = i / RATE
        s = sum(math.sin(2 * math.pi * f * t) for f in toene) / len(toene)
        if moduliert:  # grob sprachartig: Huellkurve mit 3 Hz
            s *= 0.55 + 0.45 * math.sin(2 * math.pi * 3 * t)
        werte.append(int(max(-1.0, min(1.0, s * pegel)) * 32767))
    with wave.open(str(pfad), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(werte.tobytes())
    return pfad


def dauer(pfad: Path) -> float:
    with wave.open(str(pfad), "rb") as w:
        return w.getnframes() / w.getframerate()


def lies_werte(pfad: Path) -> list[int]:
    with wave.open(str(pfad), "rb") as w:
        roh = array.array("h")
        roh.frombytes(w.readframes(w.getnframes()))
    return list(roh)


def betrag(werte: list[int], hz: float) -> float:
    """Goertzel: Betrag der Frequenz `hz` im Signal (ohne numpy)."""
    k = 2 * math.cos(2 * math.pi * hz / RATE)
    s1 = s2 = 0.0
    for x in werte:
        s1, s2 = x + k * s1 - s2, s1
    return math.sqrt(s1 * s1 + s2 * s2 - k * s1 * s2) / len(werte)


def nulldurchgaenge_hz(pfad: Path) -> float:
    werte = lies_werte(pfad)
    wechsel = sum(1 for a, b in itertools.pairwise(werte) if a < 0 <= b)
    return wechsel / (len(werte) / RATE)


def lautheit(pfad: Path) -> tuple[float, float]:
    """(integrierte Lautheit in LUFS, True Peak in dBTP) per ebur128."""
    lauf = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(pfad), "-af", "ebur128=peak=true",
         "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    summe = lauf.stderr.rsplit("Summary:", 1)[1]
    i = float(re.search(r"\n\s+I:\s+(-?[\d.]+) LUFS", summe).group(1))
    spitze = float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", summe).group(1))
    return i, spitze


def ffprobe(*argumente: str) -> dict:
    lauf = subprocess.run(
        ["ffprobe", "-v", "error", "-of", "json", *argumente],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return json.loads(lauf.stdout)


def mache_stimme(**felder) -> Stimme:
    vorgabe = dict(
        name="test",
        beschreibung="Teststimme",
        vorlage=Path("vorlage.wav"),
        exaggeration=0.45,
        cfg_weight=0.45,
        temperature=0.75,
        tempo=1.0,
        stand="probe",
    )
    vorgabe.update(felder)
    return Stimme(**vorgabe)


@pytest.fixture
def sprache():
    return mache_stimme()


# -- kapitel_ton ----------------------------------------------------------------------


def _stuecke_mit_ton(tmp_path, dauern, raten, struktur):
    """Baut Stuecke, ihre WAVs und die Messwerte. struktur: (absatz, art) je Stueck."""
    stuecke, ton, wavs = [], {}, {}
    for nr, (d, rate, (absatz, art)) in enumerate(zip(dauern, raten, struktur, strict=True)):
        s = Stueck(kapitel=0, absatz=absatz, nr=nr, text=f"Text {nr}", art=art)
        stuecke.append(s)
        wavs[nr] = schreibe_sinus(tmp_path / f"s{nr}.wav", d)
        ton[nr] = {"dauer": d, "sprechrate": rate, "versuche": 1, "zu_kurz": False}
    return stuecke, ton, lambda s: wavs[s.nr]


def test_kapitel_ton_pausen_je_ebene(tmp_path, sprache):
    # Titel | Absatz 0: zwei Stuecke | Absatz 1: ein Stueck  -> Titel-, Stueck-, Absatzpause
    struktur = [(-1, "titel"), (0, "text"), (0, "text"), (1, "text")]
    stuecke, ton, pfad = _stuecke_mit_ton(tmp_path, [1.0] * 4, [10.0] * 4, struktur)
    ziel = tmp_path / "kapitel.wav"

    ergebnis = kapitel_ton(stuecke, ton, sprache, pfad, ziel)

    assert ergebnis == ziel
    erwartet = 4 * 1.0 + sprache.pause_titel + sprache.pause_stueck + sprache.pause_absatz
    assert dauer(ziel) == pytest.approx(erwartet, abs=0.01)


def test_pause_vor_und_nach_ueberschrift(tmp_path, sprache):
    """Vor einer Zwischenueberschrift 1,0 s, danach 0,7 s (Vorgaben der Stimme)."""
    assert (sprache.pause_vor_ueberschrift, sprache.pause_nach_ueberschrift) == (1.0, 0.7)

    def st(absatz, art):
        return Stueck(kapitel=0, absatz=absatz, nr=0, text="x", art=art)

    # Jeder Fall hat einen anderen Wert, damit eine vertauschte Regel auffaellt.
    assert _pause_nach(st(0, "text"), st(1, "ueberschrift"), sprache) == 1.0
    assert _pause_nach(st(1, "ueberschrift"), st(2, "text"), sprache) == 0.7
    assert _pause_nach(st(-1, "titel"), st(0, "text"), sprache) == sprache.pause_titel
    assert _pause_nach(st(0, "text"), st(1, "text"), sprache) == sprache.pause_absatz
    assert _pause_nach(st(0, "text"), st(0, "text"), sprache) == sprache.pause_stueck

    # Im zusammengesetzten Kapitel: Titel | Text | Ueberschrift | Text
    struktur = [(-1, "titel"), (0, "text"), (1, "ueberschrift"), (2, "text")]
    stuecke, ton, pfad = _stuecke_mit_ton(tmp_path, [1.0] * 4, [10.0] * 4, struktur)
    ziel = kapitel_ton(stuecke, ton, sprache, pfad, tmp_path / "kapitel.wav")

    assert dauer(ziel) == pytest.approx(4 * 1.0 + sprache.pause_titel + 1.0 + 0.7, abs=0.01)


def test_kapitel_ton_format_und_atomar(tmp_path, sprache):
    stuecke, ton, pfad = _stuecke_mit_ton(tmp_path, [0.5, 0.5], [10.0] * 2, [(0, "text")] * 2)
    ziel = tmp_path / "kapitel.wav"

    kapitel_ton(stuecke, ton, sprache, pfad, ziel)

    with wave.open(str(ziel), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, RATE)
    assert sorted(p.name for p in tmp_path.glob("kapitel*")) == ["kapitel.wav"]


def test_tempo_angleich_erst_ab_vier_stuecken(tmp_path, sprache):
    # Ausreisser (Rate 15 gegen 10) als drittes Stueck: noch kein Angleich.
    stuecke, ton, pfad = _stuecke_mit_ton(
        tmp_path, [2.0] * 3, [10.0, 10.0, 15.0], [(0, "text")] * 3
    )
    ziel = tmp_path / "k.wav"

    kapitel_ton(stuecke, ton, sprache, pfad, ziel)

    assert dauer(ziel) == pytest.approx(3 * 2.0 + 2 * sprache.pause_stueck, abs=0.01)


def test_tempo_angleich_gedeckelt_auf_zehn_prozent(tmp_path, sprache):
    # Fuenftes Stueck zu schnell (15 gegen Median 10): strecken, aber hoechstens um 10 %.
    stuecke, ton, pfad = _stuecke_mit_ton(
        tmp_path, [2.0] * 5, [10.0, 10.0, 10.0, 10.0, 15.0], [(0, "text")] * 5
    )
    ziel = tmp_path / "k.wav"

    kapitel_ton(stuecke, ton, sprache, pfad, ziel)

    erwartet = 4 * 2.0 + 2.0 * 1.10 + 4 * sprache.pause_stueck
    assert dauer(ziel) == pytest.approx(erwartet, abs=0.06)


def test_tempo_angleich_langsames_stueck_wird_gestaucht(tmp_path, sprache):
    stuecke, ton, pfad = _stuecke_mit_ton(
        tmp_path, [2.0] * 5, [10.0, 10.0, 10.0, 10.0, 9.5], [(0, "text")] * 5
    )
    ziel = tmp_path / "k.wav"

    kapitel_ton(stuecke, ton, sprache, pfad, ziel)

    # 9,5 gegen Median 10 = Faktor 0,95 -> Stueck wird 5 % kuerzer.
    assert dauer(ziel) == pytest.approx(4 * 2.0 + 2.0 * 0.95 + 4 * sprache.pause_stueck, abs=0.06)


def test_tempo_angleich_unter_zwei_prozent_nichts(tmp_path, sprache):
    stuecke, ton, pfad = _stuecke_mit_ton(
        tmp_path, [2.0] * 5, [10.0, 10.0, 10.0, 10.0, 10.15], [(0, "text")] * 5
    )
    ziel = tmp_path / "k.wav"

    kapitel_ton(stuecke, ton, sprache, pfad, ziel)

    assert dauer(ziel) == pytest.approx(5 * 2.0 + 4 * sprache.pause_stueck, abs=0.001)


def test_tempo_angleich_aus_bei_null(tmp_path):
    stimme = mache_stimme(tempo_angleich=0.0)
    stuecke, ton, pfad = _stuecke_mit_ton(
        tmp_path, [2.0] * 5, [10.0, 10.0, 10.0, 10.0, 15.0], [(0, "text")] * 5
    )
    ziel = tmp_path / "k.wav"

    kapitel_ton(stuecke, ton, stimme, pfad, ziel)

    assert dauer(ziel) == pytest.approx(5 * 2.0 + 4 * stimme.pause_stueck, abs=0.001)


def test_kapitel_ton_ohne_messwert_bricht_laut(tmp_path, sprache):
    stuecke, ton, pfad = _stuecke_mit_ton(tmp_path, [0.5, 0.5], [10.0] * 2, [(0, "text")] * 2)
    del ton[1]

    with pytest.raises(Mp4Fehler, match="Stueck 1"):
        kapitel_ton(stuecke, ton, sprache, pfad, tmp_path / "k.wav")
    assert not (tmp_path / "k.wav").exists()
    assert not list(tmp_path.glob("*.teil"))


def test_kapitel_ton_ohne_stuecke_bricht(tmp_path, sprache):
    with pytest.raises(Mp4Fehler, match="ohne Stuecke"):
        kapitel_ton([], {}, sprache, lambda s: tmp_path / "x.wav", tmp_path / "k.wav")


def test_kapitel_ton_fehlende_aufnahme_bricht(tmp_path, sprache):
    stuecke, ton, _ = _stuecke_mit_ton(tmp_path, [0.5], [10.0], [(0, "text")])

    with pytest.raises(Mp4Fehler, match="gibtsnicht"):
        kapitel_ton(
            stuecke, ton, sprache, lambda s: tmp_path / "gibtsnicht.wav", tmp_path / "k.wav"
        )


# -- master ---------------------------------------------------------------------------


def test_lautheit_minus_16(tmp_path):
    quelle = schreibe_sinus(tmp_path / "q.wav", 12.0, moduliert=True, pegel=0.02)
    ziel = tmp_path / "m.wav"

    ergebnis = master(quelle, mache_stimme(), ziel)

    assert ergebnis == ziel
    i, _ = lautheit(ziel)
    assert i == pytest.approx(-16.0, abs=0.5)


def test_true_peak(tmp_path):
    # Laute Quelle: ohne Begrenzung laege der Spitzenpegel ueber der Grenze.
    quelle = schreibe_sinus(tmp_path / "q.wav", 12.0, moduliert=True, pegel=0.9)
    ziel = tmp_path / "m.wav"

    master(quelle, mache_stimme(), ziel)

    _, spitze = lautheit(ziel)
    assert spitze <= -1.4


def test_master_format(tmp_path):
    quelle = schreibe_sinus(tmp_path / "q.wav", 6.0, moduliert=True)
    ziel = tmp_path / "m.wav"

    master(quelle, mache_stimme(), ziel)

    strom = ffprobe("-show_streams", str(ziel))["streams"][0]
    assert (strom["codec_name"], strom["sample_rate"], strom["channels"]) == (
        "pcm_s16le",
        "24000",
        1,
    )
    assert sorted(p.name for p in tmp_path.iterdir()) == ["m.wav", "q.wav"]


def test_tempo_wirkt(tmp_path):
    quelle = schreibe_sinus(tmp_path / "q.wav", 10.0, moduliert=True)
    ziel = tmp_path / "m.wav"

    master(quelle, mache_stimme(tempo=0.9), ziel)

    assert dauer(ziel) == pytest.approx(10.0 / 0.9, rel=0.02)


def test_klang_nur_wenn_gesetzt(tmp_path):
    # Zwei gleich laute Toene; der Tiefpass der Stimme muss den hohen aus dem Ergebnis nehmen.
    quelle = schreibe_sinus(tmp_path / "q.wav", 8.0, hz=(200.0, 4000.0))
    ohne, mit = tmp_path / "ohne.wav", tmp_path / "mit.wav"

    master(quelle, mache_stimme(), ohne)
    master(quelle, mache_stimme(klang=("lowpass=f=800",)), mit)

    verhaeltnis_ohne = betrag(lies_werte(ohne), 4000.0) / betrag(lies_werte(ohne), 200.0)
    verhaeltnis_mit = betrag(lies_werte(mit), 4000.0) / betrag(lies_werte(mit), 200.0)
    assert verhaeltnis_ohne == pytest.approx(1.0, abs=0.15)
    assert verhaeltnis_mit < 0.05


def test_tonhoehe_nur_wenn_gesetzt(tmp_path):
    quelle = schreibe_sinus(tmp_path / "q.wav", 8.0, hz=400.0)
    gleich, tiefer = tmp_path / "gleich.wav", tmp_path / "tiefer.wav"

    master(quelle, mache_stimme(), gleich)
    master(quelle, mache_stimme(tonhoehe_ht=-12.0), tiefer)

    assert nulldurchgaenge_hz(gleich) == pytest.approx(400.0, rel=0.02)
    assert nulldurchgaenge_hz(tiefer) == pytest.approx(200.0, rel=0.03)
    assert dauer(tiefer) == pytest.approx(8.0, rel=0.02)


def test_stumme_aufnahme_bricht_laut(tmp_path):
    quelle = schreibe_sinus(tmp_path / "q.wav", 6.0, pegel=0.0)

    with pytest.raises(Mp4Fehler, match="stumm"):
        master(quelle, mache_stimme(), tmp_path / "m.wav")
    assert not (tmp_path / "m.wav").exists()


def test_master_ohne_quelle_bricht_mit_fehler(tmp_path):
    with pytest.raises(Mp4Fehler):
        master(tmp_path / "gibtsnicht.wav", mache_stimme(), tmp_path / "m.wav")


def test_master_unmoegliches_tempo_bricht_mit_ffmpeg_meldung(tmp_path):
    quelle = schreibe_sinus(tmp_path / "q.wav", 6.0, moduliert=True)

    with pytest.raises(Mp4Fehler, match="ffmpeg"):
        master(quelle, mache_stimme(tempo=0.1), tmp_path / "m.wav")
    assert not (tmp_path / "m.wav").exists()


def test_atomar_findet_die_datei_auch_in_anderer_unicode_form(tmp_path, monkeypatch):
    # Programmheft-Probe 24.10.: auf dem NAS legte ffmpeg "à" zerlegt an (NFD), das Umbenennen
    # suchte die zusammengesetzte Form (NFC) und brach ab. Simuliert: die NFC-Form "fehlt".
    import unicodedata

    from mkn_audio import mastern as m

    nfc = unicodedata.normalize("NFC", "Violin-Romantik à la Bruch.m4b")
    nfd = unicodedata.normalize("NFD", nfc)
    echt_exists = os.path.exists
    monkeypatch.setattr(
        m.os.path, "exists", lambda p: echt_exists(p) and unicodedata.is_normalized("NFD", str(p))
    )
    ziel = tmp_path / nfc
    with m.atomar(ziel) as tmp:
        (tmp.parent / unicodedata.normalize("NFD", tmp.name)).write_bytes(b"x")
        if unicodedata.normalize("NFD", tmp.name) != tmp.name:
            assert not m.os.path.exists(tmp)
    assert m.existiert(ziel)
    assert [p.name for p in tmp_path.iterdir()] == [nfd]
