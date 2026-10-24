"""Gliedern: ein Dokument wird in die Stuecke zerlegt, die einzeln gesprochen werden.

**Warum ein Satz je Stueck.** Die Sprachsynthese klingt am natuerlichsten und ist am
leichtesten zu pruefen, wenn jedes Stueck genau an einer Satzgrenze endet: die Pause
sitzt dann dort, wo ein Mensch sie auch macht, und ein misslungenes Stueck verdirbt
nur einen Satz. Der Prototyp buendelte mehrere Saetze bis zur Hoechstlaenge; das
Werkzeug tut es bewusst nicht.

**Warum die Hoechstlaenge.** Sehr lange Eingaben lassen das Modell abbrechen oder
Woerter verschlucken. Ein Satz ueber der Grenze wird deshalb geteilt, und zwar dort,
wo die Stimme ohnehin Luft holt: zuerst an `;` und `:`, sonst an `,`, sonst an einem
Leerzeichen, jeweils nahe der Mitte. Absaetze ohne Satzzeichen (Listen, Tabellen)
fallen so auf die Leerzeichen zurueck und werden nie zu einem Riesenstueck.

**Was nicht geprueft wird.** Die Satzerkennung kennt keine Abkuerzungen, Ordinal- oder
Datumspunkte: der Hoertext (vorherige Stufe) hat sie schon ausgeschrieben. Ausnahme sind
Initialen ("C. G. Jung"): sie lassen sich nicht ausschreiben, und ein einzelner Grossbuchstabe
mit Punkt beendet darum nie einen Satz -- sonst entstuenden Stuecke wie "C.", an denen die
Stimme scheitert.
"""

from __future__ import annotations

import re
from dataclasses import replace

from mkn_audio.typen import Dokument, Mp4Fehler, Stueck

# Satzende = Folge aus . ! ? oder ... , danach beliebig viele schliessende Anfuehrungs-
# zeichen/Klammern (`„Ja.“ Dann`), danach Leerraum. Ohne Leerraum danach ist es kein
# Satzende (3.5, `?“,`).
_SATZENDE = re.compile('[.!?\u2026]+["\u201c\u201d\u00bb\u00ab\u2019\u2018\u203a\u2039)\\]]*\\s+')
# Ein einzelner Grossbuchstabe direkt vor dem Punkt ("C. G. Jung", "C.G. Jung") ist eine Initiale.
_INITIALE = re.compile(r"(?:^|[\s(\u201e\u00bb.])[A-ZÄÖÜ]$")
_STARK = re.compile(r"[;:]\s")
_KOMMA = re.compile(r",\s")
_LEER = re.compile(r"\s")
# Ein Schnitt, der nur ein Stummel abtrennt, ergibt ein Stueck, das zu kurz zum Sprechen
# ist; Satzzeichen-Kandidaten gelten nur, wenn beide Seiten mindestens so lang sind.
_MIN_TEIL = 20


def _saetze(absatz: str) -> list[str]:
    """Teilt einen Absatz an seinen Satzenden; der Satzschluss bleibt am Satz."""
    saetze, start = [], 0
    for m in _SATZENDE.finditer(absatz):
        if m.group().rstrip() == "." and _INITIALE.search(absatz, 0, m.start()):
            continue
        if absatz[m.end() : m.end() + 1].islower():  # "Pius IX. zum Dogma": klein geht es weiter
            continue
        saetze.append(absatz[start : m.end()].strip())
        start = m.end()
    saetze.append(absatz[start:].strip())
    return [s for s in saetze if s]


def _schnitt(satz: str, max_zeichen: int) -> tuple[int, int]:
    """Findet die Schnittstelle fuer einen zu langen Satz: (Ende links, Anfang rechts).

    Reihenfolge `;`/`:` vor `,` vor Leerzeichen, jeweils der Kandidat, der der Mitte am
    naechsten liegt. Ein Wort ohne Leerzeichen ueber der Grenze wird hart bei
    `max_zeichen` geschnitten: ein Stueck ueber der Grenze waere schlimmer als ein
    zerschnittener Link.
    """
    mitte = len(satz) / 2
    for muster in (_STARK, _KOMMA):
        kandidaten = [
            (m.start() + 1, m.end())
            for m in muster.finditer(satz)
            if m.start() + 1 >= _MIN_TEIL and len(satz) - m.end() >= _MIN_TEIL
        ]
        if kandidaten:
            return min(kandidaten, key=lambda k: abs(k[0] - mitte))
    leer = [(m.start(), m.end()) for m in _LEER.finditer(satz)]
    if leer:
        return min(leer, key=lambda k: abs(k[0] - mitte))
    return max_zeichen, max_zeichen


def _teile(satz: str, max_zeichen: int) -> list[str]:
    """Teilt rekursiv, bis jedes Stueck hoechstens `max_zeichen` lang ist."""
    if len(satz) <= max_zeichen:
        return [satz]
    links_ende, rechts_anfang = _schnitt(satz, max_zeichen)
    links, rechts = satz[:links_ende].strip(), satz[rechts_anfang:].strip()
    return [t for haelfte in (links, rechts) if haelfte for t in _teile(haelfte, max_zeichen)]


def gliedere(dok: Dokument, *, max_zeichen: int = 400) -> tuple[Stueck, ...]:
    """Zerlegt das Dokument in Stuecke, je Kapitel zuerst der Titel, dann Satz fuer Satz.

    Nummerierung: `kapitel` und `absatz` zaehlen ab 0 als Index in `dok`; ein leerer
    Absatz faellt weg, behaelt aber seinen Index, damit die Pausen zur Quelle passen.
    Das Titelstueck hat `absatz=-1`; ein Kapitel ohne Titel hat keins (so beginnt die
    Hoerfassung der Regie mit dem Vorspann, ohne dass eine leere Ueberschrift gesprochen
    wird). `nr` zaehlt laufend ueber das ganze Dokument ab 0. Stuecke aus Absaetzen, die die
    Regie neu formuliert hat (`Kapitel.arten` ausser `wortlaut`), tragen `ansage=True`.
    """
    if max_zeichen < 1:
        raise Mp4Fehler(f"max_zeichen muss mindestens 1 sein, nicht {max_zeichen}")
    stuecke: list[Stueck] = []

    def anhaengen(kapitel: int, absatz: int, art, text: str, ansage: bool = False) -> None:
        for teil in _teile(text, max_zeichen):
            stuecke.append(Stueck(kapitel, absatz, len(stuecke), teil, art, ansage))

    for k, kapitel in enumerate(dok.kapitel):
        titel = " ".join(kapitel.titel.split())
        if titel:
            anhaengen(k, -1, "titel", titel)
        for a, absatz in enumerate(kapitel.absaetze):
            ansage = bool(kapitel.arten) and kapitel.arten[a] != "wortlaut"
            for satz in _saetze(" ".join(absatz.split())):
                anhaengen(k, a, "text", satz, ansage)
    return tuple(stuecke)


def waehle(dok: Dokument, auswahl: str | None) -> Dokument:
    """Beschraenkt das Dokument auf Kapitel: `"3"`, `"1-3"`, `"2,5"`, `"1-2,4"` (ab 1).

    `None` laesst alles. Die Kapitel behalten ihre Dokumentreihenfolge, egal in welcher
    Reihenfolge sie genannt wurden. Unlesbare oder ausserhalb liegende Angaben brechen
    laut ab: eine Auswahl, die stillschweigend etwas anderes liefert als gewollt, kostet
    einen ganzen Sprechlauf.
    """
    if auswahl is None:
        return dok
    gewaehlt: set[int] = set()
    for teil in auswahl.split(","):
        m = re.fullmatch(r"\s*([0-9]+)\s*(?:-\s*([0-9]+)\s*)?", teil)
        if m is None:
            raise Mp4Fehler(f"Kapitelauswahl nicht lesbar: {auswahl!r} (erlaubt: 3, 1-3, 2,5)")
        von = int(m.group(1))
        bis = int(m.group(2)) if m.group(2) is not None else von
        if von < 1 or bis < von or bis > len(dok.kapitel):
            raise Mp4Fehler(
                f"Kapitelauswahl {teil.strip()!r} passt nicht: das Dokument hat "
                f"{len(dok.kapitel)} Kapitel (Zaehlung ab 1)"
            )
        gewaehlt.update(range(von, bis + 1))
    return replace(
        dok, kapitel=tuple(k for i, k in enumerate(dok.kapitel, start=1) if i in gewaehlt)
    )
