"""Sprache eines Textes erkennen, nur mit der Standardbibliothek.

**Warum Stoppwoerter und kein Modell.** Gesucht ist keine Feinbestimmung, sondern die
Antwort auf die Frage, ob die Regeln der Hoertext-Stufe (deutsche Abkuerzungen, Zahlen,
Ordinalzahlen) auf diesen Text passen. Dafuer genuegt der Anteil der haeufigsten
Funktionswoerter: sie machen in jeder dieser Sprachen einen grossen Teil jedes
zusammenhaengenden Textes aus und fehlen in Namen- und Zahlenlisten fast ganz.

**Wann die Antwort `None` ist.** Unter `MIN_WOERTER` Woertern zaehlt zu wenig, und ohne
klaren Vorsprung der besten vor der zweitbesten Sprache (Deutsch und Niederlaendisch
teilen etliche Woerter) wuerde geraten. Wer `None` bekommt, sagt das dem Menschen
(Warnung im Dokument); eine geratene Sprache liesse ein englisches Buch mit deutschen
Regeln und deutscher Stimme vorlesen, ohne dass etwas auffaellt.

**Schreibweisen des Dokuments** (`wortformen`, `versal_belege`, `satzschreibung`) liegen hier
und nicht in der Hoertext-Stufe, weil die Lesestufe sie braucht: `STAND_LESEN` deckt dieses
Modul, `lesen` importiert nie aus `hoertext`, sonst rechnete eine Aenderung dort die Lesestufe
nicht neu.

**Akzente zaehlen nicht.** Beide Seiten werden ohne Akzente verglichen (`für` = `fur`),
damit die Listen reines ASCII bleiben; die wenigen Treffer, die dadurch mit einem
anderen Wort zusammenfallen, verschieben den Anteil nicht merklich.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence

from mkn_audio.typen import Kapitel

MIN_WOERTER = 30
"""Darunter ist der Text zu kurz fuer eine Aussage."""

MIN_ANTEIL = 0.12
"""Mindestanteil der Stoppwoerter der besten Sprache an allen Woertern."""

MIN_VORSPRUNG = 1.3
"""Die beste Sprache muss mindestens so viel mal so viele Treffer haben wie die zweite."""

_WORT = re.compile(r"[^\W\d_]+")


def _liste(woerter: str) -> frozenset[str]:
    return frozenset(woerter.split())


_STOPPWOERTER: dict[str, frozenset[str]] = {
    "de": _liste(
        "der die das und ist nicht ein eine einen einem einer eines zu mit auf fur von den dem "
        "des im in es sich auch an als nach bei aus wie wird sind war hat haben oder aber wenn "
        "nur noch so uber um zum zur dass er sie wir ihr ich du man kann sein seine ihre "
        "werden wurde dann schon mehr vor durch gegen"
    ),
    "en": _liste(
        "the and of to in is that it was for on with as he she they his her be at by this have "
        "from or an are not but had which you were we their there been has will would can said "
        "all who what when its them him"
    ),
    "fr": _liste(
        "le la les de des du un une et est en que qui dans pour pas sur au aux ce cette il elle "
        "ils elles nous vous je ne se son sa ses avec plus par mais ou ont etait sont fait comme "
        "tout etre avoir leur lui y a ete cela"
    ),
    "es": _liste(
        "el la los las de del un una y es en que por con para no se su sus al lo como mas pero "
        "o fue son esta este esto ha han muy sin sobre entre cuando tambien hay ser era le les "
        "habia todo"
    ),
    "it": _liste(
        "il lo la gli le di del della dei delle un una e che non in per con su come piu ma o era "
        "sono ha hanno questo questa anche se si nel nella da al alla ci perche suo sua loro "
        "molto"
    ),
    "nl": _liste(
        "de het een en van is dat niet in op te zijn voor met die ook aan er maar om als dan bij "
        "was heeft hebben werd door naar uit nog wel kan zou worden over of hij zij ze wij we "
        "dit"
    ),
}


def _ohne_akzente(wort: str) -> str:
    zerlegt = unicodedata.normalize("NFD", wort)
    return "".join(z for z in zerlegt if not unicodedata.combining(z))


def erkenne(text: str) -> str | None:
    """Zweibuchstabiger Sprachcode (`de`, `en`, `fr`, `es`, `it`, `nl`) oder `None`.

    `None` heisst: zu kurz oder kein klarer Vorsprung -- nie eine Vermutung.
    """
    woerter = [_ohne_akzente(w) for w in _WORT.findall(text.lower())]
    if len(woerter) < MIN_WOERTER:
        return None
    treffer = sorted(
        ((sum(1 for w in woerter if w in liste), code) for code, liste in _STOPPWOERTER.items()),
        reverse=True,
    )
    (beste, code), (zweite, _) = treffer[0], treffer[1]
    if beste / len(woerter) < MIN_ANTEIL or beste < zweite * MIN_VORSPRUNG:
        return None
    return code


# ---- Schreibweisen des Dokuments -----------------------------------------------------

_BUCHSTABEN = re.compile(r"[^\W\d_]+")
_ROEMISCH = re.compile(r"M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})")


def hat_kleinbuchstaben(text: str) -> bool:
    """Ob `text` einen Kleinbuchstaben traegt -- `ß` zaehlt nicht: es hat keine Versalie.

    Eine Versalien-Zeile ("DIE GROßE WENDE") schreibt das `ß` weiter klein; `str.islower()`
    hielte sie deshalb fuer gemischt geschriebenen Text.
    """
    return any(z.islower() and z != "ß" for z in text)


def ist_versalwort(wort: str) -> bool:
    """Ob `wort` ganz aus Versalien besteht (`ß` neutral, mindestens ein Grossbuchstabe)."""
    return any(z.isupper() for z in wort) and not hat_kleinbuchstaben(wort)


def wortformen(texte: Iterable[str]) -> dict[str, str]:
    """Die normal geschriebenen Woerter eines Dokuments: klein -> haeufigste Schreibweise.

    Grundlage fuer `ersetze_abkuerzungen(formen=...)` und `satzschreibung`: ein Wort in
    Versalien, das hier steht, ist kein Kuerzel ("UND", "GOTT", "EVA"); ein echtes Kuerzel
    (WHO, CERN) steht nie klein. Gezaehlt wird nur mitten im Satz -- am Satzanfang ist jedes
    Wort gross ("Die Liebe" gegen "ich liebe"); ein Wort, das nur am Satzanfang steht, zaehlt
    als Notbehelf trotzdem.
    """
    zaehler: dict[str, dict[str, int]] = {}
    notbehelf: dict[str, str] = {}
    for text in texte:
        for m in _BUCHSTABEN.finditer(text):
            wort = m[0]
            if ist_versalwort(wort):
                continue
            davor = text[: m.start()].rstrip(' \t\u201e\u00bb"(')
            if not davor or davor[-1] in ".!?:":
                notbehelf.setdefault(wort.lower(), wort)
                continue
            formen = zaehler.setdefault(wort.lower(), {})
            formen[wort] = formen.get(wort, 0) + 1
    ergebnis = dict(notbehelf)
    for klein, formen in zaehler.items():
        ergebnis[klein] = max(formen, key=lambda f: (formen[f], f.islower()))
    return ergebnis


def versal_belege(kapitel: Sequence[Kapitel]) -> frozenset[str]:
    """Die Woerter (ab zwei Buchstaben), die im Fliesstext des Dokuments in Versalien stehen.

    Fliesstext sind die Absaetze, die keine Zwischenueberschrift sind: Versalien einer
    Ueberschrift belegen sich nicht selbst als Kuerzel (WHO, HTTP), sonst bliebe jede
    Versalien-Ueberschrift Versalien. Kapiteltitel zaehlen aus demselben Grund nicht.
    """
    belegt: set[str] = set()
    for k in kapitel:
        arten = k.arten or ("wortlaut",) * len(k.absaetze)
        for absatz, art in zip(k.absaetze, arten, strict=True):
            if art == "ueberschrift":
                continue
            belegt.update(
                w for w in _BUCHSTABEN.findall(absatz) if len(w) >= 2 and ist_versalwort(w)
            )
    return frozenset(belegt)


def satzschreibung(
    text: str, formen: Mapping[str, str], sprache: str, versal_belegt: frozenset[str]
) -> str:
    """Schreibt eine Ueberschrift in Versalien in Satzschreibung -- sonst bleibt der Text.

    Gilt nur fuer Text OHNE Kleinbuchstaben (Wahl 2026-10-30): eine gemischt geschriebene
    Ueberschrift ist schon gesetzt, und Regel (3) wuerde sie verderben ("The Silent Garden").
    Ein Wort ist eine Buchstabenfolge, Bindestrich-Teile sind eigene Woerter. Regel in dieser
    Reihenfolge: (1) roemische Zahl (XVIII) oder Wort aus `versal_belegt` bleibt in Versalien;
    (2) steht das Wort (klein) in `formen`, gilt diese Form; (3) sonst `de`: erster Buchstabe
    gross, Rest klein (Substantiv-Vermutung), jede andere Sprache: klein; (4) das erste Wort
    und jedes Wort nach `.`, `?`, `!`, `:` beginnt gross.

    Die Vokal-Faustregel der Hoertext-Stufe wird hier nicht benutzt: sie hielte WERKSTATT,
    PART, START, DAS, ALS, DER, THE fuer Kuerzel.
    """
    if hat_kleinbuchstaben(text):
        return text
    deutsch = sprache.lower()[:2] == "de"

    def wort(treffer: re.Match[str]) -> str:
        w = treffer[0]
        satzanfang = not (davor := text[: treffer.start()].rstrip(' \t\u201e\u00bb"(')) or (
            davor[-1] in ".!?:"
        )
        if _ROEMISCH.fullmatch(w) or w in versal_belegt:
            return w
        form = formen.get(w.lower())
        if form is None:
            form = w.capitalize() if deutsch else w.lower()
        return form[0].upper() + form[1:] if satzanfang else form

    return _BUCHSTABEN.sub(wort, text)
