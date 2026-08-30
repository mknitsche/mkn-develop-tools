"""Die eine Stelle, an der der Anwender sagt, was er will.

**Warum es sie gibt.** Vorher lagen die Angaben an drei Orten: eine
Umgebungsvariable fuer die Schluessel, eine Datei fuer den Urheber, Pfade als
Aufrufparameter. Drei Orte fuer eine Sache sind drei Gelegenheiten, sie zu
vergessen -- und fuer jemanden, der das Werkzeug zum ersten Mal benutzt, drei
Stellen in der Anleitung, die er alle finden muss.

**Was NICHT hier steht.** Der Schluessel selbst. Die Konfiguration nennt den
ORT der Schluesseldatei, nie ihren Inhalt: eine Konfiguration wandert in
Sicherungen, in Vorlagen und gelegentlich in ein Fehlerbild, ein Schluessel
soll das nicht.

Gefunden wird sie ueber ``MKN_FOTO_KONFIG``, sonst an einer einzigen
naheliegenden Stelle. Fehlt sie ganz, bleibt alles leer -- das Werkzeug
arbeitet dann ohne Urheber, ohne Modell und mit dem Ziel aus dem Aufruf. Das
ist ein gueltiger Zustand, kein Fehler.

Eine KAPUTTE Datei dagegen ist laut. Ein Tippfehler in der eigenen
Konfiguration ist der haeufigste Fehler ueberhaupt, und wenn er als "keine
Konfiguration" durchgeht, laeuft das Werkzeug scheinbar richtig und schreibt
nichts.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from mkn_foto.urheber import Urheber

DATEI_VARIABLE = "MKN_FOTO_KONFIG"
STANDARD_ORT = Path.home() / ".config" / "mkn-foto" / "konfig.json"


class KonfigFehler(RuntimeError):
    """Die Datei ist da, aber unlesbar — mit ihrem Ort in der Meldung."""


@dataclass(frozen=True)
class Konfig:
    """Was der Anwender festgelegt hat. Jedes Feld darf fehlen."""

    ziel: Path | None = None
    schluessel_datei: Path | None = None
    modell: tuple[str, str] | None = None
    urheber: Urheber | None = None

    farbe_serie: str = "Blue"
    farbe_unklar: str = "Purple"
    """Die Namen der beiden Farben, die das Werkzeug setzt.

    **Sie gehoeren dem Anwender, nicht dem Werkzeug.** Lightroom vergleicht den
    String im XMP mit den Namen SEINES Farbbeschriftungssatzes, und die sind
    uebersetzt: ein deutsches Lightroom erwartet "Blau" und "Violett", ein
    englisches "Blue" und "Purple". Passt der Name nicht, zeigt Lightroom ein
    LEERES Feld an -- das Label ist da, die Farbe fehlt.

    Genau so ist es KT-1 am 2026-08-30 ergangen: sein Katalog enthielt 433
    Purple und 158 Blue, und er sah weisse Kaesten.

    Der Standard bleibt Englisch: es ist die Fallback-Sprache jedes
    Label-Sets. `photoshop:Urgency` ist davon unberuehrt -- die Zahl ist
    sprachunabhaengig, und Capture One liest sie."""


def _pfad(wert: object) -> Path | None:
    """Loest `~` auf.

    Wer das nicht tut, bekommt einen Ordner namens `~` im Arbeitsverzeichnis --
    und merkt es erst, wenn die Bilder darin liegen.
    """
    return Path(str(wert)).expanduser() if wert else None


def lade(pfad: Path | None = None) -> Konfig:
    """Liest die Konfiguration. Fehlt sie, ist alles leer; ist sie kaputt, knallt es."""
    if pfad is None:
        genannt = os.environ.get(DATEI_VARIABLE)
        pfad = Path(genannt).expanduser() if genannt else STANDARD_ORT

    try:
        roh = json.loads(pfad.read_text(encoding="utf-8"))
    except OSError:
        return Konfig()
    except json.JSONDecodeError as exc:
        raise KonfigFehler(f"{pfad} ist kein gueltiges JSON: {exc}") from exc

    if not isinstance(roh, dict):
        raise KonfigFehler(f"{pfad} muss ein JSON-Objekt enthalten, kein {type(roh).__name__}.")

    modell = roh.get("modell") or {}
    anbieter, name = modell.get("anbieter"), modell.get("name")

    urheber_daten = roh.get("urheber") or {}
    wer = None
    if urheber_daten.get("name"):
        wer = Urheber(
            name=str(urheber_daten["name"]),
            stadt=str(urheber_daten.get("stadt", "")),
            land=str(urheber_daten.get("land", "")),
            email=str(urheber_daten.get("email", "")),
            website=str(urheber_daten.get("website", "")),
            rechte_url=str(urheber_daten.get("rechte_url", "")),
            nutzungsbedingungen=str(urheber_daten.get("nutzungsbedingungen", "")),
        )

    farben = roh.get("farben") or {}

    return Konfig(
        farbe_serie=str(farben.get("serie") or "Blue"),
        farbe_unklar=str(farben.get("unklar") or "Purple"),
        ziel=_pfad(roh.get("ziel")),
        schluessel_datei=_pfad(roh.get("schluessel_datei")),
        modell=(str(anbieter), str(name)) if anbieter and name else None,
        urheber=wer,
    )
