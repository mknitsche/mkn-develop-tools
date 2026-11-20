"""Gezieltes Ablesen: markierte Stellen eines Diagramms ohne gedruckte Zahlen — von zwei Lesern, vom Programm geprueft.

**Der Aufrufer sagt, was er braucht.** Ein Ableseauftrag nennt EIN Diagramm einer Seite und je gesuchter Reihe die
Stellen (Vorgabe: jeder markierte Messpunkt, sonst benannte Marken), die Achsen als Kennwort und die Toleranz je
Achse. Welche Achse zu einer Reihe gehoert, sagt allein der Auftrag, nie der Leser. Die Basis liest nie von sich aus
ein ganzes Diagramm.

**Jeder Leser liefert Lagen und Werte.** Je Achse die beschrifteten Teilstriche mit gedruckter Zahl und Lage, je
Stelle die Lage des Markers und den selbst abgelesenen Wert. Das Programm rechnet aus den Ankern eine Gerade je Achse
(Richtung aus den Ankern, in Bildpunkten — das faengt einen gedrehten oder schraegen Scan ab) und daraus den Wert der
Lage. So entstehen je Wert vier Stimmen: gerechnet und abgelesen, je Leser.

**Konsistenzpruefung, keine Fehlerschranke.** Beide Leser sehen dasselbe Bild. Ein gemeinsamer Fehler — schraeger
Druck, ein von beiden ausgelassener Marker, eine von beiden verlesene Achsenzahl — bleibt unentdeckt; nur die vom
Fach erwartete ``anzahl`` faengt das Auslassen. Darum traegt das Ergebnis ``herkunft: "abgelesen"`` und je Wert seine
Spanne: ein abgelesener Wert ist nie ein gedruckter.

**Fehler gegen Klaerliste.** Ein technischer Fehler (Anbieter, ungueltige oder abgeschnittene Antwort, kaputter
Auftrag) bricht laut. Was am Diagramm nicht lesbar ist (zu wenige Anker, krumme oder schiefe Achse, uneinige Leser),
steht mit Grund auf der Klaerliste.

Die Rechnung (``zahl``, ``achse_aus_ankern``, ``gleiche_ab`` ...) ist rein und ohne Leser pruefbar; ``lies_ablesung``
ist der Lauf mit Mitschrift wie bei ``lesen``.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pymupdf

from mkn_dokument import __version__, lesen
from mkn_dokument.auftrag import AntwortUngueltig
from mkn_dokument.leser import Leser
from mkn_dokument.seitenlesung import normiere

ERGEBNIS = "ablesung.json"
FUNKTION = "ablesen"
HERKUNFT = "abgelesen"

MIN_ANKER = 3
"""Mindestens so viele Anker mit verschiedenen Zahlen traegt eine Achse."""
GERADE_GRENZE = 0.01
"""(1) Kein Anker weicht um mehr als diesen Anteil der Zahlenspanne der Anker von der Geraden ab."""
QUER_GRENZE = 0.01
"""(2) Kein Anker liegt quer zur Achsenrichtung um mehr als diesen Anteil der Ankerstrecke ab."""
WINKEL_GRENZE = 2.0
"""(3) Zwei Achsen einer Reihe stehen 90 Grad plus/minus so viele Grad zueinander, sonst ist das Bild geschert."""
LAGE_GRENZE = 0.015
"""Die Lagen eines Paars liegen hoechstens diesen Anteil der laengeren Bildkante auseinander."""

ACHSEN = ("y", "x")
_STIMMEN = ("a_lage", "a_abgelesen", "b_lage", "b_abgelesen")
_EPS = 1e-9


class AuftragUngueltig(ValueError):
    """Der Ableseauftrag hat nicht die verlangte Form."""


class AchseUnklar(ValueError):
    """Aus den Ankern eines Lesers entsteht keine verlaessliche Achse; ``grund`` sagt warum."""

    def __init__(self, grund: str) -> None:
        super().__init__(grund)
        self.grund = grund


# --- Zahlen --------------------------------------------------------------------------------------------------------

_ZAHL = re.compile(r"[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)")
#: Ein Trenner mit genau drei Ziffern dahinter und einem Ganzzahlteil ungleich 0 („2.500“, „12,500“) kann ein
#: Tausender- oder ein Dezimaltrenner sein — welcher, waere geraten.
_MEHRDEUTIG = re.compile(r"[+-]?[1-9]\d{0,2}[.,]\d{3}")


def zahl(text: object) -> float | None:
    """Die Zahl eines Textes: Vorzeichen, Ziffern, hoechstens ein Komma oder Punkt als Dezimalzeichen — sonst ``None``.

    Ein Trenner ist ein Dezimalzeichen — ausser er ist mehrdeutig: genau drei Ziffern dahinter und ein Ganzzahlteil
    ungleich 0 („1.234“, „2.500“, „12,500“) kann ebenso ein Tausendertrenner sein und ist keine Zahl (der Anker
    zaehlt nicht, die Stimme fehlt); „0.125“ und „0,500“ bleiben Zahlen. „12 W“, „ca. 5“ und „1.234,5“ sind keine Zahl.
    """
    if not isinstance(text, str):
        return None
    t = text.strip().replace(chr(0x2212), "-")  # Minuszeichen des Drucks
    if not _ZAHL.fullmatch(t) or _MEHRDEUTIG.fullmatch(t):
        return None
    return float(t.replace(",", "."))


def stellen(toleranz: object) -> int:
    """Nachkommastellen einer Toleranz (Zahl oder Text): 3 → 0, 0.3 → 1, „0,25“ → 2."""
    text = toleranz if isinstance(toleranz, str) else repr(toleranz)
    exponent = Decimal(text.strip().replace(",", ".")).normalize().as_tuple().exponent
    assert isinstance(exponent, int)
    return max(0, -exponent)


def median(werte: list[float]) -> float:
    s = sorted(werte)
    mitte = len(s) // 2
    return s[mitte] if len(s) % 2 else (s[mitte - 1] + s[mitte]) / 2


def runde(wert: float, nachkomma: int) -> float | int:
    """Kaufmaennisch auf ``nachkomma`` Stellen; ohne Nachkommastellen eine ganze Zahl."""
    gerundet = Decimal(repr(wert)).quantize(Decimal(1).scaleb(-nachkomma), rounding=ROUND_HALF_UP)
    return int(gerundet) if nachkomma == 0 else float(gerundet)


# --- Auftrag -------------------------------------------------------------------------------------------------------

_REIHE_FELDER = {"name", "achse_y", "achse_x", "toleranz", "marken", "anzahl"}


def _toleranz(wert: object, wo: str) -> float | str:
    if isinstance(wert, bool) or not isinstance(wert, (int, float, str)):
        raise AuftragUngueltig(f"{wo}: Toleranz ist keine Zahl")
    t = zahl(wert) if isinstance(wert, str) else float(wert)
    if t is None or not math.isfinite(t) or t <= 0:
        raise AuftragUngueltig(f"{wo}: Toleranz muss eine Zahl groesser 0 sein")
    return wert


def pruefe_auftrag(objekt: object) -> dict[str, Any]:
    """Prueft einen Ableseauftrag und gibt ihn in fester Form zurueck; bricht laut bei allem, was nicht passt.

    Form: ``{"seite": 1, "diagramm": "<Titel>", "reihen": [{"name", "achse_y", "achse_x" (wahlweise),
    "toleranz": {"y": <Zahl>, "x": <Zahl, wenn achse_x>}, "marken": [...] (wahlweise), "anzahl": <n> (wahlweise)}]}``.
    Ein unbekanntes Feld bricht: ein vertipptes ``anzahl`` fehlte sonst still als Pruefung.
    """
    if not isinstance(objekt, dict):
        raise AuftragUngueltig("Auftrag ist kein Objekt")
    fremd = sorted(set(objekt) - {"seite", "diagramm", "reihen"})
    if fremd:
        raise AuftragUngueltig(f"Auftrag: unbekannte Felder {fremd}")
    seite, diagramm, reihen = objekt.get("seite"), objekt.get("diagramm"), objekt.get("reihen")
    if not isinstance(seite, int) or isinstance(seite, bool) or seite < 1:
        raise AuftragUngueltig("Auftrag: seite ist keine Seitennummer ab 1")
    if not isinstance(diagramm, str) or not diagramm.strip():
        raise AuftragUngueltig("Auftrag: diagramm (Titel oder Beschreibung) fehlt")
    if not isinstance(reihen, list) or not reihen:
        raise AuftragUngueltig("Auftrag: reihen fehlt oder ist leer")
    geprueft = []
    for nr, r in enumerate(reihen, start=1):
        wo = f"Reihe {nr}"
        if not isinstance(r, dict):
            raise AuftragUngueltig(f"{wo}: kein Objekt")
        fremd = sorted(set(r) - _REIHE_FELDER)
        if fremd:
            raise AuftragUngueltig(f"{wo}: unbekannte Felder {fremd}")
        for feld in ("name", "achse_y"):
            if not isinstance(r.get(feld), str) or not normiere(r[feld]):
                raise AuftragUngueltig(f"{wo}: {feld} fehlt")
        achse_x = r.get("achse_x")
        if achse_x is not None and (not isinstance(achse_x, str) or not normiere(achse_x)):
            raise AuftragUngueltig(f"{wo}: achse_x ist leer")
        achsen = ("y", "x") if achse_x is not None else ("y",)
        toleranz = r.get("toleranz")
        if not isinstance(toleranz, dict) or set(toleranz) != set(achsen):
            raise AuftragUngueltig(
                f"{wo}: toleranz braucht genau die Achsen {list(achsen)} (ohne Toleranz keine Uebernahme)"
            )
        marken = r.get("marken")
        if marken is not None and (
            not isinstance(marken, list)
            or not marken
            or not all(isinstance(m, str) and normiere(m) for m in marken)
            or len({normiere(m) for m in marken}) != len(marken)
        ):
            raise AuftragUngueltig(f"{wo}: marken ist keine Liste verschiedener Namen")
        anzahl = r.get("anzahl")
        if anzahl is not None and (not isinstance(anzahl, int) or isinstance(anzahl, bool) or anzahl < 0):
            raise AuftragUngueltig(f"{wo}: anzahl ist keine Zahl ab 0")
        if marken is not None and anzahl is not None and anzahl != len(marken):
            raise AuftragUngueltig(f"{wo}: anzahl passt nicht zur Zahl der marken")
        geprueft.append(
            {
                "name": r["name"].strip(),
                "achse_y": r["achse_y"].strip(),
                "achse_x": achse_x.strip() if achse_x is not None else None,
                "toleranz": {k: _toleranz(toleranz[k], wo) for k in achsen},
                "marken": [m.strip() for m in marken] if marken is not None else None,
                "anzahl": anzahl,
            }
        )
    if len({normiere(r["name"]) for r in geprueft}) != len(geprueft):
        raise AuftragUngueltig("Auftrag: eine Reihe steht zweimal")
    return {"seite": seite, "diagramm": diagramm.strip(), "reihen": geprueft}


def _zitat(text: str) -> str:
    return f"„{text}“"


def auftrag(ableseauftrag: dict[str, Any]) -> str:
    """Der Auftragstext an beide Leser (``ableseauftrag`` wie ``pruefe_auftrag`` ihn liefert).

    Anzahl und Toleranz stehen bewusst nicht darin: sie pruefen den Leser und duerfen ihn nicht lenken.
    """
    zeilen = []
    for r in ableseauftrag["reihen"]:
        if r["marken"]:
            stellen_text = "die Marken " + ", ".join(_zitat(m) for m in r["marken"])
        else:
            stellen_text = (
                "jeder markierte Messpunkt (die Marker selbst — nicht die Kurve dazwischen, keine Hilfspunkte)"
            )
        achsen = f"senkrecht an der Achse mit {_zitat(r['achse_y'])} im Namen"
        if r["achse_x"]:
            achsen += f", waagrecht an der Achse mit {_zitat(r['achse_x'])} im Namen"
        zeilen.append(f"- Reihe {_zitat(r['name'])}: {stellen_text}; abzulesen {achsen}.")
    reihen = "\n".join(zeilen)
    return f"""Du liest auf diesem Seitenbild gezielt EIN Diagramm ab: {_zitat(ableseauftrag["diagramm"])}. Das Diagramm kann gedreht oder schräg auf der Seite stehen. Andere Diagramme der Seite gehören nicht dazu.
Gesucht sind nur diese Stellen:
{reihen}
- achsen: jede Achse dieses Diagramms für sich (die waagrechte Größe und jede senkrechte Größe einzeln): name wie gedruckt (mit Einheit) und anker: möglichst alle beschrifteten Teilstriche, je Teilstrich zahl (die gedruckte Zahl als Text, genau wie gedruckt) und lage (die Lage des Teilstrichs auf der Achsenlinie).
- punkte: je gesuchter Stelle reihe (der Name aus der Liste oben, genau so geschrieben), marke (der gedruckte Name der Stelle, leer wenn keiner), lage (die Mitte des Markers), x_wert und y_wert (der Wert, den du selbst an der waagrechten und an der senkrechten Achse dieser Reihe abliest, als Zahl in Textform; leer, wenn die Reihe keine solche Achse hat).
- lage ist immer [oben, links] in Tausendstel der Bildhöhe und der Bildbreite des ganzen Seitenbilds.
Nichts schätzen, was nicht markiert ist; eine Stelle, die du nicht findest, lässt du weg.
Antworte nur mit JSON: {{"achsen": [{{"name": "", "anker": [{{"zahl": "", "lage": [0, 0]}}]}}], "punkte": [{{"reihe": "", "marke": "", "lage": [0, 0], "x_wert": "", "y_wert": ""}}]}}"""


_TEXT = {"type": "string"}
_LAGE = {"type": "array", "items": {"type": "integer"}}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "achsen": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": _TEXT,
                    "anker": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"zahl": _TEXT, "lage": _LAGE},
                            "required": ["zahl", "lage"],
                        },
                    },
                },
                "required": ["name", "anker"],
            },
        },
        "punkte": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"reihe": _TEXT, "marke": _TEXT, "lage": _LAGE, "x_wert": _TEXT, "y_wert": _TEXT},
                "required": ["reihe", "marke", "lage", "x_wert", "y_wert"],
            },
        },
    },
    "required": ["achsen", "punkte"],
}
"""Antwortform fuer Anbieter, die eine erzwungene Form kennen."""


# --- Antwortform ---------------------------------------------------------------------------------------------------


def _lage(wert: object, wo: str) -> list[float]:
    if (
        not isinstance(wert, list)
        or len(wert) != 2
        or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1000 for v in wert)
    ):
        raise AntwortUngueltig(f"{wo}: lage ist nicht [oben, links] in Tausendstel")
    return list(wert)


def _text(objekt: dict[str, Any], feld: str, wo: str) -> str:
    wert = objekt.get(feld)
    if wert is not None and not isinstance(wert, str):
        # Eine Zahl statt Text hat ihr Druckbild schon verloren (5.10 wird 5.1): nie still umformen.
        raise AntwortUngueltig(f"{wo}: {feld} ist kein Text")
    return wert or ""


def pruefe_antwort(antwort: object) -> dict[str, Any]:
    """Prueft die Form einer Leser-Antwort; fehlende Textfelder werden leer, alles andere Falsche bricht laut."""
    if not isinstance(antwort, dict) or not isinstance(antwort.get("achsen"), list):
        raise AntwortUngueltig('Antwort ist kein Objekt mit der Liste "achsen"')
    if not isinstance(antwort.get("punkte"), list):
        raise AntwortUngueltig('Antwort ohne die Liste "punkte"')
    achsen = []
    for i, roh in enumerate(antwort["achsen"], start=1):
        wo = f"Achse {i}"
        if not isinstance(roh, dict) or not isinstance(roh.get("anker"), list):
            raise AntwortUngueltig(f"{wo}: kein Objekt mit der Liste anker")
        anker = []
        for j, a in enumerate(roh["anker"], start=1):
            if not isinstance(a, dict):
                raise AntwortUngueltig(f"{wo}, Anker {j}: kein Objekt")
            anker.append(
                {"zahl": _text(a, "zahl", f"{wo}, Anker {j}"), "lage": _lage(a.get("lage"), f"{wo}, Anker {j}")}
            )
        achsen.append({"name": _text(roh, "name", wo), "anker": anker})
    punkte = []
    for i, roh in enumerate(antwort["punkte"], start=1):
        wo = f"Punkt {i}"
        if not isinstance(roh, dict):
            raise AntwortUngueltig(f"{wo}: kein Objekt")
        punkte.append(
            {
                "reihe": _text(roh, "reihe", wo),
                "marke": _text(roh, "marke", wo),
                "lage": _lage(roh.get("lage"), wo),
                "x_wert": _text(roh, "x_wert", wo),
                "y_wert": _text(roh, "y_wert", wo),
            }
        )
    return {"achsen": achsen, "punkte": punkte}


# --- Achsen --------------------------------------------------------------------------------------------------------

Punkt = tuple[float, float]
"""Lage in Bildpunkten (x nach rechts, y nach unten)."""


def in_bildpunkte(lage: list[float], breite: int, hoehe: int) -> Punkt:
    """[oben, links] in Tausendsteln → (x, y) in Bildpunkten."""
    return lage[1] / 1000 * breite, lage[0] / 1000 * hoehe


@dataclass(frozen=True)
class Achse:
    """Eine lineare Achse: Wert = a + b · ((Lage - mitte) · richtung)."""

    mitte: Punkt
    richtung: Punkt
    a: float
    b: float

    def wert(self, p: Punkt) -> float:
        return self.a + self.b * ((p[0] - self.mitte[0]) * self.richtung[0] + (p[1] - self.mitte[1]) * self.richtung[1])

    def aufsteigend(self) -> Punkt:
        """Die Richtung, in der die Werte wachsen."""
        s = 1.0 if self.b >= 0 else -1.0
        return s * self.richtung[0], s * self.richtung[1]


def achse_aus_ankern(anker: list[tuple[str, Punkt]]) -> Achse:
    """Die Achse aus Ankern ``(zahl als Text, Lage in Bildpunkten)``; bricht mit ``AchseUnklar``, wenn sie nicht traegt.

    Richtung = Hauptrichtung der Ankerlagen; Wert = a + b · Lage entlang der Richtung (kleinste Quadrate). Gilt nur,
    wenn (1) kein Anker um mehr als ``GERADE_GRENZE`` der Zahlenspanne von der Geraden abweicht und (2) keiner quer
    um mehr als ``QUER_GRENZE`` der Ankerstrecke abliegt. Anker ohne Zahl zaehlen nicht.
    """
    gueltig = [(v, p) for t, p in anker if (v := zahl(t)) is not None]
    if len({v for v, _ in gueltig}) < MIN_ANKER:
        raise AchseUnklar("zu_wenige_anker")
    n = len(gueltig)
    mx = sum(p[0] for _, p in gueltig) / n
    my = sum(p[1] for _, p in gueltig) / n
    sxx = sum((p[0] - mx) ** 2 for _, p in gueltig)
    syy = sum((p[1] - my) ** 2 for _, p in gueltig)
    sxy = sum((p[0] - mx) * (p[1] - my) for _, p in gueltig)
    winkel = 0.5 * math.atan2(2 * sxy, sxx - syy)
    d = (math.cos(winkel), math.sin(winkel))
    t = [(p[0] - mx) * d[0] + (p[1] - my) * d[1] for _, p in gueltig]
    q = [-(p[0] - mx) * d[1] + (p[1] - my) * d[0] for _, p in gueltig]
    v = [w for w, _ in gueltig]
    strecke = max(t) - min(t)
    if strecke <= _EPS:
        raise AchseUnklar("zu_wenige_anker")  # alle Anker an einer Stelle
    vm = sum(v) / n
    b = sum(ti * (vi - vm) for ti, vi in zip(t, v, strict=True)) / sum(ti * ti for ti in t)
    a = vm  # t ist um die Mitte zentriert
    spanne = max(v) - min(v)
    if max(abs(vi - (a + b * ti)) for ti, vi in zip(t, v, strict=True)) > GERADE_GRENZE * spanne + _EPS:
        raise AchseUnklar("krumm")
    if max(abs(qi) for qi in q) > QUER_GRENZE * strecke + _EPS:
        raise AchseUnklar("neben_der_achse")
    return Achse(mitte=(mx, my), richtung=d, a=a, b=b)


def winkel_zwischen(r1: Punkt, r2: Punkt) -> float:
    """Winkel zwischen zwei Richtungen in Grad, 0 bis 90."""
    c = abs(r1[0] * r2[0] + r1[1] * r2[1])
    return math.degrees(math.acos(min(1.0, c)))


def _achsen_eines_lesers(
    reihe: dict[str, Any], antwort: dict[str, Any], breite: int, hoehe: int
) -> dict[str, Achse | str]:
    """Je Achse der Reihe die Achse dieses Lesers oder der Grund, warum sie unklar ist."""
    ergebnis: dict[str, Achse | str] = {}
    for k in ACHSEN:
        kennwort = reihe[f"achse_{k}"]
        if kennwort is None:
            continue
        treffer = [ax for ax in antwort["achsen"] if normiere(kennwort) in normiere(ax["name"])]
        if len(treffer) > 1:
            # „Last (N)“ und „rel. Last (%)“: gilt die eine Achse, deren Name mit dem Kennwort BEGINNT
            am_anfang = [ax for ax in treffer if normiere(ax["name"]).startswith(normiere(kennwort))]
            if len(am_anfang) == 1:
                treffer = am_anfang
        if not treffer:
            ergebnis[k] = "kennwort_keine_achse"
            continue
        if len(treffer) > 1:
            ergebnis[k] = "kennwort_mehrere_achsen"
            continue
        try:
            ergebnis[k] = achse_aus_ankern(
                [(x["zahl"], in_bildpunkte(x["lage"], breite, hoehe)) for x in treffer[0]["anker"]]
            )
        except AchseUnklar as unklar:  # Schutzgut falsche Information: die Achse traegt keinen Wert, Grund bleibt
            ergebnis[k] = unklar.grund
    y, x = ergebnis.get("y"), ergebnis.get("x")
    if isinstance(y, Achse) and isinstance(x, Achse) and winkel_zwischen(y.richtung, x.richtung) < 90 - WINKEL_GRENZE:
        ergebnis = {"y": "nicht_rechtwinklig", "x": "nicht_rechtwinklig"}
    return ergebnis


# --- Abgleich (rein) -----------------------------------------------------------------------------------------------


def _sortierrichtung(achsen: dict[str, dict[str, Achse | str]]) -> Punkt:
    """Eine gemeinsame Richtung entlang der waagrechten Groesse fuer beide Leser (beide lesen dasselbe Bild)."""
    for leser in ("a", "b"):
        x = achsen[leser].get("x")
        if isinstance(x, Achse):
            return x.aufsteigend()
    for leser in ("a", "b"):
        y = achsen[leser].get("y")
        if isinstance(y, Achse):
            u = y.aufsteigend()
            return -u[1], u[0]  # quer zur senkrechten: bei aufrechtem Diagramm nach rechts
    return 1.0, 0.0


def _paare(
    pa: list[dict[str, Any]],
    pb: list[dict[str, Any]],
    marken: list[str] | None,
    richtung: Punkt,
    breite: int,
    hoehe: int,
) -> list[tuple[dict[str, Any], dict[str, Any]]] | None:
    """Gepaart ueber normierte Marken, wenn der Auftrag Marken nennt oder alle Stellen beider Leser eine tragen, sonst
    in der Reihenfolge entlang ``richtung``. ``None``, wenn die Marken nicht zueinander passen — nennt der Auftrag
    Marken, muessen die Marken jedes Lesers genau diese sein."""
    if marken is not None or (pa and all(normiere(p["marke"]) for p in pa + pb)):
        ma = {normiere(p["marke"]): p for p in pa}
        mb = {normiere(p["marke"]): p for p in pb}
        if len(ma) != len(pa) or len(mb) != len(pb) or set(ma) != set(mb) or "" in ma:
            return None
        if marken is not None and set(ma) != {normiere(m) for m in marken}:
            return None
        reihenfolge = sorted(ma, key=lambda m: _entlang(ma[m], richtung, breite, hoehe))
        return [(ma[m], mb[m]) for m in reihenfolge]
    sa = sorted(pa, key=lambda p: _entlang(p, richtung, breite, hoehe))
    sb = sorted(pb, key=lambda p: _entlang(p, richtung, breite, hoehe))
    return list(zip(sa, sb, strict=True))


def _entlang(p: dict[str, Any], richtung: Punkt, breite: int, hoehe: int) -> float:
    x, y = in_bildpunkte(p["lage"], breite, hoehe)
    return x * richtung[0] + y * richtung[1]


def _stelle(
    reihe: dict[str, Any],
    pa: dict[str, Any],
    pb: dict[str, Any],
    achsen: dict[str, dict[str, Achse | str]],
    breite: int,
    hoehe: int,
) -> dict[str, Any]:
    lage_a, lage_b = in_bildpunkte(pa["lage"], breite, hoehe), in_bildpunkte(pb["lage"], breite, hoehe)
    werte: dict[str, Any] = {}
    unklar = fehlt = uneins = False
    for k in ACHSEN:
        if reihe[f"achse_{k}"] is None:
            continue
        stimmen: dict[str, float | None] = {}
        for leser, p, lage in (("a", pa, lage_a), ("b", pb, lage_b)):
            achse = achsen[leser][k]
            stimmen[f"{leser}_lage"] = achse.wert(lage) if isinstance(achse, Achse) else None
            stimmen[f"{leser}_abgelesen"] = zahl(p[f"{k}_wert"])
            unklar |= not isinstance(achse, Achse)
        da = [v for v in stimmen.values() if v is not None]
        spanne = [min(da), max(da)] if da else None
        fehlt |= any(stimmen[s] is None for s in _STIMMEN if s.endswith("abgelesen"))
        tol = reihe["toleranz"][k]
        tol_zahl = zahl(tol) if isinstance(tol, str) else float(tol)
        assert tol_zahl is not None
        uneins |= spanne is not None and spanne[1] - spanne[0] > tol_zahl + _EPS
        werte[k] = {
            "kennwort": reihe[f"achse_{k}"],
            "wert": None,
            "spanne": spanne,
            "stimmen": {s: stimmen[s] for s in _STIMMEN},
            "_median": (median(da), stellen(tol)) if da else None,
        }
    abstand = math.dist(lage_a, lage_b)
    if abstand > LAGE_GRENZE * max(breite, hoehe):
        ausgang, grund = "klaerliste", "lage_uneins"
    elif unklar:
        ausgang, grund = "klaerliste", "achse_unklar"
    elif fehlt:
        ausgang, grund = "klaerliste", "wert_fehlt"
    elif uneins:
        ausgang, grund = "klaerliste", "stimmen_uneins"
    else:
        ausgang, grund = "uebernommen", None
    for w in werte.values():
        m = w.pop("_median")
        if ausgang == "uebernommen" and m is not None:
            w["wert"] = runde(*m)
    return {
        "reihe": reihe["name"],
        "marke": pa["marke"] or pb["marke"],
        "lage": [round((pa["lage"][i] + pb["lage"][i]) / 2, 1) for i in (0, 1)],
        "achsen": werte,
        "ausgang": ausgang,
        "grund": grund,
    }


def gleiche_ab(
    ableseauftrag: dict[str, Any], a: dict[str, Any], b: dict[str, Any], breite: int, hoehe: int
) -> dict[str, Any]:
    """Gleicht die Antworten zweier Leser zu einem Ableseauftrag ab (rein; Bildgroesse in Bildpunkten).

    Rueckgabe: ``reihen`` (je Reihe ``ausgang`` ``abgeglichen`` oder ``klaerliste`` mit ``grund`` ``anzahl_uneins``,
    ``anzahl_passt_nicht`` oder ``marke_uneins``, die ``anzahl`` je Leser und erwartet, und je Leser der Zustand jeder
    Achse), ``stellen`` (je gepaarter Stelle der abgeglichenen Reihen ``reihe``, ``marke``, ``lage``, je Achse
    ``wert``, ``spanne`` und die vier ``stimmen``, ``ausgang``, ``grund``) und ``ohne_reihe`` (Stellen je Leser, die
    keiner Reihe des Auftrags gehoeren).
    """
    reihen_ergebnis: list[dict[str, Any]] = []
    stellen_ergebnis: list[dict[str, Any]] = []
    namen = {normiere(r["name"]) for r in ableseauftrag["reihen"]}
    ohne_reihe = {
        name: sum(1 for p in antwort["punkte"] if normiere(p["reihe"]) not in namen)
        for name, antwort in (("a", a), ("b", b))
    }
    for reihe in ableseauftrag["reihen"]:
        pa = [p for p in a["punkte"] if normiere(p["reihe"]) == normiere(reihe["name"])]
        pb = [p for p in b["punkte"] if normiere(p["reihe"]) == normiere(reihe["name"])]
        achsen = {
            "a": _achsen_eines_lesers(reihe, a, breite, hoehe),
            "b": _achsen_eines_lesers(reihe, b, breite, hoehe),
        }
        erwartet = (
            reihe["anzahl"] if reihe["anzahl"] is not None else (len(reihe["marken"]) if reihe["marken"] else None)
        )
        zeile: dict[str, Any] = {
            "reihe": reihe["name"],
            "ausgang": "abgeglichen",
            "grund": None,
            "anzahl": {"a": len(pa), "b": len(pb), "erwartet": erwartet},
            "achsen": {
                leser: {k: "ok" if isinstance(v, Achse) else v for k, v in achsen[leser].items()}
                for leser in ("a", "b")
            },
        }
        reihen_ergebnis.append(zeile)
        if len(pa) != len(pb):
            zeile |= {"ausgang": "klaerliste", "grund": "anzahl_uneins"}
            continue
        if erwartet is not None and len(pa) != erwartet:
            zeile |= {"ausgang": "klaerliste", "grund": "anzahl_passt_nicht"}
            continue
        paare = _paare(pa, pb, reihe["marken"], _sortierrichtung(achsen), breite, hoehe)
        if paare is None:
            zeile |= {"ausgang": "klaerliste", "grund": "marke_uneins"}
            continue
        stellen_ergebnis += [_stelle(reihe, x, y, achsen, breite, hoehe) for x, y in paare]
    return {"reihen": reihen_ergebnis, "stellen": stellen_ergebnis, "ohne_reihe": ohne_reihe}


# --- Lauf ----------------------------------------------------------------------------------------------------------


def lies_ablesung(
    eingabe: Path,
    ordner: Path,
    leser_a: Leser,
    leser_b: Leser,
    ableseauftrag: object,
) -> dict[str, Any]:
    """Liest das Diagramm des Auftrags mit beiden Lesern ab, gleicht ab und schreibt ``ordner/ablesung.json``.

    Rueckgabe und Datei: ``{"fassung", "funktion": "ablesen", "herkunft": "abgelesen", "quelle", "seite", "auftrag",
    "leser", "bild": {"breite", "hoehe"}, "reihen", "stellen", "ohne_reihe"}``. Ein Auftrag ist ein Diagramm; ein
    zweiter Auftrag im selben Ordner ersetzt die Datei (die Mitschrift bleibt). Jeder Fehler bricht laut.
    """
    geprueft = pruefe_auftrag(ableseauftrag)
    eingabe = Path(eingabe)
    ordner = Path(ordner)
    quelle, bilder = lesen.bereite_vor(eingabe, ordner, leser_a, leser_b)
    if geprueft["seite"] > len(bilder):
        raise AuftragUngueltig(f"Auftrag nennt Seite {geprueft['seite']}, das Dokument hat {len(bilder)}")
    bild = bilder[geprueft["seite"] - 1]
    pixel = pymupdf.Pixmap(str(bild))
    breite, hoehe = pixel.width, pixel.height
    text = auftrag(geprueft)
    a, _ = lesen.gemerkt(leser_a, text, bild, ordner, pruefe_antwort)
    b, _ = lesen.gemerkt(leser_b, text, bild, ordner, pruefe_antwort)
    ergebnis = {
        "fassung": __version__,
        "funktion": FUNKTION,
        "herkunft": HERKUNFT,
        "quelle": quelle,
        "seite": geprueft["seite"],
        "auftrag": geprueft,
        "leser": {"a": leser_a.kennung, "b": leser_b.kennung},
        "bild": {"breite": breite, "hoehe": hoehe},
        **gleiche_ab(geprueft, a, b, breite, hoehe),
        "antworten": {"a": a, "b": b},
    }
    lesen.schreibe(ordner / ERGEBNIS, ergebnis)
    return json.loads(json.dumps(ergebnis))  # dieselbe Form wie die Datei (Tupel werden Listen)


def zaehle(ergebnis: dict[str, Any]) -> dict[str, int]:
    """Stellen je Ausgang (``uebernommen`` und je Grund) und Reihen auf der Klaerliste (``reihe_<grund>``)."""
    zahl_je: dict[str, int] = {}
    for s in ergebnis["stellen"]:
        k = "uebernommen" if s["ausgang"] == "uebernommen" else s["grund"]
        zahl_je[k] = zahl_je.get(k, 0) + 1
    for r in ergebnis["reihen"]:
        if r["ausgang"] == "klaerliste":
            k = f"reihe_{r['grund']}"
            zahl_je[k] = zahl_je.get(k, 0) + 1
    return zahl_je
