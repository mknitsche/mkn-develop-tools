"""Was das Modell im Bild sieht — und die Regel, die es zaehmt.

**Regel A** (Spec § 10a, KT-1-Entscheid 2026-08-29): nur was das Modell `sicher`
nennt, wird geschrieben. Die Herleitung ist gemessen (§ 4 Stufe 3): Sonnet lag
bei 15/20 und war einmal falsch UND selbstsicher, Opus bei 17/20 mit **14/14
Praezision auf seiner eigenen Sicherheitsangabe**. Einem Modell, dessen
Selbsteinschaetzung traegt, darf man sie glauben — aber nur sie.

Alles `unsicher` geht ins Protokoll, nicht in die Datei. Dieselbe Regel wie beim
Ort: im Zweifel nicht schreiben, sondern vorlegen.

**Ein kaputtes Urteil reisst den Lauf nicht ab.** Bei 1.293 Aufnahmen ist ein
einzelnes unlesbares Ergebnis normal; es gilt dann als unsicher und traegt seinen
Grund mit, damit man ihn im Protokoll sieht statt im Blinden zu suchen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

BELICHTUNG = ("gut", "unterbelichtet", "ueberbelichtet", "unklar")
"""Die vier Werte, die der Prompt zulaesst. `unklar` ist kein Mangel, sondern
eine Aussage — KT-1s "gruselig" faellt unter die mittleren beiden."""


@dataclass(frozen=True)
class Urteil:
    """Was das Modell zu einem Bild gesagt hat."""

    sicher: bool
    motive: tuple[str, ...] = ()
    beschreibung: str = ""
    belichtung: str = "unklar"
    fehler: str = ""
    """Warum das Urteil unbrauchbar war — leer, wenn es brauchbar ist."""

    roh: dict[str, Any] = field(default_factory=dict, repr=False)

    def zum_schreiben(self) -> dict[str, Any]:
        """Was davon in die Datei darf. Bei `unsicher`: nichts.

        Nicht "nichts zurueckgeben und den Rest verwerfen" — `motive` und
        `beschreibung` bleiben am Urteil erhalten, damit das Protokoll sie
        zeigen kann. Die Trennung ist Schreiben gegen Vorlegen, nicht Behalten
        gegen Wegwerfen.
        """
        if not self.sicher:
            return {}
        return {
            "motive": self.motive,
            "beschreibung": self.beschreibung,
            "belichtung": self.belichtung,
        }


def prompt() -> str:
    """Die Frage an das Modell.

    Sie verlangt die Sicherheitsangabe ausdruecklich: ohne sie kann Regel A nicht
    greifen, und das Modell antwortet in einer Form, die der Parser nicht kennt.
    """
    return (
        "Du siehst eine Fotografie. Antworte AUSSCHLIESSLICH mit einem JSON-Objekt, "
        "ohne Vor- oder Nachtext, mit genau diesen Feldern:\n"
        "\n"
        '  "sicher"        true nur, wenn du dir bei Motiven UND Beschreibung sicher\n'
        "                  bist. Im Zweifel false — eine unsichere Angabe wird\n"
        "                  verworfen, eine falsche waere schlimmer als keine.\n"
        '  "motive"        Liste von 2 bis 6 Stichworten zum Bildinhalt, freies\n'
        "                  Vokabular, deutsch, jeweils ein bis zwei Woerter.\n"
        "                  Was IM Bild ist, nicht was es bedeutet.\n"
        '  "beschreibung"  EIN Satz, deutsch, sachlich.\n'
        '  "belichtung"    einer von: ' + ", ".join(BELICHTUNG) + "\n"
        "\n"
        "Keine Ortsnamen raten — der Ort ist bekannt und kommt aus anderer Quelle."
    )


def aus_antwort(antwort: dict[str, Any]) -> Urteil:
    """Liest ein Urteil aus der Anbieter-Antwort.

    Wirft nicht: ein einzelnes unlesbares Ergebnis darf einen Lauf ueber 1.293
    Aufnahmen nicht abreissen. Es gilt als unsicher und traegt seinen Grund.
    """
    text = _text(antwort)
    if not text:
        return Urteil(sicher=False, fehler="leere Antwort", roh=antwort)

    try:
        d = json.loads(_ohne_zaun(text))
    except json.JSONDecodeError as exc:
        return Urteil(sicher=False, fehler=f"kein JSON: {exc}", roh=antwort)

    if not isinstance(d, dict):
        return Urteil(sicher=False, fehler=f"kein Objekt, sondern {type(d).__name__}", roh=antwort)

    motive = tuple(str(m) for m in d.get("motive") or () if str(m).strip())
    belichtung = str(d.get("belichtung") or "unklar")
    return Urteil(
        sicher=bool(d.get("sicher")),
        motive=motive,
        beschreibung=str(d.get("beschreibung") or ""),
        belichtung=belichtung if belichtung in BELICHTUNG else "unklar",
        roh=antwort,
    )


def _text(antwort: dict[str, Any]) -> str:
    """Der Antworttext, ueber die Formen der Anbieter hinweg."""
    inhalt = antwort.get("content")
    if isinstance(inhalt, list):
        return "".join(t.get("text", "") for t in inhalt if isinstance(t, dict))
    if isinstance(inhalt, str):
        return inhalt
    # Gemini-Form. Sie fehlte, und das fiel nicht auf, weil ihr Fehlen wie
    # eine ehrliche "unsicher"-Antwort aussieht: kein Text, also kein Urteil.
    # Der erste echte Gemini-Lauf meldete `sicher=False` und keine Motive --
    # das Modell hatte vier genannt.
    kandidaten = antwort.get("candidates")
    if isinstance(kandidaten, list) and kandidaten:
        teile = (kandidaten[0].get("content") or {}).get("parts") or []
        return "".join(t.get("text", "") for t in teile if isinstance(t, dict))

    # OpenAI-Form
    wahlen = antwort.get("choices")
    if isinstance(wahlen, list) and wahlen:
        nachricht = wahlen[0].get("message") or {}
        return str(nachricht.get("content") or "")
    # Ollama-Form
    nachricht = antwort.get("message")
    if isinstance(nachricht, dict):
        return str(nachricht.get("content") or "")
    return ""


def _ohne_zaun(text: str) -> str:
    """Entfernt einen Markdown-Codezaun, falls das Modell einen setzt.

    Der Prompt verbietet ihn, aber "verbieten" ist keine Zusicherung -- und ein
    Zaun ist der haeufigste Grund, warum sonst gueltiges JSON nicht parst.
    """
    roh = text.strip()
    if not roh.startswith("```"):
        return roh
    zeilen = roh.splitlines()
    return "\n".join(zeilen[1:-1] if zeilen[-1].strip() == "```" else zeilen[1:])


# ---------------------------------------------------------------------------
# Serienurteil -- die ZWEITE Frage (Design 2026-08-30 Stufe 3 § 4): ist eine
# Kandidaten-Gruppe ein Panorama, eine Wiederholung oder gar keine Serie. Der
# Aufruf ERSETZT den Motiv-Aufruf der Gruppe, statt zu ihm hinzuzukommen (§ 7)
# -- deshalb traegt das Urteil dieselben Motiv-Felder wie `Urteil` daneben.
# ---------------------------------------------------------------------------

SERIE_WERTE = ("panorama", "wiederholung", "keine")
"""Die drei Werte, die der Serien-Prompt zulaesst (Design § 4)."""


@dataclass(frozen=True)
class Serienurteil:
    """Was das Modell zu einer Kandidaten-Gruppe gesagt hat.

    Traegt dieselben Bild-Felder wie `Urteil` (motive, beschreibung,
    belichtung, fehler, roh) UND die Antwort auf die Serien-Frage selbst:
    `serie` und `bilder` -- welche Nummern des Kontaktbogens dazugehoeren.
    """

    sicher: bool
    serie: str = "keine"
    bilder: tuple[int, ...] = ()
    motive: tuple[str, ...] = ()
    beschreibung: str = ""
    belichtung: str = "unklar"
    fehler: str = ""
    """Warum das Urteil unbrauchbar war -- leer, wenn es brauchbar ist."""

    roh: dict[str, Any] = field(default_factory=dict, repr=False)

    def zum_schreiben(self) -> dict[str, Any]:
        """Was die Serie an Motiv-Feldern vererbt -- Regel A samt Sonderfall.

        `keine` vererbt NICHT, auch wenn das Modell sicher ist: die Mitglieder
        gehoeren nicht zusammen, ein Sammel-Motiv ueber eine Gehsequenz waere
        je Bild falsch (Design § 4). Alles Uebrige folgt Regel A wie bei
        `Urteil`: nur ein sicheres Urteil schreibt.
        """
        if not self.sicher or self.serie == "keine":
            return {}
        return {
            "motive": self.motive,
            "beschreibung": self.beschreibung,
            "belichtung": self.belichtung,
        }


def serien_prompt(messbefund: str = "") -> str:
    """Die Frage, ob eine Kandidaten-Gruppe ein Panorama, eine Wiederholung
    oder gar keine Serie ist (Design Stufe 3 § 4). Der Wortlaut ist aus dem
    Design uebernommen, nicht neu formuliert -- es ist zweimal gegengeprueft
    worden.

    **`messbefund` traegt, was die Messung schon weiss.** Ohne ihn sieht das
    Modell nur den Kontaktbogen -- und urteilt dann ueber Bilder, deren
    Verschiebung gegeneinander bereits gemessen ist. Firsthand: KT-1s Panorama
    von der Sebalduskirche besteht aus einem Schwenk (36 % Versatz) und einer
    Wiederholung derselben Stelle; auf dem blossen Bogen sind zwei der drei
    Bilder fast gleich, und das Modell nannte die Gruppe folgerichtig
    "wiederholung". Es hatte nicht unrecht -- ihm fehlte die Haelfte.

    Die Messung entscheidet weiterhin NICHT (sie kann eine Gehsequenz nicht von
    einem Schwenk trennen, Design § 3a). Sie sagt dem Modell nur, was sie
    gesehen hat, und das Modell sagt, was es bedeutet.
    """
    return (
        "Du siehst einen Kontaktbogen: nummerierte Aufnahmen, die kurz "
        "nacheinander mit derselben Kamera entstanden sind. Antworte "
        "AUSSCHLIESSLICH mit einem JSON-Objekt, ohne Vor- oder Nachtext, mit "
        "genau diesen Feldern:\n"
        "\n"
        '  "serie"        einer von: ' + ", ".join(SERIE_WERTE) + "\n"
        "                 panorama: die Bilder sind ueberlappende Ausschnitte\n"
        "                 EINER groesseren Szene -- Schwenk oder Raster, jede\n"
        "                 Richtung. wiederholung: mehrere Anlaeufe desselben\n"
        "                 Motivs mit etwa gleichem Ausschnitt. keine: sie\n"
        "                 gehoeren nicht zusammen -- zum Beispiel eine\n"
        "                 Bilderfolge beim Gehen mit wechselnden Motiven.\n"
        '  "bilder"       Liste der Nummern, die zur Serie gehoeren. Alle\n'
        "                 Nummern, wenn alle dazugehoeren.\n"
        '  "sicher"       true nur, wenn du dir bei serie UND bilder sicher\n'
        "                 bist. Im Zweifel false -- eine unsichere Angabe\n"
        "                 wird vorgelegt, eine falsche bekaeme einen falschen\n"
        "                 Dateinamen.\n"
        '  "motive"       Liste von 2 bis 6 Stichworten zum Bildinhalt der\n'
        "                 Serie, freies Vokabular, deutsch, ein bis zwei\n"
        "                 Woerter.\n"
        '  "beschreibung" EIN Satz, deutsch, sachlich, ueber die Serie als\n'
        "                 Ganzes.\n"
        '  "belichtung"   einer von: ' + ", ".join(BELICHTUNG) + "\n"
        "\n"
        "Keine Ortsnamen raten -- der Ort ist bekannt und kommt aus anderer "
        "Quelle." + (f"\n\n{messbefund}" if messbefund else "")
    )


def serie_aus_antwort(antwort: dict[str, Any]) -> Serienurteil:
    """Liest ein Serienurteil aus der Anbieter-Antwort (Design Stufe 3 § 4).

    Wirft nicht -- dieselbe Fehler-Mechanik wie `aus_antwort`: ein kaputtes,
    leeres oder fremdformatiges Ergebnis gilt als unsicher und traegt seinen
    Grund, statt den Lauf abzureissen.
    """
    text = _text(antwort)
    if not text:
        return Serienurteil(sicher=False, fehler="leere Antwort", roh=antwort)

    try:
        d = json.loads(_ohne_zaun(text))
    except json.JSONDecodeError as exc:
        return Serienurteil(sicher=False, fehler=f"kein JSON: {exc}", roh=antwort)

    if not isinstance(d, dict):
        return Serienurteil(
            sicher=False, fehler=f"kein Objekt, sondern {type(d).__name__}", roh=antwort
        )

    serie = str(d.get("serie") or "")
    if serie not in SERIE_WERTE:
        # Ein Wert ausserhalb des Vokabulars ist so wenig vertrauenswuerdig
        # wie kaputtes JSON -- Regel A darf ihm nicht glauben, nur weil
        # "sicher" daneben "true" sagt.
        return Serienurteil(
            sicher=False, fehler=f"unbekannter Wert fuer serie: {serie!r}", roh=antwort
        )

    motive = tuple(str(m) for m in d.get("motive") or () if str(m).strip())
    belichtung = str(d.get("belichtung") or "unklar")
    return Serienurteil(
        sicher=bool(d.get("sicher")),
        serie=serie,
        bilder=_bildnummern(d.get("bilder")),
        motive=motive,
        beschreibung=str(d.get("beschreibung") or ""),
        belichtung=belichtung if belichtung in BELICHTUNG else "unklar",
        roh=antwort,
    )


def _bildnummern(wert: object) -> tuple[int, ...]:
    """Die Nummern aus `bilder`, robust gegen fremde Formen.

    Ein `bool` ist in Python ein `int` (`isinstance(True, int)` ist wahr) und
    wuerde sonst unbemerkt als 0/1 durchrutschen.
    """
    if not isinstance(wert, list):
        return ()
    return tuple(x for x in wert if isinstance(x, int) and not isinstance(x, bool))
