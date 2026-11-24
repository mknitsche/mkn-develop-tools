"""Befehle ``mkn-dokument lesen | seiten | ablesen <datei> --aus <ordner>``, ``mkn-dokument epub <datei>`` und
``mkn-dokument deckblatt setzen | abnehmen | lesen``.

``lesen`` liest gedruckte Angaben mit Wert, ``seiten`` Kopf, Texte und Diagramm-Verzeichnis je Seite, ``ablesen``
die Stellen eines Diagramms nach einem Ableseauftrag (``--auftrag <datei.json>``). ``epub`` gibt Metadaten und
Kapitelliste eines EPUB als JSON aus (ohne Modell, ohne Leser). ``deckblatt`` setzt eine Seite vor ein PDF, nimmt
sie wieder ab oder liest ihre Kennung (ohne Modell, ohne Leser). Die Bausteine fuer die Modell-Anfrage werden erst
geladen, wenn ein Lese-Befehl sie braucht.

Die zwei Leser waehlt der Anwender: ``--leser-a`` und ``--leser-b`` als
``anbieter:modell`` oder ueber ``MKN_DOKUMENT_LESER_A`` / ``MKN_DOKUMENT_LESER_B``.
Es gibt keine Vorgabe — wer nichts waehlt, bekommt eine Frage und keine Rechnung.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from mkn_dokument import deckblatt, epub

if TYPE_CHECKING:
    from mkn_dokument import seitenlesung
    from mkn_dokument.leser import KernLeser


def _leser(angabe: str | None, variable: str) -> KernLeser:
    from mkn_kern import modelle

    from mkn_dokument.leser import KernLeser

    angabe = angabe or os.environ.get(variable)
    if not angabe or ":" not in angabe:
        raise modelle.KeinModellGewaehlt(
            f"Leser nicht gewaehlt: --{variable.removeprefix('MKN_DOKUMENT_').lower().replace('_', '-')} "
            f"oder {variable} als anbieter:modell angeben"
        )
    anbieter, modell = angabe.split(":", 1)
    return KernLeser(modelle.waehle(anbieter, modell))


def _anbieter(leser: object) -> str | None:
    wahl = getattr(leser, "wahl", None)
    return getattr(wahl, "anbieter", None)


def _woerter(angabe: str | None) -> tuple[str, ...] | None:
    """Komma-getrennte Woerter; ``None``, wenn nicht angegeben. Ein leeres Wort weist ``Fach`` ab."""
    return None if angabe is None else tuple(w.strip() for w in angabe.split(","))


def _fach(args: argparse.Namespace) -> seitenlesung.Fach:
    from mkn_dokument import seitenlesung

    angaben = {
        "dokumentart": args.dokumentart,
        "seitenarten": _woerter(args.seitenarten),
        "inhaltsarten": _woerter(args.inhaltsarten),
        "textarten": _woerter(args.textarten),
        "datum_hinweis": args.datum_hinweis,
    }
    return seitenlesung.Fach(**{k: v for k, v in angaben.items() if v is not None})


def _befehl(befehle: argparse._SubParsersAction, name: str, hilfe: str) -> argparse.ArgumentParser:
    p = befehle.add_parser(name, help=hilfe)
    p.add_argument("datei", type=Path)
    p.add_argument("--aus", type=Path, required=True, help="Arbeitsordner fuer Seitenbilder, Mitschrift, Ergebnis")
    p.add_argument("--leser-a", help="anbieter:modell des ersten Lesers")
    p.add_argument("--leser-b", help="anbieter:modell des zweiten Lesers (anderer Anbieter)")
    return p


def _melde(args: argparse.Namespace, ergebnis: dict) -> None:
    from mkn_dokument import ablesen, lesen, seitenlesung

    if args.befehl == "lesen":
        zahl, datei, vorne = lesen.zaehle(ergebnis), lesen.ERGEBNIS, f"{ergebnis['quelle']['seiten']} Seite(n)"
    elif args.befehl == "seiten":
        zahl = seitenlesung.zaehle(ergebnis)
        vorne = f"{zahl.pop('seiten')} Seite(n)"
        datei = seitenlesung.ERGEBNIS
    else:
        zahl, datei, vorne = ablesen.zaehle(ergebnis), ablesen.ERGEBNIS, f"Seite {ergebnis['seite']}"
    teile = ", ".join(f"{k} {v}" for k, v in sorted(zahl.items()))
    print(f"{vorne}: {teile or 'keine Angaben'} -> {args.aus / datei}")


def _epub(datei: Path) -> int:
    """Metadaten und Kapitelliste (Titel, Zeichen) als JSON; ein geschuetztes Buch ohne Kapitel."""
    try:
        buch = epub.epub_buch(datei)
    except (epub.EpubLesefehlerError, OSError) as exc:
        print(f"mkn-dokument: {exc}", file=sys.stderr)
        return 1
    aus = {
        "titel": buch.titel,
        "autoren": list(buch.autoren),
        "verlag": buch.verlag,
        "sprache": buch.sprache,
        "datum": buch.datum,
        "isbns": list(buch.isbns),
        "geschuetzt": buch.geschuetzt,
        "kapitel": [{"titel": k.titel, "zeichen": len(k.text)} for k in buch.kapitel],
    }
    print(json.dumps(aus, ensure_ascii=False, indent=2))
    return 0


def _paare(texte: list[str], schalter: str) -> tuple[tuple[str, str], ...]:
    """``Beschriftung=Wert``, geteilt am ersten ``=``; ohne ``=`` oder mit leerer Seite ein Abbruch."""
    paare = []
    for text in texte:
        name, gleich, wert = text.partition("=")
        if not gleich or not name.strip() or not wert.strip():
            raise ValueError(f"{schalter} {text!r}: erwartet 'Beschriftung=Wert'")
        paare.append((name.strip(), wert.strip()))
    return tuple(paare)


def _deckblatt_befehle(befehle: argparse._SubParsersAction) -> None:
    d = befehle.add_parser("deckblatt", help="Deckblatt vor ein PDF setzen, wieder abnehmen oder lesen")
    arten = d.add_subparsers(dest="art", required=True)
    s = arten.add_parser(
        "setzen",
        help="Seite vorn dazu: Titel, Datum, Herkunft, Schlagworte, Verweise, Status",
        description="Setzt ein Deckblatt vor die Quelle; das Ziel wird nie ueberschrieben. Ein signiertes PDF wird "
        "abgewiesen. Eine zugesicherte PDF/A-Konformitaet der Quelle bleibt nicht erhalten.",
    )
    s.add_argument("quelle", type=Path)
    s.add_argument("--aus", type=Path, required=True, help="Ziel-PDF (darf noch nicht existieren)")
    s.add_argument("--titel", required=True)
    s.add_argument("--datum", required=True, help="JJJJ, JJJJ-MM oder JJJJ-MM-TT")
    s.add_argument("--quelle", dest="herkunft", default="", help="woher das Dokument kommt")
    s.add_argument("--tag", action="append", default=[], help="Schlagwort (mehrfach)")
    for schalter in ("link", "status", "angabe"):
        s.add_argument(f"--{schalter}", action="append", default=[], metavar="BESCHRIFTUNG=WERT")
    s.add_argument("--marke", default="", help="Zeile ueber dem Titel (Vorgabe: keine)")
    s.add_argument("--css", type=Path, help="CSS-Datei fuer die Gestaltung der Seite")
    s.add_argument("--schriften", type=Path, help="Ordner mit Schriftdateien fuer @font-face im CSS")
    a = arten.add_parser(
        "abnehmen",
        help="Deckblatt wieder abnehmen",
        description="Entfernt ein Deckblatt dieses Werkzeugs (Kennung und Pruefsumme muessen passen). Das Ergebnis "
        "ist inhaltsgleich mit dem, was hinter dem Deckblatt lag, aber nicht bytegleich mit der urspruenglichen "
        "Quelle - wer das Original bytegenau braucht, hebt es auf (die Kennung nennt seinen SHA-256).",
    )
    a.add_argument("quelle", type=Path)
    a.add_argument("--aus", type=Path, required=True, help="Ziel-PDF (darf noch nicht existieren)")
    le = arten.add_parser("lesen", help="Kennung des Deckblatts als JSON ausgeben")
    le.add_argument("quelle", type=Path)


def _deckblatt(args: argparse.Namespace) -> int:
    """Ohne Modell: setzen, abnehmen oder lesen; jeder Abbruch ist Exit 1 mit einem Satz auf stderr."""
    try:
        if args.art == "setzen":
            angaben = deckblatt.Angaben(
                titel=args.titel,
                datum=args.datum,
                quelle=args.herkunft,
                tags=tuple(args.tag),
                links=_paare(args.link, "--link"),
                status=_paare(args.status, "--status"),
                weitere=_paare(args.angabe, "--angabe"),
                marke=args.marke,
            )
            css = args.css.read_text(encoding="utf-8") if args.css else ""
            ziel = deckblatt.setzen(
                args.quelle, args.aus, angaben, stil=deckblatt.Stil(css=css, schriften=args.schriften)
            )
        elif args.art == "abnehmen":
            ziel = deckblatt.abnehmen(args.quelle, args.aus)
        else:
            print(json.dumps(deckblatt.lesen(args.quelle), ensure_ascii=False, indent=2))
            return 0
    except (deckblatt.DeckblattFehler, OSError, ValueError) as exc:
        print(f"mkn-dokument: {exc}", file=sys.stderr)
        return 1
    print(ziel)
    return 0


def haupt(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mkn-dokument", description=__doc__.splitlines()[0])
    befehle = parser.add_subparsers(dest="befehl", required=True)
    p = _befehl(befehle, "lesen", "Dokument (PDF, Scan, Foto) mit zwei Lesern lesen und abgleichen")
    p.add_argument("--dokumentart", default="eines Dokuments", help='z. B. "eines medizinischen Belegs"')
    s = _befehl(befehle, "seiten", "Seitenkopf, Fliesstexte und Diagramm-Verzeichnis je Seite lesen und abgleichen")
    s.add_argument("--dokumentart", help='z. B. "eines medizinischen Belegs"')
    s.add_argument("--seitenarten", help="erlaubte Seitenarten, mit Komma getrennt")
    s.add_argument("--inhaltsarten", help="erlaubte Inhaltsarten, mit Komma getrennt (ohne: frei)")
    s.add_argument("--textarten", help="erlaubte Textarten, mit Komma getrennt (ohne: frei)")
    s.add_argument("--datum-hinweis", help="welches Datum massgeblich ist, als Satzteil")
    a = _befehl(befehle, "ablesen", "Stellen eines Diagramms nach Ableseauftrag ablesen und abgleichen")
    a.add_argument("--auftrag", type=Path, required=True, help="Ableseauftrag als JSON-Datei")
    e = befehle.add_parser("epub", help="Metadaten und Kapitelliste eines EPUB als JSON")
    e.add_argument("datei", type=Path)
    _deckblatt_befehle(befehle)
    args = parser.parse_args(argv)
    if args.befehl == "epub":
        return _epub(args.datei)
    if args.befehl == "deckblatt":
        return _deckblatt(args)
    return _lesebefehl(args)


def _lesebefehl(args: argparse.Namespace) -> int:
    """``lesen``, ``seiten`` oder ``ablesen``: zwei Leser, je eine Modell-Anfrage pro Seite."""
    from mkn_kern import anfrage, modelle

    from mkn_dokument import ablesen, lesen, seiten, seitenlesung
    from mkn_dokument.auftrag import AntwortUngueltig
    from mkn_dokument.leser import LeserFehler

    try:
        leser_a = _leser(args.leser_a, "MKN_DOKUMENT_LESER_A")
        leser_b = _leser(args.leser_b, "MKN_DOKUMENT_LESER_B")
        if _anbieter(leser_a) is not None and _anbieter(leser_a) == _anbieter(leser_b):
            raise ValueError(
                f"Beide Leser kommen von {_anbieter(leser_a)!r}: Modelle derselben Herkunft irren gemeinsam, "
                "ihre Uebereinstimmung prueft zu wenig. Waehle zwei verschiedene Anbieter."
            )
        if args.befehl == "lesen":
            ergebnis = lesen.lies_dokument(args.datei, args.aus, leser_a, leser_b, dokumentart=args.dokumentart)
        elif args.befehl == "seiten":
            ergebnis = seitenlesung.lies_seiten(args.datei, args.aus, leser_a, leser_b, fach=_fach(args))
        else:
            auftrag = json.loads(args.auftrag.read_text(encoding="utf-8"))
            ergebnis = ablesen.lies_ablesung(args.datei, args.aus, leser_a, leser_b, auftrag)
    except (
        seiten.SeitenFehler,
        LeserFehler,
        AntwortUngueltig,
        anfrage.AnfrageFehler,
        modelle.KeinModellGewaehlt,
        modelle.UnbekannterAnbieter,
        modelle.KeinSchluessel,
        OSError,  # Auftragsdatei fehlt oder ist nicht lesbar
        ValueError,  # auch kaputtes JSON und ein kaputter Ableseauftrag
    ) as exc:
        print(f"mkn-dokument: {exc}", file=sys.stderr)
        return 1
    _melde(args, ergebnis)
    return 0


if __name__ == "__main__":
    raise SystemExit(haupt())
