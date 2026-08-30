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
from datetime import datetime, timedelta
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
                # Bis zum ENDE der Minute. Der Ordnername traegt Minuten, ein
                # Spot Sekunden -- bei einer Einzelaufnahme um 18:41:23 und einem
                # Ordner `1841-1841` ueberlappen die Fenster sonst nicht, und die
                # Antwort geht verloren. Firsthand: fuenf von KT-1 beantwortete
                # Sessions standen nach dem Lauf wieder auf der Frageliste --
                # genau das, was er zwei Stunden zuvor beanstandet hatte.
                bis=datetime.strptime(f"{tag} {bis}", "%Y-%m-%d %H%M") + timedelta(seconds=59),
                text=text,
                ordner=pfad.parent.name,
            )
        )
    return gefunden


def zu_ankern(
    gelesen: Sequence[Notiz],
    footprints: Sequence[Anker],
    *,
    urteile: dict[str, object] | None = None,
) -> list[Anker]:
    """Macht aus Notizen Anker, wo ein Ortsname einen Wegpunkt findet.

    Die ZEIT kommt aus dem Ordner, nicht aus dem Wegpunkt: der Anker muss in der
    Session liegen, die er beantwortet — sonst beantwortet er die Nachbarsession
    mit. Genommen wird die Mitte des Fensters.

    **`urteile` loest die Wortsuche ab** (KT-1, 2026-08-30: *"meine antworten
    wurden nicht intelligent interpretiert, sondern 1:1 uebernommen ... das ist
    doch bloedsinn"*). Liegt zu einer Notiz ein gelesenes Urteil vor, entscheidet
    es — sonst greift die alte Stichwortsuche weiter, damit ein Lauf ohne Modell
    nicht schlechter wird als vorher.

    Gemessen an KT-1s 20 echten Notizen: die Wortsuche erkannte neun und warf
    "Schon Zugspitze ganz oben", "also Stubaier Gletscher", "zu Hause" und jedes
    "vorheriger Ordner" weg. Das gelesene Urteil erkennt sie.
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
    urteile = urteile or {}
    anker: list[Anker] = []
    # Was eine frueher beantwortete Session ergeben hat -- fuer "vorheriger
    # Ordner". Die Notizen kommen in zeitlicher Reihenfolge, also steht der
    # Bezugspunkt schon fest, wenn der Verweis darauf gelesen wird.
    zuletzt: Anker | None = None

    for n in sorted(gelesen, key=lambda x: x.von):
        klein = n.text.lower()
        urteil = urteile.get(n.ordner)

        if urteil is not None:
            gesucht = _aus_urteil(urteil, zuletzt)
            if gesucht is None:
                continue
            if isinstance(gesucht, Anker):
                # Ein Bezug erbt den Ort, aber nie die Zeit: der Anker muss in
                # SEINER Session liegen, sonst beantwortet er die falsche.
                zuletzt = Anker(
                    zeit=n.von + (n.bis - n.von) / 2,
                    lat=gesucht.lat,
                    lon=gesucht.lon,
                    name=gesucht.name,
                )
                anker.append(zuletzt)
                continue
            klein = gesucht.lower()
        elif not any(w in klein for w in _BELEG):
            # Ohne Urteil bleibt es bei der Stichwortsuche: der Name allein ist
            # eine Erwaehnung, keine Zuordnung. Siehe _BELEG.
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
        zuletzt = Anker(
            zeit=n.von + (n.bis - n.von) / 2,
            lat=passend.lat,
            lon=passend.lon,
            name=passend.name,
        )
        anker.append(zuletzt)
    return anker


def _aus_urteil(urteil: object, zuletzt: Anker | None) -> str | Anker | None:
    """Was ein gelesenes Urteil zur Ortssuche beitraegt.

    Drei Ausgaenge, und die Unterscheidung ist der ganze Punkt:

      `Anker`  der Bezug ist aufgeloest — derselbe Ort wie die Session davor
      `str`    ein Ortsname, mit dem in den Wegpunkten gesucht wird
      `None`   nichts zu holen: Vermutung, kein Ort, oder zu verwerfen

    **Regel A** (Spec Paragraf 10a): nur was der Mensch SICHER genannt hat, wird
    zum Anker. Eine Vermutung bleibt im Protokoll und geht nicht in die Datei --
    genau die Regel, deren Fehlen frueher drei falsche Anker erzeugt hat.
    """
    if not getattr(urteil, "sicher", False):
        return None

    art = getattr(urteil, "art", "")
    if art == "bezug":
        return zuletzt
    if art != "zuordnung":
        return None

    ort = (getattr(urteil, "ort", "") or "").strip()
    return ort or None


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
