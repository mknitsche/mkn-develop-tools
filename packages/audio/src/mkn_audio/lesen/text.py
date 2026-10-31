"""Text und Markdown lesen -- und die Bausteine, die alle Leser teilen.

**Warum die gemeinsamen Bausteine hier liegen.** Ob ein Absatz aus einem EPUB, einem PDF
oder einer Textdatei stammt: am Ende muessen Silbentrennung geheilt, unsichtbare Zeichen
entfernt und Webadressen weggelassen sein, und zwar ueberall gleich. Taete jeder Leser
das auf seine Art, klaenge dasselbe Wort je nach Quelle anders.

**Webadressen werden weggelassen, nicht gekuerzt.** Eine vorgelesene Adresse ist
Buchstabensalat; ein Hoerer kann ihr nicht folgen. Wie viele es waren, steht als
Warnung im Bericht, damit das Fehlen auffaellt.

**`KeinText`** liegt hier, weil jeder Leser es braucht und `lesen/__init__` die Leser
importiert (ein Import in die andere Richtung wuerde im Kreis laufen).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from mkn_audio.sprache import satzschreibung, versal_belege, wortformen
from mkn_audio.typen import Dokument, Kapitel, Mp4Fehler


class KeinText(Mp4Fehler):
    """Die Quelle enthaelt nichts, was sich vorlesen liesse.

    Eigener Fehler, damit der Dienst "diese Quelle ist unbrauchbar" (Quelle und Bericht
    nach `fehlgeschlagen/`, kein Neuversuch) von einem Defekt der Umgebung trennen kann.
    Ein leeres Hoerstueck waere die schlechtere Antwort: es sieht nach Erfolg aus.
    """


_LIGATUREN = str.maketrans(
    {
        "ﬀ": "ff",
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
        "ﬅ": "st",
        "ﬆ": "st",
    }
)
# Weicher Trennstrich und unsichtbare Zeichen: nie vorzulesen, stoeren aber jeden Vergleich.
_UNSICHTBAR = dict.fromkeys(map(ord, "­​‌‍⁠﻿"))
_LEERRAUM = re.compile(r"\s+")
_URL = re.compile(r"(?:https?://|www\.)[^\s<>]*[^\s<>.,;:!?)\]\"'»«“”]")
_LEERE_KLAMMER = re.compile(r"\(\s*\)|\[\s*\]")
_ZEICHEN_VOR_LEERRAUM = re.compile(r"\s+([,.;:!?])")
# Nach einem Trennstrich bleibt dieses Wort ein eigenes Wort ("Ein- und Ausgang").
_BINDEWOERTER = frozenset({"und", "oder", "bzw", "sowie", "beziehungsweise"})

# -- Beiwerk: Quellenangaben in Klammern, Literaturabschnitte, Quellvermerke --------------
# Eng gefasst (Spec 6.3 c): eine Jahreszahl in Klammern allein ist keine Quellenangabe. Zitat-
# Syntax: `(` Angabe ((`; `|`, `) Angabe)* `)`, Angabe = [Vorwort [Vorwort]] Namen Jahr
# (`, ` Jahr)* [Seite]. Ein Name ist Grossbuchstabe + Kleinbuchstaben (Bindestrich erlaubt)
# oder ein Kuerzel von der festen Liste `_ZITAT_KUERZEL` -- und weder Monat noch Wort der
# Stoppliste `_KEIN_NAME`. Ein beliebiges Versal-Kuerzel ist KEIN Name: "(DDR 1989)",
# "(EN 1990)", "(NATO 1949)" sind Text und werden vorgelesen; ein zu weiter Treffer loescht
# Gesprochenes, ein zu enger laesst eine Quellenangabe stehen -- das erste ist der teurere
# Fehler.
_GROSS, _KLEIN = "A-ZÀ-ÖØ-Þ", "a-zß-öø-ÿ"
_MONATE = (
    "Januar|Jänner|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember"
    "|January|February|March|May|June|July|October|December"
)
# Herausgebende Organisationen, die als Autor einer Quellenangabe vorkommen.
_ZITAT_KUERZEL = "WHO|OECD|UNICEF|UNESCO|UN|UNO|IPCC|IARC|CDC|NIH|RKI|BZgA|DGE"
# Grossgeschriebene Woerter, die vor einer Jahreszahl in Klammern kein Autor sind (de/en).
_KEIN_NAME = (
    "Stand|Anfang|Ende|Mitte|Auflage|Ausgabe|Version|Fassung|Jahr|Frühjahr|Frühling|Sommer"
    "|Herbst|Winter|Ostern|Pfingsten|Weihnachten|Spring|Summer|Autumn|Fall|Easter|Christmas"
    "|Edition|Early|Late|Mid"
)
_NAME = (
    rf"(?!(?:{_MONATE}|{_KEIN_NAME})\b)(?:[{_GROSS}][{_KLEIN}]+(?:-[{_GROSS}]?[{_KLEIN}]+)*"
    rf"|(?:{_ZITAT_KUERZEL})(?![{_GROSS}{_KLEIN}]))"  # Organisation als Autor
)
_NAMEN = rf"{_NAME}(?:(?:, | und | & ){_NAME})*(?: et al\.?| u\. a\.)?"
_JAHRESZAHL = r"(?:18|19|20)\d{2}[a-z]?(?!\d)"
# `???` steht in Quellenangaben fuer ein unbekanntes Jahr; zaehlt nur neben einer echten
# Jahreszahl in derselben Klammer -- "(Warum ???)" ist Text.
_JAHR = rf"(?:{_JAHRESZAHL}|\?\?\?)"
_SEITE = r", (?:S\.|p\.) ?\d+(?:[\u2013-]\d+)?(?: ff?\.)?"
_ZITAT_VORWORT = r"(?i:vgl\.|siehe|s\.|nach|Übersicht(?:en)? (?:in|bei):?) "
_ANGABE = rf"(?:{_ZITAT_VORWORT}){{0,2}}{_NAMEN} {_JAHR}(?:, {_JAHR})*(?:{_SEITE})?"
# Angaben getrennt mit `; ` oder `, ` ("(Mustermann 2004, Beispiel 2006)"); "(Berlin, 1989)"
# bleibt, weil zwischen Name und Jahr kein Komma steht.
_ZITAT = re.compile(rf"\s*\((?=[^()]*{_JAHRESZAHL}){_ANGABE}(?:(?:; |, ){_ANGABE})*\)")

_LITERATUR_TITEL = re.compile(
    r"(?:\d+(?:\.\d+)*\.?\s+)?(?:Literatur|Literaturverzeichnis|Quellen|Quellen und Literatur"
    r"|Weiterführende Literatur|Sachbücher zum Weiterlesen|Zum Weiterlesen|Bibliographie"
    r"|References|Bibliography|Further reading):?",
    re.IGNORECASE,
)
_QUELLVERMERK = re.compile(r"Aus:\s.*\bSeiten?\s+\d+(?:\s*[\u2013-]\s*\d+)?\.?")


def normalisiere(text: str) -> str:
    """NFC, Ligaturen aufgeloest, unsichtbare Zeichen weg, Leerraum auf ein Leerzeichen."""
    text = unicodedata.normalize("NFC", text).translate(_LIGATUREN).translate(_UNSICHTBAR)
    return _LEERRAUM.sub(" ", text).strip()


def verbinde_zeilen(zeilen: Iterable[str], *, versalien: bool = False) -> str:
    """Fuegt hart umbrochene Zeilen zu einem Absatz und heilt die Silbentrennung.

    Ein Trennstrich am Zeilenende vor Kleinschreibung ist Silbentrennung ("Silben-" /
    "trennung" -> "Silbentrennung"). Vor Grossschreibung gehoert der Strich zum Wort
    ("Ost-" / "Westfalen" -> "Ost-Westfalen"), und vor "und"/"oder" ist er ein
    Ergaenzungsstrich ("vor-" / "und nachher"). Ein weicher Trennstrich am Zeilenende
    ist immer Silbentrennung.

    `versalien=True` gilt fuer Zeilen, die ganz in Versalien stehen (Ueberschrift-Lauf): dort
    ist die Grossschreibung nach dem Strich kein Zeichen fuer ein Eigenwort, der Strich ist
    Silbentrennung ("VER-" / "AENDERN" -> "VERAENDERN") -- ausser vor einem Bindewort.
    """
    text = ""
    for zeile in (z.strip() for z in zeilen):
        if not zeile:
            continue
        if not text:
            text = zeile
        elif text.endswith("­"):
            text = text[:-1] + zeile
        elif text.endswith("-") and len(text) > 1 and text[-2].isalpha() and zeile[0].isalpha():
            erstes_wort = zeile.split(maxsplit=1)[0].lower().strip(".,;:")
            if zeile[0].isupper() and not versalien:
                text += zeile
            elif erstes_wort in _BINDEWOERTER:
                text += " " + zeile
            else:
                text = text[:-1] + zeile
        else:
            text += " " + zeile
    return text


def absaetze_aus_text(roh: str) -> list[str]:
    """Teilt Text an Leerzeilen in Absaetze; Zeilen im Absatz werden verbunden."""
    absaetze: list[str] = []
    zeilen: list[str] = []
    for zeile in [*roh.splitlines(), ""]:
        if zeile.strip():
            zeilen.append(zeile)
        elif zeilen:
            absaetze.append(verbinde_zeilen(zeilen))
            zeilen = []
    return absaetze


@dataclass
class Befunde:
    """Sammelt, was beim Lesen weggelassen oder unsicher war, fuer den Bericht.

    Zaehlt die weggelassenen Webadressen, Quellenangaben, Literatur-Absaetze und Quellvermerke
    mit, damit nicht jeder Absatz eine eigene Warnung erzeugt, der Bericht sie aber als EINE
    Zeile je Regel nennt: nichts wird still weggelassen.
    """

    warnungen: list[str] = field(default_factory=list)
    urls: int = 0
    zitate: int = 0
    literatur: int = 0
    vermerke: int = 0

    def warne(self, text: str) -> None:
        if text not in self.warnungen:
            self.warnungen.append(text)

    def reinige(self, text: str) -> str:
        """Normalisiert einen Absatz und entfernt Webadressen und Quellenangaben in Klammern.

        Leer ist das Ergebnis, wenn kein einziges Wort uebrig bleibt (Zierlinien wie
        `* * *`, Seitenschmuck): so etwas vorzulesen waere Laerm.
        """
        text = normalisiere(text)
        text, anzahl = _URL.subn("", text)
        if anzahl:
            self.urls += anzahl
            text = _ZEICHEN_VOR_LEERRAUM.sub(r"\1", _LEERE_KLAMMER.sub("", text))
            text = normalisiere(text)
        text, anzahl = _ZITAT.subn("", text)
        if anzahl:
            self.zitate += anzahl
            text = normalisiere(text)
        return text if any(z.isalnum() for z in text) else ""

    def alle(self) -> tuple[str, ...]:
        """Die Warnungen samt der Sammelzeile je Beiwerk-Regel."""
        zeilen = [
            (self.zitate, f"weggelassen: Quellenangaben in Klammern ({self.zitate})"),
            (self.literatur, f"weggelassen: Literaturabschnitt ({self.literatur} Absätze)"),
            (self.vermerke, f"weggelassen: Quellvermerk ({self.vermerke})"),
            (self.urls, f"weggelassen: Webadressen ({self.urls})"),
        ]
        return (*self.warnungen, *(text for anzahl, text in zeilen if anzahl))


class Ueberschrift(str):
    """Ein Absatz, den der Leser als Zwischenueberschrift erkannt hat (Markdown `###`, PDF).

    Ein gewoehnlicher `str` mit Marke: `baue_kapitel` macht daraus die Art `ueberschrift`.
    So bleiben alle Leser, die nur Text liefern, unveraendert.
    """

    __slots__ = ()


def _ohne_literatur(
    absaetze: Sequence[tuple[str, bool]], befunde: Befunde
) -> list[tuple[str, bool]]:
    """Laesst Literaturabschnitte weg: ab einem Absatz, der GANZ eine Literatur-Ueberschrift ist,
    bis zur naechsten Ueberschrift (oder zum Ende). Die Ueberschrift selbst zaehlt mit.
    """
    behalten = []
    im_abschnitt = False
    for text, ist_ueberschrift in absaetze:
        if im_abschnitt and ist_ueberschrift:
            im_abschnitt = False
        if not im_abschnitt and _LITERATUR_TITEL.fullmatch(text):
            im_abschnitt = True
        if im_abschnitt:
            befunde.literatur += 1
        else:
            behalten.append((text, ist_ueberschrift))
    return behalten


def _ohne_quellvermerk(
    absaetze: list[tuple[str, bool]], befunde: Befunde
) -> list[tuple[str, bool]]:
    """Laesst Quellvermerke (`Aus: ... Seiten 25-34`) am Kapitelende weg, nie mitten im Text."""
    while absaetze and _QUELLVERMERK.fullmatch(absaetze[-1][0]):
        absaetze = absaetze[:-1]
        befunde.vermerke += 1
    return absaetze


def baue_kapitel(
    rohe: Sequence[tuple[str | None, Sequence[str]]], *, vorspann: str, befunde: Befunde
) -> tuple[Kapitel, ...]:
    """Macht aus `(Titel, Absaetze)` bereinigte Kapitel.

    Eine Ueberschrift ohne Text dahinter wird nicht zum leeren Kapitel (das gaebe eine
    Kapitelmarke ohne Inhalt), sondern als Warnung gemeldet. Absaetze vor der ersten
    Ueberschrift (`Titel=None`) laufen unter `vorspann`. Absaetze vom Typ `Ueberschrift`
    bekommen die Art `ueberschrift`; ein Kapitel ganz ohne solche behaelt `arten=()`
    ("alles Wortlaut").

    Beiwerk faellt weg und wird gezaehlt (`Befunde`): ein Kapitel, dessen Titel GANZ eine
    Literatur-Ueberschrift ist, ein Literaturabschnitt darin, ein Quellvermerk am Kapitelende.
    Das passiert vor dem Bereinigen, damit Quellenangaben in der Literaturliste nicht als
    Quellenangaben im Text mitgezaehlt werden -- gilt fuer Absaetze, die noch nicht bereinigt
    sind (EPUB, Text, Markdown, Bild). Das PDF reinigt seine Absaetze schon beim Lesen
    (`lies_pdf` ruft `Befunde.reinige` davor): dort werden Zitate in einer Literaturliste
    mitgezaehlt, der Abschnitt faellt trotzdem ganz weg.
    """
    kapitel = []
    for titel, absaetze in rohe:
        roh = [(normalisiere(x), isinstance(x, Ueberschrift)) for x in absaetze]
        if titel and _LITERATUR_TITEL.fullmatch(normalisiere(titel)):
            befunde.literatur += len(roh)
            continue
        roh = _ohne_quellvermerk(_ohne_literatur(roh, befunde), befunde)
        sauber = [(a, ist) for x, ist in roh if (a := befunde.reinige(x))]
        name = befunde.reinige(titel) if titel else ""
        if not sauber:
            if name:
                befunde.warne(f"weggelassen: Ueberschrift ohne Text: {name}")
            continue
        arten = tuple("ueberschrift" if ist else "wortlaut" for _a, ist in sauber)
        kapitel.append(
            Kapitel(
                name or vorspann,
                tuple(a for a, _ist in sauber),
                arten if "ueberschrift" in arten else (),
            )
        )
    return tuple(kapitel)


def wende_satzschreibung(dok: Dokument) -> Dokument:
    """Setzt Kapiteltitel und Ueberschrift-Absaetze in Versalien in Satzschreibung.

    Nach der Spracherkennung, weil Regel (3) die Sprache braucht (`sprache.satzschreibung`).
    Die Schreibweisen kommen aus dem ganzen Dokument; `Dokument.titel` bleibt, wie er ist.
    """
    formen = wortformen([dok.titel, *(t for k in dok.kapitel for t in (k.titel, *k.absaetze))])
    belegt = versal_belege(dok.kapitel)

    def schreibe(text: str) -> str:
        return satzschreibung(text, formen, dok.sprache, belegt)

    kapitel = []
    for k in dok.kapitel:
        arten = k.arten or ("wortlaut",) * len(k.absaetze)
        absaetze = tuple(
            schreibe(a) if art == "ueberschrift" else a
            for a, art in zip(k.absaetze, arten, strict=True)
        )
        kapitel.append(replace(k, titel=schreibe(k.titel), absaetze=absaetze))
    return replace(dok, kapitel=tuple(kapitel))


def pruefe_text_da(dokument: Dokument, quelle: Path, was: str) -> Dokument:
    """Gibt das Dokument zurueck, wenn es Text hat -- sonst bricht es mit `KeinText`."""
    if not dokument.kapitel:
        raise KeinText(f"{was} ohne lesbaren Text: {quelle.name}")
    return dokument


# ---- Textdateien ------------------------------------------------------------------


def lies_datei_text(pfad: Path, befunde: Befunde) -> str:
    """Liest eine Textdatei als UTF-8, sonst als Windows-1252 (mit Warnung).

    Eine andere Kodierung raten wir nicht: lieber laut abbrechen als Umlaute
    verfaelscht vorlesen.
    """
    daten = pfad.read_bytes()
    try:
        return daten.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        text = daten.decode("cp1252")
    except UnicodeDecodeError:
        raise Mp4Fehler(f"Textdatei weder UTF-8 noch Windows-1252: {pfad.name}") from None
    befunde.warne("Kodierung war nicht UTF-8, als Windows-1252 gelesen")
    return text


_FRONTMATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
_TITEL_ZEILE = re.compile(r"^title:\s*[\"']?(.+?)[\"']?\s*$", re.MULTILINE)
_UEBERSCHRIFT = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_ZAUN = re.compile(r"^\s*(```|~~~)")
_TRENNLINIE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_TABELLENTRENNER = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
_LISTENPUNKT = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_BILD = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)|\[([^\]]*)\]\[[^\]]*\]")
_LINKDEFINITION = re.compile(r"^\s*\[[^\]]+\]:\s*\S+")
_FETT = re.compile(r"(?<!\w)(\*\*|__)(.+?)\1(?!\w)")
_SCHIEF = re.compile(r"(?<!\w)([*_])(.+?)\1(?!\w)")
_DURCHGESTRICHEN = re.compile(r"~~(.+?)~~")
_CODE = re.compile(r"`([^`]*)`")
_HTML = re.compile(r"</?[A-Za-z][^>]*>")


def _inline(zeile: str) -> str:
    """Entfernt Markdown-Auszeichnung innerhalb einer Zeile, der Text bleibt."""
    zeile = _BILD.sub("", zeile)
    zeile = _LINK.sub(lambda m: m.group(1) or m.group(2) or "", zeile)
    zeile = _CODE.sub(r"\1", zeile)
    zeile = _HTML.sub("", zeile)
    zeile = _FETT.sub(r"\2", zeile)
    zeile = _SCHIEF.sub(r"\2", zeile)
    return _DURCHGESTRICHEN.sub(r"\1", zeile)


def _markdown(text: str, befunde: Befunde) -> tuple[str | None, list[tuple[str | None, list[str]]]]:
    """Zerlegt Markdown in `(Titel der Datei, [(Kapiteltitel, Absaetze)])`.

    `#` und `##` eroeffnen Kapitel, tiefere Ueberschriften sind Zwischentitel und werden
    als eigener Absatz der Art `ueberschrift` gelesen. Code ist nicht vorlesbar und wird
    weggelassen, Tabellen werden zeilenweise gelesen (der Hoertext entscheidet danach, was
    daraus wird).
    """
    dateititel = None
    vorn = _FRONTMATTER.match(text)
    if vorn:
        treffer = _TITEL_ZEILE.search(vorn.group(1))
        dateititel = treffer.group(1).strip() if treffer else None
        text = text[vorn.end() :]

    rohe: list[tuple[str | None, list[str]]] = [(None, [])]
    erste_ueberschrift = True
    h1_ist_titel = False
    puffer: list[str] = []
    in_code = False
    codebloecke = 0
    tabellen = False

    def leere() -> None:
        if puffer:
            rohe[-1][1].append(verbinde_zeilen(puffer))
            puffer.clear()

    for zeile in text.splitlines():
        if _ZAUN.match(zeile):
            leere()
            if not in_code:
                codebloecke += 1
            in_code = not in_code
            continue
        if in_code:
            continue
        if not zeile.strip() or _TRENNLINIE.match(zeile) or _LINKDEFINITION.match(zeile):
            leere()
            continue
        kopf = _UEBERSCHRIFT.match(zeile)
        if kopf:
            leere()
            titel = _inline(kopf.group(2))
            if erste_ueberschrift and len(kopf.group(1)) == 1 and dateititel is None:
                dateititel, h1_ist_titel = titel, True
            erste_ueberschrift = False
            if len(kopf.group(1)) <= 2:
                rohe.append((titel, []))
            else:
                rohe[-1][1].append(Ueberschrift(titel))
            continue
        if zeile.strip().startswith("|"):
            leere()
            if not _TABELLENTRENNER.match(zeile):
                zellen = [_inline(z).strip() for z in zeile.strip().strip("|").split("|")]
                rohe[-1][1].append(", ".join(z for z in zellen if z))
                tabellen = True
            continue
        punkt = _LISTENPUNKT.match(zeile)
        if punkt:
            leere()
            puffer.append(_inline(punkt.group(1)))
        else:
            puffer.append(_inline(zeile.lstrip().removeprefix(">")))
    leere()

    if codebloecke:
        befunde.warne(f"weggelassen: Codebloecke ({codebloecke})")
    if tabellen:
        befunde.warne("Tabellen zeilenweise gelesen")
    if not rohe[0][1]:
        rohe.pop(0)
    # Eine erste Ueberschrift der Ebene 1 ohne Text darunter ist der Titel der Datei,
    # kein leeres Kapitel.
    if h1_ist_titel and rohe and rohe[0][0] == dateititel and not rohe[0][1]:
        rohe.pop(0)
    return dateititel, rohe


def lies_text(pfad: Path) -> Dokument:
    """Liest `.txt` (Absaetze an Leerzeilen) oder `.md` (Ueberschriften -> Kapitel)."""
    befunde = Befunde()
    text = lies_datei_text(pfad, befunde)
    stamm = normalisiere(pfad.stem)
    if pfad.suffix.lower() == ".md":
        titel, rohe = _markdown(text, befunde)
        titel = normalisiere(titel or "") or stamm
        kapitel = baue_kapitel(rohe, vorspann=titel, befunde=befunde)
    else:
        titel = stamm
        kapitel = baue_kapitel([(None, absaetze_aus_text(text))], vorspann=titel, befunde=befunde)
    dok = Dokument(titel=titel, autor=None, sprache="de", kapitel=kapitel, warnungen=befunde.alle())
    return pruefe_text_da(dok, pfad, "Textdatei")
