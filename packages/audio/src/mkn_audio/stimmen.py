"""Die Stimmen-Tabelle: eine Zeile je Stimme, gewaehlt je Dokument.

**Warum eine Tabelle und nicht Parameter am Aufruf.** Eine Stimme ist ein Bundel aus
Vorlage, Reglern, Tempo und Klang, das zusammen gehoert und zusammen gemessen wurde.
Einzeln verstellt, ergibt es eine Stimme, die niemand gehoert hat. Die Tabelle ist eine
Datei, damit mehrere Rechner dieselbe lesen und das Paket ohne Datenbank auskommt.

**Schema 2: Weg x Sprache x Rolle.** Eine Zeile ist die Stimme EINES Wegs (`local`:
Chatterbox mit Vorlage und Reglern, `gemini`: eine Google-Stimme) in einer Sprache.
`[wege.<weg>]` nennt das Modell und die Grenzen des Wegs, `[standard.<weg>.<sprache>]` bindet
die Rollen: `text` (Fliesstext) und `ansage` (Titel, Ueberschriften, Vorspann, Ueberleitung,
Abspann). Ein Feld des anderen Wegs, ein `modell` an der Zeile oder eine `ansage_stimme` ist ein
Fehler mit Ort -- sonst klaenge die Stimme anders als die Tabelle behauptet.

**Schema 1** (ohne `schema`-Schluessel, `standard = "name"`) wird abgebildet und meldet einen
Hinweis (`Stimmentabelle.hinweise`); es entfaellt mit Fassung 0.4.0.

**Vorlagen-Pfade** gelten relativ zur Tabelle, damit Tabelle und Vorlagen als Ordner
umziehen koennen. Ob die Vorlage existiert, prueft erst der Arbeiter beim Sprechen; hier
zaehlt nur, dass die Tabelle in sich stimmt.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, get_args

from mkn_audio import _toml
from mkn_audio.typen import Mp4Fehler

Stand = Literal["standard", "freigegeben", "probe"]

MODELLE = ("chatterbox-multilingual",)
"""Die Stimm-Modelle, die der Arbeiter kann. Ein anderer Tabellenwert wuerde nirgends
gelesen: die Stimme klaenge nach Chatterbox, obwohl die Tabelle ein anderes Modell nennt."""


@dataclass(frozen=True)
class Weg:
    """Ein Weg zur Stimme: sein Befehl, seine Zeilenfelder und sein Pruefband.

    `pflicht` und `nur_hier` sind die Zeilenfelder, die nur dieser Weg kennt; ein Feld
    aus `nur_hier` an einer Zeile eines anderen Wegs ist ein Fehler. `pruefband` ist das
    Verhaeltnis gemessener zu erwarteter Dauer eines Blocks, ausserhalb dessen er auffaellt;
    `band_relativ` sagt, ob die Erwartung der Median des Laufs ist (gemini) oder eine feste
    Sprechrate (local).
    """

    name: str
    befehl: str
    pflicht: frozenset[str]
    nur_hier: frozenset[str]
    pruefband: tuple[float, float]
    band_relativ: bool


WEGE: Mapping[str, Weg] = {
    "local": Weg(
        "local",
        "mkn-mp4-local",
        frozenset({"vorlage", "exaggeration", "cfg_weight", "temperature"}),
        frozenset({"vorlage", "exaggeration", "cfg_weight", "temperature", "pausen_kuerzen"}),
        (0.55, 2.5),
        False,
    ),
    "gemini": Weg(
        "gemini",
        "mkn-mp4-gemini",
        frozenset({"stimme"}),
        frozenset({"stimme", "stil"}),
        (0.75, 1.3),
        True,
    ),
}

# Vorgaben der geteilten Zeilenfelder je Weg: Gemini spricht gleichmaessig (kein
# Tempo-Angleich) und setzt die Absatzpause selbst, Chatterbox behaelt seine heutigen Werte.
_VORGABEN: Mapping[str, Mapping[str, float]] = {
    "local": {
        "pause_stueck": 0.25,
        "pause_absatz": 0.6,
        "pause_titel": 1.5,
        "pause_kapitel": 2.0,
        "pause_vor_ueberschrift": 1.0,
        "pause_nach_ueberschrift": 0.7,
        "tempo_angleich": 0.10,
    },
    "gemini": {
        "pause_stueck": 0.35,
        "pause_absatz": 0.35,
        "pause_titel": 0.7,
        "pause_kapitel": 1.8,
        "pause_vor_ueberschrift": 1.0,
        "pause_nach_ueberschrift": 0.7,
        "tempo_angleich": 0.0,
    },
}


@dataclass(frozen=True, kw_only=True)
class Stimme:
    """Eine Stimme samt Vortrag und Nachbearbeitung.

    Nur mit Schluesselwoertern zu bauen: die Felder haben gemischt Vorgaben und
    Pflichtwerte, und eine Stimme mit vertauschten Reglern klaenge falsch, ohne dass
    etwas abbricht. Die Felder `vorlage`, `exaggeration`, `cfg_weight`, `temperature` gibt
    es nur an einer lokalen Zeile, `stimme` und `stil` nur an einer Gemini-Zeile; das jeweils
    andere ist `None`.
    """

    name: str
    beschreibung: str
    weg: str = "local"
    vorlage: Path | None = None
    stimme: str | None = None
    stil: str = ""
    sprache: str = "de"
    exaggeration: float | None = None
    cfg_weight: float | None = None
    temperature: float | None = None
    tempo: float = 1.0
    pause_stueck: float = 0.25
    pause_absatz: float = 0.6
    pause_titel: float = 1.5
    pause_kapitel: float = 2.0
    pause_vor_ueberschrift: float = 1.0
    pause_nach_ueberschrift: float = 0.7
    pausen_kuerzen: bool = True
    tempo_angleich: float = 0.10
    tonhoehe_ht: float = 0.0
    klang: tuple[str, ...] = ()
    version: int = 1
    stand: Stand


@dataclass(frozen=True)
class WegKonfig:
    """Modell und Grenzen eines Wegs (`[wege.<weg>]`).

    Die Preise dienen nur dem Kostenausweis des freien Pakets; das PKA setzt Katalogpreise.
    """

    modell: str
    parallel: int = 3
    block_zeichen: int = 1100
    zeitgrenze_s: float = 300.0
    preis_usd_je_1m_text_token: float | None = None
    preis_usd_je_1m_audio_token: float | None = None
    preisstand: date | None = None


@dataclass(frozen=True)
class Stimmentabelle:
    """Alle Stimmen einer Tabellendatei, die Wege und welche Stimmen ohne Wahl gelten.

    `fingerabdruck` identifiziert den Inhalt der Datei: der Bericht nennt ihn als
    Tabellen-Stand, damit ein Hoerstueck auch nach einer spaeteren Aenderung der
    Stimme nachvollziehbar bleibt. `standards` bindet (Weg, Sprache) an (Text-, Ansage-
    Stimme); `hinweise` sind Meldungen an den Bedienenden (Schema 1).
    """

    pfad: Path
    fingerabdruck: str
    schema: int
    wege: Mapping[str, WegKonfig]
    standards: Mapping[tuple[str, str], tuple[str, str]]
    stimmen: Mapping[str, Stimme]
    hinweise: tuple[str, ...] = ()

    def standard_fuer(self, weg: str, sprache: str) -> tuple[Stimme, Stimme, str | None]:
        """Text- und Ansage-Stimme des Wegs fuer die Dokumentsprache, dazu eine Warnung.

        Fehlt die Sprache unter `[standard.<weg>]`, spricht die deutsche Stimme des Wegs --
        mit Warnung, nie still: ein englisches Buch mit deutscher Stimme faellt auf.
        """
        code = _sprachcode(sprache)
        warnung = None
        paar = self.standards.get((weg, code))
        if paar is None:
            paar = self.standards.get((weg, "de"))
            if paar is None:
                raise Mp4Fehler(
                    f"Stimmen-Tabelle {self.pfad}: kein [standard.{weg}.{code}] und "
                    f"kein [standard.{weg}.de] -- der Weg '{weg}' hat keine Standard-Stimme"
                )
            warnung = (
                f"Keine Standard-Stimme fuer Sprache '{code}' im Weg '{weg}': "
                f"es spricht [standard.{weg}.de]"
            )
        text, ansage = paar
        return self.stimmen[text], self.stimmen[ansage], warnung

    def hole(self, name: str, *, weg: str | None = None) -> Stimme:
        """Die Stimme dieses Namens; mit `weg` muss sie diesem Weg gehoeren."""
        try:
            stimme = self.stimmen[name]
        except KeyError:
            raise Mp4Fehler(
                f"unbekannte Stimme '{name}' (verfuegbar: {', '.join(self.namen())})"
            ) from None
        if weg is not None and stimme.weg != weg:
            raise Mp4Fehler(
                f"Stimme '{name}' gehoert zum Weg '{stimme.weg}', nicht zu '{weg}' "
                f"(Stimmen des Wegs '{weg}': {', '.join(self.namen(weg)) or 'keine'})"
            )
        return stimme

    def namen(self, weg: str | None = None) -> tuple[str, ...]:
        return tuple(n for n, s in self.stimmen.items() if weg is None or s.weg == weg)


_GETEILT_PFLICHT = {"beschreibung", "stand"}
_GETEILT = _GETEILT_PFLICHT | {
    "sprache",
    "pause_stueck",
    "pause_absatz",
    "pause_titel",
    "pause_kapitel",
    "pause_vor_ueberschrift",
    "pause_nach_ueberschrift",
    "tempo",
    "tempo_angleich",
    "tonhoehe_ht",
    "klang",
    "version",
}
_WEGFELDER = frozenset().union(*(w.nur_hier for w in WEGE.values()))


# Der Name steht in Dateinamen (Vorlage `JJJJ-MM-TT Vorlage <name>_vNN.wav`, Bericht) und
# auf der Kommandozeile (`--stimme`). Darum nur Kleinbuchstaben, Ziffern und Bindestriche,
# Schema `<sprache>-<art>[-<merkmal>]`, etwa `deutsch-maennlich`: ein Umlaut kommt ueber SMB
# vom Mac in NFD-Form auf das NAS, und ein so geschriebener Name passt dort nicht mehr auf
# denselben Namen in NFC -- die Stimme waere nicht waehlbar, ohne dass es jemand merkt.
_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _sprachcode(sprache: str) -> str:
    return sprache.lower()[:2]


def _version(wert: object, wo: str) -> int:
    """Die Fassung der Stimme (`_v01`, `_v02` ...): ganze Zahl ab 1."""
    if isinstance(wert, bool) or not isinstance(wert, int) or wert < 1:
        raise Mp4Fehler(f"{wo}: 'version' muss eine ganze Zahl ab 1 sein (ist {wert!r})")
    return wert


def _pruefe_zeilenfelder(daten: dict[str, Any], weg: str, schema: int, wo: str) -> None:
    """Pflicht und Erlaubtes einer Zeile; ein Feld des anderen Wegs nennt seinen Weg."""
    if schema == 2:
        for feld, hinweis in (
            ("modell", f"steht in Schema 2 beim Weg: [wege.{weg}] modell = ..."),
            (
                "ansage_stimme",
                "entfaellt in Schema 2: die Rolle bindet [standard.<weg>.<sprache>] ansage = ...",
            ),
        ):
            if feld in daten:
                raise Mp4Fehler(f"{wo}: '{feld}' {hinweis}")
    fremd = sorted((_WEGFELDER - WEGE[weg].nur_hier) & daten.keys())
    if fremd:
        raise Mp4Fehler(
            f"{wo}: Feld {', '.join(repr(f) for f in fremd)} gibt es nur an Zeilen eines anderen "
            f"Wegs; diese Zeile gehoert zum Weg '{weg}'"
        )
    pflicht = _GETEILT_PFLICHT | WEGE[weg].pflicht | ({"sprache"} if schema == 2 else set())
    erlaubt = _GETEILT | WEGE[weg].nur_hier | ({"weg"} if schema == 2 else set())
    _toml.pruefe_schluessel(daten, pflicht=pflicht, erlaubt=erlaubt, wo=wo)


def _baue(name: str, daten: dict[str, Any], basis: Path, schema: int) -> Stimme:
    wo = f"Stimme '{name}'"
    if not _NAME.fullmatch(name):
        raise Mp4Fehler(
            f"{wo}: Name nur aus Kleinbuchstaben, Ziffern und Bindestrichen, "
            "etwa 'deutsch-maennlich' (er steht in Dateinamen und auf der Kommandozeile)"
        )
    weg = "local"
    if schema == 2 and "weg" in daten:
        weg = _toml.text(daten["weg"], "weg", wo)
        if weg not in WEGE:
            raise Mp4Fehler(f"{wo}: 'weg' '{weg}' unbekannt (bekannt: {', '.join(WEGE)})")
    _pruefe_zeilenfelder(daten, weg, schema, wo)

    stand = daten["stand"]
    if stand not in get_args(Stand):
        raise Mp4Fehler(f"{wo}: 'stand' muss {' | '.join(get_args(Stand))} sein (ist {stand!r})")

    klang = daten.get("klang", [])
    if not isinstance(klang, list) or not all(isinstance(z, str) and z for z in klang):
        raise Mp4Fehler(f"{wo}: 'klang' muss eine Liste von Filtertexten sein")
    pausen_kuerzen = daten.get("pausen_kuerzen", True)
    if not isinstance(pausen_kuerzen, bool):
        raise Mp4Fehler(f"{wo}: 'pausen_kuerzen' muss true oder false sein")

    vorgabe = _VORGABEN[weg]

    def zahl(feld: str, standardwert: float | None = None, **grenzen: Any) -> float:
        return _toml.zahl(daten.get(feld, standardwert), feld, wo, **grenzen)

    if weg == "local":
        vorlage = Path(_toml.text(daten["vorlage"], "vorlage", wo)).expanduser()
        if not vorlage.is_absolute():
            vorlage = basis / vorlage
        regler: dict[str, Any] = {
            "vorlage": vorlage,
            "exaggeration": zahl("exaggeration", minimum=0.0),
            "cfg_weight": zahl("cfg_weight", minimum=0.0),
            "temperature": zahl("temperature", minimum=0.0, offen=True),
            "pausen_kuerzen": pausen_kuerzen,
        }
    else:
        stil = daten.get("stil", "")
        if not isinstance(stil, str):
            raise Mp4Fehler(f"{wo}: 'stil' muss ein Text sein")
        regler = {"stimme": _toml.text(daten["stimme"], "stimme", wo), "stil": stil}

    return Stimme(
        name=name,
        beschreibung=_toml.text(daten["beschreibung"], "beschreibung", wo),
        weg=weg,
        sprache=_toml.text(daten.get("sprache", "de"), "sprache", wo),
        tempo=zahl("tempo", 1.0, minimum=0.0, offen=True),
        pause_stueck=zahl("pause_stueck", vorgabe["pause_stueck"], minimum=0.0),
        pause_absatz=zahl("pause_absatz", vorgabe["pause_absatz"], minimum=0.0),
        pause_titel=zahl("pause_titel", vorgabe["pause_titel"], minimum=0.0),
        pause_kapitel=zahl("pause_kapitel", vorgabe["pause_kapitel"], minimum=0.0),
        pause_vor_ueberschrift=zahl(
            "pause_vor_ueberschrift", vorgabe["pause_vor_ueberschrift"], minimum=0.0
        ),
        pause_nach_ueberschrift=zahl(
            "pause_nach_ueberschrift", vorgabe["pause_nach_ueberschrift"], minimum=0.0
        ),
        tempo_angleich=_angleich(daten.get("tempo_angleich", vorgabe["tempo_angleich"]), wo),
        tonhoehe_ht=_toml.zahl(daten.get("tonhoehe_ht", 0.0), "tonhoehe_ht", wo, minimum=-12.0),
        klang=tuple(klang),
        version=_version(daten.get("version", 1), wo),
        stand=stand,
        **regler,
    )


def _angleich(wert: object, wo: str) -> float:
    """Tempo-Angleich als Anteil: 0 schaltet ihn aus, 1 oder mehr waere sinnlos."""
    angleich = _toml.zahl(wert, "tempo_angleich", wo, minimum=0.0)
    if angleich >= 1.0:
        raise Mp4Fehler(f"{wo}: 'tempo_angleich' muss < 1 sein (ist {wert})")
    return angleich


def _tabelle(wert: object, was: str, wo: str) -> dict[str, Any]:
    if not isinstance(wert, dict):
        raise Mp4Fehler(f"{wo}: '{was}' muss eine Tabelle sein")
    return wert


def _wegkonfig(weg: str, daten: dict[str, Any], wo: str) -> WegKonfig:
    """Eine `[wege.<weg>]`-Tabelle; `local` kennt nur das Modell, `gemini` auch die Grenzen."""
    wo = f"{wo}: [wege.{weg}]"
    if weg == "local":
        _toml.pruefe_schluessel(daten, pflicht=set(), erlaubt={"modell"}, wo=wo)
    else:
        _toml.pruefe_schluessel(
            daten,
            pflicht={"modell"},
            erlaubt={
                "modell",
                "parallel",
                "block_zeichen",
                "zeitgrenze_s",
                "preis_usd_je_1m_text_token",
                "preis_usd_je_1m_audio_token",
                "preisstand",
            },
            wo=wo,
        )
    modell = _toml.text(daten.get("modell", MODELLE[0] if weg == "local" else None), "modell", wo)
    if weg == "local" and modell not in MODELLE:
        raise Mp4Fehler(
            f"{wo}: 'modell' '{modell}' wird nicht unterstuetzt "
            f"(unterstuetzt: {', '.join(MODELLE)})"
        )
    if weg == "local":
        return WegKonfig(modell=modell)

    def ganz(feld: str, vorgabe: int) -> int:
        wert = daten.get(feld, vorgabe)
        if isinstance(wert, bool) or not isinstance(wert, int) or wert < 1:
            raise Mp4Fehler(f"{wo}: '{feld}' muss eine ganze Zahl ab 1 sein (ist {wert!r})")
        return wert

    def preis(feld: str) -> float | None:
        return _toml.zahl(daten[feld], feld, wo, minimum=0.0) if feld in daten else None

    stand = daten.get("preisstand")
    if stand is not None and (not isinstance(stand, date) or hasattr(stand, "hour")):
        raise Mp4Fehler(f"{wo}: 'preisstand' muss ein Datum JJJJ-MM-TT sein (ist {stand!r})")
    return WegKonfig(
        modell=modell,
        parallel=ganz("parallel", 3),
        block_zeichen=ganz("block_zeichen", 1100),
        zeitgrenze_s=_toml.zahl(
            daten.get("zeitgrenze_s", 300.0), "zeitgrenze_s", wo, minimum=0.0, offen=True
        ),
        preis_usd_je_1m_text_token=preis("preis_usd_je_1m_text_token"),
        preis_usd_je_1m_audio_token=preis("preis_usd_je_1m_audio_token"),
        preisstand=stand,
    )


def _standards2(
    roh: object, stimmen: Mapping[str, Stimme], wo: str
) -> dict[tuple[str, str], tuple[str, str]]:
    """`[standard.<weg>.<sprache>]` mit `text` und `ansage`: Zeilen desselben Wegs und Sprache."""
    standards: dict[tuple[str, str], tuple[str, str]] = {}
    for weg, nach_sprache in _tabelle(roh, "standard", wo).items():
        if weg not in WEGE:
            raise Mp4Fehler(f"{wo}: [standard.{weg}]: Weg unbekannt (bekannt: {', '.join(WEGE)})")
        for sprache, rollen in _tabelle(nach_sprache, f"standard.{weg}", wo).items():
            ort = f"{wo}: [standard.{weg}.{sprache}]"
            rollen = _tabelle(rollen, f"standard.{weg}.{sprache}", wo)
            _toml.pruefe_schluessel(
                rollen, pflicht={"text", "ansage"}, erlaubt={"text", "ansage"}, wo=ort
            )
            namen = []
            for rolle in ("text", "ansage"):
                name = _toml.text(rollen[rolle], rolle, ort)
                zeile = stimmen.get(name)
                if zeile is None:
                    raise Mp4Fehler(
                        f"{ort}: '{rolle}' nennt '{name}', verfuegbar: {', '.join(stimmen)}"
                    )
                if zeile.weg != weg:
                    raise Mp4Fehler(
                        f"{ort}: '{rolle}' nennt '{name}', eine Stimme des Wegs '{zeile.weg}' "
                        f"(erwartet: Weg '{weg}')"
                    )
                if _sprachcode(zeile.sprache) != _sprachcode(sprache):
                    raise Mp4Fehler(
                        f"{ort}: '{rolle}' nennt '{name}' in Sprache '{zeile.sprache}' "
                        f"(erwartet: '{sprache}')"
                    )
                namen.append(name)
            standards[(weg, _sprachcode(sprache))] = (namen[0], namen[1])
    return standards


def lade_tabelle(pfad: Path) -> Stimmentabelle:
    """Liest die Tabelle (Schema 1 oder 2); jede Unstimmigkeit bricht mit Ort und Feldnamen."""
    inhalt = pfad.read_bytes() if pfad.is_file() else b""
    daten = _toml.lies(pfad, "Stimmen-Tabelle")
    wo = f"Stimmen-Tabelle {pfad}"

    schema = daten.get("schema", 1)
    if "schema" in daten and (isinstance(schema, bool) or schema != 2):
        raise Mp4Fehler(f"{wo}: 'schema' muss 2 sein (ist {schema!r}; ohne 'schema' gilt Schema 1)")
    _toml.pruefe_schluessel(
        daten,
        pflicht={"standard", "stimmen"},
        erlaubt={"standard", "stimmen", "schema", "wege"}
        if schema == 2
        else {"standard", "stimmen"},
        wo=wo,
    )

    rohe = daten["stimmen"]
    if not isinstance(rohe, dict) or not rohe:
        raise Mp4Fehler(f"{wo}: 'stimmen' muss mindestens eine Stimme enthalten")
    for name, eintrag in rohe.items():
        if not isinstance(eintrag, dict):
            raise Mp4Fehler(f"{wo}: 'stimmen.{name}' muss eine Tabelle sein")

    if schema == 1:
        return _lade1(pfad, inhalt, daten, wo)

    basis = pfad.parent
    stimmen = {name: _baue(name, eintrag, basis, 2) for name, eintrag in rohe.items()}
    wege: dict[str, WegKonfig] = {}
    for weg, eintrag in _tabelle(daten.get("wege", {}), "wege", wo).items():
        if weg not in WEGE:
            raise Mp4Fehler(f"{wo}: [wege.{weg}]: Weg unbekannt (bekannt: {', '.join(WEGE)})")
        wege[weg] = _wegkonfig(weg, _tabelle(eintrag, f"wege.{weg}", wo), wo)
    wege.setdefault("local", WegKonfig(modell=MODELLE[0]))
    for name, stimme in stimmen.items():
        if stimme.weg not in wege:
            raise Mp4Fehler(
                f"{wo}: Stimme '{name}' nutzt den Weg '{stimme.weg}': "
                f"[wege.{stimme.weg}] mit 'modell' fehlt"
            )
    return Stimmentabelle(
        pfad=pfad,
        fingerabdruck=hashlib.sha256(inhalt).hexdigest()[:16],
        schema=2,
        wege=wege,
        standards=_standards2(daten["standard"], stimmen, wo),
        stimmen=stimmen,
    )


def _lade1(pfad: Path, inhalt: bytes, daten: dict[str, Any], wo: str) -> Stimmentabelle:
    """Schema 1 auf Schema 2 abbilden: `standard = "x"` wird `[standard.local.<sprache>]`."""
    rohe: dict[str, dict[str, Any]] = daten["stimmen"]
    standard = daten["standard"]
    if standard not in rohe:
        raise Mp4Fehler(f"{wo}: 'standard' nennt '{standard}', verfuegbar: {', '.join(rohe)}")

    ansagen: dict[str, str | None] = {}
    modelle: set[str] = set()
    zeilen: dict[str, dict[str, Any]] = {}
    for name, eintrag in rohe.items():
        zeilen[name] = rest = dict(eintrag)
        ansage = rest.pop("ansage_stimme", None)
        ansagen[name] = (
            None if ansage is None else _toml.text(ansage, "ansage_stimme", f"Stimme '{name}'")
        )
        modell = _toml.text(rest.pop("modell", MODELLE[0]), "modell", f"Stimme '{name}'")
        if modell not in MODELLE:
            raise Mp4Fehler(
                f"Stimme '{name}': 'modell' '{modell}' wird nicht unterstuetzt "
                f"(unterstuetzt: {', '.join(MODELLE)})"
            )
        modelle.add(modell)

    basis = pfad.parent
    stimmen = {name: _baue(name, zeile, basis, 1) for name, zeile in zeilen.items()}
    for name, ansage in ansagen.items():
        # Ein Tippfehler waere sonst erst beim Sprechen der ersten Ansage sichtbar -- nach
        # Lesen, Regie und Hoertext. Die eigene Stimme ist erlaubt: "keine zweite Stimme".
        if ansage is not None and ansage not in stimmen:
            raise Mp4Fehler(
                f"{wo}: Stimme '{name}': 'ansage_stimme' nennt '{ansage}', "
                f"verfuegbar: {', '.join(stimmen)}"
            )
    return Stimmentabelle(
        pfad=pfad,
        fingerabdruck=hashlib.sha256(inhalt).hexdigest()[:16],
        schema=1,
        wege={"local": WegKonfig(modell=sorted(modelle)[0])},
        standards={
            ("local", _sprachcode(stimmen[standard].sprache)): (
                standard,
                ansagen[standard] or standard,
            )
        },
        stimmen=stimmen,
        hinweise=("Stimmen-Tabelle im alten Format (Schema 1); bitte auf Schema 2 heben",),
    )
