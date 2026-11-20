"""Abgleich zweier Lesungen einer Seite: nur Uebereinstimmung wird uebernommen.

**Warum ueber Wert und Ort statt ueber Text.** Zwei Modelle schreiben dieselbe
Seite nie gleich ab: der eine setzt Klammern um die Einheit, der andere nicht,
einer schreibt „6,5-9,5“, der andere „6,5~9,5“. Wer Texte vergleicht, verliert
deshalb fast alles an Formatierung. Verglichen wird hier, was eine Angabe
ausmacht: die Zeichen des Werts (als Schluessel ohne Formatierung) und wo er
steht. Namen dienen nur der Paarung, wenn die Lage nicht reicht.

**Was nicht uebereinstimmt, wird nie geraten.** Liest nur ein Leser eine Angabe
oder lesen beide an derselben Stelle Verschiedenes, steht sie mit Grund auf der
Klaerliste. Ein fehlender Wert ist sichtbar, ein falscher nicht.

Reine Funktionen, kein Modell, keine Datei: gleiche Lesungen ergeben immer
dasselbe Ergebnis.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

LAGE_NAH = 45
"""Hoechster Abstand der Wertmitten (Tausendstel der Seite), bis zu dem gleiche Werte als dieselbe Stelle gelten."""

NAME_AEHNLICH = 0.6
"""Ab dieser Namensaehnlichkeit gelten gleiche Werte auch ohne nahe Lage als dieselbe Angabe."""

LAGE_GLEICH = 12
"""Bis zu diesem Abstand stehen zwei Angaben an derselben Stelle: verschiedene Werte dort sind ein Widerspruch."""

FELDER = (
    "abschnitt",
    "bezeichnung",
    "zusatz",
    "art",
    "wert",
    "vergleich",
    "einheit",
    "bereich",
    "kennzeichen",
)
"""Die Textfelder einer Angabe, wie der Leseauftrag sie verlangt."""

_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def _roh(text: object) -> str | None:
    """Der Text ohne Leerraum und ohne Klammern oder Tabellenstriche am Rand; ``None`` fuer leer."""
    if text is None:
        return None
    # Minuszeichen und Halbgeviertstrich sind fuer den Vergleich ein Bindestrich.
    t = str(text).replace("\u2212", "-").replace("\u2013", "-")
    t = t.strip().strip("|()[]{};*").strip()
    t = re.sub(r"\s+", "", t)
    return t or None


def wert_schluessel(wert: object) -> str | None:
    """Der Vergleichsschluessel eines Werts: ohne Leerraum und Randklammern, ein Punkt am Ende einer Zahl zaehlt nicht.

    Der Schluessel entscheidet nur, ob zwei Leser dieselben Zeichen gesehen haben. Geschrieben wird der Wert,
    wie er gedruckt ist — der Schluessel landet nie im Ergebnis. Komma und Punkt bleiben verschieden: „1.234“
    und „1,234“ sind zwei Zahlen, und zwei Leser derselben Seite waren sich im Dezimalzeichen nie uneins.
    """
    t = _roh(wert)
    if t is None:
        return None
    return re.sub(r"(?<=\d)\.$", "", t)


def einheit_schluessel(einheit: object) -> str | None:
    """Einheit ohne Gross-/Kleinschreibung; Hochzwei und Mikro in ihrer Tastaturform."""
    t = _roh(einheit)
    if t is None:
        return None
    return t.replace("²", "2").replace("µ", "u").replace("μ", "u").lower()


def bereich_schluessel(bereich: object) -> str | None:
    """Bereich mit einem Trenner: Tilde, Bindestrich und „bis“ zwischen zwei Zahlen sind dasselbe."""
    t = _roh(bereich)
    if t is None:
        return None
    t = re.sub(r"(?<=\d)bis(?=[\d-])", "~", t)
    return re.sub(r"(?<=\d)[~-](?=[\d-])", "~", t)


def name_schluessel(name: object) -> str:
    """Name ohne Umlaute, Satzzeichen und Gross-/Kleinschreibung."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower().translate(_UMLAUTE))


def name_aehnlichkeit(a: object, b: object) -> float:
    """0 bis 1; 0, wenn einer der Namen leer ist."""
    x, y = name_schluessel(a), name_schluessel(b)
    if not x or not y:
        return 0.0
    return difflib.SequenceMatcher(None, x, y).ratio()


def _teile(angabe: dict[str, Any], *felder: str) -> str:
    return " ".join(str(angabe[f]) for f in felder if angabe.get(f))


def _woerter(name: str) -> set[str]:
    return {w for w in (name_schluessel(t) for t in re.split(r"[^0-9A-Za-zÄÖÜäöüß]+", name)) if w}


def _direkt(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Aehnlichkeit der Namen ohne jede Umdeutung: Bezeichnung und Zusatz gegen Bezeichnung und Zusatz."""
    return name_aehnlichkeit(_teile(a, "bezeichnung", "zusatz"), _teile(b, "bezeichnung", "zusatz"))


def namen_aehnlichkeit(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Wie aehnlich zwei Leser dieselbe Angabe benennen — gleich, wie sie den Namen aufteilen.

    Der eine schreibt den Zeilennamen in ``bezeichnung`` und die Spalte in ``zusatz``, der andere umgekehrt; der
    eine nennt die Ueberschrift als ``abschnitt``, der andere als Teil des Namens; der eine schreibt die Langform
    dazu („USt Umsatzsteuer“), der andere nicht („USt“). Verglichen wird in jeder dieser Gliederungen, es
    zaehlt die beste. Immer zaehlt der ganze Name mit Zusatz (die Spalte oder das Datum unterscheidet), und der
    Abschnitt zaehlt nie auf beiden Seiten zugleich: zwei verschiedene Groessen derselben Tabelle wuerden sonst
    allein durch ihre gemeinsame Ueberschrift aehnlich.
    """
    name_a, name_b = _teile(a, "bezeichnung", "zusatz"), _teile(b, "bezeichnung", "zusatz")
    woerter_a, woerter_b = _woerter(name_a), _woerter(name_b)
    if woerter_a and woerter_b and (woerter_a <= woerter_b or woerter_b <= woerter_a):
        return 1.0
    return max(
        name_aehnlichkeit(name_a, name_b),
        name_aehnlichkeit(name_a, _teile(b, "zusatz", "bezeichnung")),
        name_aehnlichkeit(_teile(a, "abschnitt", "bezeichnung", "zusatz"), name_b),
        name_aehnlichkeit(name_a, _teile(b, "abschnitt", "bezeichnung", "zusatz")),
    )


NAME_GLEICH = 0.8
"""Ab dieser direkten Aehnlichkeit nennt eine Angabe dieselbe Groesse wie eine andere."""


def _widerspricht(x: dict[str, Any], y: dict[str, Any], frei: list[dict[str, Any]]) -> bool:
    """Hat der andere Leser die Groesse von ``x`` selbst gelesen — mit einem anderen Wert?

    ``x`` und ``y`` sind ein Paar mit gleichem Wert. ``frei`` sind die Angaben des Lesers von ``y``, die kein Paar
    gefunden haben. Nennt eine davon die Groesse von ``x`` (direkte Aehnlichkeit ab ``NAME_GLEICH``) und besser als
    ``y`` es tut, dann hat dieser Leser die Zeile von ``x`` gesehen und dort etwas anderes gelesen: einer von beiden
    ist in der Zeile verrutscht, das Paar ist keine Bestaetigung.
    """
    eigen = _direkt(x, y)
    return any(_direkt(x, z) >= NAME_GLEICH and _direkt(x, z) > eigen for z in frei)


def _lage(angabe: dict[str, Any]) -> tuple[int, int, int, int] | None:
    lage = angabe.get("lage")
    if not isinstance(lage, (list, tuple)) or len(lage) != 4:
        return None
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1000 for v in lage):
        return None
    oben, links, unten, rechts = (int(v) for v in lage)
    if (oben, links, unten, rechts) == (0, 0, 0, 0):
        return None  # die Vorlage aus dem Auftrag, keine Lage
    return (oben, links, unten, rechts)


def abstand(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Abstand der Wertmitten in Tausendstel; unendlich, wenn eine Lage fehlt oder ungueltig ist."""
    la, lb = _lage(a), _lage(b)
    if la is None or lb is None:
        return float("inf")
    dy = (la[0] + la[2]) / 2 - (lb[0] + lb[2]) / 2
    dx = (la[1] + la[3]) / 2 - (lb[1] + lb[3]) / 2
    return (dx * dx + dy * dy) ** 0.5


def _text(angabe: dict[str, Any], feld: str) -> str | None:
    wert = angabe.get(feld)
    if wert is None:
        return None
    t = str(wert).strip()
    return t or None


def _text_schluessel(text: object) -> str | None:
    """Text ohne Leerraum, sonst Zeichen fuer Zeichen: ein Stern als Kennzeichen ist nicht dasselbe wie keins."""
    t = re.sub(r"\s+", "", str(text)) if text is not None else ""
    return t or None


def _einig(a: dict[str, Any], b: dict[str, Any]) -> tuple[dict[str, str | None], list[str]]:
    """Die Nebenfelder eines Paars: uebernommen, wo beide Leser dasselbe sagen, sonst offen."""
    felder: dict[str, str | None] = {}
    offen: list[str] = []
    for feld, schluessel in (
        ("einheit", einheit_schluessel),
        ("bereich", bereich_schluessel),
        ("kennzeichen", _text_schluessel),
        ("art", _text_schluessel),
    ):
        if schluessel(a.get(feld)) == schluessel(b.get(feld)):
            felder[feld] = _text(a, feld)
        else:
            felder[feld] = None
            offen.append(feld)
    return felder, offen


def _eintrag(
    a: dict[str, Any] | None,
    b: dict[str, Any] | None,
    ausgang: str,
    grund: str,
) -> dict[str, Any]:
    erster = a if a is not None else b
    assert erster is not None
    eintrag: dict[str, Any] = {
        "abschnitt": _text(erster, "abschnitt"),
        "bezeichnung": _text(erster, "bezeichnung"),
        "zusatz": _text(erster, "zusatz"),
        "art": _text(erster, "art"),
        "wert": _text(erster, "wert"),
        "vergleich": _text(erster, "vergleich"),
        "einheit": _text(erster, "einheit"),
        "bereich": _text(erster, "bereich"),
        "kennzeichen": _text(erster, "kennzeichen"),
        "lage": list(_lage(erster) or ()) or None,
        "ausgang": ausgang,
        "grund": grund,
        "offen": [],
        "unsicher": bool((a or {}).get("unsicher")) or bool((b or {}).get("unsicher")),
        "leser": {"a": a, "b": b},
    }
    return eintrag


def gleiche_ab(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Gleicht die Angaben zweier Leser einer Seite ab.

    Rueckgabe: je Angabe ein Eintrag mit ``ausgang`` (``uebernommen`` oder ``klaerliste``), ``grund``
    (``zwei_leser``, ``vergleich_uneins``, ``name_uneins``, ``leser_uneins``, ``nur_leser_a``, ``nur_leser_b``),
    den Feldern wie der erste Leser sie gedruckt gelesen hat, ``offen`` (Nebenfelder, in denen die Leser uneins
    sind; sie sind dann ``None``) und beiden Lesungen unter ``leser``. Angaben ohne Wert werden nicht gefuehrt.
    """
    a = [x for x in a if wert_schluessel(x.get("wert"))]
    b = [x for x in b if wert_schluessel(x.get("wert"))]

    kandidaten: list[tuple[float, int, int]] = []
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            if wert_schluessel(x.get("wert")) != wert_schluessel(y.get("wert")):
                continue
            d = abstand(x, y)
            s = namen_aehnlichkeit(x, y)
            if d <= LAGE_NAH or s >= NAME_AEHNLICH:
                kandidaten.append((s - min(d, 1000.0) / 100, i, j))
    # Bestes Paar zuerst; bei gleicher Guete entscheidet die Reihenfolge der Lesungen, nie der Zufall.
    kandidaten.sort(key=lambda k: (-k[0], k[1], k[2]))

    vergeben_a: set[int] = set()
    vergeben_b: set[int] = set()
    paare: dict[int, int] = {}
    for _, i, j in kandidaten:
        if i in vergeben_a or j in vergeben_b:
            continue
        vergeben_a.add(i)
        vergeben_b.add(j)
        paare[i] = j

    frei_a = [x for i, x in enumerate(a) if i not in vergeben_a]
    frei_b = [y for j, y in enumerate(b) if j not in vergeben_b]
    ergebnis: list[dict[str, Any]] = []
    for i, x in enumerate(a):
        if i in paare:
            y = b[paare[i]]
            if _text_schluessel(x.get("vergleich")) != _text_schluessel(y.get("vergleich")):
                # „< 5“ und „5“ sind verschiedene Aussagen, auch wenn die Ziffern stimmen.
                ergebnis.append(_eintrag(x, y, "klaerliste", "vergleich_uneins"))
                continue
            if namen_aehnlichkeit(x, y) < NAME_AEHNLICH or _widerspricht(x, y, frei_b) or _widerspricht(y, x, frei_a):
                # Gleicher Wert an naher Stelle, aber die Leser nennen verschiedene Groessen — oder einer hat die
                # Groesse des anderen mit einem anderen Wert gelesen: einer ist in der Zeile verrutscht. Der Wert
                # stimmt, wozu er gehoert, ist ungeklaert.
                ergebnis.append(_eintrag(x, y, "klaerliste", "name_uneins"))
                continue
            eintrag = _eintrag(x, y, "uebernommen", "zwei_leser")
            felder, offen = _einig(x, y)
            eintrag.update(felder)
            eintrag["offen"] = offen
            ergebnis.append(eintrag)
            continue
        naechster = min(
            ((abstand(x, y), j) for j, y in enumerate(b) if j not in vergeben_b),
            default=(float("inf"), -1),
        )
        if naechster[0] <= LAGE_GLEICH:
            vergeben_b.add(naechster[1])
            eintrag = _eintrag(x, b[naechster[1]], "klaerliste", "leser_uneins")
            eintrag["wert"] = None
            ergebnis.append(eintrag)
        else:
            ergebnis.append(_eintrag(x, None, "klaerliste", "nur_leser_a"))
    for j, y in enumerate(b):
        if j not in vergeben_b:
            ergebnis.append(_eintrag(None, y, "klaerliste", "nur_leser_b"))
    return ergebnis
