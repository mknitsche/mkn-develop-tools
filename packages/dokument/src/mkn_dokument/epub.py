"""EPUB lesen: Text in Lesereihenfolge und das Buch mit Metadaten, ISBN und Kapiteln.

Gelesen wird im Prozess mit der Standardbibliothek (``zipfile``, ``html.parser``); die Steuerdateien (``container.xml``,
OPF, ``encryption.xml``, NCX) laufen ueber ``defusedxml`` - Entitaeten und externe Verweise werden abgewiesen, nie
aufgeloest. Paketdatei ueber ``META-INF/container.xml``, Lesereihenfolge nach dem Spine der OPF-Datei (nie nach
Dateinamen), je nicht-leerem Spine-Dokument ein Kapitel.

Zwei Wege ueber dieselbe Kapitelfolge:

- ``epub_text``: der ganze Text, Kapitel durch ``KAPITELGRENZE`` getrennt (Seitenvorschub auf eigener Zeile - fuer
  einen Zerteiler nach Absaetzen immer auch eine Absatzgrenze). Ein Riss ist ``EpubRissError`` mit ``grund``:
  ``geschuetzt`` (Kopierschutz), ``groesse`` (entpackt ueber ``max_entpackt``), ``leser`` (kaputtes Archiv, fehlende
  Paketdatei oder fehlendes Spine-Dokument, unlesbares XML).
- ``epub_buch``: Metadaten aus dem OPF, alle ISBN (``isbns``), die Kapitel mit Titel aus dem Verzeichnis (nav,
  sonst NCX). Ein geschuetztes Buch liefert nur die Metadaten und oeffnet kein Kapitel-Dokument; ein Lesefehler ist
  ``EpubLesefehlerError``, nie ein leeres Buch.

Kopierschutz wird erkannt und abgewiesen, nie umgangen: ``META-INF/encryption.xml`` mit einem Verfahren ausser der
Schrift-Verschleierung, ein Schluessel ohne Daten, oder ein verschluesselter Zip-Eintrag.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
import zlib
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Literal
from urllib.parse import unquote, urldefrag
from xml.etree import ElementTree as ET

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring as xml_sicher

if TYPE_CHECKING:
    from collections.abc import Iterable

#: Grenze der entpackten Spine-Dokumente zusammen (und jeder einzelnen Steuerdatei); darueber ``groesse``.
MAX_ENTPACKT_BYTES = 50 * 2**20
#: Kapitelgrenze im Text von ``epub_text``: Seitenvorschub auf eigener Zeile.
KAPITELGRENZE = "\n\f\n"

Grund = Literal["geschuetzt", "groesse", "leser"]

_OCF = "{urn:oasis:names:tc:opendocument:xmlns:container}"
_OPF = "{http://www.idpf.org/2007/opf}"
_XMLENC = "{http://www.w3.org/2001/04/xmlenc#}"
_DC = "{http://purl.org/dc/elements/1.1/}"
_NCX = "{http://www.daisy.org/z3986/2005/ncx/}"
# Schrift-Verschleierung (IDPF, Adobe): steht in encryption.xml, schuetzt aber nur eingebettete Schriften, keinen Text
_SCHRIFT_VERSCHLEIERUNG = frozenset({"http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC"})
_LESEFEHLER = (
    zipfile.BadZipFile,
    zipfile.LargeZipFile,
    KeyError,
    ET.ParseError,
    DefusedXmlException,
    EOFError,
    zlib.error,
    NotImplementedError,  # Kompressionsverfahren, das zipfile nicht kennt
    ValueError,
)
#: Ein ``dc:date`` vor dem Buchdruck ist ein Platzhalter (manche Werkzeuge schreiben ``0101-01-01``), kein Datum.
_FRUEHESTES_JAHR = 1450
_DATUM = re.compile(r"(\d{4})(-\d{2}(?:-\d{2})?)?")
#: Leerzeichen wie Bindestriche in der Kennung (``978 3 16 148410 0``); ``_isbn`` bereinigt beide.
_ISBN_OPF = re.compile(r"(?:urn:)?(?:isbn:?)?\s*([\dXx][\dXx -]*)", re.I)
#: Im Dateinamen strenger: ISBN-13 nur mit 978/979, ISBN-10 nur hinter dem Marker „isbn“.
_ISBN13_NAME = re.compile(r"(?<![\d])(97[89](?:[- ]?\d){10})(?![\d])")
_ISBN10_NAME = re.compile(r"isbn[\s_:.-]*((?:\d[- ]?){9}[\dXx])(?![\dXx])", re.I)


class EpubRissError(Exception):
    """Das EPUB ist nicht lesbar; ``grund`` ist ``geschuetzt``, ``groesse`` oder ``leser``. Ein Ergebnis fuer den
    Aufrufer (die Datei bleibt ungelesen), kein Fehler der Umgebung."""

    def __init__(self, grund: Grund) -> None:
        super().__init__(grund)
        self.grund: Grund = grund


class EpubLesefehlerError(Exception):
    """Das EPUB ist nicht als Buch lesbar (kaputtes Archiv, fehlende Paketdatei, Groesse); nie ein leeres Buch."""


@dataclass(frozen=True)
class Kapitel:
    """Ein nicht-leeres Spine-Dokument: Titel aus dem Verzeichnis und Text mit Absaetzen (``\\n\\n``)."""

    titel: str
    text: str


@dataclass(frozen=True)
class Buch:
    """Metadaten aus dem OPF und die Kapitel; ein geschuetztes Buch hat nur Metadaten (``kapitel=()``)."""

    titel: str
    autoren: tuple[str, ...]
    verlag: str | None
    sprache: str | None
    datum: str | None
    isbns: tuple[str, ...]
    kapitel: tuple[Kapitel, ...]
    geschuetzt: bool = False

    @property
    def isbn(self) -> str | None:
        return self.isbns[0] if self.isbns else None


# --- Text eines Spine-Dokuments -------------------------------------------------------------------


class _EpubText(HTMLParser):
    """Text eines Spine-Dokuments (XHTML): ohne ``head``, ``script``, ``style``; Leerraum wie im Browser
    zusammengefasst, Blockgrenzen als Absatzgrenze (der Quelltext eines Kapitels bricht Zeilen beliebig)."""

    _BLOCK = frozenset(
        {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"}
        | {"section", "article", "aside", "blockquote", "figure", "figcaption", "dl", "dt", "dd", "hr", "pre"}
        | {"header", "footer", "nav"}
    )
    _UNSICHTBAR = frozenset({"head", "script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.teile: list[str] = []
        self._tief = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._UNSICHTBAR:
            self._tief += 1
        elif tag in self._BLOCK:
            self.teile.append("\n\n")
        elif tag in ("td", "th"):
            self.teile.append(" ")

    def handle_startendtag(self, tag, attrs):
        if tag in self._BLOCK:  # <br/>, <hr/>
            self.teile.append("\n\n" if tag != "br" else "\n")

    def handle_endtag(self, tag):
        if tag in self._UNSICHTBAR:
            self._tief = max(0, self._tief - 1)
        elif tag in self._BLOCK:
            self.teile.append("\n\n")

    def handle_data(self, data):
        if not self._tief:
            self.teile.append(re.sub(r"\s+", " ", data))

    def text(self) -> str:
        roh = "".join(self.teile)
        roh = re.sub(r" *\n *", "\n", roh)
        return re.sub(r"\n{3,}", "\n\n", roh).strip()


def _dekodieren(daten: bytes) -> str:
    try:
        return daten.decode("utf-8-sig")
    except UnicodeDecodeError:
        return daten.decode("cp1252", errors="replace")


# --- Archiv, Steuerdateien, Spine ------------------------------------------------------------------


def _epub_eintrag(z: zipfile.ZipFile, pfad: str, bisher: int = 0, grenze: int = MAX_ENTPACKT_BYTES) -> bytes:
    """Ein Eintrag des Archivs; die entpackte Groesse zaehlt mit ``bisher`` gegen ``grenze`` (``groesse``)."""
    info = z.getinfo(pfad)  # KeyError: Eintrag fehlt -> ``leser``
    if info.flag_bits & 0x1:
        raise EpubRissError("geschuetzt")  # verschluesselter Zip-Eintrag
    if bisher + info.file_size > grenze:
        raise EpubRissError("groesse")
    with z.open(info) as f:
        daten = f.read(info.file_size + 1)
    if len(daten) > info.file_size:  # mehr als im Verzeichnis angegeben: kaputt
        raise EpubRissError("leser")
    return daten


def _epub_xml(daten: bytes) -> ET.Element:
    """Steuerdatei als XML ueber defusedxml (``DefusedXmlException`` -> ``leser``)."""
    return xml_sicher(daten)


def _epub_geschuetzt(z: zipfile.ZipFile, grenze: int = MAX_ENTPACKT_BYTES) -> bool:
    if "META-INF/encryption.xml" not in z.namelist():
        return False
    wurzel = _epub_xml(_epub_eintrag(z, "META-INF/encryption.xml", grenze=grenze))
    for daten in wurzel.iter(f"{_XMLENC}EncryptedData"):
        methode = daten.find(f"{_XMLENC}EncryptionMethod")
        if methode is None or methode.get("Algorithm") not in _SCHRIFT_VERSCHLEIERUNG:
            return True
    # ein Schluessel ohne verschluesselte Daten (EncryptedKey allein) ist ebenso ein Schutz
    return any(True for _ in wurzel.iter(f"{_XMLENC}EncryptedKey"))


def _zip_pfad(basis: str, href: str) -> str:
    """Ein ``href`` (relativ zu ``basis``) als Pfad im Archiv, ohne Fragment."""
    return posixpath.normpath(posixpath.join(basis, unquote(urldefrag(href)[0])))


@dataclass(frozen=True)
class _EpubRoh:
    """Paketdatei und Spine eines EPUB; ``kapitel`` sind die nicht-leeren Spine-Dokumente (Pfad, Text)."""

    opf: ET.Element
    opf_basis: str
    manifest: dict[str, tuple[str, str]]  # id -> (Pfad im Archiv, properties)
    kapitel: tuple[tuple[str, str], ...]


def _epub_roh(z: zipfile.ZipFile, *, kapitel_lesen: bool, grenze: int = MAX_ENTPACKT_BYTES) -> _EpubRoh:
    """OPF ueber ``container.xml``, Manifest und Spine; die Spine-Dokumente nur mit ``kapitel_lesen`` (die eine
    Stelle fuer Text und Buch). Risse sind ``EpubRissError``; die Lesefehler (``_LESEFEHLER``) gehen durch."""
    container = _epub_xml(_epub_eintrag(z, "META-INF/container.xml", grenze=grenze))
    rootfile = container.find(f"{_OCF}rootfiles/{_OCF}rootfile")
    opf_pfad = rootfile.get("full-path") if rootfile is not None else None
    if not opf_pfad:
        raise EpubRissError("leser")
    opf = _epub_xml(_epub_eintrag(z, opf_pfad, grenze=grenze))
    basis = posixpath.dirname(opf_pfad)
    manifest = {  # nur Eintraege mit id und href: ein None als Schluessel traefe ein idref-loses itemref
        item.get("id"): (_zip_pfad(basis, item.get("href")), item.get("properties") or "")
        for item in opf.iterfind(f"{_OPF}manifest/{_OPF}item")
        if item.get("id") and item.get("href")
    }
    spine = [ref.get("idref") for ref in opf.iterfind(f"{_OPF}spine/{_OPF}itemref")]
    if not spine or not all(spine):
        raise EpubRissError("leser")  # ein itemref ohne idref verweist auf nichts
    kapitel: list[tuple[str, str]] = []
    gelesen = 0
    for idref in spine:
        if idref not in manifest:
            raise EpubRissError("leser")  # Spine verweist auf nichts: nie still ueberspringen
        pfad = manifest[idref][0]
        if not kapitel_lesen:
            z.getinfo(pfad)  # das Dokument muss bestehen (KeyError -> ``leser``), gelesen wird es nicht
            continue
        daten = _epub_eintrag(z, pfad, gelesen, grenze)
        gelesen += len(daten)
        p = _EpubText()
        p.feed(_dekodieren(daten))
        p.close()
        if text := p.text():
            kapitel.append((pfad, text))
    return _EpubRoh(opf, basis, manifest, tuple(kapitel))


def epub_text(datei: BinaryIO | Path, *, max_entpackt: int = MAX_ENTPACKT_BYTES) -> str:
    """Text eines EPUB in Lesereihenfolge (Spine), Kapitel durch ``KAPITELGRENZE`` getrennt.

    ``datei`` ist ein Pfad oder eine suchbare Binaerdatei. ``max_entpackt`` begrenzt die entpackten Spine-Dokumente
    zusammen. Raises ``EpubRissError`` (``geschuetzt``, ``groesse``, ``leser``); ``OSError`` eines Pfads geht durch.
    """
    try:
        with zipfile.ZipFile(datei) as z:
            if _epub_geschuetzt(z, max_entpackt):
                raise EpubRissError("geschuetzt")
            roh = _epub_roh(z, kapitel_lesen=True, grenze=max_entpackt)
    except _LESEFEHLER as ex:
        raise EpubRissError("leser") from ex
    return KAPITELGRENZE.join(text for _, text in roh.kapitel)


# --- Das Buch: ISBN, Verzeichnis, Metadaten --------------------------------------------------------


def _isbn13_gueltig(z: str) -> bool:
    return len(z) == 13 and z.isdigit() and sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(z)) % 10 == 0


def _isbn13_aus_10(z: str) -> str | None:
    """Die ISBN-13 zu einer ISBN-10 mit gueltiger Pruefziffer, sonst None."""
    z = z.upper()
    if len(z) != 10 or not z[:9].isdigit() or not (z[9].isdigit() or z[9] == "X"):
        return None
    summe = sum((10 - i) * (10 if d == "X" else int(d)) for i, d in enumerate(z))
    if summe % 11:
        return None
    rumpf = "978" + z[:9]
    pruef = (10 - sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(rumpf)) % 10) % 10
    return rumpf + str(pruef)


def _isbn(wert: str) -> str | None:
    """Eine bereinigte Kennung (ohne Bindestriche, Leerraum, ``urn:isbn:``) als ISBN-13, sonst None. Eine ISBN-13
    beginnt mit 978 oder 979; eine andere EAN mit gueltiger Pruefziffer (Artikelnummer) ist keine ISBN."""
    z = re.sub(r"[\s-]", "", wert).upper()
    if len(z) == 13:
        return z if z.startswith(("978", "979")) and _isbn13_gueltig(z) else None
    return _isbn13_aus_10(z) if len(z) == 10 else None


def isbns(werte: Iterable[str], *, dateiname: str | None = None) -> tuple[str, ...]:
    """Die gueltigen ISBN-13 aus ``werte`` (in dieser Reihenfolge, z. B. ``unique-identifier``, dann die uebrigen
    ``dc:identifier``) und danach aus ``dateiname`` (strenger: ISBN-13 nur mit 978/979, ISBN-10 nur hinter „isbn“),
    ohne Doppel. Eine ISBN-10 wird umgerechnet, die Pruefziffer geprueft; was keine ganze ISBN ist, zaehlt nicht."""
    aus: list[str] = []
    for wert in werte:
        m = _ISBN_OPF.fullmatch((wert or "").strip())
        if m and (isbn := _isbn(m.group(1))):
            aus.append(isbn)
    if dateiname:
        for m in _ISBN13_NAME.finditer(dateiname):
            if isbn := _isbn(m.group(1)):
                aus.append(isbn)
        for m in _ISBN10_NAME.finditer(dateiname):
            if isbn := _isbn(m.group(1)):
                aus.append(isbn)
    return tuple(dict.fromkeys(aus))


class _NavLinks(HTMLParser):
    """Die Links ``(href, Text)`` des Inhaltsverzeichnisses eines nav-Dokuments (EPUB 3), in Reihenfolge; die
    ``nav`` mit ``epub:type="toc"``, sonst die erste."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.navs: list[tuple[bool, list[tuple[str, str]]]] = []
        self._tief = 0
        self._link: list[str] | None = None
        self._href = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "nav":
            if not self._tief:
                self.navs.append(("toc" in (a.get("epub:type") or "").split(), []))
            self._tief += 1
        elif tag == "a" and self._tief and a.get("href"):
            self._link, self._href = [], a["href"] or ""

    def handle_endtag(self, tag):
        if tag == "nav":
            self._tief = max(0, self._tief - 1)
        elif tag == "a" and self._link is not None:
            self.navs[-1][1].append((self._href, re.sub(r"\s+", " ", "".join(self._link)).strip()))
            self._link = None

    def handle_data(self, data):
        if self._link is not None:
            self._link.append(data)

    def eintraege(self) -> list[tuple[str, str]]:
        for toc, links in self.navs:
            if toc:
                return links
        return self.navs[0][1] if self.navs else []


def _verzeichnis(z: zipfile.ZipFile, roh: _EpubRoh, grenze: int) -> list[tuple[str, str]]:
    """Das Inhaltsverzeichnis als (Pfad im Archiv ohne Fragment, Titel) in Verzeichnis-Reihenfolge: nav (EPUB 3),
    sonst NCX (Spine-Attribut ``toc``), sonst leer."""
    nav = next((p for p, props in roh.manifest.values() if "nav" in props.split()), None)
    if nav is not None:
        p = _NavLinks()
        p.feed(_dekodieren(_epub_eintrag(z, nav, grenze=grenze)))
        p.close()
        basis = posixpath.dirname(nav)
        return [(_zip_pfad(basis, href), titel) for href, titel in p.eintraege() if titel]
    spine = roh.opf.find(f"{_OPF}spine")
    toc = spine.get("toc") if spine is not None else None
    if not toc or toc not in roh.manifest:
        return []
    ncx_pfad = roh.manifest[toc][0]
    ncx = _epub_xml(_epub_eintrag(z, ncx_pfad, grenze=grenze))
    basis = posixpath.dirname(ncx_pfad)
    aus = []
    for punkt in ncx.iter(f"{_NCX}navPoint"):
        text = punkt.find(f"{_NCX}navLabel/{_NCX}text")
        inhalt = punkt.find(f"{_NCX}content")
        titel = re.sub(r"\s+", " ", text.text or "").strip() if text is not None else ""
        if titel and inhalt is not None and inhalt.get("src"):
            aus.append((_zip_pfad(basis, inhalt.get("src") or ""), titel))
    return aus


def _kapitel_mit_titel(roh: _EpubRoh, verzeichnis: list[tuple[str, str]]) -> tuple[Kapitel, ...]:
    """Titel: erster Verzeichniseintrag auf das Dokument; sonst der des vorigen Kapitels, sonst „Kapitel n“."""
    erster: dict[str, str] = {}
    for pfad, titel in verzeichnis:
        erster.setdefault(pfad, titel)
    aus: list[Kapitel] = []
    for n, (pfad, text) in enumerate(roh.kapitel, start=1):
        titel = erster.get(pfad) or (aus[-1].titel if aus else f"Kapitel {n}")
        aus.append(Kapitel(titel, text))
    return tuple(aus)


def _datum(wert: str | None) -> str | None:
    m = _DATUM.match((wert or "").strip())
    if not m or int(m.group(1)) < _FRUEHESTES_JAHR:
        return None
    return m.group(0)


def _texte(opf: ET.Element, feld: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", e.text).strip()
        for e in opf.iterfind(f"{_OPF}metadata/{_DC}{feld}")
        if e.text and e.text.strip()
    ]


def epub_buch(datei: BinaryIO | Path, *, dateiname: str | None = None, max_entpackt: int = MAX_ENTPACKT_BYTES) -> Buch:
    """Das EPUB als Buch: Metadaten aus dem OPF, alle ISBN (``isbns``), die Kapitel mit Titel.

    ``datei`` ist ein Pfad oder eine suchbare Binaerdatei. ``dateiname`` ist der urspruengliche Name (bei einer
    Kopie oder einer Binaerdatei); aus ihm kommen die ISBN aus dem Namen und, ohne ``dc:title``, der Titel (Stamm
    des Namens). Ohne ``dateiname`` gilt der Name des Pfads.

    Ein geschuetztes Buch liefert nur die Metadaten (``geschuetzt=True``, ``kapitel=()``); kein Kapitel-Dokument
    wird geoeffnet. Den Abbruch macht der Aufrufer. Ein Lesefehler ist ``EpubLesefehlerError`` (bei einem Pfad
    mit dessen Namen vorn), nie ein leeres Buch; ``OSError`` eines Pfads geht durch.
    """
    vorn = f"{datei.name}: " if isinstance(datei, Path) else ""
    try:
        with zipfile.ZipFile(datei) as z:
            geschuetzt = _epub_geschuetzt(z, max_entpackt)
            try:
                roh = _epub_roh(z, kapitel_lesen=not geschuetzt, grenze=max_entpackt)
            except EpubRissError as r:
                if r.grund != "geschuetzt":
                    raise
                geschuetzt, roh = True, _epub_roh(z, kapitel_lesen=False, grenze=max_entpackt)
            kapitel = () if geschuetzt else _kapitel_mit_titel(roh, _verzeichnis(z, roh, max_entpackt))
    except EpubRissError as r:
        raise EpubLesefehlerError(f"{vorn}EPUB nicht lesbar ({r.grund})") from r
    except _LESEFEHLER as ex:
        raise EpubLesefehlerError(f"{vorn}EPUB nicht lesbar ({type(ex).__name__})") from ex
    opf = roh.opf
    unique = opf.get("unique-identifier")
    kennungen = [(e.get("id"), (e.text or "").strip()) for e in opf.iterfind(f"{_OPF}metadata/{_DC}identifier")]
    reihe = [w for i, w in kennungen if unique and i == unique] + [w for i, w in kennungen if not unique or i != unique]
    name = dateiname or (datei.name if isinstance(datei, Path) else "")
    titel = _texte(opf, "title")
    verlag, sprache, datum = (_texte(opf, f) for f in ("publisher", "language", "date"))
    return Buch(
        titel=titel[0] if titel else Path(name).stem,  # ohne dc:title: der urspruengliche Name
        autoren=tuple(_texte(opf, "creator")),
        verlag=verlag[0] if verlag else None,
        sprache=sprache[0] if sprache else None,
        datum=_datum(datum[0] if datum else None),
        isbns=isbns(reihe, dateiname=name or None),
        kapitel=kapitel,
        geschuetzt=geschuetzt,
    )
