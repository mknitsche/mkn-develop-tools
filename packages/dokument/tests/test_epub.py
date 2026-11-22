"""EPUB lesen: Lesereihenfolge, Kopierschutz, kaputtes Archiv, Groesse, ISBN, Kapitel und Kapiteltitel.

Risiken: falsche Information (falsche Reihenfolge, falsche Identitaet eines Buchs, falscher Kapiteltitel, ein
Lesefehler als leeres Buch) und nach aussen (ein geschuetztes Buch wird doch gelesen). Die Test-EPUB baut der Test
mit ``zipfile`` aus erfundenen Saetzen; Titel, Namen und Verlag sind erfunden.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from mkn_dokument import epub, kommandozeile

DC = "http://purl.org/dc/elements/1.1/"
ADEPT = "http://www.w3.org/2001/04/xmlenc#aes128-cbc"

_CONTAINER = (
    '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="OEBPS/inhalt.opf" media-type="application/oebps-package+xml"/>'
    "</rootfiles></container>"
)


def _xhtml(*absaetze: str, kopf: str = "Kopftitel") -> str:
    rumpf = "".join(f"<p>{a}</p>" for a in absaetze)
    return (
        '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml">'
        f"<head><title>{kopf}</title><style>p {{color: red}}</style></head><body>{rumpf}</body></html>"
    )


def _nav(eintraege: list[tuple[str, str]]) -> str:
    punkte = "".join(f'<li><a href="{href}">{titel}</a></li>' for href, titel in eintraege)
    return (
        '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Inhalt</title></head><body>'
        f'<nav epub:type="toc"><ol>{punkte}</ol></nav></body></html>'
    )


def _ncx(eintraege: list[tuple[str, str]]) -> str:
    punkte = "".join(
        f'<navPoint id="n{i}"><navLabel><text>{titel}</text></navLabel><content src="{src}"/></navPoint>'
        for i, (src, titel) in enumerate(eintraege)
    )
    return (
        '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        f"<navMap>{punkte}</navMap></ncx>"
    )


def _epub(
    kapitel: dict[str, str],
    spine: list[str],
    *,
    kennungen: tuple[tuple[str, str], ...] = (),
    unique: str | None = None,
    meta: str = "",
    nav: list[tuple[str, str]] | None = None,
    ncx: list[tuple[str, str]] | None = None,
    verschluesselt: dict[str, bytes] | None = None,
    schutz: list[tuple[str, str]] | None = None,
    manifest_extra: str = "",
) -> bytes:
    """``kapitel``: Dateiname unter OEBPS -> XHTML; ``spine``: Dateinamen (oder ids) in Lesereihenfolge;
    ``kennungen``: (id, Wert) der ``dc:identifier``; ``verschluesselt``: Kapitel -> unlesbare Bytes, mit
    ``encryption.xml``; ``schutz``: (URI, Verfahren) fuer ``encryption.xml`` ohne eigene Bytes."""
    namen = sorted(kapitel) + sorted(verschluesselt or {})
    ids = {name: f"d{i}" for i, name in enumerate(namen)}
    items = "".join(f'<item id="{ids[n]}" href="{n}" media-type="application/xhtml+xml"/>' for n in namen)
    if nav is not None:
        items += '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
    if ncx is not None:
        items += '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
    refs = "".join(f'<itemref idref="{ids.get(n, n)}"/>' for n in spine)
    idents = "".join(f'<dc:identifier id="{i}">{w}</dc:identifier>' for i, w in kennungen)
    kennung = f' unique-identifier="{unique}"' if unique else ""
    toc = ' toc="ncx"' if ncx is not None else ""
    opf = (
        f'<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0"{kennung}>'
        f'<metadata xmlns:dc="{DC}"><dc:title>Der erfundene Garten</dc:title>'
        "<dc:creator>Anna Probe</dc:creator><dc:creator>Ben Beispiel</dc:creator>"
        f"<dc:publisher>Testverlag</dc:publisher><dc:language>de</dc:language>{idents}{meta}</metadata>"
        f"<manifest>{items}{manifest_extra}</manifest><spine{toc}>{refs}</spine></package>"
    )
    eintraege = [(f"OEBPS/{n}", ADEPT) for n in verschluesselt or {}] + list(schutz or [])
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", _CONTAINER)
        if eintraege:
            daten = "".join(
                '<enc:EncryptedData xmlns:enc="http://www.w3.org/2001/04/xmlenc#">'
                f'<enc:EncryptionMethod Algorithm="{alg}"/>'
                f'<enc:CipherData><enc:CipherReference URI="{uri}"/></enc:CipherData></enc:EncryptedData>'
                for uri, alg in eintraege
            )
            z.writestr(
                "META-INF/encryption.xml",
                f'<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container">{daten}</encryption>',
            )
        z.writestr("OEBPS/inhalt.opf", opf)
        for name, html in kapitel.items():
            z.writestr(f"OEBPS/{name}", html)
        for name, roh in (verschluesselt or {}).items():
            z.writestr(f"OEBPS/{name}", roh)
        if nav is not None:
            z.writestr("OEBPS/nav.xhtml", _nav(nav))
        if ncx is not None:
            z.writestr("OEBPS/toc.ncx", _ncx(ncx))
    return puffer.getvalue()


def _opf_epub(manifest: str, spine: str, *, metadaten: str = "<dc:creator>Anna Probe</dc:creator>") -> bytes:
    """Ein EPUB mit frei gesetztem Manifest, Spine und Metadaten (fehlende Attribute, fehlender Titel)."""
    opf = (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        f'<metadata xmlns:dc="{DC}">{metadaten}</metadata>'
        f"<manifest>{manifest}</manifest><spine>{spine}</spine></package>"
    )
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OEBPS/inhalt.opf", opf)
        z.writestr("OEBPS/a.xhtml", _xhtml("Ein Satz."))
    return puffer.getvalue()


def _datei(tmp_path: Path, daten: bytes, name: str = "buch.epub") -> Path:
    pfad = tmp_path / name
    pfad.write_bytes(daten)
    return pfad


def _riss(daten: bytes, **k) -> str:
    with pytest.raises(epub.EpubRissError) as fehler:
        epub.epub_text(io.BytesIO(daten), **k)
    return fehler.value.grund


# --- Text: Lesereihenfolge, Kopierschutz, Risse -----------------------------------------------------


def test_lesereihenfolge_folgt_dem_spine_nicht_dem_dateinamen():
    """Falsche Information: die Kapitel stehen in der Reihenfolge des Buchs, ohne Kopf und Stil."""
    daten = _epub(
        {
            "a.xhtml": _xhtml("Schlusskapitel", "Ende der Erzaehlung."),
            "b.xhtml": _xhtml("Erstes Kapitel", "Anfang der Erzaehlung."),
            "c.xhtml": _xhtml("Mittelteil", "Mitte der Erzaehlung."),
        },
        ["b.xhtml", "c.xhtml", "a.xhtml"],
    )
    text = epub.epub_text(io.BytesIO(daten))

    assert text.index("Anfang der") < text.index("Mitte der") < text.index("Ende der")
    kapitel = text.split(epub.KAPITELGRENZE)
    assert len(kapitel) == 3
    assert kapitel[0] == "Erstes Kapitel\n\nAnfang der Erzaehlung."
    assert "Kopftitel" not in text
    assert "color" not in text


def test_text_aus_einem_pfad(tmp_path):
    daten = _epub({"k.xhtml": _xhtml("Text im Buch.")}, ["k.xhtml"])
    assert epub.epub_text(_datei(tmp_path, daten)) == "Text im Buch."


def test_geschuetztes_epub_ist_ein_riss_geschuetzt():
    """Nach aussen: ein Kopierschutz wird erkannt und abgewiesen, nie umgangen."""
    daten = _epub({}, ["k.xhtml"], verschluesselt={"k.xhtml": bytes(range(256)) * 8})
    assert _riss(daten) == "geschuetzt"


def test_nur_verschleierte_schriften_sind_kein_schutz():
    """Schrift-Verschleierung (IDPF/Adobe) steht auch in encryption.xml, schuetzt aber keinen Text."""
    daten = _epub(
        {"k.xhtml": _xhtml("Lesbarer Inhalt.")},
        ["k.xhtml"],
        schutz=[
            ("OEBPS/fonts/schrift.otf", "http://www.idpf.org/2008/embedding"),
            ("OEBPS/fonts/zwei.otf", "http://ns.adobe.com/pdf/enc#RC"),
        ],
    )
    assert epub.epub_text(io.BytesIO(daten)) == "Lesbarer Inhalt."


@pytest.mark.parametrize(
    "daten",
    [
        pytest.param(b"PK\x03\x04" + b"\x00" * 60, id="kein-zip"),
        pytest.param(_epub({"k.xhtml": _xhtml("x")}, ["k.xhtml"])[:200], id="abgeschnitten"),
        pytest.param(_epub({"k.xhtml": _xhtml("x")}, ["fehlt"]), id="spine-ohne-manifest"),
        pytest.param(
            _epub(
                {"k.xhtml": _xhtml("x")},
                ["k.xhtml", "weg"],
                manifest_extra='<item id="weg" href="weg.xhtml" media-type="application/xhtml+xml"/>',
            ),
            id="spine-datei-fehlt-im-archiv",
        ),
    ],
)
def test_kaputtes_epub_ist_ein_riss_leser(daten):
    """Falsche Information: ein kaputtes Archiv wird nie still als (Teil-)Text gelesen."""
    assert _riss(daten) == "leser"


def test_entpackte_groesse_ist_begrenzt():
    daten = _epub({"k.xhtml": _xhtml("x" * 5_000)}, ["k.xhtml"])
    assert len(daten) < 2_000  # gepackt klein, entpackt ueber der Grenze
    assert _riss(daten, max_entpackt=2_000) == "groesse"
    assert epub.MAX_ENTPACKT_BYTES == 50 * 2**20


# --- Buch: Identitaet ---------------------------------------------------------------------------------


def test_isbn_reihenfolge_pruefziffer_isbn10_und_zwei_ausgaben(tmp_path):
    """Falsche Information: eine falsche Identitaet ersetzt ein fremdes Buch."""
    daten = _epub(
        {"a.xhtml": _xhtml("Ein Satz.")},
        ["a.xhtml"],
        kennungen=(
            ("ebook", "9781234567897"),  # E-Book-Ausgabe, nicht der unique-identifier
            ("falsch", "978-3-16-148410-1"),  # falsche Pruefziffer: verworfen
            ("werkzeug", "werkzeug:12345"),
            ("druck", "urn:isbn:978-3-16-148410-0"),  # unique-identifier: vorn
            ("alt", "3-16-148410-X"),  # ISBN-10 derselben Ausgabe: kein Doppel
        ),
        unique="druck",
    )
    buch = epub.epub_buch(_datei(tmp_path, daten, "Beispiel_Garten_9780000000019.epub"))

    assert buch.isbns == ("9783161484100", "9781234567897", "9780000000019")
    assert buch.isbn == "9783161484100"
    assert epub.isbns(["3-16-148410-X"]) == ("9783161484100",)
    assert epub.isbns(["978-3-16-148410-1", "uuid:0123456789abc"]) == ()
    assert (buch.titel, buch.autoren, buch.verlag, buch.sprache) == (
        "Der erfundene Garten",
        ("Anna Probe", "Ben Beispiel"),
        "Testverlag",
        "de",
    )


def test_ean_im_opf_ist_keine_isbn(tmp_path):
    """Eine Artikel-EAN (13 Stellen, gueltige Pruefziffer, kein 978/979) ist keine Kennung des Buchs."""
    daten = _epub(
        {"a.xhtml": _xhtml("Ein Satz.")},
        ["a.xhtml"],
        kennungen=(("ean", "4006381333931"), ("druck", "urn:isbn:978-3-16-148410-0")),
        unique="ean",
    )
    assert epub.epub_buch(_datei(tmp_path, daten, "garten.epub")).isbns == ("9783161484100",)
    assert epub.isbns(["4006381333931", "urn:isbn:4006381333931", "urn:isbn:979-0-000000-00-1"]) == ("9790000000001",)


@pytest.mark.parametrize(
    ("name", "erwartet"),
    [
        ("Garten_7345029182.epub", ()),  # Bestellnummer mit gueltiger ISBN-10-Pruefziffer, ohne Marker
        ("Garten_ISBN7345029182.epub", ("9787345029187",)),
        ("Garten isbn-734502918-2.epub", ("9787345029187",)),
        ("Garten_4006381333931.epub", ()),  # gueltige EAN, kein 978/979
        ("Garten_978-0-00-000001-9.epub", ("9780000000019",)),
    ],
)
def test_dateiname_gilt_nur_streng_als_isbn(name, erwartet):
    """Falsche Information: eine Zahl im Dateinamen, die keine ISBN ist, gilt nicht als Kennung."""
    assert epub.isbns([], dateiname=name) == erwartet


def test_isbn_im_opf_mit_leerzeichen_zaehlt():
    assert epub.isbns(["978 3 16 148410 0"]) == ("9783161484100",)
    assert epub.isbns(["urn:isbn:978 3 16 148410 0"]) == ("9783161484100",)
    assert epub.isbns(["ISBN 3 16 148410 X"]) == ("9783161484100",)
    assert epub.isbns(["400 6381 333931"]) == ()  # EAN ohne 978/979


# --- Buch: Kapitel und Titel -------------------------------------------------------------------------


def test_kapitel_zaehlen_wie_der_text_auch_mit_leerem_spine_dokument(tmp_path):
    """Falsche Information: Buch und Text zaehlen dieselben Kapitel."""
    daten = _epub(
        {
            "a.xhtml": _xhtml("Erster Absatz eins.", "Zweiter Absatz eins."),
            "leer.xhtml": _xhtml(),
            "b.xhtml": _xhtml("Erster Absatz zwei."),
        },
        ["a.xhtml", "leer.xhtml", "b.xhtml"],
    )
    buch = epub.epub_buch(_datei(tmp_path, daten))

    assert len(buch.kapitel) == 2
    assert epub.KAPITELGRENZE.join(k.text for k in buch.kapitel) == epub.epub_text(io.BytesIO(daten))
    assert buch.kapitel[0].text == "Erster Absatz eins.\n\nZweiter Absatz eins."


@pytest.mark.parametrize("verzeichnis", ["nav", "ncx"])
def test_kapiteltitel_erster_eintrag_ohne_fragment_sonst_geerbt(tmp_path, verzeichnis):
    """Falsche Information: ein falscher Kapiteltitel."""
    eintraege = [("a.xhtml#teil2", "Der Anfang"), ("a.xhtml#teil3", "Noch im Anfang"), ("c.xhtml", "Das Ende")]
    daten = _epub(
        {"a.xhtml": _xhtml("A."), "b.xhtml": _xhtml("B."), "c.xhtml": _xhtml("C.")},
        ["a.xhtml", "b.xhtml", "c.xhtml"],
        **{verzeichnis: eintraege},
    )
    buch = epub.epub_buch(_datei(tmp_path, daten))
    assert [k.titel for k in buch.kapitel] == ["Der Anfang", "Der Anfang", "Das Ende"]


def test_kapitel_ohne_jeden_eintrag_heisst_kapitel_n(tmp_path):
    daten = _epub(
        {"a.xhtml": _xhtml("A."), "b.xhtml": _xhtml("B.")}, ["a.xhtml", "b.xhtml"], nav=[("b.xhtml", "Zweites")]
    )
    buch = epub.epub_buch(_datei(tmp_path, daten))
    assert [k.titel for k in buch.kapitel] == ["Kapitel 1", "Zweites"]


def test_datum_nur_der_datumsteil_und_kein_platzhalter(tmp_path):
    """Falsche Information: das Datum nie genauer als bekannt, ein Platzhalter ist kein Datum."""
    mit = _epub({"a.xhtml": _xhtml("A.")}, ["a.xhtml"], meta="<dc:date>2021-03-04T00:00:00+00:00</dc:date>")
    jahr = _epub({"a.xhtml": _xhtml("A.")}, ["a.xhtml"], meta="<dc:date>2017</dc:date>")
    platzhalter = _epub({"a.xhtml": _xhtml("A.")}, ["a.xhtml"], meta="<dc:date>0101-01-01T00:00:00+00:00</dc:date>")
    assert epub.epub_buch(_datei(tmp_path, mit, "a.epub")).datum == "2021-03-04"
    assert epub.epub_buch(_datei(tmp_path, jahr, "b.epub")).datum == "2017"
    assert epub.epub_buch(_datei(tmp_path, platzhalter, "c.epub")).datum is None


def test_ohne_titel_gilt_der_stamm_des_urspruenglichen_namens(tmp_path):
    daten = _opf_epub('<item id="a" href="a.xhtml" media-type="application/xhtml+xml"/>', '<itemref idref="a"/>')
    kopie = _datei(tmp_path, daten, "buch.epub")

    assert epub.epub_buch(kopie, dateiname="Der_erfundene_Garten.epub").titel == "Der_erfundene_Garten"
    assert epub.epub_buch(kopie).titel == "buch"
    assert epub.epub_buch(io.BytesIO(daten), dateiname="Aus_dem_Strom.epub").titel == "Aus_dem_Strom"


# --- Buch: Lesefehler und Kopierschutz ----------------------------------------------------------------


def test_kaputtes_archiv_wirft_eine_ausnahme(tmp_path):
    """Falsche Information: ein Lesefehler wird nie ein leeres Buch."""
    with pytest.raises(epub.EpubLesefehlerError, match=r"^eins\.epub: "):
        epub.epub_buch(_datei(tmp_path, b"PK\x03\x04" + b"\x00" * 60, "eins.epub"))
    kaputt = _epub({"a.xhtml": _xhtml("A.")}, ["a.xhtml"])[:200]
    with pytest.raises(epub.EpubLesefehlerError, match=r"^EPUB nicht lesbar"):
        epub.epub_buch(io.BytesIO(kaputt))


@pytest.mark.parametrize(
    ("manifest", "spine"),
    [
        # Manifest-Eintrag ohne id und Spine-Verweis ohne idref: None traefe None
        ('<item href="a.xhtml" media-type="application/xhtml+xml"/>', "<itemref/>"),
        ('<item id="a" href="a.xhtml" media-type="application/xhtml+xml"/>', '<itemref idref="a"/><itemref/>'),
        ('<item id="a" href="a.xhtml" media-type="application/xhtml+xml"/>', '<itemref idref="fehlt"/>'),
    ],
)
def test_manifest_ohne_id_oder_spine_ohne_idref_ist_ein_lesefehler(manifest, spine):
    """Falsche Information: ein kaputtes Paket wird nie still gelesen (Text wie Buch)."""
    daten = _opf_epub(manifest, spine)
    with pytest.raises(epub.EpubLesefehlerError, match="leser"):
        epub.epub_buch(io.BytesIO(daten))
    assert _riss(daten) == "leser"


def test_geschuetztes_buch_liefert_nur_metadaten_und_liest_kein_kapitel(tmp_path, monkeypatch):
    """Nach aussen: ein geschuetztes Buch wird nie gelesen, nur seine Metadaten."""
    gelesen: list[str] = []
    echt = epub._epub_eintrag

    def spion(z, pfad, *a, **k):
        gelesen.append(pfad)
        return echt(z, pfad, *a, **k)

    monkeypatch.setattr(epub, "_epub_eintrag", spion)
    daten = _epub(
        {},
        ["k.xhtml"],
        kennungen=(("druck", "urn:isbn:9783161484100"),),
        unique="druck",
        verschluesselt={"k.xhtml": bytes(range(256)) * 8},
    )
    buch = epub.epub_buch(_datei(tmp_path, daten))

    assert buch.geschuetzt is True
    assert buch.kapitel == ()
    assert (buch.titel, buch.isbn) == ("Der erfundene Garten", "9783161484100")
    assert "OEBPS/k.xhtml" not in gelesen
    assert "OEBPS/inhalt.opf" in gelesen  # der Spion sieht die Lesungen ueberhaupt


# --- Befehl ``mkn-dokument epub`` ---------------------------------------------------------------------


def test_befehl_epub_gibt_metadaten_und_kapitelliste_als_json(tmp_path, capsys):
    daten = _epub(
        {"a.xhtml": _xhtml("Erster Satz."), "b.xhtml": _xhtml("Zweiter Satz.", "Dritter.")},
        ["a.xhtml", "b.xhtml"],
        kennungen=(("druck", "urn:isbn:978-3-16-148410-0"),),
        unique="druck",
        nav=[("a.xhtml", "Anfang"), ("b.xhtml", "Weiter")],
    )
    assert kommandozeile.haupt(["epub", str(_datei(tmp_path, daten))]) == 0
    aus = json.loads(capsys.readouterr().out)

    assert aus["titel"] == "Der erfundene Garten"
    assert aus["isbns"] == ["9783161484100"]
    assert aus["geschuetzt"] is False
    assert aus["kapitel"] == [{"titel": "Anfang", "zeichen": 12}, {"titel": "Weiter", "zeichen": 23}]


def test_befehl_epub_meldet_einen_lesefehler_laut(tmp_path, capsys):
    assert kommandozeile.haupt(["epub", str(_datei(tmp_path, b"kein epub"))]) == 1
    assert "EPUB nicht lesbar" in capsys.readouterr().err
