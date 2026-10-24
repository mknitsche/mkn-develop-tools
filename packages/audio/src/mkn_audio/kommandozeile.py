"""Die Kommandozeile `mkn-mp4`.

    mkn-mp4 <quelle> [--stimme NAME] [--ziel ORDNER] [--auswahl K] [--format m4b|mp3]
                     [--regie voll|buch|aus]
    mkn-mp4 vorlage <aufnahme> --ziel <wav> [--dauer 24]
    mkn-mp4 stimmen

**Exit-Codes.** 0 gut, 1 Fehler (Meldung auf stderr: die Quelle ist unbrauchbar, die
Umgebung defekt, ein Dienst antwortet nicht ...), 2 Bedienfehler (falsche Eingabe: gleich
neu aufrufen). Ein Skript soll den Unterschied sehen: bei 2 hilft Wiederholen nicht ohne
Aenderung des Aufrufs, bei 1 nicht ohne Aenderung der Umgebung.

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
import os
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from mkn_kern import anfrage, modelle

from mkn_audio.arbeiter_client import Arbeiter
from mkn_audio.konfig import lade
from mkn_audio.lauf import konvertiere
from mkn_audio.stimmen import lade_tabelle
from mkn_audio.typen import Mp4Fehler, Textmodell

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

_ZUSATZ = """\
weitere Befehle:
  mkn-mp4 vorlage <aufnahme> --ziel <wav> [--dauer 24]
      schneidet aus einer Aufnahme die ausdrucksstaerkste Stelle als Stimmvorlage
  mkn-mp4 stimmen
      zeigt die Stimmen-Tabelle

Das Sprachmodell kommt aus MKN_LLM_ANBIETER und MKN_LLM_MODELL (Schluessel je Anbieter);
ohne sie wird der Hoertext nur nach Regeln aufbereitet. Exit: 0 gut, 1 Fehler, 2 Bedienfehler.
"""


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


def _parser_lauf() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mkn-mp4",
        description="Verwandelt eine Quelle (EPUB, PDF, Text, Foto) in eine Hoerdatei.",
        epilog=_ZUSATZ,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("quelle", help="EPUB, PDF, TXT, MD oder Bild (JPG, PNG, HEIC)")
    parser.add_argument(
        "--stimme", metavar="NAME", help="Stimme aus der Tabelle (Vorgabe: Standard)"
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
    return parser


def _lauf(argumente: Sequence[str]) -> int:
    a = _parser_lauf().parse_args(argumente)
    quelle = Path(a.quelle).expanduser()
    if not quelle.is_file():
        raise _Bedienfehler(f"Quelle nicht gefunden: {quelle}")

    konfig = lade()
    tabelle = lade_tabelle(konfig.stimmen_tabelle)
    if a.stimme is not None and a.stimme not in tabelle.namen():
        raise _Bedienfehler(
            f"unbekannte Stimme '{a.stimme}' (verfuegbar: {', '.join(tabelle.namen())})"
        )
    stimme = tabelle.hole(a.stimme) if a.stimme is not None else tabelle.standard
    ziel = Path(a.ziel).expanduser() if a.ziel else quelle.parent

    textmodell = baue_textmodell()
    if textmodell is None:
        _meldung(
            "Hinweis: MKN_LLM_ANBIETER nicht gesetzt -- ohne Sprachmodell: Hörtext nur nach "
            "Regeln, Bilder per Texterkennung"
        )

    with Arbeiter(konfig.arbeiter_python, whisper_modell=konfig.whisper_modell) as arbeiter:
        ergebnis = konvertiere(
            quelle,
            ziel,
            stimme,
            arbeiter=arbeiter,
            textmodell=textmodell,
            konfig=konfig,
            auswahl=a.auswahl,
            format=a.format,
            fortschritt=_meldung,
            regie_modus=a.regie,
        )
    for datei in (*ergebnis.dateien, ergebnis.bericht):
        print(datei)
    if ergebnis.warnungen:
        _meldung(f"{len(ergebnis.warnungen)} Hinweise, siehe {ergebnis.bericht.name}")
    return 0


def _vorlage(argumente: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="mkn-mp4 vorlage",
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
    ziel = Path(a.ziel).expanduser()
    with Arbeiter(konfig.arbeiter_python, whisper_modell=konfig.whisper_modell) as arbeiter:
        messung = arbeiter.vorlage(aufnahme, ziel, a.dauer)
    print(ziel)
    _meldung(
        f"Ausschnitt ab {float(messung['start']):.1f} s, "
        f"Streuung {float(messung['streuung_ht']):.1f} Halbtöne".replace(".", ",")
    )
    return 0


def _stimmen(argumente: Sequence[str]) -> int:
    argparse.ArgumentParser(
        prog="mkn-mp4 stimmen", description="Zeigt die Stimmen-Tabelle (* = Standard)."
    ).parse_args(argumente)
    tabelle = lade_tabelle(lade().stimmen_tabelle)
    for name, stimme in tabelle.stimmen.items():
        marke = "*" if name == tabelle.standard_name else " "
        print(
            f"{marke} {name}_v{stimme.version:02d}  {stimme.sprache}  {stimme.stand:<11}  "
            f"{stimme.beschreibung}"
        )
    return 0


def haupt(argv: Sequence[str] | None = None) -> int:
    """Einstieg. Gibt den Exit-Code zurueck (0 gut, 1 Fehler, 2 Bedienfehler)."""
    argumente = list(sys.argv[1:] if argv is None else argv)
    befehle: dict[str, Callable[[Sequence[str]], int]] = {"vorlage": _vorlage, "stimmen": _stimmen}
    try:
        if not argumente:
            _parser_lauf().print_usage(sys.stderr)
            _meldung("Befehle: mkn-mp4 <quelle> | vorlage | stimmen (mkn-mp4 --help)")
            return 2
        return befehle.get(argumente[0], _lauf)(
            argumente[1:] if argumente[0] in befehle else argumente
        )
    except SystemExit as ende:  # argparse: --help (0) und Bedienfehler (2)
        return ende.code if isinstance(ende.code, int) else 1
    except _Bedienfehler as fehler:
        _meldung(f"Fehler: {fehler}")
        return 2
    except (Mp4Fehler, OSError) as fehler:
        _meldung(f"Fehler: {fehler}")
        return 1
    except KeyboardInterrupt:
        _meldung("Abgebrochen (der Lauf setzt mit demselben Aufruf fort)")
        return 130


if __name__ == "__main__":
    sys.exit(haupt())
