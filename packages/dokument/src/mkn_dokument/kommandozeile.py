"""Befehle ``mkn-dokument lesen | seiten | ablesen <datei> --aus <ordner>``.

``lesen`` liest gedruckte Angaben mit Wert, ``seiten`` Kopf, Texte und Diagramm-Verzeichnis je Seite, ``ablesen``
die Stellen eines Diagramms nach einem Ableseauftrag (``--auftrag <datei.json>``).

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

from mkn_kern import anfrage, modelle

from mkn_dokument import ablesen, lesen, seiten, seitenlesung
from mkn_dokument.auftrag import AntwortUngueltig
from mkn_dokument.leser import KernLeser, LeserFehler


def _leser(angabe: str | None, variable: str) -> KernLeser:
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
    args = parser.parse_args(argv)
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
