"""Liest die handschriftlichen Antworten aus den Entscheidungsordnern.

Was das Werkzeug nicht belegen konnte, hat ein Mensch beantwortet. Diese
Antworten sind die belastbarste Ortsquelle im ganzen System — und ohne dieses
Modul waeren sie Wegwerfarbeit: beim naechsten Lauf stuenden dieselben Ordner
wieder da, mit denselben Fragen.

Der Weg vom Fliesstext zur Koordinate geht ueber die Footprints. Eine Notiz sagt
*"Tag 1 - erster spot - Montag, 24. August 2026 um 07:23 / Lenggries im
findpinguines"*; verwertbar wird das, weil die GPX-Wegpunkte Namen UND
Koordinaten tragen. Der Name im Text findet den Wegpunkt.

**Kein Treffer heisst kein Anker.** *"Spontan auf einer wiese"* und *"irgendwo im
nirgendwo"* sind ehrliche Antworten ohne Ort. Sie duerfen keine Koordinate
erfinden — im Zweifel nicht schreiben. Der Text bleibt trotzdem erhalten: er ist
die Beschreibung, auch wenn er keine Koordinate hergibt.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from mkn_foto.modell import Anker

NOTIZ = "ort.md"

_UEBERSCHRIFTEN = ("## Ort", "## Gehoert zusammen mit")
"""BEIDE. Die Vorlage bietet zwei Felder, und KT-1 hat ueberwiegend unter dem
zweiten geschrieben — ein Leser, der nur das erste kennt, findet fast nichts und
meldet das als "keine Notizen" statt als eigenen Fehler. Firsthand passiert."""

_ORDNER = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{4})-(\d{4})")

_BELEG = ("footprint", "findpinguin", "findpenguin")
"""Ein Ortsname im Text macht noch keinen Ort. Erst der ausdrueckliche Verweis
auf einen Footprint macht ihn zur ZUORDNUNG statt zur blossen Erwaehnung.

Firsthand an KT-1s 20 Notizen gemessen — ohne diese Bedingung entstanden drei
falsche Anker, und alle drei aus Saetzen, die das Gegenteil sagen:

  "ganz spontan ... irgendwo im nirgendwo ... auf der Rueckfahrt VON Grainau"
  "wahrscheinlich irgendwie bei Mehrwald"
  "von Grainau unten Eibsee DENKE ICH"

Eine reine Namenssuche liest daraus einen Ort. Das ist genau das Erfinden, das
die oberste Regel verbietet: wird nicht sauber erkannt, was es ist, darf nichts
ergaenzt werden. Die acht Notizen MIT Beleg lesen sich anders — dort steht
"da gibt es einen footprint", "Lenggries im findpinguines", "Auch ein footprint"."""


@dataclass(frozen=True)
class Notiz:
    """Eine beantwortete Session: ihr Zeitfenster und was der Mensch dazu sagt."""

    von: datetime
    bis: datetime
    text: str
    ordner: str


def lies(wurzel: Path) -> list[Notiz]:
    """Sammelt alle ausgefuellten Notizen unterhalb von `wurzel`.

    Auch verschachtelt: KT-1 verschiebt beantwortete Ordner in einen
    Unterordner (`erl/`), sobald er sie abgearbeitet hat. Wer nur eine Ebene
    tief sucht, findet ausgerechnet die BEANTWORTETEN nicht.
    """
    gefunden: list[Notiz] = []
    for pfad in sorted(Path(wurzel).rglob(f"*/{NOTIZ}")):
        treffer = _ORDNER.search(pfad.parent.name)
        if treffer is None:
            continue
        text = _antwort(pfad.read_text(encoding="utf-8"))
        if not text:
            continue
        tag, von, bis = treffer.groups()
        gefunden.append(
            Notiz(
                von=datetime.strptime(f"{tag} {von}", "%Y-%m-%d %H%M"),
                bis=datetime.strptime(f"{tag} {bis}", "%Y-%m-%d %H%M"),
                text=text,
                ordner=pfad.parent.name,
            )
        )
    return gefunden


def zu_ankern(gelesen: Sequence[Notiz], footprints: Sequence[Anker]) -> list[Anker]:
    """Macht aus Notizen Anker, wo ein Ortsname einen Wegpunkt findet.

    Die ZEIT kommt aus dem Ordner, nicht aus dem Wegpunkt: der Anker muss in der
    Session liegen, die er beantwortet — sonst beantwortet er die Nachbarsession
    mit. Genommen wird die Mitte des Fensters.
    """
    # Nach NAMEN entdoppeln: zwei Wegpunkte mit demselben Namen sind derselbe
    # Ort, keine Alternative -- sonst waere jede Notiz mehrdeutig, sobald ein Ort
    # zweimal in der Spur steht (oder sobald ein aus einer Notiz erzeugter Anker
    # neben seinem eigenen Footprint liegt: der Ort machte sich dann SELBST
    # mehrdeutig, firsthand beim Verdrahten der Pipeline gesehen).
    je_name: dict[str, Anker] = {}
    for f in footprints:
        if f.name and f.name not in je_name:
            je_name[f.name] = f
    benannt = sorted(je_name.values(), key=lambda f: len(f.name or ""), reverse=True)
    anker: list[Anker] = []
    for n in gelesen:
        klein = n.text.lower()
        if not any(w in klein for w in _BELEG):
            # Der Name allein ist eine Erwaehnung, keine Zuordnung. Siehe _BELEG.
            continue
        treffer = [f for f in benannt if (f.name or "").lower() in klein]
        # Ein Name, der in einem laengeren steckt ("Kochel" in "Kochel am See"),
        # ist DERSELBE Treffer, keine Alternative -- sonst waere jeder Text mit
        # dem laengeren Namen mehrdeutig und faellt durch. `benannt` ist nach
        # Laenge absteigend sortiert, der erste ist damit der genaueste.
        echte = [
            f
            for f in treffer
            if not any(
                (f.name or "").lower() in (g.name or "").lower() for g in treffer if g is not f
            )
        ]
        if len(echte) != 1:
            # Kein Name: nichts zu holen. Mehrere: mehrdeutig, und Mehrdeutigkeit
            # ist ein Grund zu fragen, nicht zu raten.
            continue
        passend = echte[0]
        anker.append(
            Anker(
                zeit=n.von + (n.bis - n.von) / 2,
                lat=passend.lat,
                lon=passend.lon,
                name=passend.name,
            )
        )
    return anker


def _antwort(inhalt: str) -> str:
    """Zieht den vom Menschen geschriebenen Teil heraus — aus BEIDEN Feldern.

    Alles vor der ersten Ueberschrift stammt vom Werkzeug selbst und ist keine
    Antwort; es waere sonst in jeder Vorlage vorhanden und jede leere Vorlage
    saehe beantwortet aus.
    """
    stuecke: list[str] = []
    for ueberschrift in _UEBERSCHRIFTEN:
        if ueberschrift not in inhalt:
            continue
        dahinter = inhalt.split(ueberschrift, 1)[1]
        for zeile in dahinter.splitlines():
            if zeile.startswith("#"):
                break
            if zeile.strip():
                stuecke.append(zeile.strip())
    return " ".join(stuecke)
