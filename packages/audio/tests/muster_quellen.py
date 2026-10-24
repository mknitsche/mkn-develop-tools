"""Muster-Quellen fuer die Lese-Tests, im Test erzeugt.

Keine Buchtexte, keine Personendaten: alle Inhalte sind erfundene Platzhalter. Die
Quellen entstehen hier statt als Dateien im Repo, damit jede Eigenschaft, auf die ein
Test sich stuetzt (Beiwerk, Kopfzeile, Spalte ...), an genau einer Stelle zu lesen ist.
"""

from __future__ import annotations

import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import pymupdf

COVER_BYTES = b"\x89PNG\r\n\x1a\n-kein-echtes-bild-"

_XHTML = """\
<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>{titel}</title></head>
<body>{koerper}</body>
</html>
"""

_CONTAINER = """\
<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf"
 media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""


def xhtml(koerper: str, titel: str = "Seite") -> str:
    return _XHTML.format(titel=titel, koerper=koerper)


def opf(
    *,
    items: Sequence[tuple[str, str, str, str]],
    spine: Sequence[str],
    titel: str = "Das Musterbuch",
    autor: str | None = "Erika Muster",
    sprache: str = "de-DE",
    cover_id: str | None = None,
    guide: str = "",
    kopf: str = "",
) -> str:
    """Baut ein OPF. `items` sind `(id, href, media-type, properties)`."""
    manifest = "".join(
        f'<item id="{i}" href="{h}" media-type="{m}"' + (f' properties="{p}"' if p else "") + "/>"
        for i, h, m, p in items
    )
    autor_zeile = f"<dc:creator>{autor}</dc:creator>" if autor else ""
    cover = f'<meta name="cover" content="{cover_id}"/>' if cover_id else ""
    return (
        f'<?xml version="1.0"?>{kopf}'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>{titel}</dc:title>{autor_zeile}"
        f"<dc:language>{sprache}</dc:language>{cover}</metadata>"
        f"<manifest>{manifest}</manifest>"
        f"<spine>{''.join(f'<itemref idref="{s}"/>' for s in spine)}</spine>"
        f"{guide}</package>"
    )


def epub_schreiben(pfad: Path, dateien: Mapping[str, str | bytes]) -> Path:
    """Schreibt ein EPUB; `dateien` sind Pfade unter `OEBPS/`."""
    with zipfile.ZipFile(pfad, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", _CONTAINER)
        for name, inhalt in dateien.items():
            zf.writestr(f"OEBPS/{name}", inhalt)
    return pfad


NAV = xhtml(
    '<nav epub:type="toc"><ol><li><a href="kap1.xhtml">Erstes Kapitel</a></li></ol></nav>'
    '<nav epub:type="landmarks"><ol>'
    '<li><a epub:type="copyright-page" href="impressum.xhtml">Rechtliches</a></li>'
    "</ol></nav>",
    "Navigation",
)

KAP1 = xhtml(
    '<h1>Erstes Kapitel</h1><p>Das ist der erste Absatz.<a epub:type="noteref" '
    'href="#n1">1</a></p><p>Zweiter Absatz mit <i>Betonung</i>, ganz normal.</p>'
    '<aside epub:type="footnote" id="n1"><p>Eine Fussnote, die nicht vorgelesen wird.</p>'
    "</aside>",
    "Erstes Kapitel",
)

KAP2 = xhtml(
    "<h1>Zweites Kapitel</h1><p>Hier beginnt das zweite Kapitel.</p>"
    "<h3>Eine Zwischenueberschrift</h3><p>Und es geht weiter.</p>",
    "Zweites Kapitel",
)

IMPRESSUM = xhtml(
    '<section epub:type="copyright-page"><h1>Alle Rechte</h1>'
    "<p>Alle Rechte vorbehalten. Erfundene Verlagsangaben.</p></section>",
    "Rechtliches",
)

INHALT = xhtml(
    "<h1>Inhaltsverzeichnis</h1><ol><li>Erstes Kapitel</li><li>Zweites Kapitel</li></ol>",
    "Inhalt",
)

ANMERKUNGEN = xhtml("<h1>Anmerkungen</h1><ol><li>Notiz eins</li></ol>", "Anmerkungen")


def muster_epub(pfad: Path) -> Path:
    """Ein EPUB mit Beiwerk jeder Art.

    Die Manifest-Reihenfolge ist absichtlich NICHT die Lesereihenfolge (Kapitel 2 steht
    vor Kapitel 1): wer das Manifest statt der Lesefolge abliefe, bekaeme die Kapitel
    vertauscht.
    """
    xml, html = "application/xhtml+xml", "application/xhtml+xml"
    items = [
        ("kap2", "kap2.xhtml", html, ""),
        ("kap1", "kap1.xhtml", html, ""),
        ("nav", "nav.xhtml", xml, "nav"),
        ("imp", "impressum.xhtml", html, ""),
        ("inh", "inhalt.xhtml", html, ""),
        ("anm", "anmerkungen.xhtml", html, ""),
        ("cov", "bilder/cover.png", "image/png", "cover-image"),
    ]
    inhalt = opf(items=items, spine=["nav", "imp", "inh", "kap1", "kap2", "anm"])
    return epub_schreiben(
        pfad,
        {
            "content.opf": inhalt,
            "nav.xhtml": NAV,
            "impressum.xhtml": IMPRESSUM,
            "inhalt.xhtml": INHALT,
            "kap1.xhtml": KAP1,
            "kap2.xhtml": KAP2,
            "anmerkungen.xhtml": ANMERKUNGEN,
            "bilder/cover.png": COVER_BYTES,
        },
    )


def epub_mit_kapiteln(pfad: Path, kapitel: Mapping[str, str], *, opf_kopf: str = "") -> Path:
    """Ein schlichtes EPUB: je Eintrag `{dateiname: xhtml}` in Lesereihenfolge."""
    items = [(n.split(".")[0], n, "application/xhtml+xml", "") for n in kapitel]
    inhalt = opf(items=items, spine=[i[0] for i in items], kopf=opf_kopf)
    return epub_schreiben(pfad, {"content.opf": inhalt, **kapitel})


_NCX_TYP = "application/x-dtbncx+xml"

Verzeichnis = Sequence[tuple[str, str, "Verzeichnis"]]
"""Inhaltsverzeichnis als Baum: `(Label, href, verschachtelte Eintraege)`."""


def _ncx_punkte(eintraege: Verzeichnis) -> str:
    return "".join(
        f"<navPoint><navLabel><text>{label}</text></navLabel>"
        f'<content src="{href}"/>{_ncx_punkte(kinder)}</navPoint>'
        for label, href, kinder in eintraege
    )


def ncx(eintraege: Verzeichnis) -> str:
    """Inhaltsverzeichnis des alten Formats (EPUB 2)."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        f"<navMap>{_ncx_punkte(eintraege)}</navMap></ncx>"
    )


def _nav_liste(eintraege: Verzeichnis) -> str:
    if not eintraege:
        return ""
    punkte = "".join(
        f'<li><a href="{href}">{label}</a>{_nav_liste(kinder)}</li>'
        for label, href, kinder in eintraege
    )
    return f"<ol>{punkte}</ol>"


def nav_dokument(eintraege: Verzeichnis) -> str:
    """Navigationsdokument des neuen Formats (EPUB 3), mit `<h1>` im `nav`."""
    return xhtml(f'<nav epub:type="toc"><h1>Inhalt</h1>{_nav_liste(eintraege)}</nav>', "Navigation")


def epub_mit_verzeichnis(
    pfad: Path,
    seiten: Mapping[str, str],
    *,
    ncx_eintraege: Verzeichnis | None = None,
    nav_eintraege: Verzeichnis | None = None,
) -> Path:
    """Ein EPUB mit Inhaltsverzeichnis als NCX und/oder nav; `seiten` in Lesefolge.

    NCX und nav stehen im Manifest, aber nicht im Spine (wie bei Verlagsdateien).
    """
    html = "application/xhtml+xml"
    items = [(n.split(".")[0], n, html, "") for n in seiten]
    dateien: dict[str, str | bytes] = dict(seiten)
    if ncx_eintraege is not None:
        items.append(("ncx", "toc.ncx", _NCX_TYP, ""))
        dateien["toc.ncx"] = ncx(ncx_eintraege)
    if nav_eintraege is not None:
        items.append(("nav", "nav.xhtml", html, "nav"))
        dateien["nav.xhtml"] = nav_dokument(nav_eintraege)
    spine = [i[0] for i in items if i[0] not in ("ncx", "nav")]
    dateien["content.opf"] = opf(items=items, spine=spine)
    return epub_schreiben(pfad, dateien)


def _neue_pdf() -> pymupdf.Document:
    return pymupdf.open()


def muster_pdf_kopf_fuss(pfad: Path) -> Path:
    """Drei Textseiten mit Kopfzeile, Seitenzahl, Silbentrennung und einer URL."""
    doc = _neue_pdf()
    for nr in (1, 2, 3):
        seite = doc.new_page()
        seite.insert_text((72, 40), "Kopfzeile des Musterbuchs", fontsize=9)
        seite.insert_textbox(
            pymupdf.Rect(72, 100, 520, 160),
            f"Erster Absatz auf Seite {nr}. Er hat zwei Saetze.",
            fontsize=11,
        )
        seite.insert_textbox(
            pymupdf.Rect(72, 200, 520, 280),
            "Zweiter Absatz mit Silben-\ntrennung am Zeilenende und einer Adresse\n"
            "https://beispiel.example/pfad/seite im Text.",
            fontsize=11,
        )
        seite.insert_text((290, 810), str(nr), fontsize=9)
    doc.save(pfad)
    return pfad


def muster_pdf_zwei_spalten(pfad: Path) -> Path:
    """Eine Seite mit zwei Spalten, deren Zeilen sich in der Hoehe ueberlappen."""
    doc = _neue_pdf()
    seite = doc.new_page()
    boxen = {
        "Linke Spalte oben.": (50, 100, 280, 130),
        "Rechte Spalte oben.": (320, 100, 550, 130),
        "Linke Spalte unten.": (50, 200, 280, 230),
        "Rechte Spalte unten.": (320, 200, 550, 230),
    }
    for text, (x0, y0, x1, y1) in boxen.items():
        seite.insert_textbox(pymupdf.Rect(x0, y0, x1, y1), text, fontsize=11)
    doc.save(pfad)
    return pfad


def muster_pdf_mit_gliederung(pfad: Path) -> Path:
    """Vier Seiten mit Lesezeichen: Kapitel 'Eins' ab Seite 1, 'Zwei' ab Seite 3."""
    doc = _neue_pdf()
    for nr in range(1, 5):
        seite = doc.new_page()
        seite.insert_textbox(
            pymupdf.Rect(72, 100, 520, 160), f"Text auf Seite {nr} des Musterbuchs.", fontsize=11
        )
    doc.set_toc([[1, "Eins", 1], [1, "Zwei", 3]])
    doc.save(pfad)
    return pfad


def muster_pdf_leer(pfad: Path) -> Path:
    """Ein PDF aus einer einzigen leeren Seite."""
    doc = _neue_pdf()
    doc.new_page()
    doc.save(pfad)
    return pfad


def muster_pdf_scan(pfad: Path, seiten: int = 1) -> Path:
    """Seiten ohne Textebene, aber mit einem Bild darauf -- wie ein Scan."""
    doc = _neue_pdf()
    grau = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 60, 60), False)
    grau.clear_with(200)
    for _ in range(seiten):
        seite = doc.new_page()
        seite.insert_image(seite.rect, pixmap=grau)
    doc.save(pfad)
    return pfad


def muster_png(pfad: Path) -> Path:
    """Ein PNG mit einer Zeile Text (per Render, kein Foto)."""
    doc = _neue_pdf()
    seite = doc.new_page(width=300, height=100)
    seite.insert_text((20, 50), "Ein erfundener Satz.", fontsize=14)
    seite.get_pixmap(dpi=96).save(str(pfad))
    return pfad
