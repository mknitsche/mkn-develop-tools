"""Schein-Google fuer die Tests: ein Transport wie die Interactions API, ohne Netz.

**Warum ein eigener Transport.** Kein Test braucht Netz oder Schluessel (Plan, Global
Constraints). `SprecherGemini` spricht ueber `mkn_kern.anfrage.sende` mit einem
einspeisbaren `Transport` -- `(url, koerper, kopf, zeitgrenze) -> (status, bytes)`. Dieser
Schein antwortet wie die Interactions API, **zeichnet jeden Rumpf auf** (die Zusicherungen
der Tests haengen am gesehenen Rumpf, nicht an einer Bauanleitung) und laesst sich je Test
mit einer `regel` zu Sperren, Limits und Fehlerantworten bringen.

Ohne Regel antwortet er mit Ton (Sinus, PCM 16 bit mono 24 kHz) der Dauer
`len(text) / zeichen_je_s` -- so ist die Sprechrate jedes Blocks bekannt.
"""

from __future__ import annotations

import base64
import io
import json
import math
import threading
import time
import wave
from array import array
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mkn_audio.stimmen import Stimme

RATE = 24_000
PCM_MIME = "audio/L16;codec=pcm;rate=24000"
MODELL = "gemini-test-tts"

Antwort = tuple[int, bytes]
Regel = Callable[[int, dict[str, Any]], "Antwort | BaseException | float | None"]


def pcm(sekunden: float, *, stumm: bool = False, rate: int = RATE) -> bytes:
    """Kopfloses PCM 16 bit LE mono: Sinus oder Stille."""
    n = round(sekunden * rate)
    if stumm:
        return bytes(2 * n)
    return array(
        "h", (int(8000 * math.sin(2 * math.pi * 220 * i / rate)) for i in range(n))
    ).tobytes()


def wav_bytes(sekunden: float, *, stumm: bool = False, rate: int = RATE) -> bytes:
    """Eine RIFF-WAV (16 bit mono) als Bytes."""
    puffer = io.BytesIO()
    with wave.open(puffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm(sekunden, stumm=stumm, rate=rate))
    return puffer.getvalue()


def audio_antwort(
    daten: bytes, *, mime: str = PCM_MIME, nutzung: dict[str, Any] | None = None
) -> Antwort:
    """Eine Antwort mit Ton im letzten `steps[].content[]`-Eintrag (`type == "audio"`)."""
    koerper: dict[str, Any] = {
        "steps": [
            {
                "content": [
                    {"type": "audio", "data": base64.b64encode(daten).decode(), "mime_type": mime}
                ]
            }
        ]
    }
    if nutzung is not None:
        koerper["usage"] = nutzung
    return 200, json.dumps(koerper).encode()


def ohne_audio() -> Antwort:
    """Status 200, aber kein Audio-Eintrag: eine Fehlerantwort fuer den Sprecher."""
    return 200, json.dumps(
        {"steps": [{"content": [{"type": "text", "text": "kein Ton"}]}]}
    ).encode()


def fehler(status: int, code: str | int | None = None, meldung: str = "Schein-Fehler") -> Antwort:
    """Eine Fehlerantwort mit `error.code` und `error.message` im Koerper."""
    fehlerteil: dict[str, Any] = {"message": meldung}
    if code is not None:
        fehlerteil["code"] = code
    return status, json.dumps({"error": fehlerteil}).encode()


def sperre() -> Antwort:
    return fehler(400, "content_blocked", "Request blocked for an unspecified policy reason")


def limit() -> Antwort:
    return fehler(429, "RESOURCE_EXHAUSTED", "Resource has been exhausted")


def text_von(rumpf: dict[str, Any]) -> str:
    return rumpf["input"][0]["content"][0]["text"]


def stimme_von(rumpf: dict[str, Any]) -> str:
    return rumpf["generation_config"]["speech_config"][0]["voice"]


class ScheinGoogle:
    """Der Transport. `regel(n, rumpf)` entscheidet je Anfrage (n zaehlt ab 0):

    `None` -> Ton nach Sprechrate; eine Zahl -> Ton dieser Dauer (s); ein Tupel
    `(status, bytes)` -> genau diese Antwort; eine Ausnahme -> wird geworfen.
    `verzoegerung_s` haelt jede Ton-Antwort so lange zurueck (Gleichzeitigkeit messbar).
    """

    def __init__(
        self,
        *,
        zeichen_je_s: float = 16.0,
        regel: Regel | None = None,
        verzoegerung_s: float = 0.0,
    ) -> None:
        self.zeichen_je_s = zeichen_je_s
        self.regel = regel
        self.verzoegerung_s = verzoegerung_s
        self.ruempfe: list[dict[str, Any]] = []
        self.urls: list[str] = []
        self.koepfe: list[dict[str, str]] = []
        self.zeitgrenzen: list[float] = []
        self.status: list[int | None] = []
        self.beginn: list[float] = []
        self.ende: list[float] = []
        self.gleichzeitig = 0
        self._sperre = threading.Lock()

    def __call__(
        self, url: str, koerper: bytes, kopf: dict[str, str], zeitgrenze: float
    ) -> Antwort:
        rumpf = json.loads(koerper)
        with self._sperre:
            n = len(self.ruempfe)
            self.ruempfe.append(rumpf)
            self.urls.append(url)
            self.koepfe.append(dict(kopf))
            self.zeitgrenzen.append(zeitgrenze)
            self.status.append(None)
            self.beginn.append(time.monotonic())
            self.ende.append(math.inf)
            self.gleichzeitig += 1
        try:
            antwort = self.regel(n, rumpf) if self.regel is not None else None
            if isinstance(antwort, BaseException):
                raise antwort
            if antwort is None:
                antwort = self.ton(len(text_von(rumpf)) / self.zeichen_je_s)
            elif isinstance(antwort, (int, float)):
                antwort = self.ton(float(antwort))
            with self._sperre:
                self.status[n] = antwort[0]
            return antwort
        finally:
            with self._sperre:
                self.ende[n] = time.monotonic()
                self.gleichzeitig -= 1

    def ton(self, sekunden: float) -> Antwort:
        if self.verzoegerung_s:
            time.sleep(self.verzoegerung_s)
        return audio_antwort(pcm(sekunden))

    @property
    def modelle(self) -> set[str]:
        return {r["model"] for r in self.ruempfe}

    @property
    def texte(self) -> list[str]:
        return [text_von(r) for r in self.ruempfe]

    def anfragen_mit(self, teil: str) -> int:
        return sum(teil in t for t in self.texte)

    def max_gleichzeitig_ab(self, zeitpunkt: float) -> int:
        """Hoechste Gleichzeitigkeit unter den Anfragen, die ab `zeitpunkt` begannen."""
        spannen = [(b, e) for b, e in zip(self.beginn, self.ende, strict=True) if b >= zeitpunkt]
        hoechste = 0
        for b, _ in spannen:
            hoechste = max(hoechste, sum(1 for b2, e2 in spannen if b2 <= b < e2))
        return hoechste


class Uhr:
    """Eingespeiste Uhr und Schlaf: `schlaf(s)` rueckt die Uhr um `s` vor und schreibt mit.

    `echt_s` haelt jeden Schlaf zusaetzlich so lange wirklich an -- nur dort, wo ein Test ein
    Zeitfenster braucht, in dem andere Faeden etwas tun koennten.
    """

    def __init__(self, echt_s: float = 0.0) -> None:
        self.jetzt = 0.0
        self.schlaefe: list[float] = []
        self.echt_s = echt_s
        self._sperre = threading.Lock()

    def __call__(self) -> float:
        return self.jetzt

    def schlaf(self, sekunden: float) -> None:
        with self._sperre:
            self.schlaefe.append(sekunden)
            self.jetzt += sekunden
        if self.echt_s:
            time.sleep(self.echt_s)


def gemini_stimme(
    name: str = "deutsch-gemini-charon", stimme: str = "Charon", **felder: Any
) -> Stimme:
    """Eine Gemini-Zeile wie aus der Tabelle (Pausen des Wegs gemini)."""
    vorgaben: dict[str, Any] = {
        "beschreibung": "Teststimme",
        "weg": "gemini",
        "stimme": stimme,
        "sprache": "de",
        "stand": "probe",
        "pause_stueck": 0.35,
        "pause_absatz": 0.35,
        "pause_titel": 0.7,
        "pause_kapitel": 1.8,
        "tempo_angleich": 0.0,
    }
    vorgaben.update(felder)
    return Stimme(name=name, **vorgaben)


TABELLE_SCHEMA2 = """\
schema = 2

[wege.local]
modell = "chatterbox-multilingual"

[wege.gemini]
modell = "{modell}"
{wege_gemini_extra}
[standard.local.de]
text = "beispiel"
ansage = "beispiel"

[standard.gemini.de]
text = "deutsch-gemini-charon"
ansage = "deutsch-gemini-kore"

[stimmen.beispiel]
beschreibung = "Teststimme lokal"
vorlage = "vorlagen/beispiel.wav"
sprache = "de"
exaggeration = 0.5
cfg_weight = 0.5
temperature = 0.8
stand = "probe"

[stimmen.deutsch-gemini-charon]
weg = "gemini"
stimme = "Charon"
beschreibung = "Teststimme Text"
sprache = "de"
stand = "probe"

[stimmen.deutsch-gemini-kore]
weg = "gemini"
stimme = "Kore"
beschreibung = "Teststimme Ansage"
sprache = "de"
stand = "probe"
"""


def schreibe_tabelle_schema2(ordner: Path, *, wege_gemini_extra: str = "") -> Path:
    """Tabelle Schema 2 mit einer lokalen und zwei Gemini-Zeilen; Vorlage als Platzhalter."""
    (ordner / "vorlagen").mkdir(exist_ok=True)
    (ordner / "vorlagen" / "beispiel.wav").write_bytes(b"erfundene Vorlage")
    pfad = ordner / "stimmen.toml"
    pfad.write_text(
        TABELLE_SCHEMA2.format(modell=MODELL, wege_gemini_extra=wege_gemini_extra),
        encoding="utf-8",
    )
    return pfad
