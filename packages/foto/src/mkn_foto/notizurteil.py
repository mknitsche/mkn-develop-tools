"""Was der Mensch in seine Notiz geschrieben hat — gelesen, nicht abgetippt.

**Der Anlass, woertlich (KT-1, 2026-08-30):** *"dann wurden auch meine antworten
nicht intelligent interpretiert, sondern 1:1 uebernommen - da steht dann kein
ort - obwohl genannt war 'gehoert zu granau' oder 'zu vorordner' usw ... das ist
doch bloedsinn"* -- und, unmissverstaendlich: *"ich hatte einfach in die datei
unten reingeschrieben - fertig ... mey, kann doch nicht so schwer sein!!!"*

**Der Beleg ist eine Zahl.** Die bisherige Wortsuche (`footprint`,
`findpinguin`) erkannte von 20 Notizen **neun**. Die elf verworfenen enthielten:

    "Schon Zugspitze ganz oben"              ein Ort
    "zu Hause - Probebilder"                 ein Ort
    "also Stubaier G[letscher]"              ein Ort
    "Gehoert ebenfalls dazu - vorheriger Ordner"   ein Bezug
    "ist schwarz - falsch belichtet"         eine Belichtungsaussage
    "Uhrzeit stimmt nicht / letzte location am 24."  eine Korrektur

Alles weggeworfen, weil ein Stichwort fehlte.

**Warum eine Wortsuche das nicht kann.** Sie sieht in *"gehoert zu Grainau"* und
*"auf der Rueckfahrt VON Grainau"* dieselben Zeichen. Der Unterschied liegt in
der Absicht des Satzes, nicht in seinen Woertern. Genau deshalb entstanden mit
der reinen Namenssuche drei falsche Anker -- und die Antwort darauf war, die
Bedingung zu verschaerfen, statt richtig zu lesen. Das hat die Fehler beseitigt
und mit ihnen die Haelfte der Auskuenfte.

**Regel A gilt unveraendert** (Spec Paragraf 10a): nur was das Modell `sicher`
nennt, wird geschrieben. Eine Vermutung bleibt am Urteil erhalten -- fuers
Protokoll und fuer die Vorlage --, aber sie geht nicht in die Datei. Im Zweifel
nicht schreiben, sondern vorlegen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

ARTEN = ("zuordnung", "vermutung", "bezug", "kein_ort", "verwerfen")
"""Was eine Notiz sein kann.

`zuordnung`  der Mensch NENNT den Ort              -> wird geschrieben
`vermutung`  er glaubt es ("denke ich")            -> wird vorgelegt
`bezug`      derselbe Ort wie eine andere Session  -> wird aufgeloest
`kein_ort`   ehrlich ohne Ort ("im nirgendwo")     -> bleibt leer
`verwerfen`  "Loeschen - war im Hotel"             -> Hinweis, kein Ort
"""

BELICHTUNG = ("gut", "unterbelichtet", "ueberbelichtet", "unklar")


@dataclass(frozen=True)
class Urteil:
    """Was in einer Notiz steht."""

    sicher: bool
    ort: str = ""
    art: str = "kein_ort"
    bezug: str = ""
    """Auf welche andere Session sich die Notiz beruft — ein Ordnername oder
    das Wort `vorheriger`."""

    belichtung: str = "unklar"
    zeit_zweifel: str = ""
    """Was der Mensch zur Uhrzeit sagt. Er hat es mehrfach angemerkt, und eine
    verworfene Zweifelsmeldung ist eine verlorene Korrektur."""

    beschreibung: str = ""
    fehler: str = ""
    roh: dict[str, Any] = field(default_factory=dict, repr=False)

    def zum_schreiben(self) -> dict[str, Any]:
        """Was davon in die Datei darf. Bei `unsicher`: kein Ort.

        Die anderen Angaben bleiben am Urteil -- die Trennung ist Schreiben
        gegen Vorlegen, nicht Behalten gegen Wegwerfen.
        """
        if not self.sicher or self.art in ("vermutung", "kein_ort", "verwerfen"):
            return {}
        return {"ort": self.ort, "art": self.art, "bezug": self.bezug}


def prompt(text: str, *, ordner: str, nachbarn: tuple[str, ...] = ()) -> str:
    """Die Frage an das Modell.

    **Der Kontext ist Teil der Frage.** Ohne die Nachbarsessions kann
    "vorheriger Ordner" nicht aufgeloest werden -- das Modell muss wissen,
    welche das sind. Wer nur den Satz schickt, bekommt eine Antwort, die nicht
    falsch ist, sondern unmoeglich.
    """
    liste = "\n".join(f"  - {n}" for n in nachbarn) or "  (keine)"
    return f"""Du liest die handschriftliche Notiz eines Fotografen zu einer Aufnahme-Session.
Er schreibt frei, in ganzen oder halben Saetzen, irgendwo in die Datei. Deine
Aufgabe ist, seine AUSSAGE zu verstehen — nicht Stichworte zu suchen.

Diese Session: {ordner}
Andere Sessions in zeitlicher Reihenfolge:
{liste}

Seine Notiz:
---
{text}
---

Antworte NUR mit JSON, ohne Rahmen:

{{"art": "zuordnung|vermutung|bezug|kein_ort|verwerfen",
  "ort": "der Ortsname, so wie man ihn auf einer Karte sucht — sonst \\"\\"",
  "bezug": "Ordnername oder \\"vorheriger\\", nur bei art=bezug — sonst \\"\\"",
  "belichtung": "gut|unterbelichtet|ueberbelichtet|unklar",
  "zeit_zweifel": "was er zur Uhrzeit sagt, woertlich — sonst \\"\\"",
  "beschreibung": "ein Satz, was diese Session war",
  "sicher": true oder false}}

Regeln:
- "gehoert zu X" / "X heisst der Ort" / "Schon X ganz oben"  -> art=zuordnung, ort=X, sicher=true
- "denke ich" / "wahrscheinlich" / "irgendwie bei X"         -> art=vermutung, sicher=false
- "vorheriger Ordner" / "gehoert dazu"                       -> art=bezug
- "irgendwo im nirgendwo" / "spontan, kein Anhaltspunkt"     -> art=kein_ort, sicher=true
- "Loeschen" / "war im Hotel" / "zu Hause, Probebilder"      -> art=verwerfen, ort falls genannt
- Ein Ort, den er NUR ERWAEHNT ("auf der Rueckfahrt VON X"), ist KEINE Zuordnung.
- "zu Hause", "im Hotel", "in der Wohnung" sind KEINE Ortsnamen: art=verwerfen,
  ort="". ERFINDE NIEMALS eine Adresse, eine Strasse oder eine Hausnummer —
  auch nicht, wenn du meinst, den Ort zu kennen. Was nicht im Text steht,
  existiert fuer dich nicht.
- `sicher` heisst: du wuerdest diesen Ort in seine Bilddatei schreiben. Im
  Zweifel false — ein falscher Ort ist schlimmer als kein Ort."""


def aus_antwort(roh: str | dict[str, Any]) -> Urteil:
    """Liest die Modellantwort. Eine kaputte reisst nichts ab.

    Bei 20 Notizen ist eine unlesbare Antwort normal; sie gilt dann als unsicher
    und traegt ihren Grund mit, damit man ihn im Protokoll sieht statt im
    Blinden zu suchen.
    """
    text = roh if isinstance(roh, str) else _text_aus(roh)
    try:
        d = json.loads(_entrahme(text))
    except (json.JSONDecodeError, TypeError) as exc:
        return Urteil(sicher=False, fehler=f"Antwort nicht lesbar: {exc}")

    if not isinstance(d, dict):
        return Urteil(sicher=False, fehler="Antwort ist kein Objekt")

    art = str(d.get("art") or "kein_ort")
    if art not in ARTEN:
        return Urteil(sicher=False, fehler=f"unbekannte Art {art!r}", roh=d)

    belichtung = str(d.get("belichtung") or "unklar")
    return Urteil(
        sicher=bool(d.get("sicher")),
        ort=str(d.get("ort") or "").strip(),
        art=art,
        bezug=str(d.get("bezug") or "").strip(),
        belichtung=belichtung if belichtung in BELICHTUNG else "unklar",
        zeit_zweifel=str(d.get("zeit_zweifel") or "").strip(),
        beschreibung=str(d.get("beschreibung") or "").strip(),
        roh=d,
    )


def _text_aus(antwort: dict[str, Any]) -> str:
    """Holt den Text aus der Antwort — in den drei Formen der drei Anbieter."""
    inhalt = antwort.get("content")
    if isinstance(inhalt, list):
        # ALLE Bloecke, nicht der erste: Opus 5 liefert `thinking` UND `text`.
        # Wer blind den ersten nimmt, liest die Signatur des Denkens statt der
        # Antwort -- und haelt eine einwandfreie Auskunft fuer unlesbar. Genau
        # das ist beim ersten Lauf ueber KT-1s 20 Notizen passiert: alle 20
        # galten als unsicher, obwohl das Modell "Lenggries" sauber erkannt hat.
        return "".join(b.get("text", "") for b in inhalt if isinstance(b, dict))
    if isinstance(inhalt, str):
        return inhalt
    if kandidaten := antwort.get("candidates"):
        teile = (kandidaten[0].get("content") or {}).get("parts") or []
        return "".join(b.get("text", "") for b in teile if isinstance(b, dict))
    if wahlen := antwort.get("choices"):
        return str(wahlen[0].get("message", {}).get("content", ""))
    return ""


def _entrahme(text: str) -> str:
    """Entfernt einen Markdown-Rahmen, falls das Modell einen gesetzt hat.

    Gemini tut es zuverlaessig (```json ... ```), Anthropic gelegentlich. Ein
    Parser, der daran scheitert, verwirft eine voellig richtige Antwort.
    """
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    return t.strip()
