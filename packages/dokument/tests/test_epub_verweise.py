"""Anmerkungen eines EPUB ihrer Fundstelle zuordnen (``epub_verweise``).

Risiko: falsche Information - eine Anmerkung haengt an der falschen Aussage. Darum prueft jeder Test die Marke
``K<Kapitel>.<Absatz>`` gegen dieselbe Absatzzaehlung wie ``epub_buch`` (Absaetze durch Leerzeile, leere verworfen),
und im Zweifel bleibt eine Anmerkung ohne Zuordnung (gezaehlt), nie geraten. Die Test-EPUB baut der Test mit
``zipfile`` aus erfundenen Saetzen und erfundenen Literaturangaben.
"""

from __future__ import annotations

import io
import zipfile

from mkn_dokument import epub

_CONTAINER = (
    '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="OEBPS/inhalt.opf" media-type="application/oebps-package+xml"/>'
    "</rootfiles></container>"
)


def _doc(rumpf: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Kopf</title></head>'
        f"<body>{rumpf}</body></html>"
    )


def _epub(dokumente: list[tuple[str, str]]) -> io.BytesIO:
    """``dokumente``: (Dateiname unter OEBPS/text, Rumpf des body) in Lesereihenfolge."""
    items = "".join(
        f'<item id="d{i}" href="text/{n}" media-type="application/xhtml+xml"/>' for i, (n, _) in enumerate(dokumente)
    )
    refs = "".join(f'<itemref idref="d{i}"/>' for i in range(len(dokumente)))
    opf = (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Der erfundene Garten</dc:title></metadata>'
        f"<manifest>{items}</manifest><spine>{refs}</spine></package>"
    )
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OEBPS/inhalt.opf", opf)
        for name, rumpf in dokumente:
            z.writestr(f"OEBPS/text/{name}", _doc(rumpf))
    puffer.seek(0)
    return puffer


def _absatz(daten: io.BytesIO, marke: str) -> str:
    """Der Absatz zu ``K<k>.<a>`` nach der Zaehlung der Buch-Kette (``epub_buch``, Absaetze ``\\n\\n``)."""
    k, a = (int(x) for x in marke[1:].split("."))
    daten.seek(0)
    kapitel = epub.epub_buch(daten).kapitel
    daten.seek(0)
    return [x for x in kapitel[k - 1].text.split("\n\n") if x.strip()][a - 1]


def _paare(ergebnis: epub.Anmerkungen) -> list[tuple[str, str, str]]:
    return [(v.fundstelle, v.anmerkung, v.zeichen) for v in ergebnis.verweise]


def _indesign_fussnote(n: int, satz: str, notiz: str) -> tuple[str, str]:
    """Verweis im Absatz und Fussnote im selben Dokument wie InDesign: Link -> div mit id, Ruecklink am
    Absatzanfang der Fussnote; keine Semantik, kein ``<sup>``."""
    verweis = f'<p>{satz}<a class="_idFootnoteLink" id="fn-{n}-back" href="#fn-{n}">{n}</a> und weiter.</p>'
    fussnote = (
        f'<div class="_idFootnote" id="fn-{n}"><p><a class="_idFootnoteAnchor" href="#fn-{n}-back">{n}</a>'
        f"\t{notiz}</p></div>"
    )
    return verweis, fussnote


def test_indesign_form_mit_ruecklink_trifft_die_absatzzaehlung_der_buchkette():
    """Falsche Information: Verweis und Fussnote stehen an derselben Marke wie in der Buch-Kette - auch hinter einem
    leeren Spine-Dokument, das kein Kapitel ist."""
    v1, f1 = _indesign_fussnote(1, "Die Hecke waechst langsam", "Probe A, Gartenjahrbuch 12 (1999) 3-4.")
    v2, f2 = _indesign_fussnote(2, "Der Teich friert spaet", "Beispiel B, Wasserkunde 7 (2001) 55.")
    daten = _epub(
        [
            ("leer.xhtml", "<div></div>"),
            ("titel.xhtml", "<h1>Erfundener Titel</h1>"),
            ("k1.xhtml", f"<h2>Kapitel eins</h2><p>Ein Satz ohne Verweis.</p>{v1}<p>Zwischentext.</p>{v2}{f1}{f2}"),
        ]
    )

    ergebnis = epub.epub_verweise(daten)

    assert _paare(ergebnis) == [("K2.3", "K2.6", "1"), ("K2.5", "K2.7", "2")]
    assert [v.form for v in ergebnis.verweise] == ["ruecklink", "ruecklink"]
    for v in ergebnis.verweise:
        assert v.text == _absatz(daten, v.anmerkung)
        assert "Hecke" in _absatz(daten, v.fundstelle) or "Teich" in _absatz(daten, v.fundstelle)
    assert ergebnis.verweise[0].text.endswith("Gartenjahrbuch 12 (1999) 3-4.")
    assert ergebnis.anmerkungen == 2
    assert ergebnis.kapitel_abweichend == ()
    assert ergebnis.ohne_zuordnung == 0
    assert ergebnis.meldung.startswith("2 verlinkt")


def test_marke_am_absatzanfang_zaehlt_die_richtung_nur_einmal():
    """Falsche Information: Der Ruecklink am Anfang der Fussnote ist kein zweiter Verweis (sonst haengt die Fussnote
    an sich selbst und der Absatz an der Fussnote). Ein Link am Absatzanfang ohne erklaerte Semantik zaehlt nie."""
    v1, f1 = _indesign_fussnote(1, "Die Rose blueht", "Probe C, Bluetenkunde 3 (1987) 9.")
    daten = _epub([("k1.xhtml", f'{v1}{f1}<p><a id="oben" href="#fn-1">1</a> Absatz beginnt mit Link.</p>')])

    ergebnis = epub.epub_verweise(daten)

    assert _paare(ergebnis) == [("K1.1", "K1.2", "1")]
    assert ergebnis.anmerkungen == 1


def test_noteref_mit_aside_nach_erklaerter_semantik():
    """``epub:type="noteref"`` am Link und ``aside epub:type="footnote"`` am Ziel; das Ziel verlinkt nicht zurueck.
    Ein Link mit Kurzmarke ohne Semantik und ohne Ruecklink (Querverweis auf eine Ueberschrift) zaehlt nicht."""
    rumpf = (
        '<h2 id="abschnitt-3">3 Der Boden</h2>'
        '<p>Lehm haelt Wasser<a epub:type="noteref" href="#n1">*</a>, Sand nicht; '
        'siehe <a href="#abschnitt-3">3</a>.</p>'
        '<aside epub:type="footnote" id="n1"><p>Erfunden nach Probe D, Bodenblatt 4 (2010).</p></aside>'
        '<p>Kies<a role="doc-noteref" href="#n2">[2]</a> liegt oben.</p>'
        '<aside role="doc-footnote" id="n2"><p>Beispiel E, Steinheft (2015).</p></aside>'
    )
    daten = _epub([("k1.xhtml", rumpf)])

    ergebnis = epub.epub_verweise(daten)

    assert _paare(ergebnis) == [("K1.2", "K1.3", "*"), ("K1.4", "K1.5", "[2]")]
    assert [v.form for v in ergebnis.verweise] == ["semantik", "semantik"]
    assert ergebnis.verweise[0].text == _absatz(daten, "K1.3")


def test_endnoten_kapitel_mit_ruecklink_in_das_dokument_des_verweises():
    """Anmerkungen gesammelt in einem eigenen Dokument; jede verlinkt zurueck in das Kapitel ihres Verweises. Ein
    Ziel in einem anderen Dokument, das nicht zurueckverlinkt, ist keine Anmerkung."""
    kap1 = (
        "<h1>Eins</h1>"
        '<p>Die Linde ist alt<a id="r1" href="noten.xhtml#e1">(1)</a> und gross.</p>'
        '<p>Die Eiche auch<a id="r2" href="noten.xhtml#e2">(2)</a>.</p>'
        '<p>Mehr im <a href="anhang.xhtml#tab">2</a>. Anhang.</p>'
    )
    kap2 = '<h1>Zwei</h1><p>Die Birke<a id="r3" href="../text/noten.xhtml#e3">(3)</a> ist hell.</p>'
    noten = (
        "<h1>Anmerkungen</h1>"
        '<p id="e1"><a href="k1.xhtml#r1">1</a> Probe F, Baumbuch (1975) 10.</p>'
        '<p id="e2"><a href="k1.xhtml#r2">2</a> Probe G, Rindenheft 2 (1980) 1.</p>'
        '<p id="e3"><a href="k2.xhtml#r3">3</a> Probe H, Laubkunde (1990).</p>'
    )
    anhang = '<p id="tab">Tabelle ohne Ruecklink.</p>'
    daten = _epub([("k1.xhtml", kap1), ("k2.xhtml", kap2), ("noten.xhtml", noten), ("anhang.xhtml", anhang)])

    ergebnis = epub.epub_verweise(daten)

    assert _paare(ergebnis) == [("K1.2", "K3.2", "(1)"), ("K1.3", "K3.3", "(2)"), ("K2.2", "K3.4", "(3)")]
    assert ergebnis.verweise[2].text == _absatz(daten, "K3.4")
    assert ergebnis.anmerkungen == 3


def test_kapitel_mit_abweichender_gegenprobe_bekommt_keine_zuordnung_und_wird_gezaehlt():
    """Falsche Information: Teilen die Marken einen Absatz anders als die Buch-Kette (hier: ein ``id`` zwischen zwei
    Zeilenumbruechen), bekommt das Kapitel keine Zuordnung - gezaehlt, nie verschoben. Das andere Kapitel bleibt."""
    v1, f1 = _indesign_fussnote(1, "Der Apfel reift", "Probe I, Obstheft 1 (2000).")
    v2, f2 = _indesign_fussnote(2, "Die Birne faellt", "Probe J, Obstheft 2 (2001).")
    gestoert = f'<p>Zeile eins<br/> <span id="mitte"></span><br/>Zeile zwei</p>{v2}{f2}'
    daten = _epub([("k1.xhtml", f"{v1}{f1}"), ("k2.xhtml", gestoert)])

    ergebnis = epub.epub_verweise(daten)

    assert _paare(ergebnis) == [("K1.1", "K1.2", "1")]
    assert ergebnis.kapitel_abweichend == (2,)
    assert ergebnis.ohne_zuordnung == 1
    assert "Kapitel 2" in ergebnis.meldung
    assert "1 ohne Zuordnung" in ergebnis.meldung


def test_buch_ohne_verweise_ergibt_eine_leere_liste():
    """Ein Buch ohne verlinkte Anmerkungen ist kein Fehler: leere Liste, die Meldung sagt es."""
    daten = _epub([("k1.xhtml", "<h1>Eins</h1><p>Nur Text, Seite 12 und 13.</p><p>Noch ein Satz.</p>")])

    ergebnis = epub.epub_verweise(daten)

    assert ergebnis.verweise == []
    assert ergebnis.anmerkungen == 0
    assert ergebnis.ohne_zuordnung == 0
    assert ergebnis.meldung == "keine verlinkten Anmerkungen erkannt"
