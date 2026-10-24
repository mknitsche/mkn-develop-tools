"""Export des gelesenen und verstandenen Dokuments ins gemeinsame Bereichs-Manifest.

**Warum es das gibt.** Mehrere Werkzeuge erschliessen Quellen. Damit ein spaeterer
gemeinsamer Erschliesser dieselbe Sprache findet, schreibt dieses Paket sein Ergebnis in das
gemeinsame Bereichs-Manifest (Format siehe README): je Quelle EINE JSON-Datei mit
Abschnitten, Bereichen (Art, Lesereihenfolge, Text) und einer Text-Bilanz.

**Keine Fachlogik, kein Weglassen.** Das Manifest zeigt ALLES, jeden Absatz mit seiner
Art; was davon gesprochen wird (nur Haupttext und Ueberschrift, `regie.WORTLAUT_ROLLEN`),
ist Sache des Abnehmers. Wuerde diese Stufe selbst auslassen, erfuehre der Abnehmer nie,
dass etwas fehlt. Der Text bleibt Zeichen fuer Zeichen, wie ihn der Leser geliefert hat.

**Die Bilanz ist ehrlich, nicht schoen.** Was der Leser VOR den Rollen schon entfernt hat
(Kopf-/Fusszeilen), steht als `rest`: die Erschliessung gilt dann als nicht vollstaendig
(Regel 1 der Schnittstelle). Das soll sichtbar sein; ein stilles "alles zugeordnet" waere
falsch.

**Was dieses Paket nicht weiss**, bleibt leer statt geraten: Seiten, Lage, Datum
(`""`), Seitenzahl des Dokuments. `handschrift` ist immer `False` -- erkannt wird sie hier
nicht. Der Quellpfad ist nur der Dateiname: ein Manifest traegt den Inhalt der Quelle
(TLP wie die Quelle), aber nicht deren Ablageort.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mkn_audio.arbeitsverzeichnis import schreibe_atomar
from mkn_audio.regie import Rollenbild
from mkn_audio.typen import Dokument, Mp4Fehler

ART_VON_ROLLE = {
    "haupttext": "fliesstext",
    "ueberschrift": "ueberschrift",
    "metadaten": "kopf",
    "uebersicht": "uebersicht",
    "bildunterschrift": "bildunterschrift",
    "zitatkasten": "zitatkasten",
    "bedienelement": "bedienelement",
    "fussnote": "fussnote",
    "tabelle": "wert_tabelle",
    "seitenzahl": "seitenzahl",
}
"""Rolle der Regie -> `art` der Schnittstelle. Jede Rolle hat genau eine Art (Test)."""

HERKUENFTE = ("textschicht", "ocr", "bildmodell")
"""Woher der Text eines Bereichs stammt (feste Liste der Schnittstelle)."""

_GRUND_VOR_ROLLEN = "vom Leser vor den Rollen entfernt"


def _woerter(text: str) -> int:
    """Wortzahl durch Leerraum-Trennung: bewusst ohne Sprachregeln, damit der Nenner des
    Abnehmers (der denselben Text anders zaehlen koennte) nicht von hier abhaengt."""
    return len(text.split())


def als_manifest(
    dok: Dokument,
    rollenbild: Rollenbild | None,
    *,
    quelle: Path,
    sha256: str,
    herkunft: str,
    leser: str,
    weggelassen_vor_rollen: int = 0,
) -> dict[str, Any]:
    """Das Bereichs-Manifest zu `dok`.

    `rollenbild=None` (Regie nicht gelaufen): alles `fliesstext`, `dokumentart` leer.
    `herkunft` gilt fuers ganze Dokument (so liest `lies` jede Quelle). `leser` nennt
    Werkzeug oder Modell. `weggelassen_vor_rollen` sind die Woerter, die der Leser vor den
    Rollen entfernt hat; sie gehen als `rest` in die Bilanz, nicht verloren.
    """
    if herkunft not in HERKUENFTE:
        raise Mp4Fehler(f"Manifest: unbekannte herkunft {herkunft!r} (erlaubt: {HERKUENFTE})")
    rollen = rollenbild.rollen if rollenbild is not None else {}

    abschnitte: list[dict[str, Any]] = []
    reihenfolge = 0
    woerter_zugeordnet = 0
    for k, kapitel in enumerate(dok.kapitel):
        bereiche: list[dict[str, Any]] = []
        for a, text in enumerate(kapitel.absaetze):
            rolle = rollen.get((k, a), "haupttext")
            if rolle not in ART_VON_ROLLE:
                # Eine Rolle ohne Art wuerde sonst still zu etwas anderem: laut statt raten.
                raise Mp4Fehler(
                    f"Manifest: Rolle {rolle!r} bei Kapitel {k}, Absatz {a} hat keine Art"
                )
            reihenfolge += 1
            woerter_zugeordnet += _woerter(text)
            bereiche.append(
                {
                    "nr": a + 1,
                    "reihenfolge": reihenfolge,
                    "art": ART_VON_ROLLE[rolle],
                    "titel": None,
                    "seite": None,
                    "text": text,
                    "handschrift": False,
                    "herkunft": herkunft,
                    "lage": None,
                    "leser": leser,
                }
            )
        abschnitte.append(
            {
                "nr": k + 1,
                "titel": kapitel.titel,
                "seite_von": None,
                "seite_bis": None,
                "bereiche": bereiche,
            }
        )

    rest = (
        [{"grund": _GRUND_VOR_ROLLEN, "woerter": weggelassen_vor_rollen}]
        if weggelassen_vor_rollen > 0
        else []
    )
    return {
        "quelle": {
            "pfad": Path(quelle).name,
            "sha256": sha256,
            "dokumentart": rollenbild.dokumentart if rollenbild is not None else "",
            "titel": dok.titel,
            "autor": dok.autor,
            "datum": "",
            "sprache": dok.sprache,
            "seiten_gesamt": None,
        },
        "abschnitte": abschnitte,
        "text_bilanz": {
            "woerter_gesamt": woerter_zugeordnet + max(weggelassen_vor_rollen, 0),
            "woerter_zugeordnet": woerter_zugeordnet,
            "rest": rest,
        },
    }


def schreibe_manifest(manifest: dict[str, Any], ziel: Path) -> Path:
    """Schreibt das Manifest atomar nach `ziel` (UTF-8, Umlaute im Klartext).

    Erst serialisiert, dann geschrieben: ein nicht darstellbarer Wert bricht ab, BEVOR die
    alte Datei angefasst wird.
    """
    ziel = Path(ziel)
    text = json.dumps(manifest, ensure_ascii=False, indent=2)
    schreibe_atomar(ziel, text.encode("utf-8"))
    return ziel
