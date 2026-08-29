"""exiftool-Wrapper: Stapel-Lesen und Kamerakuerzel.

Die einzige Stelle im Paket, die exiftool aufruft.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

#: Kamerakuerzel fuer die Notation. Bewusst eine GESCHLOSSENE Zuordnung: ein
#: geratenes Kuerzel landet im Dateinamen und ist danach nicht mehr von einem
#: echten zu unterscheiden. Neue Kamera heisst: hier eintragen.
KAMERA_KUERZEL: dict[str, str] = {
    "NIKON D850": "D850",
    "X-E5": "XE5",
    "iPhone 16 Pro": "iP16Pro",
}

#: Felder, die OHNE `-n` gelesen werden muessen: mit `-n` liefert exiftool die
#: Rohzahl, die Serienerkennung braucht aber den Text ("Single-Frame, Exposure
#: Bracketing"). Firsthand belegt 2026-08-28.
_TEXTFELDER: tuple[str, ...] = ("MakerNotes:ShootingMode",)


class UnbekannteKamera(RuntimeError):
    """Das EXIF-Modell hat kein hinterlegtes Kuerzel."""


class ExiftoolFehlt(RuntimeError):
    """exiftool ist nicht auffindbar."""


class ExiftoolFehler(RuntimeError):
    """exiftool hat einen Fehler gemeldet."""


def _exiftool_pfad() -> str | None:
    """Sucht exiftool auf dem PATH.

    Bewusst OHNE Rueckfall auf einen festen Pfad: ein hartkodiertes
    `/opt/homebrew/bin/exiftool` bindet das Werkzeug an einen Mac mit Homebrew
    und laesst es auf jedem anderen System an einer Stelle scheitern, die
    nichts mit der Ursache zu tun hat.
    """
    return shutil.which("exiftool")


def kamera_kuerzel(model: str) -> str:
    """Uebersetzt das EXIF-Modell in das Kuerzel der Notation."""
    try:
        return KAMERA_KUERZEL[model]
    except KeyError:
        raise UnbekannteKamera(
            f"Kein Kuerzel fuer Kameramodell {model!r} hinterlegt. "
            f"Bekannt: {sorted(KAMERA_KUERZEL)}. "
            f"Eintragen in exif.KAMERA_KUERZEL — nicht raten."
        ) from None


def lies(pfade: Sequence[Path]) -> list[dict[str, Any]]:
    """Liest die EXIF-Felder aller Pfade in EINEM exiftool-Aufruf je Modus.

    Gibt **genau einen** Eintrag je uebergebenem Pfad zurueck, in derselben
    Reihenfolge — auch fuer Dateien, zu denen exiftool nichts sagt. Der
    Aufrufer paart die Ergebnisse strikt mit seinen Pfaden; eine gekuerzte
    Liste wuerde dort brechen oder, schlimmer, still verrutschen.
    """
    if not pfade:
        return []

    zahlen = _ruf_exiftool(["-n", *(str(p) for p in pfade)])
    texte = _ruf_exiftool([f"-{feld}" for feld in _TEXTFELDER] + [str(p) for p in pfade])

    nach_datei: dict[str, dict[str, Any]] = {d["SourceFile"]: dict(d) for d in zahlen}
    for d in texte:
        nach_datei.setdefault(d["SourceFile"], {}).update(d)

    return [nach_datei.get(str(p), {"SourceFile": str(p)}) for p in pfade]


def _ruf_exiftool(argumente: list[str]) -> list[dict[str, Any]]:
    werkzeug = _exiftool_pfad()
    if werkzeug is None:
        raise ExiftoolFehlt(
            "exiftool ist nicht auf dem PATH. Es wird als externes Programm "
            "aufgerufen und nicht mitgeliefert. Installation: "
            "macOS 'brew install exiftool', Debian "
            "'apt install libimage-exiftool-perl', Windows exiftool.org."
        )

    ergebnis = subprocess.run(
        [werkzeug, "-j", "-G", *argumente],
        capture_output=True,
        text=True,
        check=False,
    )
    if ergebnis.returncode != 0 and not ergebnis.stdout.strip():
        raise ExiftoolFehler(
            f"exiftool exit={ergebnis.returncode}: {ergebnis.stderr.strip()[:400]}"
        )
    if ergebnis.stderr.strip():
        _LOG.warning("exiftool: %s", ergebnis.stderr.strip()[:400])
    return json.loads(ergebnis.stdout or "[]")
