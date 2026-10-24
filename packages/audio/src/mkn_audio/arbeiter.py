"""Arbeiter-Prozess: Sprechen, Messen, Hoeren -- eigenstaendig, ohne Import aus `mkn_audio`.

**Warum eigenstaendig.** Dieses Skript laeuft unter einem FREMDEN Python 3.11 (eigene
Umgebung mit Chatterbox, torch, librosa, faster-whisper), in der das Paket nicht
installiert ist. Es kennt darum nur die Standardbibliothek; alles Schwere wird erst
beim ersten Gebrauch importiert, damit `miss` und `vorlage` nicht das Sprachmodell laden.

**Protokoll.** Eine JSON-Zeile auf stdin, eine JSON-Zeile auf stdout, eine Anfrage nach
der anderen. Fehler kommen als `{"fehler": "..."}` zurueck und beenden den Arbeiter nicht;
Einzelheiten stehen auf stderr. Befehle: `sprich`, `miss`, `hoere`, `vorlage` (Felder:
siehe die gleichnamigen Funktionen unten).

**Warum stdout umgeleitet wird.** Bibliotheken schreiben gern mit `print` auf stdout und
wuerden das Protokoll zerreissen. Die echte Leitung wird deshalb gleich beim Start
gesichert, `sys.stdout` zeigt danach auf stderr.

`--schein` ersetzt Chatterbox und Whisper durch ein Ersatzmodell (Sinus-Ton), das nur die
Standardbibliothek braucht: Tests pruefen so das Protokoll und die Regeln ohne Stimm-Software.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import subprocess
import sys
import traceback
import wave
from array import array
from collections.abc import Callable
from pathlib import Path
from typing import Any

SAMPLERATE = 24_000
"""Alle Aufnahmen dieses Pakets: 24 kHz, mono, PCM16 -- wie das Modell sie liefert."""

VERSUCHE = 3
ZEICHEN_JE_S = 14.0
MIN_ANTEIL = 0.55
"""3-Versuche-Regel aus dem Prototyp: Chatterbox bricht bei erkannter Wiederholung ab und
liefert dann ein zu kurzes Stueck. Unter 55 % der erwarteten Dauer (Zeichen / 14 je s) wird
neu gesprochen, nach drei Versuchen gewinnt das laengste."""


# -- Gemeinsames: Pfade, Schreiben ----------------------------------------------------


def _atomar(ziel: Path, schreibe: Callable[[Path], None]) -> None:
    """Schreibt erst nach `<ziel>.tmp`, sichert auf die Platte, benennt dann um.

    Bricht das Schreiben ab (Fehler, Neustart, Strom), liegt nie eine halbe Datei unter
    dem Zielnamen: die Wiederaufnahme haelt jede vorhandene Zieldatei fuer fertig.
    """
    tmp = ziel.with_name(ziel.name + ".tmp")
    try:
        schreibe(tmp)
        with open(tmp, "rb") as datei:
            os.fsync(datei.fileno())
        os.replace(tmp, ziel)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _datei(anfrage: dict[str, Any], feld: str, name: str) -> Path:
    """Liest ein Pfadfeld und besteht darauf, dass die Datei da ist."""
    pfad = Path(_feld(anfrage, feld, str))
    if not pfad.is_file():
        raise FileNotFoundError(f"{name} fehlt: {pfad}")
    return pfad


def _feld(anfrage: dict[str, Any], feld: str, typ: type) -> Any:
    if feld not in anfrage:
        raise ValueError(f"Feld '{feld}' fehlt")
    wert = anfrage[feld]
    if typ is float and isinstance(wert, int | float) and not isinstance(wert, bool):
        return float(wert)
    if not isinstance(wert, typ):
        raise ValueError(f"Feld '{feld}' hat den falschen Typ ({type(wert).__name__})")
    return wert


# -- Werk: Schein ---------------------------------------------------------------------


class ScheinWerk:
    """Ersatzmodell nur mit Standardbibliothek: Sinus-Ton statt Stimme.

    Aufnahmen sind `array('h')` (PCM16). `dauern` sind Anteile der erwarteten Dauer, die
    reihum je Sprech-Versuch gelten -- so lassen sich zu kurze Versuche herstellen. Die
    Messwerte von `miss` sind feste Platzhalter (nur die Dauer ist echt).
    """

    def __init__(self, dauern: list[float] | None = None) -> None:
        self._dauern = dauern or [1.0]
        self._aufrufe = 0

    def _sinus(self, sekunden: float) -> array:
        n = round(sekunden * SAMPLERATE)
        return array(
            "h", (int(8000 * math.sin(2 * math.pi * 220 * i / SAMPLERATE)) for i in range(n))
        )

    def erzeuge(self, text: str, **_ignoriert: Any) -> array:
        anteil = self._dauern[self._aufrufe % len(self._dauern)]
        self._aufrufe += 1
        return self._sinus(len(text) / ZEICHEN_JE_S * anteil)

    def dauer(self, w: array) -> float:
        return len(w) / SAMPLERATE

    def kern_dauer(self, w: array) -> float:
        return self.dauer(w)

    def kuerzen(self, w: array) -> array:
        return w

    def schreibe(self, w: array, pfad: Path) -> None:
        with wave.open(str(pfad), "wb") as datei:
            datei.setnchannels(1)
            datei.setsampwidth(2)
            datei.setframerate(SAMPLERATE)
            datei.writeframes(w.tobytes())

    def miss(self, wav: Path) -> dict[str, float]:
        with wave.open(str(wav), "rb") as datei:
            dauer = datei.getnframes() / datei.getframerate()
        return {"f0_median": 120.0, "streuung_ht": 3.0, "pause_anteil": 0.0, "dauer": dauer}

    def hoere(self, wav: Path, sprache: str) -> str:
        return "schein"

    def vorlage(self, aufnahme: Path, ziel: Path, dauer: float) -> dict[str, float]:
        _atomar(ziel, lambda tmp: self.schreibe(self._sinus(dauer), tmp))
        return {"start": 0.0, "streuung_ht": 3.0}


# -- Werk: echt -----------------------------------------------------------------------


class EchtesWerk:
    """Chatterbox, librosa und faster-whisper -- jedes erst beim ersten Gebrauch geladen."""

    def __init__(self, whisper_modell: str) -> None:
        self._whisper_modell = whisper_modell
        self._tts: Any = None
        self._whisper: Any = None

    def _modell(self) -> Any:
        if self._tts is None:
            import torch
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS

            geraet = "mps" if torch.backends.mps.is_available() else "cpu"
            tts = ChatterboxMultilingualTTS.from_pretrained(device=geraet)
            if tts.sr != SAMPLERATE:
                raise RuntimeError(f"Modell liefert {tts.sr} Hz statt {SAMPLERATE} Hz")
            self._tts = tts
        return self._tts

    def erzeuge(
        self,
        text: str,
        *,
        sprache: str,
        vorlage: Path,
        exaggeration: float,
        cfg_weight: float,
        temperature: float,
    ) -> Any:
        import torch

        modell = self._modell()
        with torch.inference_mode():
            ausgabe = modell.generate(
                text,
                language_id=sprache,
                audio_prompt_path=str(vorlage),
                exaggeration=exaggeration,
                cfg_weight=cfg_weight,
                temperature=temperature,
            )
        w = ausgabe.squeeze().cpu().numpy().astype("float32")
        del ausgabe
        # Zwischenspeicher des Geraets nach jedem Stueck freigeben: ohne das waechst er auf MPS
        # ueber Hunderte Stuecke bis zum Abbruch (siehe arbeiter_client, neustart_nach).
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        return w

    def dauer(self, w: Any) -> float:
        return len(w) / SAMPLERATE

    def kern_dauer(self, w: Any) -> float:
        import librosa

        kern, _ = librosa.effects.trim(w, top_db=35)
        return len(kern) / SAMPLERATE

    def kuerzen(self, w: Any) -> Any:
        """Pausen im Stueck ueber 0,2 s stauchen: g -> 0,2 + 0,6*(g-0,2), hoechstens 0,6 s.

        Die Reihenfolge der Pausenlaengen bleibt erhalten (Rhythmus), nur der Abstand
        schrumpft. Anfang und Ende der Aufnahme werden dabei auf die Sprache beschnitten.
        """
        import librosa
        import numpy as np

        iv = librosa.effects.split(w, top_db=40, frame_length=1024, hop_length=256)
        if len(iv) < 2:
            return w
        aus = [w[iv[0][0] : iv[0][1]]]
        for (_, a1), (b0, b1) in itertools.pairwise(iv):
            luecke = (b0 - a1) / SAMPLERATE
            neu = luecke if luecke <= 0.2 else min(0.2 + 0.6 * (luecke - 0.2), 0.6)
            aus += [np.zeros(int(neu * SAMPLERATE), dtype=w.dtype), w[b0:b1]]
        return np.concatenate(aus)

    def schreibe(self, w: Any, pfad: Path) -> None:
        import soundfile as sf

        sf.write(str(pfad), w, SAMPLERATE, subtype="PCM_16", format="WAV")

    def miss(self, wav: Path) -> dict[str, float]:
        """Tonlage und Streuung wie die Prosodie-Messung der Stimmfindung.

        F0 per pyin (65-400 Hz), nur stimmhafte Frames; Streuung in Halbtoenen (damit
        Mann und Frau vergleichbar sind), robust: Spruenge ueber 8 HT fliegen raus, dann
        IQR / 1,349. Pausenanteil = Anteil unter -40 dB.
        """
        import librosa
        import numpy as np

        y, sr = librosa.load(str(wav), sr=16000, mono=True)
        f0, stimmhaft, _ = librosa.pyin(y, fmin=65, fmax=400, sr=sr, frame_length=1024)
        f0 = f0[stimmhaft & ~np.isnan(f0)]
        if len(f0) == 0:
            raise ValueError(f"keine stimmhaften Frames in {wav}")
        ht = 12 * np.log2(f0 / np.median(f0))
        ht = ht[np.abs(ht) < 8]
        q1, q3 = np.percentile(ht, [25, 75])
        sprech = sum(b - a for a, b in librosa.effects.split(y, top_db=40)) / len(y)
        return {
            "f0_median": float(np.median(f0)),
            "streuung_ht": float((q3 - q1) / 1.349),
            "pause_anteil": float(1 - sprech),
            "dauer": float(len(y) / sr),
        }

    def hoere(self, wav: Path, sprache: str) -> str:
        if self._whisper is None:
            from faster_whisper import WhisperModel

            self._whisper = WhisperModel(self._whisper_modell, device="cpu", compute_type="int8")
        stuecke, _ = self._whisper.transcribe(str(wav), language=sprache, beam_size=5)
        return " ".join(s.text.strip() for s in stuecke).strip()

    def vorlage(self, aufnahme: Path, ziel: Path, dauer: float) -> dict[str, float]:
        """Sucht das Fenster mit der hoechsten Tonhoehen-Streuung bei wenig Pause.

        Eine Vorlage mit lebendiger Betonung macht die ganze Stimme lebendiger. Fenster
        schreiten in 6-s-Schritten; zugelassen sind nur Fenster mit Pausenanteil <= 15 %.
        """
        import librosa
        import numpy as np

        y, sr = librosa.load(str(aufnahme), sr=16000, mono=True)
        hop = 320
        f0, stimmhaft, _ = librosa.pyin(
            y, fmin=65, fmax=300, sr=sr, frame_length=1024, hop_length=hop
        )
        zeit = librosa.times_like(f0, sr=sr, hop_length=hop)
        rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=hop)[0][: len(f0)]
        mindest_frames = max(20, int(200 * dauer / 24))
        beste: tuple[float, float] | None = None
        for start in np.arange(0, len(y) / sr - dauer, 6.0):
            im_fenster = (zeit >= start) & (zeit < start + dauer)
            f = f0[im_fenster & stimmhaft & ~np.isnan(f0)]
            if len(f) < mindest_frames:
                continue
            if float(np.mean(rms[im_fenster] < 0.01)) > 0.15:
                continue
            ht = 12 * np.log2(f / np.median(f))
            ht = ht[np.abs(ht) < 8]
            q1, q3 = np.percentile(ht, [25, 75])
            streuung = float((q3 - q1) / 1.349)
            if beste is None or streuung > beste[0]:
                beste = (streuung, float(start))
        if beste is None:
            raise ValueError(f"kein Fenster von {dauer:g} s mit Pausenanteil <= 15 % in {aufnahme}")
        streuung, start = beste

        def schneide(tmp: Path) -> None:
            lauf = subprocess.run(
                [
                    "ffmpeg", "-loglevel", "error", "-y",
                    "-ss", f"{start:.2f}", "-t", f"{dauer:g}", "-i", str(aufnahme),
                    "-af", "highpass=f=70,loudnorm=I=-18:TP=-1.5:LRA=11",
                    "-ac", "1", "-ar", str(SAMPLERATE), "-c:a", "pcm_s16le", "-f", "wav", str(tmp),
                ],
                capture_output=True,
                text=True,
                check=False,
            )  # fmt: skip
            if lauf.returncode != 0:
                raise RuntimeError(f"ffmpeg schnitt die Vorlage nicht: {lauf.stderr.strip()}")

        _atomar(ziel, schneide)
        return {"start": start, "streuung_ht": streuung}


# -- Befehle --------------------------------------------------------------------------


def sprich(werk: Any, anfrage: dict[str, Any]) -> dict[str, Any]:
    """`sprich`: Text -> WAV (PCM16, 24 kHz, mono, atomar) mit der 3-Versuche-Regel.

    Die Sprechrate (Zeichen je Sekunde nach dem Beschneiden von Stille an den Enden)
    wird VOR dem Pausenkuerzen gemessen: sie beschreibt, wie schnell die Stimme
    gesprochen hat, nicht wie dicht das Stueck danach gepackt ist.
    """
    text = _feld(anfrage, "text", str).strip()
    if not text:
        raise ValueError("Text ist leer")
    parameter = {
        "sprache": _feld(anfrage, "sprache", str),
        "vorlage": _datei(anfrage, "vorlage", "Vorlage"),
        "exaggeration": _feld(anfrage, "exaggeration", float),
        "cfg_weight": _feld(anfrage, "cfg_weight", float),
        "temperature": _feld(anfrage, "temperature", float),
    }
    ziel = Path(_feld(anfrage, "ziel", str))
    erwartet = len(text) / ZEICHEN_JE_S
    beste = None
    versuche = 0
    while versuche < VERSUCHE:
        versuche += 1
        w = werk.erzeuge(text, **parameter)
        if beste is None or werk.dauer(w) > werk.dauer(beste):
            beste = w
        if werk.dauer(beste) >= MIN_ANTEIL * erwartet:
            break
    zu_kurz = werk.dauer(beste) < MIN_ANTEIL * erwartet
    if zu_kurz:
        print(
            f"nach {VERSUCHE} Versuchen zu kurz"
            f" ({werk.dauer(beste):.1f} s statt ~{erwartet:.0f} s): {text[:60]}",
            file=sys.stderr,
            flush=True,
        )
    rate = len(text) / max(werk.kern_dauer(beste), 0.3)
    if anfrage.get("pausen_kuerzen", True):
        beste = werk.kuerzen(beste)
    _atomar(ziel, lambda tmp: werk.schreibe(beste, tmp))
    return {
        "dauer": round(werk.dauer(beste), 3),
        "sprechrate": round(rate, 3),
        "versuche": versuche,
        "zu_kurz": zu_kurz,
    }


def miss(werk: Any, anfrage: dict[str, Any]) -> dict[str, Any]:
    """`miss`: `{"wav"}` -> Tonlage (Hz), Streuung (HT), Pausenanteil, Dauer."""
    return werk.miss(_datei(anfrage, "wav", "Aufnahme"))


def hoere(werk: Any, anfrage: dict[str, Any]) -> dict[str, Any]:
    """`hoere`: `{"wav", "sprache"}` -> `{"text"}`."""
    return {"text": werk.hoere(_datei(anfrage, "wav", "Aufnahme"), _feld(anfrage, "sprache", str))}


def vorlage(werk: Any, anfrage: dict[str, Any]) -> dict[str, Any]:
    """`vorlage`: `{"aufnahme", "ziel", "dauer"}` -> Start und Streuung des gewaehlten Fensters."""
    dauer = _feld(anfrage, "dauer", float)
    if dauer <= 0:
        raise ValueError("dauer muss positiv sein")
    aufnahme = _datei(anfrage, "aufnahme", "Aufnahme")
    return werk.vorlage(aufnahme, Path(_feld(anfrage, "ziel", str)), dauer)


BEFEHLE: dict[str, Callable[[Any, dict[str, Any]], dict[str, Any]]] = {
    "sprich": sprich,
    "miss": miss,
    "hoere": hoere,
    "vorlage": vorlage,
}


def behandle(werk: Any, anfrage: Any) -> dict[str, Any]:
    if not isinstance(anfrage, dict):
        raise ValueError("Anfrage ist kein JSON-Objekt")
    befehl = anfrage.get("befehl")
    if befehl not in BEFEHLE:
        raise ValueError(f"unbekannter Befehl {befehl!r}; bekannt: {', '.join(BEFEHLE)}")
    return BEFEHLE[befehl](werk, anfrage)


def haupt(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Arbeiter: Sprechen, Messen, Hoeren")
    parser.add_argument("--whisper", default="small", help="Whisper-Modell fuer `hoere`")
    parser.add_argument(
        "--schein", action="store_true", help="Ersatzmodell statt Chatterbox/Whisper"
    )
    parser.add_argument(
        "--schein-dauern",
        default="1.0",
        help="nur mit --schein: Anteile der erwarteten Dauer je Sprech-Versuch, reihum",
    )
    args = parser.parse_args(argv)

    leitung = sys.stdout
    sys.stdout = sys.stderr  # Bibliotheken duerfen das Protokoll nicht zerreissen
    if args.schein:
        werk: Any = ScheinWerk([float(x) for x in args.schein_dauern.split(",")])
    else:
        werk = EchtesWerk(args.whisper)

    for zeile in sys.stdin:
        if not zeile.strip():
            continue
        try:
            antwort = behandle(werk, json.loads(zeile))
            text = json.dumps(antwort, allow_nan=False)
        except Exception as fehler:  # jede Ursache geht als Fehlerantwort an den Auftraggeber
            traceback.print_exc()
            text = json.dumps({"fehler": f"{type(fehler).__name__}: {fehler}"})
        leitung.write(text + "\n")
        leitung.flush()
    return 0


if __name__ == "__main__":
    sys.exit(haupt())
