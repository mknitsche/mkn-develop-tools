"""Der Leseauftrag an beide Leser und die Pruefung ihrer Antwort.

**Ein Auftrag fuer beide.** Die Leser sollen dieselbe Frage unabhaengig beantworten;
nur dann sagt ihre Uebereinstimmung etwas. Ein Fach (Gesundheit, Rechnungen, ...)
gibt hoechstens einen Hinweis-Absatz mit — die Regeln des Lesens bleiben gleich.
"""

from __future__ import annotations

from typing import Any

from mkn_dokument.abgleich import FELDER

ARTEN = ("messwert", "vorwert", "zielwert", "angabe")
"""Arten einer Angabe: Ergebnis dieses Dokuments, frueheres Ergebnis, Soll oder Grenze, Stammdaten und Rahmen."""

_REGELN = """Erfasse JEDE gedruckte Angabe, die einen Zahlen- oder Messwert traegt: Tabellenzeilen, Kopfangaben, beschriftete Zahlen an Balken und in Diagrammen, Verlaufswerte, Zielwerte.

Regeln:
- Schreibe jedes Zeichen genau so, wie es gedruckt ist (Komma oder Punkt als Dezimalzeichen wie gedruckt, fuehrende und abschliessende Nullen, Doppelpunkt in Zeiten, Vorzeichen). Nichts runden, nichts umrechnen, nichts ergaenzen.
- Lies nur gedruckte Zahlen. Lies KEINE Werte an Achsen oder Kurven ab, die nicht als Zahl dastehen. Achsenskalen und Skalenstriche sind keine Angaben.
- "bezeichnung": der gedruckte Name der Groesse, so wie er in dieser Zeile steht (ohne Einheit).
- "abschnitt": die Ueberschrift des Abschnitts oder der Tabelle, in der die Angabe steht (leer, wenn keine).
- "zusatz": was die Angabe innerhalb des Abschnitts eindeutig macht, wenn die Bezeichnung allein nicht reicht: Spaltenkopf, Koerperteil, Datum der Spalte, Zeitangabe in Klammern (leer, wenn nicht noetig).
- "art": "messwert" (Ergebnis dieser Untersuchung oder dieses Dokuments), "vorwert" (Ergebnis einer frueheren Untersuchung, z. B. Verlaufsspalten), "zielwert" (Soll, Empfehlung, Grenze), "angabe" (Stammdaten und Rahmen: Groesse, Alter, Datum, Dauer, Kennnummern).
- "wert": nur der Wert selbst, ohne Einheit und ohne Vergleichszeichen. "vergleich": ein gedrucktes Zeichen < > <= >= vor dem Wert, sonst leer.
- "einheit": wie gedruckt, ohne Klammern (leer, wenn keine gedruckt ist).
- "bereich": der gedruckte Referenz- oder Normalbereich zu diesem Wert, ohne Klammern (leer, wenn keiner).
- "kennzeichen": gedruckte Markierung am Wert (z. B. +, -, *, H, L, Pfeil als "hoch"/"tief"), sonst leer.
- "lage": Rechteck um den WERT im Bild als [oben, links, unten, rechts] in Tausendstel der Bildhoehe und Bildbreite.
- Jede Angabe genau einmal je Stelle im Bild. Steht derselbe Wert an zwei Stellen gedruckt, sind das zwei Angaben.
- Ist eine Zahl nicht sicher lesbar, erfasse sie trotzdem und setze "unsicher": true.

Antworte nur mit JSON: {"angaben": [{"abschnitt": "", "bezeichnung": "", "zusatz": "", "art": "", "wert": "", "vergleich": "", "einheit": "", "bereich": "", "kennzeichen": "", "lage": [0,0,0,0], "unsicher": false}]}"""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "angaben": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {feld: {"type": "string"} for feld in FELDER}
                | {
                    "lage": {"type": "array", "items": {"type": "integer"}},
                    "unsicher": {"type": "boolean"},
                },
                "required": [*FELDER, "lage", "unsicher"],
            },
        }
    },
    "required": ["angaben"],
}
"""Antwortform fuer Anbieter, die eine erzwungene Form kennen."""


class AntwortUngueltig(ValueError):
    """Die Antwort eines Lesers hat nicht die verlangte Form."""


def auftrag(dokumentart: str = "eines Dokuments") -> str:
    """Der Auftragstext. ``dokumentart`` setzt das Fach ein, z. B. ``"eines medizinischen Belegs (Laborbefund, ...)"``."""
    return f"Du liest eine Seite {dokumentart} vom Seitenbild.\n{_REGELN}"


def pruefe_antwort(antwort: object) -> list[dict[str, Any]]:
    """Prueft die Form einer Leser-Antwort und gibt die Angaben zurueck (Textfelder nur als Text, fehlende leer).

    Bricht laut bei allem, was keine Liste von Angaben ist: eine halb verstandene Antwort darf nicht als
    „dieser Leser hat nichts gesehen“ in den Abgleich gehen.
    """
    if not isinstance(antwort, dict) or not isinstance(antwort.get("angaben"), list):
        raise AntwortUngueltig('Antwort ist kein Objekt mit der Liste "angaben"')
    angaben: list[dict[str, Any]] = []
    for nr, roh in enumerate(antwort["angaben"], start=1):
        if not isinstance(roh, dict):
            raise AntwortUngueltig(f"Angabe {nr} ist kein Objekt")
        angabe: dict[str, Any] = {}
        for feld in FELDER:
            wert = roh.get(feld)
            if wert is not None and not isinstance(wert, str):
                # Eine Zahl statt Text hat ihr Druckbild schon verloren (5.10 wird 5.1): nie still umformen.
                raise AntwortUngueltig(f"Angabe {nr}: Feld {feld} ist kein Text")
            angabe[feld] = wert or ""
        angabe["lage"] = roh.get("lage") if isinstance(roh.get("lage"), list) else []
        angabe["unsicher"] = roh.get("unsicher") is True
        angaben.append(angabe)
    return angaben
