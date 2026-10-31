"""Die eine Stelle, an der der Anwender sagt, wo seine Dinge liegen.

**Warum es sie gibt.** Das Paket braucht drei Orte, die nur der Anwender kennt: die
Stimmen-Tabelle, den Python des Arbeiter-Prozesses (optional, nur fuer den Weg local und die
Abschrift-Pruefung; eine eigene Umgebung, weil die
Stimm-Software eine andere Python-Version verlangt als das Paket) und einen Ort fuer
Zwischenergebnisse. Stuenden sie als Aufrufparameter verteilt, muesste jeder Aufruf
sie wiederholen.

Gefunden wird die Datei ueber `MKN_MP4_KONFIG`, sonst am Standardort.

**Fehlt sie, ist das ein Fehler.** Anders als bei Werkzeugen, die ohne Angaben sinnvoll
weiterarbeiten, kann dieses ohne Stimmen-Tabelle und Arbeiter nichts sprechen; ein
stiller Ersatz waere nur ein spaeterer, schwerer zu deutender Abbruch. Die Meldung nennt
den Ort, an dem gesucht wurde.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from mkn_audio import _toml
from mkn_audio.typen import Mp4Fehler

DATEI_VARIABLE = "MKN_MP4_KONFIG"
STANDARD_ORT = Path.home() / ".config" / "mkn-mp4" / "konfig.toml"

_PFLICHT = {"stimmen_tabelle"}
_ERLAUBT = _PFLICHT | {"arbeiter_python", "arbeitsort", "whisper_modell"}


@dataclass(frozen=True)
class Konfig:
    """Was der Anwender festgelegt hat.

    `arbeiter_python` ist nur fuer den Weg local Pflicht (der Arbeiter spricht und hoert); wer
    nur den Weg gemini nutzt, laesst es weg -- dann gibt es keine Whisper-Stichprobe. Es fehlt
    als `None`, nie als Ersatzpfad.
    """

    stimmen_tabelle: Path
    arbeitsort: Path
    arbeiter_python: Path | None = None
    whisper_modell: str = "small"


def _pfad(wert: object, feld: str, basis: Path) -> Path:
    """`~` wird aufgeloest; relativ heisst relativ zur Konfigurationsdatei.

    Nicht relativ zum Aufrufer: derselbe Eintrag soll von jedem Ordner aus auf
    dieselbe Stelle zeigen.
    """
    pfad = Path(_toml.text(wert, feld, "Konfiguration")).expanduser()
    return pfad if pfad.is_absolute() else basis / pfad


def lade(pfad: Path | None = None) -> Konfig:
    """Liest die Konfiguration. Vorrang: Aufruf-Pfad, dann Umgebung, dann Standardort."""
    if pfad is None:
        pfad = Path(os.environ.get(DATEI_VARIABLE) or STANDARD_ORT)
    daten = _toml.lies(pfad, "Konfiguration")
    _toml.pruefe_schluessel(daten, pflicht=_PFLICHT, erlaubt=_ERLAUBT, wo=f"Konfiguration {pfad}")
    basis = pfad.parent
    try:
        arbeitsort = (
            _pfad(daten["arbeitsort"], "arbeitsort", basis)
            if "arbeitsort" in daten
            else Path.home() / ".cache" / "mkn-mp4"
        )
        return Konfig(
            stimmen_tabelle=_pfad(daten["stimmen_tabelle"], "stimmen_tabelle", basis),
            arbeitsort=arbeitsort,
            arbeiter_python=(
                _pfad(daten["arbeiter_python"], "arbeiter_python", basis)
                if "arbeiter_python" in daten
                else None
            ),
            whisper_modell=_toml.text(
                daten.get("whisper_modell", "small"), "whisper_modell", "Konfiguration"
            ),
        )
    except Mp4Fehler as fehler:
        raise Mp4Fehler(f"{fehler} (Datei: {pfad})") from fehler
