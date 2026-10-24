"""Gemeinsames Einlesen und Pruefen von TOML-Dateien.

**Warum geteilt.** Konfiguration und Stimmen-Tabelle werden beide von Hand gepflegt, und
der haeufigste Fehler in so einer Datei ist ein Tippfehler. Beide sollen ihn gleich
laut melden: mit dem Ort der Datei und dem Namen des Feldes. Ein stillschweigend
ignoriertes Feld liesse die Stimme anders klingen oder den Arbeiter an einem anderen
Ort suchen, ohne dass jemand es merkt.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from mkn_audio.typen import Mp4Fehler


def lies(pfad: Path, was: str) -> dict[str, Any]:
    """Liest eine TOML-Datei; fehlende oder kaputte Datei bricht mit ihrem Ort."""
    try:
        with pfad.open("rb") as datei:
            return tomllib.load(datei)
    except FileNotFoundError:
        raise Mp4Fehler(f"{was} nicht gefunden: {pfad}") from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as fehler:
        raise Mp4Fehler(f"{was} unlesbar: {pfad} ({fehler})") from fehler


def pruefe_schluessel(
    daten: dict[str, Any], *, pflicht: set[str], erlaubt: set[str], wo: str
) -> None:
    """Pflichtfelder muessen da sein, unbekannte Felder darf es nicht geben."""
    fehlt = sorted(pflicht - daten.keys())
    if fehlt:
        raise Mp4Fehler(f"{wo}: Pflichtfeld fehlt: {', '.join(fehlt)}")
    fremd = sorted(daten.keys() - erlaubt)
    if fremd:
        raise Mp4Fehler(
            f"{wo}: unbekanntes Feld: {', '.join(fremd)} (erlaubt: {', '.join(sorted(erlaubt))})"
        )


def text(wert: object, feld: str, wo: str) -> str:
    if not isinstance(wert, str) or not wert:
        raise Mp4Fehler(f"{wo}: '{feld}' muss ein nicht leerer Text sein")
    return wert


def zahl(wert: object, feld: str, wo: str, *, minimum: float, offen: bool = False) -> float:
    """Eine Zahl ab `minimum` (bei `offen` echt groesser); `true` ist keine Zahl."""
    if isinstance(wert, bool) or not isinstance(wert, int | float):
        raise Mp4Fehler(f"{wo}: '{feld}' muss eine Zahl sein")
    ok = wert > minimum if offen else wert >= minimum
    if not ok:
        vergleich = ">" if offen else ">="
        raise Mp4Fehler(f"{wo}: '{feld}' muss {vergleich} {minimum} sein (ist {wert})")
    return float(wert)
