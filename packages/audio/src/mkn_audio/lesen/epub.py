"""EPUB lesen: Kapitel in Lesefolge, ohne Beiwerk.

**Lesefolge ist der Spine, nicht das Manifest.** Das Manifest listet Dateien in
beliebiger Reihenfolge; nur der Spine sagt, wie das Buch gelesen wird.

**Kapitel kennt das Inhaltsverzeichnis, nicht die Auszeichnung.** Verlage setzen
Kapitelueberschriften oft als `<p class="ch-title1">` statt als `<h1>`; wer nur Ueberschriften-
Elemente trennt, liest das ganze Buch als ein Kapitel. Darum bestimmt das Inhaltsverzeichnis
(nav vor NCX, EPUB 3 vor 2) die Kapitel: je Eintrag der obersten Ebene eines, von seinem
Anker (oder Dateianfang) bis zum naechsten Eintrag. Verschachtelte Eintraege sind Zwischentitel
und bleiben als Absatz im Text. Eine Datei, die das Verzeichnis nicht nennt, und ein Buch ohne
brauchbares Verzeichnis werden je Datei gelesen (Titel aus `h1`/`h2`, der Titel-Klasse oder dem
Dateinamen; `h1`/`h2` trennen innerhalb der Datei).

**Beiwerk wird nicht vorgelesen, aber gemeldet.** Impressum, Inhaltsverzeichnis,
Widmung, Anmerkungen, Literatur, Register und Verzeichnisse erkennt der Leser an drei
Stellen: am `epub:type` bzw. der DPUB-Rolle im Text, an den Landmarks der Navigation
(und dem `guide` des alten Formats) und, wenn ein Buch das alles nicht pflegt, an der
Ueberschrift. Was weggelassen wurde, steht als Warnung im Bericht: wer das Hoerstueck
hoert, soll wissen koennen, was in ihm fehlt.

**Eine fremde Datei ist feindliche Eingabe.** XML (Container, OPF) laeuft durch
`defusedxml`, das externe Entitaeten verweigert; die XHTML-Kapitel liest der
`html.parser`, der gar keine Entitaeten aufloest. Das Archiv hat Grenzen fuer Anzahl der
Eintraege und entpackte Groesse (Zip-Bombe). Es wird nie entpackt, nur gelesen.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urldefrag

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString
from defusedxml import DefusedXmlException
from defusedxml import ElementTree as DefusedET

from mkn_audio.lesen.text import Befunde, baue_kapitel, normalisiere, pruefe_text_da
from mkn_audio.typen import Dokument, Mp4Fehler

MAX_EINTRAEGE = 2000
"""Mehr Eintraege im Archiv gelten als Zip-Bombe."""

MAX_ENTPACKT = 500 * 1024 * 1024
"""Mehr entpackte Bytes (laut Archivverzeichnis) gelten als Zip-Bombe."""

_HTML = "application/xhtml+xml"

# Beiwerk-Typen (epub:type ohne Namensraum, DPUB-Rollen ohne `doc-`) -> Bezeichnung.
_BEIWERK_ARTEN = {
    "copyright-page": "Impressum",
    "colophon": "Impressum",
    "toc": "Inhaltsverzeichnis",
    "loi": "Abbildungsverzeichnis",
    "lot": "Tabellenverzeichnis",
    "dedication": "Widmung",
    "index": "Register",
    "bibliography": "Literatur",
    "footnotes": "Anmerkungen",
    "endnotes": "Anmerkungen",
    "rearnotes": "Anmerkungen",
    "notes": "Anmerkungen",
    "titlepage": "Titelseite",
    "title-page": "Titelseite",
    "halftitlepage": "Titelseite",
    "cover": "Titelseite",
    "landmarks": "Navigation",
    "page-list": "Navigation",
    "pagelist": "Navigation",
}
# Einzelne Fussnoten im Text: gehen verloren, werden gezaehlt.
_NOTEN = frozenset({"footnote", "endnote", "rearnote"})
_NOTENVERWEIS = frozenset({"noteref"})

# Ueberschriften, an denen ein Kapitel als Beiwerk gilt (ganze Ueberschrift, kleingeschrieben).
_BEIWERK_TITEL = re.compile(
    r"^(impressum|copyright|urheberrechte?|inhalt|inhaltsverzeichnis|inhaltsuebersicht"
    r"|inhaltsübersicht|inhaltsangabe|cover|titelblatt|titelseite|navigation|widmung|anmerkungen?|fussnoten|fußnoten|endnoten|literatur"
    r"|literaturverzeichnis|quellen|quellenverzeichnis|register|stichwortverzeichnis"
    r"|abbildungsverzeichnis|tabellenverzeichnis)$"
)
# Anhang-Kapitel mit zusammengesetztem Titel ("Anmerkungen, Quellen und Weiterfuehrendes",
# "Quellen und Literatur"): ein Verlags-EPUB fuehrt sie als eigenes Kapitel, vorgelesen waeren
# es Tausende Woerter Seitenzahlen und Fundstellen.
_ANHANG_TITEL = re.compile(
    r"^(anmerkungen|endnoten|fussnoten|fußnoten|quellen|quellenangaben|literatur"
    r"|literaturverzeichnis|quellenverzeichnis|register)(\s*,|\s+und\s|\s*&)"
)

_BLOCK = frozenset(
    {
        *("address", "article", "aside", "blockquote", "body", "dd", "details", "div", "dl"),
        *("dt", "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header"),
        *("hr", "li", "main", "nav", "ol", "p", "pre", "section", "summary", "table", "tr", "ul"),
    }
)
_UEBERSPRINGEN = frozenset(
    {
        *("script", "style", "svg", "img", "head", "math", "audio", "video"),
        *("iframe", "object", "canvas", "rt", "rp"),
    }
)


@dataclass(frozen=True)
class _Eintrag:
    pfad: str
    media: str
    eigenschaften: frozenset[str]


@dataclass(frozen=True)
class _Verzeichniseintrag:
    """Ein Eintrag der obersten Ebene des Inhaltsverzeichnisses."""

    label: str
    pfad: str
    anker: str | None


# Klassen, an denen eine Kapitelueberschrift ohne `<h1>` zu erkennen ist.
_TITEL_KLASSE = re.compile(r"title|titel|chapter|kapitel|heading", re.IGNORECASE)
_MAX_TITEL = 160
"""Laengere Elemente sind Text, auch wenn ihre Klasse nach Titel klingt."""

_NCX = "application/x-dtbncx+xml"


def _lies_eintrag(zf: zipfile.ZipFile, name: str) -> bytes:
    try:
        return zf.read(name)
    except KeyError:
        raise Mp4Fehler(f"EPUB-Eintrag fehlt im Archiv: {name}") from None
    except (zipfile.BadZipFile, zlib.error, NotImplementedError, EOFError, RuntimeError) as fehler:
        raise Mp4Fehler(f"EPUB-Eintrag nicht lesbar: {name} ({fehler})") from None


def _xml(daten: bytes, wo: str):
    try:
        return DefusedET.fromstring(daten)
    except (DefusedXmlException, DefusedET.ParseError) as fehler:
        raise Mp4Fehler(f"EPUB: {wo} ist kein sicheres, gueltiges XML ({fehler})") from None


def _pruefe_archiv(zf: zipfile.ZipFile) -> None:
    eintraege = zf.infolist()
    if len(eintraege) > MAX_EINTRAEGE:
        raise Mp4Fehler(f"EPUB hat {len(eintraege)} Eintraege (Grenze {MAX_EINTRAEGE})")
    entpackt = sum(e.file_size for e in eintraege)
    if entpackt > MAX_ENTPACKT:
        raise Mp4Fehler(f"EPUB entpackt {entpackt} Bytes (Grenze {MAX_ENTPACKT})")


def _aufloesen(basis: str, href: str) -> str:
    """Macht aus einem relativen `href` den Namen im Archiv."""
    ziel, _anker = urldefrag(href)
    return posixpath.normpath(posixpath.join(basis, unquote(ziel)))


def _arten(tag: Tag) -> set[str]:
    """`epub:type` und DPUB-Rolle eines Elements als Menge einfacher Namen."""
    werte = f"{tag.get('epub:type', '')} {tag.get('role', '')}".split()
    return {w.removeprefix("doc-") for w in werte}


# Fussnoten-Verweis: hochgestellte Ziffern ("4", "1,2", "3-5") oder ein Sternchen/Kreuz.
_VERWEIS = re.compile(r"[\d,\u2013\-]+|[*\u2020]+")
# Davor eine Ziffer oder eine Laengeneinheit: dann ist es eine Hochzahl (10^6, m^2), kein Verweis.
_HOCHZAHL_DAVOR = re.compile(r"(?:\d|\b[kcdm]?m)\s*$")


def _entferne_verweise(soup: BeautifulSoup) -> int:
    """Entfernt Fussnoten-Verweise aus dem Fliesstext; gibt ihre Anzahl.

    Vorgelesen ergaeben sie "Islam vier" oder ein eigenes Stueck "Eins." -- die Fussnoten
    selbst stehen im Beiwerk und werden ohnehin nicht gelesen. Verweise mit `epub:type`
    `noteref` fallen immer weg, nackte `<sup>`-Ziffern nur, wenn keine Hochzahl gemeint ist.
    """
    anzahl = 0
    for tag in soup.find_all(["a", "sup"]):
        if tag.decomposed:
            continue
        if "noteref" in _arten(tag):
            ziel = tag.parent if tag.parent and tag.parent.name == "sup" else tag
        elif tag.name == "sup" and _VERWEIS.fullmatch(tag.get_text().strip()):
            davor = tag.previous_sibling
            if isinstance(davor, str) and _HOCHZAHL_DAVOR.search(davor):
                continue
            ziel = tag
        else:
            continue
        ziel.decompose()
        anzahl += 1
    return anzahl


def _text(tag: Tag) -> str:
    return normalisiere(tag.get_text())


def _landmarks(soup: BeautifulSoup, basis: str) -> dict[str, str]:
    """`Datei -> Art` aus den Landmarks einer Navigation."""
    ergebnis: dict[str, str] = {}
    for nav in soup.find_all("nav"):
        if "landmarks" not in _arten(nav):
            continue
        for a in nav.find_all("a", href=True):
            for art in _arten(a):
                ergebnis.setdefault(_aufloesen(basis, a["href"]), art)
    return ergebnis


def _ist_titel_element(tag: Tag) -> bool:
    """Ein kurzes Blattelement, dessen Klasse nach Ueberschrift klingt.

    Ein Umschlag wie `<div class="chapter">` traegt dieselbe Klasse, ist aber der ganze
    Kapitelinhalt: nur ein Element ohne Bloecke darin ist ein Titel.
    """
    if tag.name not in _BLOCK or not _TITEL_KLASSE.search(" ".join(tag.get("class") or [])):
        return False
    text = _text(tag)
    return 0 < len(text) <= _MAX_TITEL and tag.find(list(_BLOCK)) is None


class _Leser:
    """Liest die Bloecke einer Datei und sammelt, was dabei wegfaellt."""

    def __init__(self, befunde: Befunde) -> None:
        self.befunde = befunde
        self.fussnoten = 0
        self.tabellen = 0

    def bloecke(
        self, soup: BeautifulSoup, datei: str, ankers: frozenset[str] = frozenset()
    ) -> list[tuple[str, str]]:
        """`(Art, Text)` in Dokumentreihenfolge.

        Art ist `h1`/`h2`, `titel` (ein Element, dessen Klasse nach Ueberschrift klingt),
        `p` -- oder `anker`: eine Marke (Text = die `id`) dort, wo ein Element mit einer
        der gesuchten `ankers` beginnt. Das Inhaltsverzeichnis teilt an solchen Marken.
        """
        ergebnis: list[tuple[str, str]] = []
        puffer: list[str] = []

        def leere() -> None:
            text = "".join(puffer)
            puffer.clear()
            if text.strip():
                ergebnis.append(("p", text))

        def gehe(knoten: Tag) -> None:
            for kind in knoten.children:
                if type(kind) is NavigableString:  # nicht Kommentar, Doctype ...
                    puffer.append(str(kind))
                    continue
                if not isinstance(kind, Tag) or kind.name in _UEBERSPRINGEN:
                    continue
                if kind.get("id") in ankers:
                    leere()
                    ergebnis.append(("anker", kind["id"]))
                arten = _arten(kind)
                if arten & _NOTENVERWEIS:
                    continue
                if arten & _NOTEN:
                    self.fussnoten += 1
                    continue
                beiwerk = arten & _BEIWERK_ARTEN.keys()
                if beiwerk:
                    leere()
                    kopf = kind.find(["h1", "h2", "h3"])
                    bezeichnung = _text(kopf) if kopf else _BEIWERK_ARTEN[sorted(beiwerk)[0]]
                    self.befunde.warne(f"weggelassen: {bezeichnung} ({datei})")
                    continue
                if kind.name in ("h1", "h2"):
                    leere()
                    ergebnis.append((kind.name, _text(kind)))
                elif kind.name == "table":
                    leere()
                    for zeile in kind.find_all("tr"):
                        zellen = [_text(z) for z in zeile.find_all(["th", "td"])]
                        ergebnis.append(("p", ", ".join(z for z in zellen if z)))
                    self.tabellen += 1
                elif kind.name == "br":
                    puffer.append(" ")
                elif _ist_titel_element(kind):
                    leere()
                    ergebnis.append(("titel", _text(kind)))
                elif kind.name in _BLOCK:
                    leere()
                    gehe(kind)
                    leere()
                else:  # Inline-Element: gehoert zum laufenden Absatz
                    gehe(kind)

        wurzel = soup.body or soup
        if wurzel is not soup:
            arten = _arten(wurzel)
            if arten & _BEIWERK_ARTEN.keys():
                bezeichnung = _BEIWERK_ARTEN[sorted(arten & _BEIWERK_ARTEN.keys())[0]]
                self.befunde.warne(f"weggelassen: {bezeichnung} ({datei})")
                return []
        if wurzel.get("id") in ankers:
            ergebnis.append(("anker", wurzel["id"]))
        gehe(wurzel)
        leere()
        return ergebnis


def _metadaten(opf, stamm: str) -> tuple[str, str | None, str]:
    """Titel, Autor und Sprache (zweibuchstabig) aus dem OPF."""

    def alle(name: str) -> list[str]:
        werte = (normalisiere(e.text or "") for e in opf.iterfind(f".//{{*}}metadata/{{*}}{name}"))
        return [w for w in werte if w]

    titel = (alle("title") or [stamm])[0]
    autoren = alle("creator")
    sprache = (alle("language") or ["de"])[0].split("-")[0].lower()
    return titel, ", ".join(autoren) or None, sprache


def _cover(opf, manifest: dict[str, _Eintrag]) -> str | None:
    for eintrag in manifest.values():
        if "cover-image" in eintrag.eigenschaften:
            return eintrag.pfad
    for meta in opf.iterfind(".//{*}metadata/{*}meta"):
        if meta.get("name") == "cover" and meta.get("content") in manifest:
            return manifest[meta.get("content")].pfad
    return None


def _ziel(basis: str, href: str, label: str) -> _Verzeichniseintrag:
    """Datei und Anker eines Verzeichnis-Links; ohne Label gilt der Dateiname."""
    pfad = _aufloesen(basis, href)
    anker = unquote(urldefrag(href)[1]) or None
    return _Verzeichniseintrag(label or _dateiname_ohne_endung(pfad), pfad, anker)


def _dateiname_ohne_endung(pfad: str) -> str:
    return posixpath.splitext(posixpath.basename(pfad))[0]


def _nav_eintraege(daten: bytes, basis: str) -> list[_Verzeichniseintrag]:
    """Oberste Ebene des `toc`-Navigationsdokuments (EPUB 3)."""
    soup = BeautifulSoup(daten, "html.parser")
    nav = next((n for n in soup.find_all("nav") if "toc" in _arten(n)), None)
    liste = nav.find("ol") if nav else None

    def oberste(ol: Tag) -> list[_Verzeichniseintrag]:
        ergebnis: list[_Verzeichniseintrag] = []
        for li in ol.find_all("li", recursive=False):
            a = li.find("a", href=True, recursive=False)
            if a is not None:
                ergebnis.append(_ziel(basis, a["href"], _text(a)))
            else:  # nur eine Gruppenueberschrift: ihre Kinder sind dann die oberste Ebene
                for unter in li.find_all("ol", recursive=False):
                    ergebnis.extend(oberste(unter))
        return ergebnis

    return oberste(liste) if liste is not None else []


def _ncx_eintraege(daten: bytes, basis: str) -> list[_Verzeichniseintrag]:
    """Oberste Ebene der `navMap` (EPUB 2)."""
    karte = _xml(daten, "Inhaltsverzeichnis (NCX)").find("{*}navMap")
    ergebnis: list[_Verzeichniseintrag] = []
    for punkt in karte.findall("{*}navPoint") if karte is not None else []:
        inhalt = punkt.find("{*}content")
        if inhalt is None or not inhalt.get("src"):
            continue
        label = punkt.find("{*}navLabel/{*}text")
        ergebnis.append(_ziel(basis, inhalt.get("src"), normalisiere(label.text or "")))
    return ergebnis


def _lade_verzeichnis(
    zf: zipfile.ZipFile,
    manifest: dict[str, _Eintrag],
    namen: set[str],
    lesbar: set[str],
    befunde: Befunde,
) -> list[_Verzeichniseintrag]:
    """Das erste brauchbare Inhaltsverzeichnis: nav (EPUB 3) vor NCX (EPUB 2).

    Brauchbar heisst: mindestens ein Eintrag zeigt auf eine gelesene Datei. Ein kaputtes
    Verzeichnis bricht das Buch nicht ab (der Text ist ja da), wird aber gemeldet.
    """
    quellen = (
        (_nav_eintraege, [e for e in manifest.values() if "nav" in e.eigenschaften]),
        (_ncx_eintraege, [e for e in manifest.values() if e.media == _NCX]),
    )
    for lese, kandidaten in quellen:
        for eintrag in kandidaten:
            name = posixpath.basename(eintrag.pfad)
            if eintrag.pfad not in namen:
                befunde.warne(f"Datei fehlt im Archiv: {name}")
                continue
            try:
                eintraege = lese(_lies_eintrag(zf, eintrag.pfad), posixpath.dirname(eintrag.pfad))
            except Mp4Fehler as fehler:
                befunde.warne(f"Inhaltsverzeichnis nicht lesbar: {name} ({fehler})")
                continue
            if any(e.pfad in lesbar for e in eintraege):
                return eintraege
    return []


def _dateikapitel(bloecke: list[tuple[str, str]]) -> list[tuple[str | None, list[str]]]:
    """Kapitel einer Datei ohne Verzeichnis: `h1`/`h2` trennen.

    Der Titel kommt aus der Ueberschrift; steht am Dateianfang stattdessen ein Element mit
    Titel-Klasse, ist das der Titel (und nicht zusaetzlich erster Absatz). Text ohne jeden
    Titel davor hat keinen (`None`): der Aufrufer entscheidet, ob der Dateiname einspringt
    oder der Text zum Kapitel davor gehoert. Eine Titel-Klasse mitten im Text ist ein
    Zwischentitel und bleibt Absatz.
    """
    kapitel: list[tuple[str | None, list[str]]] = []
    for art, text in bloecke:
        if art == "anker":
            continue
        if art in ("h1", "h2") or (art == "titel" and not kapitel):
            kapitel.append((text, []))
            continue
        if not kapitel:
            kapitel.append((None, []))
        kapitel[-1][1].append(text)
    return kapitel


def lies_epub(pfad: Path) -> Dokument:
    """Liest ein EPUB; Kapitel entstehen aus dem Inhaltsverzeichnis, sonst je Datei."""
    try:
        zf = zipfile.ZipFile(pfad)
    except (zipfile.BadZipFile, OSError) as fehler:
        raise Mp4Fehler(f"kaputtes EPUB: {pfad.name} ({fehler})") from None
    with zf:
        _pruefe_archiv(zf)
        befunde = Befunde()
        namen = set(zf.namelist())

        container = _xml(_lies_eintrag(zf, "META-INF/container.xml"), "container.xml")
        wurzel = container.find(".//{*}rootfile")
        if wurzel is None or not wurzel.get("full-path"):
            raise Mp4Fehler("EPUB ohne Paketdatei (container.xml nennt keine)")
        opf_pfad = wurzel.get("full-path")
        if opf_pfad not in namen:
            raise Mp4Fehler(f"EPUB: Paketdatei fehlt im Archiv: {opf_pfad}")
        opf = _xml(_lies_eintrag(zf, opf_pfad), "Paketdatei")
        basis = posixpath.dirname(opf_pfad)

        manifest = {
            i.get("id"): _Eintrag(
                _aufloesen(basis, i.get("href", "")),
                i.get("media-type", ""),
                frozenset((i.get("properties") or "").split()),
            )
            for i in opf.iterfind(".//{*}manifest/{*}item")
            if i.get("id")
        }
        spine = [
            manifest[r.get("idref")]
            for r in opf.iterfind(".//{*}spine/{*}itemref")
            if r.get("idref") in manifest
        ]
        if not spine:
            raise Mp4Fehler("EPUB ohne Lesefolge (spine ist leer)")

        # Beiwerk laut Landmarks (EPUB 3) und guide (EPUB 2): Datei -> Art.
        beiwerk_dateien: dict[str, str] = {}
        for eintrag in manifest.values():
            if "nav" in eintrag.eigenschaften and eintrag.pfad in namen:
                nav = BeautifulSoup(_lies_eintrag(zf, eintrag.pfad), "html.parser")
                beiwerk_dateien.update(_landmarks(nav, posixpath.dirname(eintrag.pfad)))
        for ref in opf.iterfind(".//{*}guide/{*}reference"):
            if ref.get("href") and ref.get("type"):
                beiwerk_dateien.setdefault(_aufloesen(basis, ref.get("href")), ref.get("type"))
        beiwerk_dateien = {d: a for d, a in beiwerk_dateien.items() if a in _BEIWERK_ARTEN}

        # Die Dateien, die gelesen werden, in Lesefolge.
        dateien: list[tuple[str, str, BeautifulSoup]] = []
        verweise = 0
        for eintrag in spine:
            name = posixpath.basename(eintrag.pfad)
            if "nav" in eintrag.eigenschaften:
                befunde.warne(f"weggelassen: Navigation ({name})")
                continue
            if eintrag.pfad in beiwerk_dateien:
                art = _BEIWERK_ARTEN[beiwerk_dateien[eintrag.pfad]]
                soup = BeautifulSoup(_lies_eintrag(zf, eintrag.pfad), "html.parser")
                kopf = soup.find(["h1", "h2", "h3"])
                befunde.warne(f"weggelassen: {(_text(kopf) if kopf else '') or art} ({name})")
                continue
            if eintrag.pfad not in namen:
                befunde.warne(f"Datei fehlt im Archiv: {name}")
                continue
            if not eintrag.media.endswith(("html+xml", "html")):
                continue
            soup = BeautifulSoup(_lies_eintrag(zf, eintrag.pfad), "html.parser")
            verweise += _entferne_verweise(soup)
            dateien.append((eintrag.pfad, name, soup))

        if verweise:
            befunde.warne(f"weggelassen: Fußnoten-Verweise ({verweise})")

        # Das Inhaltsverzeichnis: Eintraege auf weggelassene Dateien sind schon gemeldet.
        lesbar = {d[0] for d in dateien}
        verzeichnis = _lade_verzeichnis(zf, manifest, namen, lesbar, befunde)
        in_spine = {e.pfad for e in spine}
        for eintrag in verzeichnis:
            if eintrag.pfad not in in_spine:
                befunde.warne(f"Inhaltsverzeichnis: Ziel nicht in der Lesefolge: {eintrag.label}")
        verzeichnis = [e for e in verzeichnis if e.pfad in lesbar]
        dateistart: dict[str, list[_Verzeichniseintrag]] = {}
        ankerstart: dict[tuple[str, str], list[_Verzeichniseintrag]] = {}
        for eintrag in verzeichnis:
            if eintrag.anker is None:
                dateistart.setdefault(eintrag.pfad, []).append(eintrag)
            else:
                ankerstart.setdefault((eintrag.pfad, eintrag.anker), []).append(eintrag)

        leser = _Leser(befunde)
        rohe: list[tuple[str | None, list[str]]] = []
        vorab: list[str] = []  # Text vor dem ersten Eintrag: gehoert zum naechsten Kapitel
        aktuell: list[str] | None = None  # Absaetze des laufenden Verzeichnis-Kapitels
        kopf_offen = False  # das Kapitel hat noch keinen Text: eine Ueberschrift ist sein Titel

        def beginne(eintrag: _Verzeichniseintrag) -> None:
            nonlocal aktuell, kopf_offen
            aktuell = vorab[:]
            vorab.clear()
            rohe.append((eintrag.label, aktuell))
            kopf_offen = True

        referenziert = {e.pfad for e in verzeichnis}
        for datei, name, soup in dateien:
            if datei not in referenziert:
                # Das Verzeichnis nennt die Datei nicht: eigene Ueberschriften machen eigene
                # Kapitel. Text ohne Titel setzt mit Verzeichnis das laufende Kapitel fort
                # (eine Titelseite oder Widmung heisst sonst nach ihrer Datei); ohne
                # Verzeichnis traegt die Datei ihren Namen.
                for titel, absaetze in _dateikapitel(leser.bloecke(soup, name)):
                    if titel is None and verzeichnis:
                        kopf_offen = False
                        (vorab if aktuell is None else aktuell).extend(absaetze)
                        continue
                    if vorab:
                        rohe.append((None, vorab[:]))
                        vorab.clear()
                    aktuell = None
                    rohe.append((titel or _dateiname_ohne_endung(datei), absaetze))
                continue
            ankers = frozenset(a for d, a in ankerstart if d == datei)
            for eintrag in dateistart.get(datei, []):
                beginne(eintrag)
            for art, text in leser.bloecke(soup, name, ankers):
                if art == "anker":
                    for eintrag in ankerstart.pop((datei, text), []):
                        beginne(eintrag)
                    continue
                if aktuell is None:
                    vorab.append(text)
                    continue
                if kopf_offen:
                    kopf_offen = False
                    if art in ("h1", "h2", "titel"):
                        continue  # der Titel steht schon als Kapitelname da
                aktuell.append(text)
            for (d, _a), eintraege in ankerstart.items():
                if d == datei:
                    for eintrag in eintraege:
                        befunde.warne(f"Inhaltsverzeichnis: Anker fehlt: {eintrag.label} ({name})")
        if vorab:
            rohe.append((None, vorab))

        titel, autor, sprache = _metadaten(opf, normalisiere(pfad.stem))
        cover_pfad = _cover(opf, manifest)
        cover = None
        if cover_pfad:
            if cover_pfad in namen:
                cover = _lies_eintrag(zf, cover_pfad)
            else:
                befunde.warne(f"Datei fehlt im Archiv: {posixpath.basename(cover_pfad)}")

    # Beiwerk, das nur an seiner Ueberschrift zu erkennen ist.
    behalten = []
    for kapitel_titel, absaetze in rohe:
        if kapitel_titel and (
            _BEIWERK_TITEL.match(kapitel_titel.casefold())
            or _ANHANG_TITEL.match(kapitel_titel.casefold())
        ):
            befunde.warne(f"weggelassen: {kapitel_titel} (Beiwerk laut Ueberschrift)")
        else:
            behalten.append((kapitel_titel, absaetze))
    if leser.fussnoten:
        befunde.warne(f"weggelassen: Fussnoten ({leser.fussnoten})")
    if leser.tabellen:
        befunde.warne(f"Tabellen zeilenweise gelesen ({leser.tabellen})")

    kapitel = baue_kapitel(behalten, vorspann=titel, befunde=befunde)
    dok = Dokument(
        titel=titel,
        autor=autor,
        sprache=sprache,
        kapitel=kapitel,
        warnungen=befunde.alle(),
        cover=cover,
    )
    return pruefe_text_da(dok, pfad, "EPUB")
