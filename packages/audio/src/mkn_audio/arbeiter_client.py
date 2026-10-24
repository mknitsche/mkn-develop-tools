"""Der Kunde des Arbeiter-Prozesses: Sprechen, Messen und Hoeren aus dem Paket heraus.

**Warum ein Prozess.** Chatterbox, librosa und Whisper brauchen eine eigene
Python-3.11-Umgebung mit schweren Abhaengigkeiten; das Paket selbst soll ohne sie
installierbar und testbar bleiben. Der Arbeiter (`arbeiter.py`) laeuft deshalb als
langlebiger Kindprozess, laedt das Modell einmal und nimmt Anfragen als JSON-Zeilen
entgegen. Dieser Client ist die einzige Stelle, die das Protokoll kennt.

**Fehler brechen laut.** Eine Fehlerantwort, ein gestorbener Prozess und eine
ueberschrittene Zeitgrenze sind alle `ArbeiterFehler` -- mit der Ursache, soweit der
Prozess sie auf stderr hinterlassen hat. Nach Tod oder Zeitgrenze gilt das Stueck als
nicht gerechnet; der naechste Aufruf startet einen frischen Arbeiter (Spec 7).
"""

from __future__ import annotations

import contextlib
import json
import queue
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import IO, Any

from mkn_audio.typen import Mp4Fehler

_STDERR_ENDE = 2000
"""Wie viele Zeichen vom Ende der stderr-Ausgabe in eine Fehlermeldung kommen."""


class ArbeiterFehler(Mp4Fehler):
    """Der Arbeiter hat einen Auftrag nicht erledigt (Fehlerantwort, Tod, Zeitgrenze).

    `klasse` nennt die Art in einem Wort (`Fehlerantwort`, `Tod`, `Zeitgrenze`, `Start`,
    `Antwort unlesbar`, `Antwort unvollstaendig`): der Lauf schreibt sie in den Bericht,
    wenn er ein Stueck deshalb nicht sprechen konnte -- wer den Bericht liest, soll den
    Grund sehen, ohne im Dienstprotokoll zu suchen.
    """

    def __init__(self, meldung: str, klasse: str = "Fehler") -> None:
        super().__init__(meldung)
        self.klasse = klasse


def _lies_zeilen(strom: IO[str], zeilen: queue.Queue[str | None]) -> None:
    """Schiebt jede Antwortzeile in die Warteschlange; `None` heisst: Strom zu.

    Ein eigener Faden, weil `readline()` keine Zeitgrenze kennt -- so laesst sich das
    Warten auf eine Antwort begrenzen, ohne den Prozess dabei zu verlieren.
    """
    try:
        for zeile in strom:
            zeilen.put(zeile)
    finally:
        zeilen.put(None)


class Arbeiter:
    """Ein Arbeiter-Prozess; als Kontextmanager benutzen.

    `skript` ist nur fuer Tests gedacht (Schein-Arbeiter mit demselben Protokoll);
    ohne Angabe laeuft das `arbeiter.py` neben diesem Modul.
    """

    def __init__(
        self,
        python: Path,
        *,
        whisper_modell: str = "small",
        zeitgrenze_s: float = 900,
        skript: Path | None = None,
        neustart_nach: int = 100,
    ) -> None:
        self._python = Path(python)
        self._skript = skript or Path(__file__).with_name("arbeiter.py")
        self._whisper_modell = whisper_modell
        self._zeitgrenze_s = zeitgrenze_s
        self._prozess: subprocess.Popen[str] | None = None
        self._zeilen: queue.Queue[str | None] = queue.Queue()
        self._stderr: IO[bytes] | None = None
        # Chatterbox haelt auf MPS (und in geringerem Mass auf der CPU) Speicher fest, der ueber
        # Hunderte Stuecke waechst -- gemessen 2026-10-24: nach rund 90 Stuecken "MPS backend
        # out of memory" bei 18,8 GB. Ein frischer Prozess alle `neustart_nach` Stuecke und
        # nach jedem Speicherfehler haelt ein 40-Stunden-Buch lauffaehig; der Neustart kostet
        # nur das Laden des Modells.
        self._neustart_nach = neustart_nach
        self._gesprochen = 0

    def __enter__(self) -> Arbeiter:
        self._starte()
        return self

    def __exit__(self, *_ausnahme: object) -> None:
        self.schliesse()

    # -- Auftraege ---------------------------------------------------------------

    def sprich(
        self,
        text: str,
        *,
        sprache: str,
        vorlage: Path,
        exaggeration: float,
        cfg_weight: float,
        temperature: float,
        ziel: Path,
        pausen_kuerzen: bool = True,
    ) -> dict[str, Any]:
        """Spricht `text` nach `ziel` (WAV, atomar) und meldet Dauer, Rate, Versuche."""
        if self._prozess is not None and self._gesprochen >= self._neustart_nach:
            self.schliesse()  # vorbeugend frisch: der naechste Auftrag startet neu
        antwort = self._frage(
            {
                "befehl": "sprich",
                "text": text,
                "sprache": sprache,
                "vorlage": str(vorlage),
                "exaggeration": exaggeration,
                "cfg_weight": cfg_weight,
                "temperature": temperature,
                "pausen_kuerzen": pausen_kuerzen,
                "ziel": str(ziel),
            },
            "dauer",
            "sprechrate",
            "versuche",
            "zu_kurz",
        )
        self._gesprochen += 1
        return antwort

    def miss(self, wav: Path) -> dict[str, Any]:
        """Tonlage, Streuung (Halbtoene), Pausenanteil und Dauer einer Aufnahme."""
        return self._frage(
            {"befehl": "miss", "wav": str(wav)},
            "f0_median",
            "streuung_ht",
            "pause_anteil",
            "dauer",
        )

    def hoere(self, wav: Path, sprache: str) -> str:
        """Schreibt auf, was in der Aufnahme gesagt wird."""
        antwort = self._frage({"befehl": "hoere", "wav": str(wav), "sprache": sprache}, "text")
        return str(antwort["text"])

    def vorlage(self, aufnahme: Path, ziel: Path, dauer: float = 24) -> dict[str, Any]:
        """Schneidet aus einer langen Aufnahme das ausdrucksstaerkste Fenster als Vorlage."""
        return self._frage(
            {"befehl": "vorlage", "aufnahme": str(aufnahme), "ziel": str(ziel), "dauer": dauer},
            "start",
            "streuung_ht",
        )

    # -- Prozess -----------------------------------------------------------------

    def schliesse(self) -> None:
        """Beendet den Prozess: erst hoeflich (stdin zu), dann mit Gewalt."""
        prozess = self._prozess
        if prozess is not None and prozess.poll() is None:
            try:
                if prozess.stdin:
                    prozess.stdin.close()
                prozess.wait(timeout=10)
            except (subprocess.TimeoutExpired, OSError):
                prozess.kill()
                prozess.wait()
        self._aufraeumen()

    def _aufraeumen(self) -> None:
        prozess = self._prozess
        if prozess is not None:
            if prozess.poll() is None:
                prozess.kill()
                prozess.wait()
            for strom in (prozess.stdin, prozess.stdout):
                if strom is not None:
                    with contextlib.suppress(OSError):  # der Strom ist mit dem Prozess tot
                        strom.close()
        if self._stderr is not None:
            self._stderr.close()
        self._prozess = None
        self._stderr = None

    def _starte(self) -> None:
        self._stderr = tempfile.TemporaryFile()  # noqa: SIM115 -- lebt so lange wie der Prozess
        befehl = [str(self._python), str(self._skript), "--whisper", self._whisper_modell]
        try:
            prozess = subprocess.Popen(
                befehl,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr,
                text=True,
                encoding="utf-8",
            )
        except OSError as fehler:
            self._stderr.close()
            self._stderr = None
            raise ArbeiterFehler(
                f"Arbeiter startet nicht ({self._python}): {fehler}", "Start"
            ) from fehler
        self._prozess = prozess
        self._gesprochen = 0
        self._zeilen = queue.Queue()
        faden = threading.Thread(
            target=_lies_zeilen, args=(prozess.stdout, self._zeilen), daemon=True
        )
        faden.start()

    def _stderr_ende(self) -> str:
        if self._stderr is None:
            return ""
        self._stderr.flush()
        groesse = self._stderr.seek(0, 2)
        self._stderr.seek(max(0, groesse - _STDERR_ENDE))
        return self._stderr.read().decode("utf-8", errors="replace").strip()

    def _scheitere(self, grund: str, klasse: str) -> ArbeiterFehler:
        """Baut den Fehler MIT der Ursache von stderr und beendet den Prozess."""
        ursache = self._stderr_ende()
        self._aufraeumen()
        return ArbeiterFehler(f"{grund}\nstderr des Arbeiters:\n{ursache or '(leer)'}", klasse)

    def _frage(self, anfrage: dict[str, Any], *erwartet: str) -> dict[str, Any]:
        if self._prozess is None:
            self._starte()
        prozess = self._prozess
        assert prozess is not None  # nach _starte() gesetzt, sonst waere es geworfen
        befehl = anfrage["befehl"]
        try:
            assert prozess.stdin is not None
            prozess.stdin.write(json.dumps(anfrage) + "\n")
            prozess.stdin.flush()
        except OSError as fehler:
            raise self._scheitere(
                f"Arbeiter nimmt '{befehl}' nicht an: {fehler}", "Tod"
            ) from fehler
        try:
            zeile = self._zeilen.get(timeout=self._zeitgrenze_s)
        except queue.Empty:
            raise self._scheitere(
                f"Zeitgrenze von {self._zeitgrenze_s:g} s fuer '{befehl}' ueberschritten",
                "Zeitgrenze",
            ) from None
        if zeile is None:
            code = prozess.wait()
            raise self._scheitere(f"Arbeiter ist bei '{befehl}' gestorben (Exit {code})", "Tod")
        try:
            antwort = json.loads(zeile)
            if not isinstance(antwort, dict):
                raise ValueError("keine Antwort-Zeile")
        except ValueError as fehler:
            raise self._scheitere(
                f"Arbeiter-Antwort unlesbar: {zeile[:200]!r}", "Antwort unlesbar"
            ) from fehler
        if "fehler" in antwort:
            if "out of memory" in str(antwort["fehler"]).lower():
                # Der Prozess lebt, aber sein Speicher ist voll: ein Neuversuch im selben
                # Prozess scheitert sicher wieder. Darum beenden -- der naechste Auftrag
                # startet frisch.
                grund = f"Arbeiter meldet bei '{befehl}': {antwort['fehler']}"
                raise self._scheitere(grund, "Speicher")
            raise ArbeiterFehler(
                f"Arbeiter meldet bei '{befehl}': {antwort['fehler']}", "Fehlerantwort"
            )
        fehlt = [schluessel for schluessel in erwartet if schluessel not in antwort]
        if fehlt:
            raise self._scheitere(
                f"Arbeiter-Antwort auf '{befehl}' ohne {', '.join(fehlt)}", "Antwort unvollstaendig"
            )
        return antwort
