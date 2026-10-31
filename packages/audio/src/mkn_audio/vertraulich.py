"""Datenschutz-Hinweis vor dem Versand an Google (Spec 9).

**Was geschuetzt wird.** Der Weg gemini schickt den Lesetext ueber das Netz an Google. Wer eine
Quelle mit Kontaktdaten, Kennziffern oder einem Brief an eine Person vertont, soll das vorher
wissen -- nicht erst im Bericht. Darum prueft der Lauf den Text nach der Regie (da ist die
Dokumentart bekannt) und VOR der ersten Anfrage.

**Was die Erkennung ist.** Deterministisch und eine Untergrenze: Namen werden nicht erkannt
(eine Namensliste im Paket waere selbst personenbezogen, und ein Sachbuch ist voller Namen).
Gegen Fehlalarme gilt: *Kontaktdaten* und *Kennziffern* zaehlen immer (eine E-Mail-Adresse im
Sachbuch ist selten, und selten ist genau der Fall, den man sehen will); *Briefform* nur mit
Personen-Anrede UND Grussformel am Ende; *Lebensdaten* nur ohne Dokumentart Buch, Sachbuch,
Artikel oder Zusammenfassung UND nur in kurzen Dokumenten -- ein biografisches Datum in einem
Buch ist Inhalt, kein Hinweis. Beispiele im Ergebnis sind maskiert: sie sollen zeigen, WAS
gefunden wurde, nicht es weitergeben.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mkn_audio.typen import Dokument, Mp4Fehler

MAX_SEITEN_LEBENSDATEN = 20
MAX_WOERTER_LEBENSDATEN = 10_000
"""Lebensdaten zaehlen nur in einem kurzen Dokument: unter dieser Seitenzahl ODER unter dieser
Wortzahl. Ein Dokument gilt als kurz, sobald eine der bekannten Groessen klein ist -- im
Zweifel mehr Hinweise: eine Frage zu viel kostet eine Sekunde, ein Geburtsdatum zu wenig ist
Weitergabe."""

BUCH_ARTEN = ("buch", "sachbuch", "artikel", "zusammenfassung", "book", "article", "summary")
"""Dokumentarten, in denen ein Datum zum Inhalt gehoert (Wort der Dokumentart, klein)."""

DOKUMENTARTEN = (
    "Brief",
    "Arztbrief",
    "Befund",
    "Gutachten",
    "Rechnung",
    "Bescheid",
    "Vertrag",
    "Zeugnis",
    "Protokoll",
    "Lebenslauf",
)
"""Dokumentarten (deutsch), die selbst ein Hinweis sind; englische Entsprechungen gleicher Art
stehen im Muster `_DOKUMENTART`."""

KLASSEN = ("Kontaktdaten", "Kennziffern", "Lebensdaten", "Briefform", "Dokumentart")


@dataclass(frozen=True)
class Hinweis:
    """Eine Klasse von Fundstellen: wie viele, und ein maskiertes Beispiel (nie der Rohwert)."""

    klasse: str
    anzahl: int
    beispiel: str


class RueckfrageNoetig(Mp4Fehler):
    """Der Text enthaelt Hinweise, und niemand hat den Versand an Google freigegeben.

    Die Kommandozeile uebersetzt das in Exit 3; der Lauf bricht ab, BEVOR die erste Anfrage
    hinausgeht.
    """


_MONATE = (
    "Januar|Jänner|Februar|März|Maerz|April|Mai|Juni|Juli|August|September|Oktober|November"
    "|Dezember"
)
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,3})?\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_TELEFON_INTERNATIONAL = re.compile(r"\+\d{1,3}[\s\-./]*\(?\d{1,5}\)?(?:[\s\-./]*\d{2,}){1,4}")
_TELEFON_NATIONAL = re.compile(r"(?<![\w.,/])\(?0\d{2,5}\)?[\s\-/]\d[\d\s\-/]{3,}\d")
_KENNZIFFER = re.compile(
    r"\b(Az\.|Aktenzeichen|Steuernummer|St\.-Nr\.|Steuer-ID|Steuer-Identifikationsnummer"
    r"|Versichertennummer|Kundennummer|Vertragsnummer|Mitgliedsnummer)"
    r"[\s:]*(?:Nr\.?\s*)?\d[\d/.\-]{2,}\d"
)
_LEBENSDATUM = re.compile(
    r"\b((?i:geb\.|geboren(?:\s+am)?|Geburtsdatum))\s*:?\s*(?:am\s+)?"
    rf"\d{{1,2}}\.\s?(?:\d{{1,2}}\.|(?:{_MONATE})\b)\s?\d{{2,4}}"
)
_ANREDE = re.compile(r"\s*(Sehr geehrte[rn]?|Liebe[rn]?|Lieber|Hallo)\s+([^,\n]{1,60}),")
_PERSON = re.compile(r"(Herr|Herrn|Frau|Dr\.|Prof\.|Doktor|Professor)\b")
_SAMMEL = frozenset(
    [
        "leser",
        "leserinnen",
        "freunde",
        "freundinnen",
        "mitglieder",
        "alle",
        "kollegen",
        "kolleginnen",
        "gäste",
        "kinder",
        "zuhörer",
        "hörer",
        "teilnehmer",
        "teilnehmerinnen",
        "schüler",
        "schülerinnen",
        "eltern",
        "nachbarn",
    ]
)
_GRUSS = re.compile(
    r"\b(gr(?:ü|ue)(?:ß|ss)e|gr(?:ü|ue)(?:ß|ss)en|gruß|gruss|hochachtungsvoll)\b", re.I
)
_GRUSS_MAX_ZEICHEN = 60
_GRUSS_LETZTE_ABSAETZE = 4
_DOKUMENTART = re.compile(
    r"\b\w*(?:" + "|".join(d.lower() for d in DOKUMENTARTEN) + r")\b"
    r"|\b(?:letter|invoice|contract|certificate|minutes|resume|cv|curriculum vitae"
    r"|medical report|expert opinion|notice)\b",
    re.I,
)
_WORT = re.compile(r"\w+")


def _maske(wert: str) -> str:
    """Zwei Zeichen und ein Auslassungszeichen: zeigt die Art, gibt den Wert nicht her."""
    wert = wert.strip()
    return wert[:2] + "…"


def _mit_vorwort(treffer: re.Match[str]) -> str:
    """`Vorwort …`: das Wort davor bleibt, die Zahl dahinter nicht."""
    return f"{treffer.group(1)} …"


def _kontaktdaten(text: str) -> tuple[int, str]:
    """Anzahl und ein maskiertes Beispiel; was gefunden ist, wird fuer die naechste Suche entfernt
    (eine IBAN enthaelt Zahlen, die auch wie eine Telefonnummer aussehen)."""
    anzahl = 0
    beispiel = ""
    for art, muster in (
        ("IBAN", _IBAN),
        ("E-Mail-Adresse", _EMAIL),
        ("Telefonnummer", _TELEFON_INTERNATIONAL),
        ("Telefonnummer", _TELEFON_NATIONAL),
    ):
        erstes = muster.search(text)
        if erstes is not None and not beispiel:
            beispiel = f"{art} ({_maske(erstes.group(0))})"
        anzahl += len(muster.findall(text))
        text = muster.sub(" ", text)
    return anzahl, beispiel


def _briefform(absaetze: list[str]) -> tuple[int, str]:
    """Personen-Anreden am Absatzanfang, wenn gegen Ende des Textes eine Grussformel steht."""
    anreden = []
    for absatz in absaetze:
        treffer = _ANREDE.match(absatz)
        if treffer is None:
            continue
        adressat = treffer.group(2).strip()
        woerter = adressat.split()
        ist_person = bool(_PERSON.match(adressat)) or (
            len(woerter) == 1 and woerter[0][:1].isupper() and woerter[0].lower() not in _SAMMEL
        )
        if ist_person:
            anreden.append(treffer.group(1))
    if not anreden:
        return 0, ""
    ende = [a for a in absaetze if a.strip()][-_GRUSS_LETZTE_ABSAETZE:]
    if not any(len(a) <= _GRUSS_MAX_ZEICHEN and _GRUSS.search(a) for a in ende):
        return 0, ""
    return len(anreden), f"{anreden[0]} …"


def _ist_buchart(dokumentart: str | None) -> bool:
    return bool(dokumentart) and any(w.lower() in BUCH_ARTEN for w in _WORT.findall(dokumentart))


def pruefe_vertraulich(
    dok: Dokument, *, dokumentart: str | None, seiten: int | None
) -> tuple[Hinweis, ...]:
    """Die Hinweise zu `dok` (Lesetext nach der Regie), leer, wenn nichts auffaellt.

    `dokumentart` ist das Feld der Regie (mit unbestimmtem Artikel, z. B. "ein Arztbrief"),
    `None` oder leer ohne Regie; `seiten` die Seitenzahl der Quelle, wo sie bekannt ist.
    """
    absaetze = [a for k in dok.kapitel for a in (k.titel, *k.absaetze) if a.strip()]
    text = "\n".join(absaetze)
    hinweise: list[Hinweis] = []

    anzahl, beispiel = _kontaktdaten(text)
    if anzahl:
        hinweise.append(Hinweis("Kontaktdaten", anzahl, beispiel))

    kennziffern = list(_KENNZIFFER.finditer(text))
    if kennziffern:
        hinweise.append(Hinweis("Kennziffern", len(kennziffern), _mit_vorwort(kennziffern[0])))

    woerter = len(_WORT.findall(text))
    kurz = (seiten is not None and seiten < MAX_SEITEN_LEBENSDATEN) or (
        woerter < MAX_WOERTER_LEBENSDATEN
    )
    if kurz and not _ist_buchart(dokumentart):
        daten = list(_LEBENSDATUM.finditer(text))
        if daten:
            hinweise.append(Hinweis("Lebensdaten", len(daten), _mit_vorwort(daten[0])))

    anzahl, beispiel = _briefform(absaetze)
    if anzahl:
        hinweise.append(Hinweis("Briefform", anzahl, beispiel))

    if dokumentart and _DOKUMENTART.search(dokumentart):
        hinweise.append(Hinweis("Dokumentart", 1, dokumentart.strip()))
    return tuple(hinweise)
