"""Der Lauf: ein Dokument lesen und das abgeglichene Ergebnis ablegen.

**Die Mitschrift macht den Lauf wiederholbar und billig.** Jede Antwort eines Lesers
liegt unter dem Hash aus Seitenbild, Auftrag und Leser-Kennung. Gleiche Eingabe liest
die gemerkte Antwort; ein abgebrochener Lauf zahlt beim zweiten Anlauf nur, was fehlt.

Die Bausteine des Laufs (``schreibe``, ``gemerkt``, ``bereite_vor``) teilen sich alle
Funktionen des Pakets (``lesen``, ``seitenlesung``, ``ablesen``).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mkn_dokument import __version__, abgleich, auftrag, seiten
from mkn_dokument.leser import Leser

ERGEBNIS = "ergebnis.json"
MITSCHRIFT = "mitschrift"
SEITEN = "seiten"


def schreibe(pfad: Path, objekt: object) -> None:
    """Atomar und nur fuer den Besitzer lesbar."""
    pfad.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    neu = pfad.with_name(pfad.name + ".neu")
    fd = os.open(neu, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        os.fchmod(f.fileno(), 0o600)  # auch wenn ein Zwischenstand mit weiteren Rechten schon dalag
        json.dump(objekt, f, ensure_ascii=False, indent=1)
    os.replace(neu, pfad)


def gemerkt[T](leser: Leser, text: str, bild: Path, ordner: Path, pruefe: Callable[[object], T]) -> tuple[T, Any]:
    """Die gepruefte Antwort eines Lesers zu einem Seitenbild, aus der Mitschrift oder frisch vom Leser.

    Rueckgabe: ``(pruefe(antwort), antwort)``. ``pruefe`` bricht laut bei falscher Form; erst geprueft, dann
    gemerkt — eine ungueltige Antwort wird nie Mitschrift.
    """
    h = hashlib.sha256()
    for teil in (bild.read_bytes(), text.encode(), leser.kennung.encode()):
        h.update(hashlib.sha256(teil).digest())
    pfad = ordner / MITSCHRIFT / f"{h.hexdigest()}.json"
    if pfad.exists():
        antwort = json.loads(pfad.read_text(encoding="utf-8"))
        return pruefe(antwort), antwort
    antwort = leser.lies(text, bild)
    geprueft = pruefe(antwort)
    schreibe(pfad, antwort)
    return geprueft, antwort


def bereite_vor(eingabe: Path, ordner: Path, leser_a: Leser, leser_b: Leser) -> tuple[dict[str, Any], list[Path]]:
    """Leser pruefen, Arbeitsordner (0700) anlegen, Seitenbilder rendern.

    Rueckgabe: ``(quelle, bilder)`` mit ``quelle = {"name", "sha256", "seiten"}``.
    """
    if leser_a.kennung == leser_b.kennung:
        raise ValueError("Beide Leser sind derselbe: Uebereinstimmung mit sich selbst prueft nichts")
    # Der Hash gehoert zu dem Stand, der gleich gerendert wird — nicht zu dem, der nach den Lesungen dort liegt.
    sha256 = hashlib.sha256(eingabe.read_bytes()).hexdigest() if eingabe.is_file() else None
    ordner.mkdir(parents=True, exist_ok=True)
    ordner.chmod(0o700)  # der Arbeitsordner ist so vertraulich wie das Dokument, auch seine Dateinamen
    bilder = seiten.seitenbilder(eingabe, ordner / SEITEN)
    return {"name": eingabe.name, "sha256": sha256, "seiten": len(bilder)}, bilder


def lies_dokument(
    eingabe: Path,
    ordner: Path,
    leser_a: Leser,
    leser_b: Leser,
    *,
    dokumentart: str = "eines Dokuments",
) -> dict[str, Any]:
    """Liest ``eingabe`` Seite fuer Seite mit beiden Lesern, gleicht ab und schreibt ``ordner/ergebnis.json``.

    Rueckgabe und Datei: ``{"fassung", "quelle": {"name", "sha256", "seiten"}, "leser": {"a", "b"},
    "angaben": [...]}`` — je Angabe die Felder aus ``abgleich.gleiche_ab`` plus ``seite``. Jeder Fehler eines
    Lesers bricht den Lauf laut ab; die Mitschrift der fertigen Seiten bleibt.
    """
    eingabe = Path(eingabe)
    ordner = Path(ordner)
    quelle, bilder = bereite_vor(eingabe, ordner, leser_a, leser_b)
    text = auftrag.auftrag(dokumentart)
    angaben: list[dict[str, Any]] = []
    for nr, bild in enumerate(bilder, start=1):
        a, _ = gemerkt(leser_a, text, bild, ordner, auftrag.pruefe_antwort)
        b, _ = gemerkt(leser_b, text, bild, ordner, auftrag.pruefe_antwort)
        for eintrag in abgleich.gleiche_ab(a, b):
            angaben.append({"seite": nr, **eintrag})
    ergebnis = {
        "fassung": __version__,
        "quelle": quelle,
        "leser": {"a": leser_a.kennung, "b": leser_b.kennung},
        "angaben": angaben,
    }
    schreibe(ordner / ERGEBNIS, ergebnis)
    return ergebnis


def zaehle(ergebnis: dict[str, Any]) -> dict[str, int]:
    """Wie viele Angaben welchen Ausgang haben (``uebernommen`` und je Grund der Klaerliste)."""
    zahl: dict[str, int] = {}
    for angabe in ergebnis["angaben"]:
        schluessel = "uebernommen" if angabe["ausgang"] == "uebernommen" else angabe["grund"]
        zahl[schluessel] = zahl.get(schluessel, 0) + 1
    return zahl
