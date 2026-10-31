"""Mastern: aus gesprochenen Stuecken ein Kapitel-Ton, dann Klang, Tempo und Lautheit.

**Zwei Schritte, zwei Gruende.** `kapitel_ton` setzt die Stuecke eines Kapitels mit ihren
Pausen zusammen und gleicht dabei das Sprechtempo je Stueck an: die Stimme spricht nicht
jeden Satz gleich schnell, und ein Hoerer merkt das Schwanken staerker als ein
gleichmaessig etwas zu schnelles Tempo. `master` bearbeitet dann das ganze Kapitel
(Klang, Gesamttempo, Tonhoehe, Lautheit): erst nach dem Zusammensetzen, weil die
Lautheit eine Eigenschaft des Ganzen ist -- ein Stueck fuer sich haette keine.

**Streamen statt laden.** Ein Kapitel kann Stunden dauern. Die WAVs werden stueckweise
gelesen und geschrieben, nie als Ganzes in den Speicher geholt; numpy braucht das
Paket dafuer nicht (der Arbeiter hat es, das Paket soll ohne ihn installierbar sein).

**Fehler brechen laut.** Jede Werkzeug-Ausfuehrung laeuft ueber `fuehre_aus`: Zeitgrenze,
Rueckgabewert und stderr-Auszug werden zu einem `Mp4Fehler`. Ausgaben entstehen atomar
(`atomar`): eine halbe Datei gilt nie als fertig.

Dieses Modul haelt auch die kleinen Helfer, die `verpacken` mitnutzt (`fuehre_aus`,
`atomar`, `wav_info`, `schreibe_stille`), damit es keinen dritten Ort fuer sie gibt.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import re
import statistics
import subprocess
import tempfile
import unicodedata
import wave
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from mkn_audio.stimmen import Stimme
from mkn_audio.typen import Mp4Fehler, Stueck

SAMPLERATE = 24_000
"""Alle Aufnahmen dieses Pakets: 24 kHz, mono, PCM16 (so liefert sie der Arbeiter)."""

LAUTHEIT = "I=-16:TP=-1.5:LRA=11"
"""Ziel der Lautheitsnormierung: -16 LUFS, True Peak -1,5 dB, LRA 11 (Spec 6)."""

_MIN_ABWEICHUNG = 0.02
"""Unter 2 % Abweichung vom Median wird ein Stueck nicht angefasst: der Eingriff
(Zeitdehnung) kostet mehr Klangqualitaet, als der Unterschied stoert."""

_MIN_STUECKE = 4
"""Erst ab dem vierten Stueck gibt es einen Median, der etwas aussagt."""

_STDERR_ENDE = 2000
"""Wie viele Zeichen vom Ende der stderr-Ausgabe in eine Fehlermeldung kommen."""

_STUMM_LUFS = -70.0
"""Unter dieser Lautheit ist nichts zu hoeren (absolutes Gate nach EBU R 128)."""

_BLOCK = 1 << 20
"""So viele Bytes werden je Schritt zwischen WAV-Dateien kopiert."""


# -- Werkzeuge ------------------------------------------------------------------------


def zeitgrenze(dauer_s: float) -> float:
    """Zeitgrenze fuer ein Werkzeug, das Audio von `dauer_s` Sekunden bearbeitet.

    Grosszuegig (mindestens 20-fach langsamer als gemessen), weil eine zu knappe Grenze
    einen langen Lauf kurz vor dem Ende abbricht; sie soll nur ein Haengen finden.
    """
    return max(300.0, 120.0 + dauer_s / 5)


def fuehre_aus(
    befehl: Sequence[str | Path],
    *,
    zeit_s: float,
    eingabe: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Fuehrt ein Werkzeug aus; jeder Misserfolg wird ein `Mp4Fehler` mit stderr-Auszug."""
    name = Path(befehl[0]).name
    try:
        lauf = subprocess.run(
            [str(teil) for teil in befehl],
            input=eingabe,
            capture_output=True,
            timeout=zeit_s,
            check=False,
        )
    except FileNotFoundError:
        raise Mp4Fehler(f"{name} nicht gefunden (ist es installiert und im PATH?)") from None
    except subprocess.TimeoutExpired:
        raise Mp4Fehler(f"{name} nach {zeit_s:.0f} s abgebrochen (Zeitgrenze)") from None
    if lauf.returncode != 0:
        ende = lauf.stderr.decode("utf-8", "replace").strip()[-_STDERR_ENDE:]
        raise Mp4Fehler(f"{name} endete mit Code {lauf.returncode}: {ende}")
    return lauf


def ffmpeg(*argumente: str | int | Path, zeit_s: float, eingabe: bytes | None = None):
    """ffmpeg mit festen Vorgaben: kein Nachfragen (`-nostdin`), `-y`, nur Fehler laut."""
    return fuehre_aus(
        ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *argumente],
        zeit_s=zeit_s,
        eingabe=eingabe,
    )


def _gefunden(pfad: Path) -> Path | None:
    """`pfad` oder der Eintrag gleichen Namens in anderer Unicode-Form, sonst `None`.

    Ein NAS-Laufwerk am Mac unterscheidet zerlegte (NFD) und zusammengesetzte (NFC) Namen:
    ffmpeg legt "à" zerlegt an, Python sucht es zusammengesetzt -- und findet nichts.
    """
    if os.path.exists(pfad):
        return pfad
    try:
        eintraege = os.listdir(pfad.parent)
    except FileNotFoundError:
        return None
    soll = unicodedata.normalize("NFC", pfad.name)
    for eintrag in eintraege:
        if unicodedata.normalize("NFC", eintrag) == soll:
            return pfad.parent / eintrag
    return None


def existiert(pfad: Path) -> bool:
    """Ob es `pfad` gibt, gleich in welcher Unicode-Form der Name angelegt wurde."""
    return _gefunden(pfad) is not None


@contextlib.contextmanager
def atomar(ziel: Path) -> Iterator[Path]:
    """Gibt einen Schreibpfad neben `ziel`; erst bei Erfolg wird er zu `ziel`.

    Bei einer Ausnahme verschwindet der halbe Rest, `ziel` bleibt unberuehrt. Der
    Schreibpfad liegt im selben Ordner, damit das Umbenennen atomar ist (gleiches
    Dateisystem).
    """
    ziel.parent.mkdir(parents=True, exist_ok=True)
    tmp = ziel.with_name(ziel.name + ".teil")
    try:
        yield tmp
        echt = _gefunden(tmp) or tmp
        if echt.name != tmp.name:  # in der Form des Schreibers umbenennen, sonst ein zweiter Name
            form = "NFD" if unicodedata.is_normalized("NFD", echt.name) else "NFC"
            ziel = ziel.with_name(unicodedata.normalize(form, ziel.name))
        os.replace(echt, ziel)
    except BaseException:
        (_gefunden(tmp) or tmp).unlink(missing_ok=True)
        raise


def temp_ordner(verzeichnis: Path) -> tempfile.TemporaryDirectory[str]:
    """Arbeitsordner in `verzeichnis`: Zwischenstufen von Stunden Audio gehoeren auf das
    Laufwerk der Ausgabe, nicht in ein knappes System-Temp."""
    verzeichnis.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=verzeichnis, prefix=".mkn-mp4-")


# -- WAV-Helfer (stdlib, keine numpy-Abhaengigkeit) -----------------------------------


def wav_info(pfad: Path) -> tuple[int, int, int, int]:
    """(Abtastrate, Kanaele, Bytes je Wert, Frames) einer PCM-WAV; sonst `Mp4Fehler`."""
    try:
        with wave.open(str(pfad), "rb") as w:
            return w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
    except (OSError, EOFError, wave.Error) as ursache:
        raise Mp4Fehler(f"Aufnahme nicht lesbar: {pfad.name} ({ursache})") from ursache


def pruefe_format(pfad: Path) -> int:
    """Stellt sicher: 24 kHz, mono, PCM16. Gibt die Frames zurueck."""
    rate, kanaele, breite, frames = wav_info(pfad)
    if (rate, kanaele, breite) != (SAMPLERATE, 1, 2):
        raise Mp4Fehler(
            f"{pfad.name}: erwartet {SAMPLERATE} Hz, mono, PCM16 -- "
            f"ist {rate} Hz, {kanaele} Kanal/Kanaele, {breite * 8} Bit"
        )
    return frames


def schreibe_stille(ausgabe: wave.Wave_write, sekunden: float) -> None:
    """Haengt `sekunden` Stille (PCM16, mono, 24 kHz) an eine offene WAV."""
    ausgabe.writeframes(b"\x00\x00" * round(sekunden * SAMPLERATE))


def _lies_alles(pfad: Path) -> bytes:
    pruefe_format(pfad)
    with wave.open(str(pfad), "rb") as w:
        return w.readframes(w.getnframes())


# -- Kapitel-Ton ----------------------------------------------------------------------


def _pause_nach(stueck: Stueck, folgendes: Stueck, stimme: Stimme) -> float:
    """Pause hinter `stueck`: nach der Ueberschrift die laengere, im Absatz die kurze.

    Reihenfolge: nach einer Zwischenueberschrift `pause_nach_ueberschrift`, vor einer
    `pause_vor_ueberschrift` (ein Satz derselben Ueberschrift bleibt `pause_stueck`), nach dem
    Kapiteltitel `pause_titel`, beim Absatzwechsel `pause_absatz`, sonst `pause_stueck`.
    """
    gleiche_ueberschrift = stueck.art == folgendes.art == "ueberschrift" and (
        stueck.absatz == folgendes.absatz
    )
    if stueck.art == "ueberschrift" and not gleiche_ueberschrift:
        return stimme.pause_nach_ueberschrift
    if folgendes.art == "ueberschrift" and not gleiche_ueberschrift:
        return stimme.pause_vor_ueberschrift
    if stueck.art == "titel":
        return stimme.pause_titel
    if folgendes.absatz == stueck.absatz:
        return stimme.pause_stueck
    return stimme.pause_absatz


def _angleich_faktor(raten: list[float], spielraum: float) -> float | None:
    """Faktor, um den das letzte Stueck gegen den laufenden Median zu schnell war.

    `None`: nichts tun (zu wenige Stuecke, Angleich aus, oder unter 2 % Abweichung).
    Der Faktor ist auf `1 +- spielraum` begrenzt: ein Ausreisser (Stueck mit
    Sprechpause oder Fehlmessung) darf nicht zu einer hoerbaren Verzerrung fuehren.
    """
    if spielraum <= 0 or len(raten) < _MIN_STUECKE:
        return None
    faktor = raten[-1] / statistics.median(raten)
    faktor = min(max(faktor, 1 - spielraum), 1 + spielraum)
    return None if abs(faktor - 1) < _MIN_ABWEICHUNG else faktor


def _atempo(daten: bytes, tempo: float) -> bytes:
    """Zeitdehnung eines PCM16-Stuecks per ffmpeg `atempo` (Tonhoehe bleibt)."""
    lauf = ffmpeg(
        *("-f", "s16le", "-ar", str(SAMPLERATE), "-ac", "1", "-i", "-"),
        *("-af", f"atempo={tempo:.4f}", "-f", "s16le", "-"),
        zeit_s=120,
        eingabe=daten,
    )
    return lauf.stdout


class _HatNr(Protocol):
    """Was `kapitel_ton` von einer Einheit braucht: die Nummer, unter der ihr Ton liegt."""

    @property
    def nr(self) -> int: ...


def _rate(ton: Mapping[int, dict[str, Any]], stueck: _HatNr) -> float:
    try:
        rate = float(ton[stueck.nr]["sprechrate"])
    except (KeyError, TypeError, ValueError):
        raise Mp4Fehler(f"kein Messwert 'sprechrate' fuer Stueck {stueck.nr}") from None
    if not math.isfinite(rate) or rate <= 0:
        raise Mp4Fehler(f"Stueck {stueck.nr}: unbrauchbare Sprechrate {rate}")
    return rate


def kapitel_ton[E: _HatNr](
    stuecke: Sequence[E],
    ton: Mapping[int, dict[str, Any]],
    stimme: Stimme,
    wav_pfad: Callable[[E], Path],
    ziel: Path,
    *,
    pause_nach: Callable[[E, E], float] | None = None,
) -> Path:
    """Setzt die Einheiten EINES Kapitels zu einer WAV zusammen (PCM16, 24 kHz, mono).

    Einheit ist ein `Stueck` (Pausen: `_pause_nach`) oder ein Block des Sprechers; fuer
    Bloecke nennt der Aufrufer die Pause (`pause_nach`: Pause hinter dem letzten Stueck des
    ersten gegenueber dem ersten des folgenden). Je Einheit wird das Tempo gegen den laufenden
    Median der Sprechraten angeglichen (`stimme.tempo_angleich`, siehe `_angleich_faktor`).
    Nach der letzten Einheit folgt keine Pause -- die Kapitelpause setzt `m4b` dazwischen.
    """
    if not stuecke:
        raise Mp4Fehler("Kapitel ohne Stuecke kann nicht zusammengesetzt werden")
    raten: list[float] = []
    with atomar(ziel) as tmp, wave.open(str(tmp), "wb") as aus:
        aus.setnchannels(1)
        aus.setsampwidth(2)
        aus.setframerate(SAMPLERATE)
        for i, stueck in enumerate(stuecke):
            raten.append(_rate(ton, stueck))
            daten = _lies_alles(wav_pfad(stueck))
            faktor = _angleich_faktor(raten, stimme.tempo_angleich)
            if faktor is not None:
                # War das Stueck schneller als der Median (faktor > 1), wird es gestreckt.
                daten = _atempo(daten, 1 / faktor)
            aus.writeframes(daten)
            if i + 1 < len(stuecke):
                folgt = stuecke[i + 1]
                pause = (
                    pause_nach(stueck, folgt)
                    if pause_nach is not None
                    else _pause_nach(stueck, folgt, stimme)  # type: ignore[arg-type]
                )
                schreibe_stille(aus, pause)
    return ziel


# -- Master ---------------------------------------------------------------------------


def _messung(wav: Path, zeit_s: float) -> dict[str, str]:
    """Erste loudnorm-Runde: misst Lautheit, Spitze, Umfang und Schwelle."""
    lauf = fuehre_aus(
        ["ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-i", wav, "-af",
         f"loudnorm={LAUTHEIT}:print_format=json", "-f", "null", "-"],
        zeit_s=zeit_s,
    )  # fmt: skip
    text = lauf.stderr.decode("utf-8", "replace")
    bloecke = re.findall(r"\{[^{}]*\}", text)
    if not bloecke:
        raise Mp4Fehler(f"loudnorm lieferte keine Messung: {text.strip()[-_STDERR_ENDE:]}")
    try:
        messung = json.loads(bloecke[-1])
        for schluessel in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
            float(messung[schluessel])
    except (ValueError, KeyError) as ursache:
        raise Mp4Fehler(f"loudnorm-Messung unlesbar: {bloecke[-1]}") from ursache
    return messung


def master(wav: Path, stimme: Stimme, ziel: Path) -> Path:
    """Klang, Gesamttempo, Tonhoehe und Lautheit; Ergebnis WAV (PCM16, 24 kHz, mono).

    Reihenfolge: `stimme.klang` (in der Reihenfolge der Tabelle, nur wenn gesetzt),
    `atempo`, die Tonhoehe per `rubberband` (nur wenn `tonhoehe_ht != 0`; ffmpeg hat
    keinen Formant-erhaltenden Tonhoehen-Filter), dann `loudnorm` in zwei Laeufen:
    erst messen, dann mit den Messwerten und `linear=true` anwenden -- die einlaeufige
    Fassung regelt die Lautstaerke laufend nach und laesst sie pumpen.
    """
    dauer_s = pruefe_format(wav) / SAMPLERATE
    zeit_s = zeitgrenze(dauer_s)
    kette = [*stimme.klang, f"atempo={stimme.tempo:.4f}"]
    with temp_ordner(ziel.parent) as werk_name:
        werk = Path(werk_name)
        stufe = werk / "stufe1.wav"
        ffmpeg(
            *("-i", wav, "-af", ",".join(kette)),
            *("-ac", 1, "-ar", SAMPLERATE, "-c:a", "pcm_s16le", stufe),
            zeit_s=zeit_s,
        )
        if stimme.tonhoehe_ht != 0:
            tiefer = werk / "stufe2.wav"
            fuehre_aus(
                ["rubberband", "-3", "-F", "-p", f"{stimme.tonhoehe_ht:g}", stufe, tiefer],
                zeit_s=zeit_s,
            )
            stufe = tiefer
        m = _messung(stufe, zeit_s)
        if float(m["input_i"]) <= _STUMM_LUFS:  # auch "-inf"
            raise Mp4Fehler(f"{wav.name} ist stumm (Lautheit {m['input_i']} LUFS)")
        norm = (
            f"loudnorm={LAUTHEIT}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
            f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
            f":offset={m['target_offset']}:linear=true"
        )
        with atomar(ziel) as tmp:
            ffmpeg(
                *("-i", stufe, "-af", norm),
                *("-ac", 1, "-ar", SAMPLERATE, "-c:a", "pcm_s16le", "-f", "wav", tmp),
                zeit_s=zeit_s,
            )
    return ziel
