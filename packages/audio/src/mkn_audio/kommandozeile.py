"""Die Kommandozeilen `mkn-mp4-local` und `mkn-mp4-gemini`.

    mkn-mp4-local  <quelle> [--stimme NAME] [--ansage NAME] [--ziel ORDNER] [--auswahl K]
                            [--format m4b|mp3] [--regie voll|buch|aus]
    mkn-mp4-local  vorlage <aufnahme> --ziel <wav> [--dauer 24]
    mkn-mp4-gemini <quelle> [... wie local ...] [--cloud-ok] [--modell ID]
    mkn-mp4-local | mkn-mp4-gemini  stimmen

Beide Befehle sind Einstiege in EINEN Kern (`haupt(argv, weg=...)`); der Weg bestimmt den
Sprecher, die Stimmen der Tabelle und die Optionen.

**Exit-Codes.** 0 gut, 1 Fehler (Meldung auf stderr: die Quelle ist unbrauchbar, die
Umgebung defekt, ein Dienst antwortet nicht ...), 2 Bedienfehler (falsche Eingabe: gleich
neu aufrufen), 3 Rueckfrage noetig (Datenschutz-Hinweise bei gemini, weder Terminal noch
`--cloud-ok`: nichts ist gesendet worden). Ein Skript soll den Unterschied sehen: bei 2 hilft
Wiederholen nicht ohne Aenderung des Aufrufs, bei 1 nicht ohne Aenderung der Umgebung.

**stdout und stderr.** stdout traegt nur das Ergebnis (eine Datei je Zeile), alles andere
-- Fortschritt, Hinweise, Fehler -- geht nach stderr: so laesst sich der Aufruf in einer
Pipe verwenden, ohne dass Fortschrittszeilen als Dateinamen gelesen werden.

**Das Sprachmodell kommt aus der Umgebung** (`MKN_LLM_ANBIETER`, `MKN_LLM_MODELL`, Schluessel
je Anbieter), nie aus dem Paket: es kennt keinen Modellnamen. Ist kein Anbieter gesetzt,
laeuft der Lauf ohne -- der Hoertext wird nur nach Regeln aufbereitet und Bilder liest die
Texterkennung. Das wird gesagt, nicht verschwiegen. Ist einer gesetzt, aber unvollstaendig
(kein Modell, kein Schluessel), bricht der Aufruf VOR der Arbeit ab: sonst wuerde der Lauf
stundenlang sprechen und erst bei der ersten Anfrage scheitern.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from mkn_kern import anfrage, modelle

from mkn_audio.arbeiter_client import Arbeiter
from mkn_audio.arbeitsverzeichnis import Arbeitsverzeichnis
from mkn_audio.gemini import SprecherGemini
from mkn_audio.konfig import lade
from mkn_audio.lauf import konvertiere, lies_mit_zwischenstand
from mkn_audio.sprecher import Sprecher, SprecherLokal
from mkn_audio.stimmen import WEGE, Stimmentabelle, lade_tabelle
from mkn_audio.typen import Mp4Fehler, Textmodell
from mkn_audio.vertraulich import Hinweis, RueckfrageNoetig

MAX_TOKENS = 8192
"""Obergrenze der Modell-Antwort: eine Aufbereitung von 6000 Zeichen oder eine Seite Text
vom Bild ist so lang wie die Eingabe; zu knapp bemessen wuerde sie mitten im Satz enden."""

ZEITGRENZE_S = 300.0
"""So lange wartet eine Modell-Anfrage (die Voreinstellung von mkn-kern ist fuer Bildurteile
gedacht, nicht fuer eine Seite Text)."""

_BILD_ENDUNGEN = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
"""Endung je Bildtyp. `baue_anfrage` leitet den Typ aus der Dateiendung ab; ein anderer als
der echte wuerde vom Anbieter abgelehnt oder falsch gelesen."""

_ENDE = """\
Das Sprachmodell kommt aus MKN_LLM_ANBIETER und MKN_LLM_MODELL (Schluessel je Anbieter);
ohne sie wird der Hoertext nur nach Regeln aufbereitet. Exit: 0 gut, 1 Fehler, 2 Bedienfehler,
3 Rueckfrage noetig.
"""


def _zusatz(weg: str) -> str:
    """Der Hilfetext unter den Optionen: die Befehle des Wegs."""
    befehl = WEGE[weg].befehl
    zeilen = ["weitere Befehle:"]
    if weg == "local":
        zeilen += [
            f"  {befehl} vorlage <aufnahme> --ziel <wav> [--dauer 24]",
            "      schneidet aus einer Aufnahme die ausdrucksstaerkste Stelle als Stimmvorlage",
        ]
    zeilen += [f"  {befehl} stimmen", "      zeigt die Stimmen-Tabelle (* = Standard dieses Wegs)"]
    if weg == "gemini":
        zeilen += [
            "",
            "Der Text geht an Google (Gemini TTS). Der Schluessel kommt aus GEMINI_API_KEY oder",
            "aus der Datei, auf die MKN_LLM_SCHLUESSEL_DATEI zeigt. Gibt es Datenschutz-Hinweise,",
            "fragt der Befehl vorher (Terminal) oder bricht mit Exit 3 ab; --cloud-ok gibt frei.",
        ]
    return "\n".join(zeilen) + "\n\n" + _ENDE


class _Bedienfehler(Exception):
    """Falsche Eingabe des Menschen (Exit 2), kein Defekt (Exit 1)."""


# -- Sprachmodell ---------------------------------------------------------------------


def _abgeschnitten(antwort: dict[str, Any]) -> bool:
    """Meldet die Antwort selbst, dass sie an der Laengengrenze endete?"""
    kandidaten = antwort.get("candidates")
    wahlen = antwort.get("choices")
    return (
        antwort.get("stop_reason") == "max_tokens"
        or antwort.get("done_reason") == "length"
        or (isinstance(kandidaten, list) and bool(kandidaten) and isinstance(kandidaten[0], dict)
            and kandidaten[0].get("finishReason") == "MAX_TOKENS")
        or (isinstance(wahlen, list) and bool(wahlen) and isinstance(wahlen[0], dict)
            and wahlen[0].get("finish_reason") == "length")
    )  # fmt: skip


def antwort_text(antwort: dict[str, Any]) -> str:
    """Der Text einer Modell-Antwort, ueber die Formen der vier Anbieter hinweg.

    **Eine abgeschnittene Antwort ist ein Fehler.** Ein Text, der mitten im Absatz endet,
    sieht fluessig aus: das Hoerstueck liesse den Rest still weg. Eine Antwort ganz ohne
    Text ebenso -- er ist eine Form, die diese Funktion nicht kennt, kein leeres Ergebnis.
    """
    if _abgeschnitten(antwort):
        raise Mp4Fehler(
            f"Antwort des Sprachmodells ist abgeschnitten (Grenze {MAX_TOKENS} Tokens erreicht)"
        )
    inhalt = antwort.get("content")
    if isinstance(inhalt, list):  # Anthropic
        return "".join(t.get("text", "") for t in inhalt if isinstance(t, dict))
    if isinstance(inhalt, str):
        return inhalt
    kandidaten = antwort.get("candidates")  # Gemini
    if isinstance(kandidaten, list) and kandidaten:
        teile = (kandidaten[0].get("content") or {}).get("parts") or []
        return "".join(t.get("text", "") for t in teile if isinstance(t, dict))
    wahlen = antwort.get("choices")  # OpenAI-Form
    if isinstance(wahlen, list) and wahlen:
        return str((wahlen[0].get("message") or {}).get("content") or "")
    nachricht = antwort.get("message")  # Ollama
    if isinstance(nachricht, dict) and "content" in nachricht:
        return str(nachricht["content"] or "")
    raise Mp4Fehler("Antwort des Sprachmodells enthaelt keinen Text (unbekannte Form)")


def _kopf(wahl: modelle.Wahl) -> dict[str, str]:
    """Die Anmelde-Kopfzeile des Anbieters; lokale Anbieter brauchen keine."""
    if modelle.ANBIETER[wahl.anbieter].schluessel_variable is None:
        return {}
    schluessel = wahl.schluessel() or ""
    if wahl.anbieter == "anthropic":
        return {"x-api-key": schluessel, "anthropic-version": "2023-06-01"}
    if wahl.anbieter == "gemini":
        return {"x-goog-api-key": schluessel}
    return {"authorization": f"Bearer {schluessel}"}


def baue_textmodell(*, transport: anfrage.Transport | None = None) -> Textmodell | None:
    """Das Sprachmodell aus der Umgebung als `Textmodell`, oder `None` ohne Anbieter.

    `transport` ist nur fuer Tests: ohne ihn geht die Anfrage ueber das Netz.
    """
    if not os.environ.get("MKN_LLM_ANBIETER"):
        return None
    try:
        wahl = modelle.waehle()
        kopf = _kopf(wahl)  # liest den Schluessel jetzt, nicht erst bei der ersten Anfrage
    except (
        modelle.UnbekannterAnbieter,
        modelle.KeinModellGewaehlt,
        modelle.KeinSchluessel,
    ) as fehler:
        raise Mp4Fehler(f"Sprachmodell: {fehler}") from fehler

    def modell(prompt: str, bilder: tuple[tuple[str, bytes], ...]) -> str:
        with tempfile.TemporaryDirectory(prefix="mkn-mp4-") as werk:
            pfade = []
            for i, (mime, daten) in enumerate(bilder):
                if mime not in _BILD_ENDUNGEN:
                    raise Mp4Fehler(
                        f"Bildtyp '{mime}' kann nicht an das Sprachmodell gehen "
                        f"(moeglich: {', '.join(_BILD_ENDUNGEN)})"
                    )
                pfad = Path(werk) / f"bild{i}{_BILD_ENDUNGEN[mime]}"
                pfad.write_bytes(daten)
                pfade.append(pfad)
            koerper = wahl.baue_anfrage(prompt, bilder=pfade, max_tokens=MAX_TOKENS)
        try:
            antwort = anfrage.sende(
                wahl.url(), koerper, kopf, zeitgrenze=ZEITGRENZE_S, transport=transport
            )
        except anfrage.AnfrageFehler as fehler:
            raise Mp4Fehler(f"Sprachmodell: {fehler}") from fehler
        return antwort_text(antwort)

    return modell


# -- Befehle --------------------------------------------------------------------------


def _meldung(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _parser_lauf(weg: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=WEGE[weg].befehl,
        description="Verwandelt eine Quelle (EPUB, PDF, Text, Foto) in eine Hoerdatei.",
        epilog=_zusatz(weg),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("quelle", help="EPUB, PDF, TXT, MD oder Bild (JPG, PNG, HEIC)")
    parser.add_argument(
        "--stimme", metavar="NAME", help="Stimme aus der Tabelle (Vorgabe: Standard)"
    )
    parser.add_argument(
        "--ansage",
        metavar="NAME",
        help="Stimme der Ansagen (Titel, Zwischenueberschriften; Vorgabe: Standard, mit "
        "--stimme diese)",
    )
    parser.add_argument(
        "--ziel", metavar="ORDNER", help="Ausgabeordner (Vorgabe: Ordner der Quelle)"
    )
    parser.add_argument(
        "--auswahl", metavar="K", help="nur diese Kapitel, ab 1: 3, 1-3, 2,5 (Vorgabe: alle)"
    )
    parser.add_argument(
        "--format",
        choices=("m4b", "mp3"),
        default="m4b",
        help="m4b mit Kapiteln (Vorgabe) oder mp3",
    )
    parser.add_argument(
        "--regie",
        choices=("voll", "buch", "aus"),
        default=None,
        help=(
            "wie weit die Regie Beiwerk weglaesst: voll (nur Haupttext und Ueberschriften), "
            "buch (nur Bildunterschriften, Seitenzahlen, Fussnoten, Bedienelemente), aus "
            "(alles lesen). Vorgabe: buch fuer ein EPUB, sonst voll"
        ),
    )
    if weg == "gemini":
        parser.add_argument(
            "--cloud-ok",
            action="store_true",
            help="Datenschutz-Hinweise vorab bestaetigen: der Text darf an Google gehen "
            "(fuer Skripte; ohne Terminal und ohne diese Option endet der Aufruf mit Exit 3)",
        )
        parser.add_argument(
            "--modell",
            metavar="ID",
            help="Gemini-Modell fuer diesen Lauf (Vorgabe: [wege.gemini].modell der Tabelle)",
        )
    return parser


def _waehle_stimme(tabelle: Stimmentabelle, name: str | None, weg: str, rolle: str):
    """Die benannte Stimme des Wegs; ein unbekannter oder fremder Name ist ein Bedienfehler."""
    if name is None:
        return None
    if name not in tabelle.namen(weg):
        raise _Bedienfehler(
            f"unbekannte {rolle} '{name}' (Stimmen des Wegs {weg}: {', '.join(tabelle.namen(weg))})"
        )
    return tabelle.hole(name, weg=weg)


def _schluessel_gemini(modell: str) -> str:
    """Der Gemini-Schluessel aus Umgebung oder Schluesseldatei -- oder ein klarer Abbruch."""
    try:
        schluessel = modelle.waehle("gemini", modell).schluessel()
    except modelle.KeinSchluessel as fehler:
        raise Mp4Fehler(f"Gemini-Schlüssel: {fehler}") from fehler
    if not schluessel:
        raise Mp4Fehler(
            "Gemini-Schlüssel fehlt: GEMINI_API_KEY setzen oder MKN_LLM_SCHLUESSEL_DATEI auf "
            "eine JSON-Datei mit dem Schlüssel zeigen lassen"
        )
    return schluessel


def _frage_cloud(a: argparse.Namespace) -> Callable[[tuple[Hinweis, ...]], bool]:
    """Die Rueckfrage bei Datenschutz-Hinweisen: Hinweise auf stderr, dann `[j/N]` am Terminal."""

    def frage(hinweise: tuple[Hinweis, ...]) -> bool:
        _meldung("Datenschutz-Hinweise (die Erkennung ist eine Untergrenze, Namen fehlen):")
        for h in hinweise:
            _meldung(f"  {h.klasse}: {h.anzahl} (Beispiel: {h.beispiel})")
        if a.cloud_ok:
            _meldung("Freigabe durch --cloud-ok: der Text geht an Google.")
            return True
        if not sys.stdin.isatty():
            return False
        print("Trotzdem an Google senden? [j/N] ", end="", file=sys.stderr, flush=True)
        return sys.stdin.readline().strip().lower() in ("j", "ja")

    return frage


def _lauf(argumente: Sequence[str], weg: str) -> int:
    a = _parser_lauf(weg).parse_args(argumente)
    quelle = Path(a.quelle).expanduser()
    if not quelle.is_file():
        raise _Bedienfehler(f"Quelle nicht gefunden: {quelle}")

    konfig = lade()
    tabelle = lade_tabelle(konfig.stimmen_tabelle)
    gewaehlt = _waehle_stimme(tabelle, a.stimme, weg, "Stimme")
    gewaehlt_ansage = _waehle_stimme(tabelle, a.ansage, weg, "Ansage-Stimme")
    if weg not in tabelle.wege:
        raise Mp4Fehler(f"Die Stimmen-Tabelle kennt den Weg '{weg}' nicht ([wege.{weg}] fehlt)")
    ziel = Path(a.ziel).expanduser() if a.ziel else quelle.parent

    if weg == "local" and konfig.arbeiter_python is None:
        raise Mp4Fehler(
            "Der Weg local braucht arbeiter_python in der Konfiguration "
            f"(nur der Weg gemini kommt ohne aus): {konfig.stimmen_tabelle.parent}"
        )
    schluessel = (
        _schluessel_gemini(a.modell or tabelle.wege["gemini"].modell) if weg == "gemini" else ""
    )

    textmodell = baue_textmodell()
    if textmodell is None:
        _meldung(
            "Hinweis: MKN_LLM_ANBIETER nicht gesetzt -- ohne Sprachmodell: Hörtext nur nach "
            "Regeln, Bilder per Texterkennung"
        )

    # Ohne --stimme gilt [standard.<weg>.<dokumentsprache>] (Spec 7.1, wie im Dienst): die
    # Sprache steht erst nach dem Lesen fest; die Quelle ist dafuer einmal gelesen.
    if gewaehlt is None:
        verz = Arbeitsverzeichnis.fuer_quelle(konfig.arbeitsort, quelle)
        sprache = lies_mit_zwischenstand(quelle, verz, textmodell, _meldung).sprache
        standard_text, standard_ansage, warnung = tabelle.standard_fuer(weg, sprache or "de")
        if warnung:
            _meldung(f"Hinweis: {warnung}")
        stimme = standard_text
        ansage = gewaehlt_ansage or standard_ansage
    else:
        stimme = gewaehlt
        ansage = gewaehlt_ansage or stimme

    with contextlib.ExitStack() as stapel:
        arbeiter = (
            stapel.enter_context(
                Arbeiter(konfig.arbeiter_python, whisper_modell=konfig.whisper_modell)
            )
            if konfig.arbeiter_python is not None
            else None
        )
        sprecher: Sprecher
        if weg == "local":
            assert arbeiter is not None  # oben geprueft
            sprecher = SprecherLokal(arbeiter, tabelle.wege["local"])
        else:
            wegkonfig = tabelle.wege["gemini"]
            if a.modell and a.modell != wegkonfig.modell:
                # Die Preise der Tabelle gehoeren dem Tabellen-Modell (Spec 8.7): fuer ein
                # anderes Modell gibt es keine Zahl statt einer falschen.
                wegkonfig = replace(
                    wegkonfig,
                    preis_usd_je_1m_text_token=None,
                    preis_usd_je_1m_audio_token=None,
                    preisstand=None,
                )
            sprecher = SprecherGemini(
                schluessel=schluessel,
                konfig=wegkonfig,
                modell=a.modell,
                arbeiter=arbeiter,
            )
        ergebnis = konvertiere(
            quelle,
            ziel,
            stimme,
            sprecher=sprecher,
            ansage=ansage,
            textmodell=textmodell,
            konfig=konfig,
            auswahl=a.auswahl,
            format=a.format,
            fortschritt=_meldung,
            regie_modus=a.regie,
            cloud_ok=_frage_cloud(a) if weg == "gemini" else False,
        )
    for datei in (*ergebnis.dateien, ergebnis.bericht):
        print(datei)
    if ergebnis.warnungen:
        _meldung(f"{len(ergebnis.warnungen)} Hinweise, siehe {ergebnis.bericht.name}")
    return 0


def _vorlage(argumente: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="mkn-mp4-local vorlage",
        description="Schneidet aus einer Aufnahme die ausdrucksstaerkste Stelle als Vorlage.",
    )
    parser.add_argument("aufnahme", help="Aufnahme der Stimme (laenger als die Vorlage)")
    parser.add_argument("--ziel", metavar="WAV", required=True, help="Vorlage (WAV) schreiben")
    parser.add_argument("--dauer", type=float, default=24.0, help="Sekunden (Vorgabe 24)")
    a = parser.parse_args(argumente)
    aufnahme = Path(a.aufnahme).expanduser()
    if not aufnahme.is_file():
        raise _Bedienfehler(f"Aufnahme nicht gefunden: {aufnahme}")
    konfig = lade()
    if konfig.arbeiter_python is None:
        raise Mp4Fehler("Die Vorlage braucht arbeiter_python in der Konfiguration")
    ziel = Path(a.ziel).expanduser()
    with Arbeiter(konfig.arbeiter_python, whisper_modell=konfig.whisper_modell) as arbeiter:
        messung = arbeiter.vorlage(aufnahme, ziel, a.dauer)
    print(ziel)
    _meldung(
        f"Ausschnitt ab {float(messung['start']):.1f} s, "
        f"Streuung {float(messung['streuung_ht']):.1f} Halbtöne".replace(".", ",")
    )
    return 0


def _stimmen(argumente: Sequence[str], weg: str) -> int:
    argparse.ArgumentParser(
        prog=f"{WEGE[weg].befehl} stimmen",
        description="Zeigt die Stimmen-Tabelle (* = Standard dieses Wegs).",
    ).parse_args(argumente)
    tabelle = lade_tabelle(lade().stimmen_tabelle)
    standards = {
        name
        for (standard_weg, _sprache), rollen in tabelle.standards.items()
        if standard_weg == weg
        for name in rollen
    }
    for name, stimme in tabelle.stimmen.items():
        marke = "*" if name in standards else " "
        print(
            f"{marke} {name}_v{stimme.version:02d}  {stimme.weg:<6}  {stimme.sprache}  "
            f"{stimme.stand:<11}  {stimme.beschreibung}"
        )
    return 0


def haupt(argv: Sequence[str] | None = None, *, weg: str) -> int:
    """Einstieg. Gibt den Exit-Code zurueck (0 gut, 1 Fehler, 2 Bedienfehler, 3 Rueckfrage)."""
    if weg not in WEGE:
        raise ValueError(f"unbekannter Weg {weg!r} (moeglich: {', '.join(WEGE)})")
    argumente = list(sys.argv[1:] if argv is None else argv)
    befehl = WEGE[weg].befehl
    try:
        if not argumente:
            _parser_lauf(weg).print_usage(sys.stderr)
            hilfe = "vorlage | stimmen" if weg == "local" else "stimmen"
            _meldung(f"Befehle: {befehl} <quelle> | {hilfe} ({befehl} --help)")
            return 2
        if argumente[0] == "vorlage":
            if weg != "local":
                raise _Bedienfehler(f"'vorlage' gibt es nur bei {WEGE['local'].befehl}")
            return _vorlage(argumente[1:])
        if argumente[0] == "stimmen":
            return _stimmen(argumente[1:], weg)
        return _lauf(argumente, weg)
    except SystemExit as ende:  # argparse: --help (0) und Bedienfehler (2)
        return ende.code if isinstance(ende.code, int) else 1
    except _Bedienfehler as fehler:
        _meldung(f"Fehler: {fehler}")
        return 2
    except RueckfrageNoetig as fehler:
        _meldung(f"Rückfrage nötig: {fehler}")
        _meldung(
            "Nichts wurde an Google gesendet. Mit --cloud-ok freigeben oder die Quelle ändern."
        )
        return 3
    except (Mp4Fehler, OSError) as fehler:
        _meldung(f"Fehler: {fehler}")
        return 1
    except KeyboardInterrupt:
        _meldung("Abgebrochen (der Lauf setzt mit demselben Aufruf fort)")
        return 130


def haupt_local(argv: Sequence[str] | None = None) -> int:
    """Einstieg `mkn-mp4-local`."""
    return haupt(argv, weg="local")


def haupt_gemini(argv: Sequence[str] | None = None) -> int:
    """Einstieg `mkn-mp4-gemini`."""
    return haupt(argv, weg="gemini")
