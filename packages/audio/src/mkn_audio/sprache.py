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

**Akzente zaehlen nicht.** Beide Seiten werden ohne Akzente verglichen (`für` = `fur`),
damit die Listen reines ASCII bleiben; die wenigen Treffer, die dadurch mit einem
anderen Wort zusammenfallen, verschieben den Anteil nicht merklich.
"""

from __future__ import annotations

import re
import unicodedata

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
