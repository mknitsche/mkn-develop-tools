"""Seitenlesung: Kopf, Fliesstexte und das Verzeichnis der Diagramme einer Seite — von zwei Lesern, abgeglichen.

**Was gelesen wird.** Je Seite der Kopf (Seitenart, Aussteller, das massgebliche Datum mit seiner Beschriftung,
Inhaltsart), jeder zusammenhaengende Fliesstext woertlich und jedes Diagramm mit Titel, Typ, Achsen und Reihen.
Tabellenwerte liest ``lesen``, Werte an Kurven liest ``ablesen`` — beides ist hier nicht Gegenstand.

**Das Fach setzt nur Woerter ein** (``Fach``): Dokumentart, die erlaubten Woerter fuer Seitenart, Inhaltsart und
Textart und einen Satz, welches Datum massgeblich ist. Die Regeln des Lesens und des Abgleichs bleiben gleich.

**Abgleich** (``gleiche_ab``, rein, kein Modell): ein Kopf-Feld gilt nur, wenn beide Leser es gleich lesen (Datum:
beide nennen genau einen und denselben Kalendertag; Aussteller: normalisiert gleich oder einer im anderen enthalten;
Woerter: normalisiert gleich), sonst steht es in ``uneins``. Ein Textblock von Leser a ist ``uebernommen``, wenn jeder
seiner Saetze bei Leser b auf der Seite steht; Bloecke nur bei b stehen auf der Klaerliste. Diagramme paaren sich bei
gleicher Anzahl nach Reihenfolge, gleichem Typ und passendem Titel oder passenden Achsen.
"""

from __future__ import annotations

import copy
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from mkn_dokument import __version__, lesen
from mkn_dokument.auftrag import AntwortUngueltig
from mkn_dokument.leser import Leser

ERGEBNIS = "seiten.json"
FUNKTION = "seiten"

SEITENARTEN = ("leer", "deckblatt", "inhalt", "brief", "formular", "sonstiges")
"""Seitenarten ohne Fach-Angabe."""

DATUM_HINWEIS = "das Datum, auf das sich der Inhalt bezieht, genau wie gedruckt"
"""Welches Datum massgeblich ist, ohne Fach-Angabe."""

DIAGRAMMTYPEN = ("linie", "balken", "punkte", "flaeche", "kreis", "sonstiges")

KOPFFELDER = ("seitenart", "aussteller", "datum", "inhaltsart")
"""Kopf-Felder des Abgleichs in fester Reihenfolge (auch die von ``uneins``)."""

ANTWORT_KOPF = ("seitenart", "aussteller", "datum", "datum_bezeichnung", "inhaltsart")
TEXT_FELDER = ("ueberschrift", "art", "text")
DIAGRAMM_TEXTE = ("titel", "typ", "x_achse", "y_achse")
DIAGRAMM_FELDER = (*DIAGRAMM_TEXTE, "reihen", "werte_gedruckt")


@dataclass(frozen=True)
class Fach:
    """Was ein Fach in den Auftrag einsetzt. Leere ``inhaltsarten`` oder ``textarten`` heissen: frei."""

    dokumentart: str = "eines Dokuments"
    seitenarten: tuple[str, ...] = SEITENARTEN
    inhaltsarten: tuple[str, ...] = ()
    textarten: tuple[str, ...] = ()
    datum_hinweis: str = DATUM_HINWEIS

    def __post_init__(self) -> None:
        if not self.dokumentart.strip() or not self.datum_hinweis.strip():
            raise ValueError("dokumentart und datum_hinweis duerfen nicht leer sein")
        if not self.seitenarten:
            raise ValueError("seitenarten braucht mindestens ein Wort")
        for liste in (self.seitenarten, self.inhaltsarten, self.textarten):
            for wort in liste:
                # Ein Komma oder eine Klammer zerbraeche die Liste im Auftragstext.
                if not isinstance(wort, str) or not wort.strip() or re.search(r"[,\[\]]", wort):
                    raise ValueError(f"Wort {wort!r} ist leer oder enthaelt Komma oder Klammer")


def _liste(woerter: tuple[str, ...]) -> str:
    return "[" + ", ".join(w.strip() for w in woerter) + "]"


def auftrag(fach: Fach | None = None) -> str:
    """Der Auftragstext an beide Leser, mit den Woertern des Fachs."""
    fach = fach or Fach()
    deckblatt = (
        "; deckblatt ist ein Vorblatt ohne Inhalt (z. B. von einer Scan-App)" if "deckblatt" in fach.seitenarten else ""
    )
    inhaltsart = (
        f"eines von {_liste(fach.inhaltsarten)}"
        if fach.inhaltsarten
        else "die Art des Inhalts dieser Seite in einem kurzen Wort"
    )
    textart = f"eines von {_liste(fach.textarten)}" if fach.textarten else "ein kurzes Wort fuer die Art des Textes"
    return f"""Du liest eine Seite {fach.dokumentart.strip()} vom Seitenbild. Erfasse NICHT die Tabellenwerte (die liest ein anderer Schritt), sondern Kopf, Fliesstext und Diagramme.
- seitenart: eines von {_liste(fach.seitenarten)}{deckblatt}.
- aussteller: Name der Stelle, die das Dokument ausgestellt hat, wie im Briefkopf gedruckt (ohne Adresse); leer, wenn auf dieser Seite keiner steht.
- datum: {fach.datum_hinweis.strip().rstrip(".")}. Leer, wenn auf dieser Seite keines steht. datum_bezeichnung: die gedruckte Beschriftung dieses Datums, leer wenn keine.
- inhaltsart: {inhaltsart}.
- texte: jeder zusammenhängende Fließtext mit Inhalt; je Text ueberschrift (gedruckt, sonst leer), art ({textart}), text (wörtlich und vollständig abgeschrieben, Zeilenumbrüche als Leerzeichen, nichts kürzen, nichts ergänzen). Keine Tabellen, keine Adressen, keine Fußzeilen, keine Grußformeln.
- diagramme: jedes Diagramm oder jede Kurve; je Diagramm titel (gedruckt, sonst kurze Beschreibung), typ ({", ".join(DIAGRAMMTYPEN)}), x_achse und y_achse (Beschriftung mit Einheit wie gedruckt, sonst leer), reihen (Namen der dargestellten Reihen), werte_gedruckt (true, wenn die Werte als Zahlen am Diagramm stehen).
Antworte nur mit JSON: {{"seitenart": "", "aussteller": "", "datum": "", "datum_bezeichnung": "", "inhaltsart": "", "texte": [{{"ueberschrift": "", "art": "", "text": ""}}], "diagramme": [{{"titel": "", "typ": "", "x_achse": "", "y_achse": "", "reihen": [""], "werte_gedruckt": false}}]}}"""


_TEXT = {"type": "string"}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        **dict.fromkeys(ANTWORT_KOPF, _TEXT),
        "texte": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": dict.fromkeys(TEXT_FELDER, _TEXT),
                "required": list(TEXT_FELDER),
            },
        },
        "diagramme": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    **dict.fromkeys(DIAGRAMM_TEXTE, _TEXT),
                    "reihen": {"type": "array", "items": _TEXT},
                    "werte_gedruckt": {"type": "boolean"},
                },
                "required": list(DIAGRAMM_FELDER),
            },
        },
    },
    "required": [*ANTWORT_KOPF, "texte", "diagramme"],
}
"""Antwortform fuer Anbieter, die eine erzwungene Form kennen."""


# --- Formpruefung --------------------------------------------------------------------------------------------------


def _leer(wert: object) -> bool:
    return wert is None or wert == "" or wert == [] or wert == {}


def _bereinigt(objekt: object, felder: tuple[str, ...], wo: str) -> dict[str, Any]:
    """Alle ``felder`` muessen da sein; ein fremdes Feld darf nur leer sein (dann entfaellt es) — eines mit Inhalt
    ginge still verloren und bricht."""
    if not isinstance(objekt, dict):
        raise AntwortUngueltig(f"{wo}: kein Objekt")
    fehlt = [f for f in felder if f not in objekt]
    if fehlt:
        raise AntwortUngueltig(f"{wo}: Felder {fehlt} fehlen")
    # Feldnamen gekuerzt: ein langer Name kann Inhalt tragen und gehoert nie ganz in eine Meldung
    fremd = sorted(str(k)[:30] for k, v in objekt.items() if k not in felder and not _leer(v))
    if fremd:
        raise AntwortUngueltig(f"{wo}: unbekannte Felder {fremd[:5]} mit Inhalt")
    return {f: objekt[f] for f in felder}


def _text_oder_nichts(wert: object, wo: str) -> None:
    if wert is not None and not isinstance(wert, str):
        raise AntwortUngueltig(f"{wo}: kein Text")


def pruefe_antwort(antwort: object) -> dict[str, Any]:
    """Prueft die Form einer Leser-Antwort und gibt sie ohne leere fremde Felder zurueck; bricht laut bei falscher Form.

    Werte bleiben, wie der Leser sie gab (``None`` bleibt ``None``): der Abgleich behandelt leer und ``None`` gleich.
    """
    wo = "Antwort"
    kopf = _bereinigt(antwort, (*ANTWORT_KOPF, "texte", "diagramme"), wo)
    for feld in ANTWORT_KOPF:
        _text_oder_nichts(kopf[feld], f"{wo}, {feld}")
    if not isinstance(kopf["texte"], list) or not isinstance(kopf["diagramme"], list):
        raise AntwortUngueltig(f"{wo}: texte oder diagramme ist keine Liste")
    texte = []
    for i, t in enumerate(kopf["texte"], start=1):
        block = _bereinigt(t, TEXT_FELDER, f"Text {i}")
        _text_oder_nichts(block["ueberschrift"], f"Text {i}, ueberschrift")
        if not isinstance(block["art"], str):
            raise AntwortUngueltig(f"Text {i}: art fehlt")
        if not isinstance(block["text"], str) or not block["text"].strip():
            raise AntwortUngueltig(f"Text {i}: text leer")
        texte.append(block)
    diagramme = []
    for i, d in enumerate(kopf["diagramme"], start=1):
        diagramm = _bereinigt(d, DIAGRAMM_FELDER, f"Diagramm {i}")
        for feld in DIAGRAMM_TEXTE:
            _text_oder_nichts(diagramm[feld], f"Diagramm {i}, {feld}")
        reihen = diagramm["reihen"]
        if not isinstance(reihen, list) or not all(isinstance(r, str) for r in reihen):
            raise AntwortUngueltig(f"Diagramm {i}: reihen ist keine Liste von Texten")
        if diagramm["werte_gedruckt"] is not None and not isinstance(diagramm["werte_gedruckt"], bool):
            raise AntwortUngueltig(f"Diagramm {i}: werte_gedruckt ist kein Wahrheitswert")
        diagramme.append(diagramm)
    return kopf | {"texte": texte, "diagramme": diagramme}


# --- Datum ---------------------------------------------------------------------------------------------------------

#: Monatsnamen deutsch und englisch, ausgeschrieben und abgekuerzt (laengere zuerst, damit die Alternation sie trifft).
MONATE = {
    "januar": 1, "january": 1, "jan": 1, "februar": 2, "february": 2, "feb": 2, "maerz": 3, "märz": 3,
    "march": 3, "mrz": 3, "mär": 3, "mar": 3, "april": 4, "apr": 4, "mai": 5, "may": 5, "juni": 6,
    "june": 6, "jun": 6, "juli": 7, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9,
    "sept": 9, "sep": 9, "oktober": 10, "october": 10, "okt": 10, "oct": 10, "november": 11, "nov": 11,
    "dezember": 12, "december": 12, "dez": 12, "dec": 12,
}  # fmt: skip
_MONATSNAME = "|".join(sorted(MONATE, key=len, reverse=True))
#: Eindeutige Schreibweisen (Tag, Monat, Jahr als Gruppen). ``TT/MM/JJJJ`` und ``JJJJ.MM.TT`` bewusst nicht.
_DATUMSMUSTER = (
    re.compile(r"(?<!\d)(?<!\d\.)(?P<t>\d{1,2})\.\s*(?P<m>\d{1,2})\.\s*(?P<j>\d{4}|\d{2})(?!\d|\.\d)"),
    re.compile(r"(?<!\d)(?<!\d[.\-])(?P<j>\d{4})-(?P<m>\d{2})-(?P<t>\d{2})(?!\d|-\d)"),
    re.compile(
        rf"(?<!\d)(?<!\d\.)(?P<t>\d{{1,2}})\.?\s*(?P<m>{_MONATSNAME})\b\.?\s*(?P<j>\d{{4}})(?!\d)",
        re.IGNORECASE,
    ),
)
_SATZENDE = re.compile(r"(?<=[.!?:;])\s+")


def normiere(text: str | None) -> str:
    """Kleinbuchstaben, jede Folge aus Nicht-Wortzeichen ein Leerzeichen — Schreibweise zaehlt nicht, Wortlaut schon."""
    return re.sub(r"[\W_]+", " ", (text or "").lower()).strip()


def tag_in(text: str | None) -> date | None:
    """Das erste gueltige Datum im Text in einer eindeutigen Schreibweise: ``TT.MM.JJJJ``, ``TT.MM.JJ`` (``JJ`` bis 30 →
    20JJ, sonst 19JJ), auch mit Leerzeichen nach den Punkten, ``JJJJ-MM-TT`` und Tag mit ausgeschriebenem oder
    abgekuerztem deutschem oder englischem Monat und Jahr. Mehrdeutiges (``TT/MM/JJJJ``) wird nie gelesen."""
    treffer = sorted(
        (m for muster in _DATUMSMUSTER for m in muster.finditer(text or "")),
        key=lambda m: m.start(),
    )
    for m in treffer:
        tag = _tag_aus(m)
        if tag is not None:
            return tag
    return None


def tage_in(text: str | None) -> set[date]:
    """Alle verschiedenen gueltigen Kalendertage im Text, in den Schreibweisen von ``tag_in``."""
    tage = set()
    for muster in _DATUMSMUSTER:
        for m in muster.finditer(text or ""):
            tag = _tag_aus(m)
            if tag is not None:
                tage.add(tag)
    return tage


def _tag_aus(m: re.Match[str]) -> date | None:
    jahr, monat = m["j"], m["m"]
    j = int(jahr) + ((2000 if int(jahr) <= 30 else 1900) if len(jahr) == 2 else 0)
    mon = int(monat) if monat.isdigit() else MONATE[monat.lower()]
    try:
        return date(j, mon, int(m["t"]))
    except ValueError:
        return None


# --- Abgleich (rein) -----------------------------------------------------------------------------------------------


def _gleicher_name(a: str | None, b: str | None) -> bool:
    """Normalisiert gleich oder einer im anderen enthalten; ein leerer Name passt zu nichts."""
    na, nb = normiere(a), normiere(b)
    return bool(na) and bool(nb) and (na in nb or nb in na)


def _saetze(text: str) -> Counter[str]:
    """Die normalisierten Saetze eines Textes als Mehrfachmenge (ein zweimal gedruckter Satz zaehlt zweimal)."""
    return Counter(s for s in (normiere(x) for x in _SATZENDE.split(text)) if s)


def _kopf(a: dict[str, Any], b: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    werte: dict[str, Any] = {}
    uneins: list[str] = []

    def setze(feld: str, wert: Any, einig: bool, beide_leer: bool) -> None:
        werte[feld] = wert if einig else None
        if not einig and not beide_leer:
            uneins.append(feld)

    for feld in KOPFFELDER:
        if feld == "datum":
            # einig nur, wenn beide Leser genau einen Tag nennen und es derselbe ist — nie gewinnt das erste Datum
            tage_a, tage_b = tage_in(a["datum"]), tage_in(b["datum"])
            einig = len(tage_a) == 1 and tage_a == tage_b
            ta = next(iter(tage_a)) if einig else None
            # beide leer heisst: kein Text — ein Text ohne lesbaren Tag ist uneins, damit nie geerbt wird
            leer = not normiere(a["datum"]) and not normiere(b["datum"])
            setze(feld, ta.isoformat() if einig and ta else None, einig, leer)
        elif feld == "aussteller":
            xa, xb = (a[feld] or "").strip(), (b[feld] or "").strip()
            einig = _gleicher_name(xa, xb)
            setze(feld, min(xa, xb, key=len) if einig else None, einig, not normiere(xa) and not normiere(xb))
        else:  # Seitenart, Inhaltsart: gleiches Wort
            xa, xb = normiere(a[feld]), normiere(b[feld])
            setze(feld, xa, bool(xa) and xa == xb, not xa and not xb)  # normiert gespeichert
    return werte, uneins


def _text_zeile(block: dict[str, Any], ausgang: str, leser: str) -> dict[str, Any]:
    return {f: block[f] for f in TEXT_FELDER} | {"ausgang": ausgang, "leser": leser}


def _texte(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Uebernommen wird ein Block von a, dessen Saetze alle (als Mehrfachmenge) bei b auf der Seite stehen; jeder andere
    Block von a und jeder Block von b mit einem Satz, den a nicht hat, steht mit seinem Leser auf der Klaerliste."""
    zeilen = []
    rest_b = sum((_saetze(x["text"]) for x in b), Counter())
    for block in a:
        s = _saetze(block["text"])
        # ein Block ohne Satz hat nichts, was b bestaetigen koennte
        passt = bool(s) and not (s - rest_b)
        if passt:
            rest_b -= s
        zeilen.append(_text_zeile(block, "uebernommen" if passt else "klaerliste", "a"))
    rest_a = sum((_saetze(x["text"]) for x in a), Counter())
    for block in b:
        s = _saetze(block["text"])
        if s and not (s - rest_a):
            rest_a -= s
        else:
            zeilen.append(_text_zeile(block, "klaerliste", "b"))
    return zeilen


def _achsen_passen(da: dict[str, Any], db: dict[str, Any]) -> bool:
    """Jede Achse bei beiden leer oder passend, und mindestens eine Achse belegt."""
    paare = [(da[f], db[f]) for f in ("x_achse", "y_achse")]
    if any(bool(normiere(x)) != bool(normiere(y)) for x, y in paare):
        return False
    belegt = [(x, y) for x, y in paare if normiere(x)]
    return bool(belegt) and all(_gleicher_name(x, y) for x, y in belegt)


def _diagramm_zeile(d: dict[str, Any], ausgang: str, leser: dict[str, Any]) -> dict[str, Any]:
    return {f: copy.deepcopy(d[f]) for f in DIAGRAMM_FELDER} | {"ausgang": ausgang, "leser": leser}


def _diagramme(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Gepaart nach Reihenfolge bei gleicher Zahl, gleichem Typ und passendem Titel oder passenden Achsen; uebernommen
    mit den Feldern von a; sind die Leser in ``werte_gedruckt`` uneins, steht dort None. Alles andere steht mit seinem
    Leser auf der Klaerliste."""
    if len(a) == len(b):
        paare = [
            normiere(da["typ"]) == normiere(db["typ"])
            and (_gleicher_name(da["titel"], db["titel"]) or _achsen_passen(da, db))
            for da, db in zip(a, b, strict=True)
        ]
    else:
        paare = [False] * max(len(a), len(b))
    zeilen = []
    for i, da in enumerate(a):
        if paare[i]:
            zeile = _diagramm_zeile(da, "uebernommen", {"a": da, "b": b[i]})
            if da["werte_gedruckt"] != b[i]["werte_gedruckt"]:
                zeile["werte_gedruckt"] = None  # uneins: weder a noch b gilt
            zeilen.append(zeile)
        else:
            zeilen.append(_diagramm_zeile(da, "klaerliste", {"a": da}))
    zeilen += [_diagramm_zeile(db, "klaerliste", {"b": db}) for i, db in enumerate(b) if not (i < len(a) and paare[i])]
    return zeilen


def _kopf_antwort(antwort: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in antwort.items() if k not in ("texte", "diagramme")}


def gleiche_ab(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, Any]:
    """Die Antworten beider Leser einer Seite abgleichen (rein; die Form prueft ``pruefe_antwort``).

    Rueckgabe: ``ausgang`` (``zwei_leser`` oder ``ein_leser``), die Kopf-Felder (``KOPFFELDER``; ``datum`` als
    ``JJJJ-MM-TT``), ``uneins``, ``leser`` (die Kopf-Antworten), ``texte`` und ``diagramme``. Fehlt ein Leser
    (``None``), ist die Seite ``ein_leser``: kein Kopf-Wert, alles auf der Klaerliste. Ohne beide bricht es.
    """
    if a is None and b is None:
        raise ValueError("Seite ohne Leser")
    if a is None or b is None:
        name, antwort = ("a", a) if b is None else ("b", b)
        assert antwort is not None
        return {
            "ausgang": "ein_leser",
            **dict.fromkeys(KOPFFELDER),
            "uneins": [],
            "leser": {name: _kopf_antwort(antwort)},
            "texte": [_text_zeile(t, "klaerliste", name) for t in antwort["texte"]],
            "diagramme": [_diagramm_zeile(d, "klaerliste", {name: d}) for d in antwort["diagramme"]],
        }
    werte, uneins = _kopf(a, b)
    return {
        "ausgang": "zwei_leser",
        **werte,
        "uneins": uneins,
        "leser": {"a": _kopf_antwort(a), "b": _kopf_antwort(b)},
        "texte": _texte(a["texte"], b["texte"]),
        "diagramme": _diagramme(a["diagramme"], b["diagramme"]),
    }


# --- Lauf ----------------------------------------------------------------------------------------------------------


def lies_seiten(
    eingabe: Path,
    ordner: Path,
    leser_a: Leser,
    leser_b: Leser,
    *,
    fach: Fach | None = None,
) -> dict[str, Any]:
    """Liest jede Seite von ``eingabe`` mit beiden Lesern, gleicht ab und schreibt ``ordner/seiten.json``.

    Rueckgabe und Datei: ``{"fassung", "funktion": "seiten", "quelle", "leser", "seiten": [...]}`` — je Seite
    ``seite``, das Ergebnis von ``gleiche_ab`` und ``antworten`` (die rohen Antworten beider Leser). Mitschrift wie
    bei ``lesen``; jeder Fehler eines Lesers bricht den Lauf laut ab.
    """
    eingabe = Path(eingabe)
    ordner = Path(ordner)
    quelle, bilder = lesen.bereite_vor(eingabe, ordner, leser_a, leser_b)
    text = auftrag(fach)
    seiten: list[dict[str, Any]] = []
    for nr, bild in enumerate(bilder, start=1):
        a, roh_a = lesen.gemerkt(leser_a, text, bild, ordner, pruefe_antwort)
        b, roh_b = lesen.gemerkt(leser_b, text, bild, ordner, pruefe_antwort)
        seiten.append({"seite": nr, **gleiche_ab(a, b), "antworten": {"a": roh_a, "b": roh_b}})
    ergebnis = {
        "fassung": __version__,
        "funktion": FUNKTION,
        "quelle": quelle,
        "leser": {"a": leser_a.kennung, "b": leser_b.kennung},
        "seiten": seiten,
    }
    lesen.schreibe(ordner / ERGEBNIS, ergebnis)
    return ergebnis


def zaehle(ergebnis: dict[str, Any]) -> dict[str, int]:
    """Seiten, Seiten mit uneinigem Kopf, Texte und Diagramme je Ausgang."""
    zahl = {"seiten": len(ergebnis["seiten"]), "kopf_uneins": 0}
    for art in ("texte", "diagramme"):
        zahl[f"{art}_uebernommen"] = 0
        zahl[f"{art}_klaerliste"] = 0
    for seite in ergebnis["seiten"]:
        zahl["kopf_uneins"] += bool(seite["uneins"])
        for art in ("texte", "diagramme"):
            for zeile in seite[art]:
                zahl[f"{art}_{zeile['ausgang']}"] += 1
    return zahl
