"""Pruefung ohne Menschen: was das Sprachmodell nicht aendern darf, in BEIDE Richtungen.

**Warum zwei Richtungen.** Ein Modell kann etwas weglassen (ein Satz fehlt im Hoerstueck)
oder etwas erfinden (ein Satz, den die Quelle nie sagte, oder eine Anweisung aus dem
fremden Dokument, der es folgt). Wer nur eine Richtung prueft, sieht die andere nie.

**Warum eine eigene Zahlen-Regel.** In einem langen Absatz bleibt ein vertauschtes
Wort unter jeder sinnvollen Wortgrenze -- und "vier" gegen "fuenf" ist der Fehler,
der nie passieren darf. Darum muss die Menge der Zahlen vor und nach der Aufbereitung
gleich sein, unabhaengig von der Wortbilanz.

Gemessen wird auf Multimengen ("Er kam." zweimal ist ein Zugewinn), nicht auf Mengen:
sonst waere ein wiederholter Satz aus lauter bekannten Woertern unsichtbar.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

# Hoechstens 3 % der Woerter duerfen fehlen oder neu sein (die Abweichungsgrenze).
GRENZE = 0.03

_MAX_WORTLAENGE = 80  # laengere "Woerter" sind keine Zahlen; begrenzt auch die Suche

_STAMM = (
    "null|eins|zwei|drei|vier|fünf|sechs|sieben|acht|neun|zehn|elf|zwölf|sechzehn|siebzehn|"
    "zwanzig|dreißig|vierzig|fünfzig|sechzig|siebzig|achtzig|neunzig|hundert|tausend|"
    "millionen|million|milliarden|milliarde"
)
# "ein" und "und" verbinden nur ("einundzwanzig"); allein sind es Artikel und Bindewort.
_BAUSTEIN = rf"(?:{_STAMM}|ein|und)"
_ORDNUNG = r"(?:te|ten|ter|tem|tes|ste|sten|ster|stem|stes)"
_ENDUNG = r"(?:e|en|er|em|es)"
_ZAHLWORT = re.compile(
    rf"(?:{_BAUSTEIN}+|{_BAUSTEIN}+{_ORDNUNG}|{_BAUSTEIN}*(?:erst|dritt|siebt|acht){_ENDUNG})"
)
_HAT_STAMM = re.compile(_STAMM + r"|erst|dritt|siebt")


def woerter(text: str) -> list[str]:
    """Die Woerter eines Textes, klein geschrieben (Gross/Klein ist hier keine Aenderung)."""
    return re.findall(r"\w+", text.lower())


def ist_zahl(wort: str) -> bool:
    """Ziffern enthalten, oder ein deutsches Zahlwort (auch zusammengesetzt, auch Ordnungszahl)."""
    if any(zeichen.isdigit() for zeichen in wort):
        return True
    if len(wort) > _MAX_WORTLAENGE or not _HAT_STAMM.search(wort):
        return False
    return _ZAHLWORT.fullmatch(wort) is not None


def zahlwoerter(woerter_: Iterable[str]) -> Counter[str]:
    """Die Zahlen in einer Wortliste, mit Haeufigkeit."""
    return Counter(w for w in (x.lower() for x in woerter_) if ist_zahl(w))


def _beispiele(menge: Counter[str]) -> str:
    return ", ".join(sorted(menge)[:5])


def _prozent(anteil: float) -> str:
    return f"{anteil * 100:.1f}".replace(".", ",") + " %"


def pruefe(vorher: str, nachher: str, *, grenze: float = GRENZE) -> str | None:
    """None, wenn `nachher` eine zulaessige Aufbereitung von `vorher` ist, sonst der Grund."""
    wv, wn = woerter(vorher), woerter(nachher)

    zv, zn = zahlwoerter(wv), zahlwoerter(wn)
    if zv != zn:
        weg = _beispiele(zv - zn) or "-"
        dazu = _beispiele(zn - zv) or "-"
        return f"Zahl geändert (fehlt: {weg}; neu: {dazu})"

    v, n = Counter(wv), Counter(wn)
    basis = max(len(wv), 1)
    fehlt, neu = v - n, n - v
    verlust, zugewinn = sum(fehlt.values()) / basis, sum(neu.values()) / basis
    if verlust > grenze:
        return f"Wortverlust {_prozent(verlust)} (fehlt: {_beispiele(fehlt)})"
    if zugewinn > grenze:
        return f"Zugewinn {_prozent(zugewinn)} (neu: {_beispiele(neu)})"
    return None
