"""Hoertext: aus dem Lesetext wird der Text, den die Stimme sprechen soll.

Drei Stufen, immer in dieser Reihenfolge:

1. **Regeln** (`abkuerzungen`, `zahlen`): Zahlen, Daten, Uhrzeiten, Einheiten,
   Abkuerzungen, Webadressen, Fussnotenzeichen, Aussprache-Woerterbuch. Vorhersagbar
   und getestet.
2. **Sprachmodell** (`glaetten`): nur Satzbau und Struktur, auf dem Ergebnis von 1.
3. **Pruefung** (`pruefen`): was das Modell aenderte, wird mit der Fassung aus 1
   verglichen; Abweichung heisst Rueckfall auf 1 -- fuer genau diesen Absatz.

**Warum diese Reihenfolge.** Die Regeln schreiben die Bezugsgroesse, an der das Modell
gemessen wird. Liefe das Modell zuerst, gaebe es nichts Verlaessliches zu vergleichen.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace

from mkn_audio.hoertext.abkuerzungen import (
    ersetze_abkuerzungen,
    ersetze_woerter,
    saeubere,
    wortformen,
)
from mkn_audio.hoertext.glaetten import glaette
from mkn_audio.hoertext.zahlen import ausschreiben, trenne_ziffern
from mkn_audio.typen import Dokument, Kapitel, Textmodell

__all__ = ["deterministisch", "hoertext"]

_ZIFFERNWORT = re.compile(r"\S*\d\S*")
_RANDZEICHEN = ".,;:!?()[]{}»«„“\"'"
_MAX_BEISPIELE = 5


def deterministisch(
    text: str,
    aussprache: dict[str, str] | None = None,
    formen: Mapping[str, str] | None = None,
) -> str:
    """Stufe a fuer einen Text: nur Regeln, kein Modell.

    Erst saeubern (Trennstriche heilen, damit das Woerterbuch geteilte Namen findet),
    dann das Aussprache-Woerterbuch, dann Abkuerzungen, zuletzt Zahlen -- "Mrd." muss
    "Milliarden" sein, bevor die Zahl davor gelesen wird. `formen` (aus `wortformen`) sind die
    normal geschriebenen Woerter des Dokuments: Versalien, die dort stehen, werden zu Woertern.
    """
    text = trenne_ziffern(saeubere(text))
    text = ersetze_woerter(text, aussprache)
    text = ersetze_abkuerzungen(text, formen=formen)
    text = ausschreiben(text)
    return re.sub(r" {2,}", " ", text).strip()


def _uebrige_ziffern(wo: str, texte: list[str]) -> str | None:
    """Warnung, wenn nach den Regeln noch Ziffern stehen (z. B. "3a", "5G")."""
    gefunden: dict[str, None] = {}
    for text in texte:
        for treffer in _ZIFFERNWORT.findall(text):
            gefunden[treffer.strip(_RANDZEICHEN)] = None
    if not gefunden:
        return None
    beispiele = list(gefunden)[:_MAX_BEISPIELE]
    mehr = ", …" if len(gefunden) > _MAX_BEISPIELE else ""
    return f"Ziffern nicht ausgeschrieben (Kapitel »{wo}«): {', '.join(beispiele)}{mehr}"


def _ist_deutsch(sprache: str) -> bool:
    # Leer heisst unbekannt; das Werkzeug ist deutsch-zuerst, also wird so gelesen.
    return sprache.lower()[:2] in ("de", "")


def _glaette_wortlaut(
    paare: list[tuple[str, str]], textmodell: Textmodell, wo: str
) -> tuple[tuple[str, ...], list[str]]:
    """Glaettet nur die Wortlaut-Absaetze; Ansagen bleiben, wie die Regel-Stufe sie liess.

    Die Regie hat Vorspann, Ueberleitung und Abspann schon fuers Ohr formuliert; eine
    Glaettung samt Pruefung in beide Richtungen waere dort nutzlos (es gibt keine Vorlage,
    an der sich messen liesse) und liesse das Modell an Text drehen, den die Regie bereits
    gegen Erfundenes abgesichert hat.
    """
    wortlaut = tuple(text for text, art in paare if art == "wortlaut")
    geglaettet, warnungen = glaette(wortlaut, textmodell, wo=wo)
    zurueck = iter(geglaettet)
    return tuple(next(zurueck) if art == "wortlaut" else text for text, art in paare), warnungen


def hoertext(
    dok: Dokument,
    *,
    textmodell: Textmodell | None,
    aussprache: dict[str, str] | None = None,
) -> tuple[Dokument, tuple[str, ...]]:
    """Bereitet ein Dokument zum Vorlesen auf; gibt das neue Dokument und die Warnungen.

    Die neuen Warnungen stehen zusaetzlich im `warnungen`-Feld des Dokuments, hinter den
    schon vorhandenen: wird diese Stufe spaeter aus dem Arbeitsverzeichnis uebersprungen,
    gehen sie sonst verloren. Wer beides liest, darf sie nicht doppelt zaehlen -- der
    Rueckgabewert `warnungen` ist nur das, was DIESE Stufe hinzufuegte.

    Ohne `textmodell` laeuft nur Stufe a. Ein Fehler des Modell-Aufrufs bricht laut ab.
    `Kapitel.arten` bleibt erhalten; Absaetze mit einer Art ausser `wortlaut` (Ansagen der
    Regie) bekommen nur Stufe a, nicht die Glaettung und deren Pruefung.
    """
    if not _ist_deutsch(dok.sprache):
        meldung = (
            f"Hörtext: Sprache »{dok.sprache}« wird nicht aufbereitet "
            "(Regeln und Prüfung gelten für Deutsch)"
        )
        return replace(dok, warnungen=(*dok.warnungen, meldung)), (meldung,)

    formen = wortformen([dok.titel, *(t for k in dok.kapitel for t in (k.titel, *k.absaetze))])
    neue: list[str] = []
    kapitel: list[Kapitel] = []
    for nr, kap in enumerate(dok.kapitel, start=1):
        titel = deterministisch(kap.titel, aussprache, formen)
        wo = titel or f"Kapitel {nr}"
        arten = kap.arten or ("wortlaut",) * len(kap.absaetze)
        # Ein Absatz, der nach den Regeln leer wird, nimmt seine Art mit.
        paare = [
            (deterministisch(x, aussprache, formen), art)
            for x, art in zip(kap.absaetze, arten, strict=True)
        ]
        paare = [(text, art) for text, art in paare if text]
        absaetze = tuple(text for text, _ in paare)
        if textmodell is not None:
            absaetze, warnungen = _glaette_wortlaut(paare, textmodell, wo)
            neue.extend(warnungen)
        ziffern = _uebrige_ziffern(wo, [titel, *absaetze])
        if ziffern:
            neue.append(ziffern)
        kapitel.append(
            Kapitel(titel, absaetze, tuple(art for _, art in paare) if kap.arten else ())
        )

    ergebnis = tuple(neue)
    return replace(dok, kapitel=tuple(kapitel), warnungen=(*dok.warnungen, *ergebnis)), ergebnis
