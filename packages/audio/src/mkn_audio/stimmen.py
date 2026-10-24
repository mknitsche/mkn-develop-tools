"""Die Stimmen-Tabelle: eine Zeile je Stimme, gewaehlt je Dokument.

**Warum eine Tabelle und nicht Parameter am Aufruf.** Eine Stimme ist ein Bundel aus
Vorlage, Reglern, Tempo und Klang, das zusammen gehoert und zusammen gemessen wurde.
Einzeln verstellt, ergibt es eine Stimme, die niemand gehoert hat. Die Tabelle ist eine
Datei, damit mehrere Rechner dieselbe lesen und das Paket ohne Datenbank auskommt.

**Die Klangkorrektur gehoert zur Stimme**, nicht zur Ausgabe: sie gleicht aus, was diese
Vorlage im Klang mitbringt, und taugt fuer eine andere Stimme nicht.

**Eine zweite Stimme fuer Ansagen** (`ansage_stimme`): Vorspann, Ueberleitungen und Abspann
der Regie koennen mit einer anderen Stimme der Tabelle gesprochen werden, wie
ein Sprecher neben dem Vorleser. Der Eintrag nennt NUR den Namen; Vorlage, Regler, Klang und
Tempo der Ansagen sind die der genannten Stimme. Ohne Eintrag spricht die Hauptstimme.

**Vorlagen-Pfade** gelten relativ zur Tabelle, damit Tabelle und Vorlagen als Ordner
umziehen koennen. Ob die Vorlage existiert, prueft erst der Arbeiter beim Sprechen; hier
zaehlt nur, dass die Tabelle in sich stimmt.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

from mkn_audio import _toml
from mkn_audio.typen import Mp4Fehler

Stand = Literal["standard", "freigegeben", "probe"]

MODELLE = ("chatterbox-multilingual",)
"""Die Stimm-Modelle, die der Arbeiter kann. Ein anderer Tabellenwert wuerde nirgends
gelesen: die Stimme klaenge nach Chatterbox, obwohl die Tabelle ein anderes Modell nennt."""


@dataclass(frozen=True, kw_only=True)
class Stimme:
    """Eine Stimme samt Vortrag und Nachbearbeitung.

    Nur mit Schluesselwoertern zu bauen: die Felder haben gemischt Vorgaben und
    Pflichtwerte, und eine Stimme mit vertauschten Reglern klaenge falsch, ohne dass
    etwas abbricht.
    """

    name: str
    beschreibung: str
    modell: str = "chatterbox-multilingual"
    vorlage: Path
    sprache: str = "de"
    exaggeration: float
    cfg_weight: float
    temperature: float
    tempo: float
    pause_stueck: float = 0.25
    pause_absatz: float = 0.6
    pause_titel: float = 1.5
    pause_kapitel: float = 2.0
    pausen_kuerzen: bool = True
    tempo_angleich: float = 0.10
    tonhoehe_ht: float = 0.0
    klang: tuple[str, ...] = ()
    version: int = 1
    ansage_stimme: str | None = None
    stand: Stand


@dataclass(frozen=True)
class Stimmentabelle:
    """Alle Stimmen einer Tabellendatei und welche ohne Wahl gilt.

    `fingerabdruck` identifiziert den Inhalt der Datei: der Bericht nennt ihn als
    Tabellen-Stand, damit ein Hoerstueck auch nach einer spaeteren Aenderung der
    Stimme nachvollziehbar bleibt.
    """

    pfad: Path
    fingerabdruck: str
    standard_name: str
    stimmen: Mapping[str, Stimme]

    @property
    def standard(self) -> Stimme:
        return self.stimmen[self.standard_name]

    def hole(self, name: str) -> Stimme:
        try:
            return self.stimmen[name]
        except KeyError:
            raise Mp4Fehler(
                f"unbekannte Stimme '{name}' (verfuegbar: {', '.join(self.namen())})"
            ) from None

    def namen(self) -> tuple[str, ...]:
        return tuple(self.stimmen)


_PFLICHT = {
    "beschreibung",
    "vorlage",
    "exaggeration",
    "cfg_weight",
    "temperature",
    "tempo",
    "stand",
}
_ERLAUBT = _PFLICHT | {
    "modell",
    "sprache",
    "pause_stueck",
    "pause_absatz",
    "pause_titel",
    "pause_kapitel",
    "pausen_kuerzen",
    "tempo_angleich",
    "tonhoehe_ht",
    "klang",
    "version",
    "ansage_stimme",
}


# Der Name steht in Dateinamen (Vorlage `JJJJ-MM-TT Vorlage <name>_vNN.wav`, Bericht) und
# auf der Kommandozeile (`--stimme`). Darum nur Kleinbuchstaben, Ziffern und Bindestriche,
# Schema `<sprache>-<art>[-<merkmal>]`, etwa `deutsch-maennlich`: ein Umlaut kommt ueber SMB
# vom Mac in NFD-Form auf das NAS, und ein so geschriebener Name passt dort nicht mehr auf
# denselben Namen in NFC -- die Stimme waere nicht waehlbar, ohne dass es jemand merkt.
_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _version(wert: object, wo: str) -> int:
    """Die Fassung der Stimme (`_v01`, `_v02` ...): ganze Zahl ab 1."""
    if isinstance(wert, bool) or not isinstance(wert, int) or wert < 1:
        raise Mp4Fehler(f"{wo}: 'version' muss eine ganze Zahl ab 1 sein (ist {wert!r})")
    return wert


def _baue(name: str, daten: dict[str, Any], basis: Path) -> Stimme:
    wo = f"Stimme '{name}'"
    if not _NAME.fullmatch(name):
        raise Mp4Fehler(
            f"{wo}: Name nur aus Kleinbuchstaben, Ziffern und Bindestrichen, "
            "etwa 'deutsch-maennlich' (er steht in Dateinamen und auf der Kommandozeile)"
        )
    _toml.pruefe_schluessel(daten, pflicht=_PFLICHT, erlaubt=_ERLAUBT, wo=wo)

    stand = daten["stand"]
    if stand not in get_args(Stand):
        raise Mp4Fehler(f"{wo}: 'stand' muss {' | '.join(get_args(Stand))} sein (ist {stand!r})")

    klang = daten.get("klang", [])
    if not isinstance(klang, list) or not all(isinstance(z, str) and z for z in klang):
        raise Mp4Fehler(f"{wo}: 'klang' muss eine Liste von Filtertexten sein")
    pausen_kuerzen = daten.get("pausen_kuerzen", True)
    if not isinstance(pausen_kuerzen, bool):
        raise Mp4Fehler(f"{wo}: 'pausen_kuerzen' muss true oder false sein")

    ansage = daten.get("ansage_stimme")
    if ansage is not None:
        ansage = _toml.text(ansage, "ansage_stimme", wo)

    modell = _toml.text(daten.get("modell", MODELLE[0]), "modell", wo)
    if modell not in MODELLE:
        raise Mp4Fehler(
            f"{wo}: 'modell' '{modell}' wird nicht unterstuetzt "
            f"(unterstuetzt: {', '.join(MODELLE)})"
        )

    vorlage = Path(_toml.text(daten["vorlage"], "vorlage", wo)).expanduser()
    if not vorlage.is_absolute():
        vorlage = basis / vorlage

    def zahl(feld: str, vorgabe: float | None = None, **grenzen: Any) -> float:
        return _toml.zahl(daten.get(feld, vorgabe), feld, wo, **grenzen)

    return Stimme(
        name=name,
        beschreibung=_toml.text(daten["beschreibung"], "beschreibung", wo),
        modell=modell,
        vorlage=vorlage,
        sprache=_toml.text(daten.get("sprache", "de"), "sprache", wo),
        exaggeration=zahl("exaggeration", minimum=0.0),
        cfg_weight=zahl("cfg_weight", minimum=0.0),
        temperature=zahl("temperature", minimum=0.0, offen=True),
        tempo=zahl("tempo", minimum=0.0, offen=True),
        pause_stueck=zahl("pause_stueck", 0.25, minimum=0.0),
        pause_absatz=zahl("pause_absatz", 0.6, minimum=0.0),
        pause_titel=zahl("pause_titel", 1.5, minimum=0.0),
        pause_kapitel=zahl("pause_kapitel", 2.0, minimum=0.0),
        pausen_kuerzen=pausen_kuerzen,
        tempo_angleich=_angleich(daten.get("tempo_angleich", 0.10), wo),
        tonhoehe_ht=_toml.zahl(daten.get("tonhoehe_ht", 0.0), "tonhoehe_ht", wo, minimum=-12.0),
        klang=tuple(klang),
        version=_version(daten.get("version", 1), wo),
        ansage_stimme=ansage,
        stand=stand,
    )


def _angleich(wert: object, wo: str) -> float:
    """Tempo-Angleich als Anteil: 0 schaltet ihn aus, 1 oder mehr waere sinnlos."""
    angleich = _toml.zahl(wert, "tempo_angleich", wo, minimum=0.0)
    if angleich >= 1.0:
        raise Mp4Fehler(f"{wo}: 'tempo_angleich' muss < 1 sein (ist {wert})")
    return angleich


def lade_tabelle(pfad: Path) -> Stimmentabelle:
    """Liest die Tabelle; jede Unstimmigkeit bricht mit Ort und Feldnamen."""
    inhalt = pfad.read_bytes() if pfad.is_file() else b""
    daten = _toml.lies(pfad, "Stimmen-Tabelle")
    wo = f"Stimmen-Tabelle {pfad}"
    _toml.pruefe_schluessel(
        daten, pflicht={"standard", "stimmen"}, erlaubt={"standard", "stimmen"}, wo=wo
    )

    rohe = daten["stimmen"]
    if not isinstance(rohe, dict) or not rohe:
        raise Mp4Fehler(f"{wo}: 'stimmen' muss mindestens eine Stimme enthalten")
    for name, eintrag in rohe.items():
        if not isinstance(eintrag, dict):
            raise Mp4Fehler(f"{wo}: 'stimmen.{name}' muss eine Tabelle sein")

    standard = daten["standard"]
    if standard not in rohe:
        raise Mp4Fehler(f"{wo}: 'standard' nennt '{standard}', verfuegbar: {', '.join(rohe)}")

    basis = pfad.parent
    stimmen = {name: _baue(name, eintrag, basis) for name, eintrag in rohe.items()}
    for name, stimme in stimmen.items():
        # Ein Tippfehler waere sonst erst beim Sprechen der ersten Ansage sichtbar -- nach
        # Lesen, Regie und Hoertext. Die eigene Stimme ist erlaubt: "keine zweite Stimme".
        if stimme.ansage_stimme is not None and stimme.ansage_stimme not in stimmen:
            raise Mp4Fehler(
                f"{wo}: Stimme '{name}': 'ansage_stimme' nennt '{stimme.ansage_stimme}', "
                f"verfuegbar: {', '.join(stimmen)}"
            )
    return Stimmentabelle(
        pfad=pfad,
        fingerabdruck=hashlib.sha256(inhalt).hexdigest()[:16],
        standard_name=standard,
        stimmen=stimmen,
    )
