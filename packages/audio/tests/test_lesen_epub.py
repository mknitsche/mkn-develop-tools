"""EPUB lesen: Lesefolge, Beiwerk, und was eine fremde Archivdatei nicht darf."""

from __future__ import annotations

import zipfile

import pytest

from mkn_audio.lesen import epub as epub_modul
from mkn_audio.lesen import lies
from mkn_audio.lesen.text import KeinText
from mkn_audio.typen import Mp4Fehler
from muster_quellen import (
    COVER_BYTES,
    epub_mit_kapiteln,
    epub_mit_verzeichnis,
    epub_schreiben,
    muster_epub,
    opf,
    xhtml,
)


def _alles(dok) -> str:
    return "\n".join(a for k in dok.kapitel for a in k.absaetze)


def test_epub_reihenfolge_und_beiwerk(tmp_path):
    dok = lies(muster_epub(tmp_path / "m.epub"), textmodell=None)

    # Lesefolge des Spine, nicht Reihenfolge des Manifests.
    assert [k.titel for k in dok.kapitel] == ["Erstes Kapitel", "Zweites Kapitel"]
    assert dok.kapitel[0].absaetze == (
        "Das ist der erste Absatz.",
        "Zweiter Absatz mit Betonung, ganz normal.",
    )
    # h3 ist Zwischentitel: wird gelesen, ist aber kein neues Kapitel.
    assert dok.kapitel[1].absaetze == (
        "Hier beginnt das zweite Kapitel.",
        "Eine Zwischenueberschrift",
        "Und es geht weiter.",
    )

    text = _alles(dok)
    for beiwerk in ("Alle Rechte", "Notiz eins", "Fussnote", "Inhaltsverzeichnis"):
        assert beiwerk not in text

    warnungen = "\n".join(dok.warnungen)
    assert "weggelassen: Navigation" in warnungen
    assert "weggelassen: Alle Rechte" in warnungen  # per epub:type erkannt
    assert "weggelassen: Inhaltsverzeichnis" in warnungen  # per Ueberschrift erkannt
    assert "weggelassen: Anmerkungen" in warnungen
    assert "weggelassen: Fussnoten (1)" in warnungen

    assert dok.titel == "Das Musterbuch"
    assert dok.autor == "Erika Muster"
    assert dok.sprache == "de"
    assert dok.cover == COVER_BYTES


def test_epub_landmarks_der_nav_kennzeichnen_beiwerk(tmp_path):
    """Eine Seite ohne Typ und ohne sprechende Ueberschrift: nur die Landmarks verraten sie."""
    seiten = {
        "kap1.xhtml": xhtml("<h1>Anfang</h1><p>Text des Anfangs.</p>"),
        "weiteres.xhtml": xhtml("<h1>Zum Buch</h1><p>Verlagsangaben ohne Typ.</p>"),
    }
    items = [
        ("kap1", "kap1.xhtml", "application/xhtml+xml", ""),
        ("w", "weiteres.xhtml", "application/xhtml+xml", ""),
        ("nav", "nav.xhtml", "application/xhtml+xml", "nav"),
    ]
    nav = xhtml(
        '<nav epub:type="landmarks"><ol><li>'
        '<a epub:type="colophon" href="weiteres.xhtml">x</a></li></ol></nav>'
    )
    inhalt = opf(items=items, spine=["kap1", "w"])
    epub_schreiben(tmp_path / "l.epub", {"content.opf": inhalt, "nav.xhtml": nav, **seiten})

    dok = lies(tmp_path / "l.epub", textmodell=None)

    assert [k.titel for k in dok.kapitel] == ["Anfang"]
    assert any(w.startswith("weggelassen: Zum Buch") for w in dok.warnungen)


def test_epub_guide_des_alten_formats_kennzeichnet_beiwerk(tmp_path):
    seiten = {
        "kap1.xhtml": xhtml("<h1>Anfang</h1><p>Text des Anfangs.</p>"),
        "weiteres.xhtml": xhtml("<h1>Zum Buch</h1><p>Verlagsangaben ohne Typ.</p>"),
    }
    items = [(n.split(".")[0], n, "application/xhtml+xml", "") for n in seiten]
    guide = '<guide><reference type="copyright-page" href="weiteres.xhtml"/></guide>'
    inhalt = opf(items=items, spine=["kap1", "weiteres"], guide=guide)
    epub_schreiben(tmp_path / "g.epub", {"content.opf": inhalt, **seiten})

    dok = lies(tmp_path / "g.epub", textmodell=None)

    assert [k.titel for k in dok.kapitel] == ["Anfang"]


def test_epub_text_vor_der_ersten_ueberschrift_und_ueberschrift_ohne_text(tmp_path):
    epub_mit_kapiteln(
        tmp_path / "v.epub",
        {
            "a.xhtml": xhtml("<p>Ein Vorwort ohne Ueberschrift.</p>"),
            "b.xhtml": xhtml("<h1>Teil I</h1>"),
            "c.xhtml": xhtml("<h2>Kapitel</h2><p>Inhalt.</p>"),
        },
    )

    dok = lies(tmp_path / "v.epub", textmodell=None)

    # Ohne Ueberschrift im Buch traegt das Kapitel den Dateinamen.
    assert [k.titel for k in dok.kapitel] == ["a", "Kapitel"]
    assert dok.kapitel[0].absaetze == ("Ein Vorwort ohne Ueberschrift.",)
    assert "weggelassen: Ueberschrift ohne Text: Teil I" in dok.warnungen


def test_epub_tabelle_wird_zeilenweise_gelesen(tmp_path):
    epub_mit_kapiteln(
        tmp_path / "t.epub",
        {
            "a.xhtml": xhtml(
                "<h1>Zahlen</h1><table><tr><th>Jahr</th><th>Wert</th></tr>"
                "<tr><td>zwei</td><td>drei</td></tr></table>"
            )
        },
    )

    dok = lies(tmp_path / "t.epub", textmodell=None)

    assert dok.kapitel[0].absaetze == ("Jahr, Wert", "zwei, drei")
    assert any("Tabelle" in w for w in dok.warnungen)


def test_epub_url_wird_weggelassen_und_gemeldet(tmp_path):
    epub_mit_kapiteln(
        tmp_path / "u.epub",
        {"a.xhtml": xhtml("<h1>K</h1><p>Siehe https://beispiel.example/x/y, dann weiter.</p>")},
    )

    dok = lies(tmp_path / "u.epub", textmodell=None)

    assert dok.kapitel[0].absaetze == ("Siehe, dann weiter.",)
    assert "https" not in _alles(dok)
    assert any("Webadressen (1)" in w for w in dok.warnungen)


def test_epub_xml_ohne_externe_entitaeten(tmp_path):
    """Im OPF bricht die Datei laut; in einem Kapitel wird nichts aufgeloest."""
    entitaet = '<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]>'

    seiten = {"a.xhtml": xhtml("<h1>K</h1><p>Text.</p>")}
    items = [("a", "a.xhtml", "application/xhtml+xml", "")]
    boese_opf = opf(items=items, spine=["a"], titel="&x;", kopf=entitaet)
    epub_schreiben(tmp_path / "opf.epub", {"content.opf": boese_opf, **seiten})
    with pytest.raises(Mp4Fehler):
        lies(tmp_path / "opf.epub", textmodell=None)

    # Auch eine harmlose, selbst deklarierte Entitaet wird nicht aufgeloest: Entitaeten, die
    # sich gegenseitig vervielfachen, sind der Angriff, und er faengt genauso an.
    intern = '<!DOCTYPE x [<!ENTITY x "doppelt">]>'
    eigene_opf = opf(items=items, spine=["a"], titel="&x;", kopf=intern)
    epub_schreiben(tmp_path / "intern.epub", {"content.opf": eigene_opf, **seiten})
    with pytest.raises(Mp4Fehler):
        lies(tmp_path / "intern.epub", textmodell=None)

    kapitel = xhtml("<h1>K</h1><p>Vorher &x; nachher.</p>").replace("<html", f"{entitaet}<html", 1)
    epub_mit_kapiteln(tmp_path / "kap.epub", {"a.xhtml": kapitel})
    dok = lies(tmp_path / "kap.epub", textmodell=None)
    assert "root:" not in _alles(dok)


def test_epub_zipbombe(tmp_path, monkeypatch):
    """Zu viele Eintraege bricht; zu viel entpackte Groesse bricht."""
    viele = tmp_path / "viele.epub"
    with zipfile.ZipFile(viele, "w") as zf:
        for i in range(2001):
            zf.writestr(f"x/{i}.txt", "a")
    with pytest.raises(Mp4Fehler, match="Eintraege"):
        lies(viele, textmodell=None)

    gross = tmp_path / "gross.epub"
    epub_mit_kapiteln(gross, {"a.xhtml": xhtml("<h1>K</h1><p>" + "wort " * 400 + "</p>")})
    assert lies(gross, textmodell=None).kapitel  # mit der echten Grenze in Ordnung
    monkeypatch.setattr(epub_modul, "MAX_ENTPACKT", 1000)
    with pytest.raises(Mp4Fehler, match="entpackt"):
        lies(gross, textmodell=None)


def test_epub_kaputtes_archiv_bricht(tmp_path):
    kaputt = tmp_path / "k.epub"
    kaputt.write_bytes(b"das ist kein zip")
    with pytest.raises(Mp4Fehler, match="EPUB"):
        lies(kaputt, textmodell=None)


def test_epub_ohne_lesbaren_text_bricht(tmp_path):
    epub_mit_kapiteln(tmp_path / "leer.epub", {"a.xhtml": xhtml("<h1>Nur Titel</h1>")})
    with pytest.raises(KeinText):
        lies(tmp_path / "leer.epub", textmodell=None)


def test_epub_fehlende_datei_im_archiv_wird_gemeldet(tmp_path):
    seiten = {"a.xhtml": xhtml("<h1>K</h1><p>Text.</p>")}
    items = [
        ("a", "a.xhtml", "application/xhtml+xml", ""),
        ("b", "fehlt.xhtml", "application/xhtml+xml", ""),
    ]
    epub_schreiben(
        tmp_path / "f.epub", {"content.opf": opf(items=items, spine=["a", "b"]), **seiten}
    )

    dok = lies(tmp_path / "f.epub", textmodell=None)

    assert "Datei fehlt im Archiv: fehlt.xhtml" in dok.warnungen


def test_epub_typ_im_text_trennt_beiwerk_mitten_im_kapitel(tmp_path):
    epub_mit_kapiteln(
        tmp_path / "w.epub",
        {
            "a.xhtml": xhtml(
                '<h1>Anfang</h1><p>Vorher.</p><section epub:type="dedication">'
                "<p>Fuer alle, die lesen.</p></section>"
                '<section role="doc-endnotes"><h2>Quellenangaben</h2><p>Eine Quelle.</p></section>'
                "<p>Nachher.</p>"
            )
        },
    )

    dok = lies(tmp_path / "w.epub", textmodell=None)

    assert [k.titel for k in dok.kapitel] == ["Anfang"]
    assert dok.kapitel[0].absaetze == ("Vorher.", "Nachher.")
    assert "weggelassen: Widmung (a.xhtml)" in dok.warnungen
    assert "weggelassen: Quellenangaben (a.xhtml)" in dok.warnungen


def test_epub_ohne_container_bricht_mit_mp4fehler(tmp_path):
    ohne = tmp_path / "o.epub"
    with zipfile.ZipFile(ohne, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
    with pytest.raises(Mp4Fehler, match=r"container\.xml"):
        lies(ohne, textmodell=None)


# ---- Kapitel aus dem Inhaltsverzeichnis --------------------------------------------
# Verlage setzen Kapitelueberschriften oft als `<p class="...">`, nicht als `<h1>`: dann
# kennt nur das Inhaltsverzeichnis die Kapitel.


def _kap(kennung: str, titel: str, *absaetze: str, klasse: str = "ch-title1") -> str:
    """Eine Kapitelseite: Umschlag-`div` mit Anker, Titel als `<p>`, dann Text."""
    text = "".join(f"<p>{a}</p>" for a in absaetze)
    return xhtml(
        f'<div id="{kennung}"><p class="{klasse}" id="t-{kennung}">{titel}</p>{text}</div>'
    )


_SEITEN = {
    "deckel.xhtml": xhtml("<p>Ein Bild und sonst nichts.</p>"),
    "inhalt.xhtml": _kap("inh", "Inhaltsangabe", "Der Anfang 5", "Das Ende 9"),
    "k1.xhtml": _kap("k1", "Der Anfang", "Erster Text.", "Zweiter Text."),
    "k2.xhtml": _kap("k2", "Das Ende", "Letzter Text."),
}
_VERZ = [
    ("Cover", "deckel.xhtml", []),
    ("Inhaltsangabe", "inhalt.xhtml#inh", []),
    ("Der Anfang", "k1.xhtml#k1", []),
    ("Das Ende", "k2.xhtml#k2", []),
]


def test_kapitel_aus_ncx_bei_p_ueberschriften(tmp_path):
    epub_mit_verzeichnis(tmp_path / "n.epub", _SEITEN, ncx_eintraege=_VERZ)

    dok = lies(tmp_path / "n.epub", textmodell=None)

    assert [k.titel for k in dok.kapitel] == ["Der Anfang", "Das Ende"]
    assert dok.kapitel[0].absaetze == ("Erster Text.", "Zweiter Text.")
    assert dok.kapitel[1].absaetze == ("Letzter Text.",)


def test_gedrucktes_inhaltsverzeichnis_ist_beiwerk(tmp_path):
    epub_mit_verzeichnis(tmp_path / "i.epub", _SEITEN, ncx_eintraege=_VERZ)

    dok = lies(tmp_path / "i.epub", textmodell=None)

    assert "Der Anfang 5" not in _alles(dok)
    assert "Ein Bild und sonst nichts." not in _alles(dok)
    assert "weggelassen: Inhaltsangabe (Beiwerk laut Ueberschrift)" in dok.warnungen
    assert "weggelassen: Cover (Beiwerk laut Ueberschrift)" in dok.warnungen


def test_kapitel_aus_nav_vor_ncx(tmp_path):
    nav = [("Nav Eins", "k1.xhtml#k1", []), ("Nav Zwei", "k2.xhtml#k2", [])]
    ncx_alt = [("Ncx Eins", "k1.xhtml#k1", []), ("Ncx Zwei", "k2.xhtml#k2", [])]
    epub_mit_verzeichnis(
        tmp_path / "v.epub",
        {n: s for n, s in _SEITEN.items() if n.startswith("k")},
        ncx_eintraege=ncx_alt,
        nav_eintraege=nav,
    )

    dok = lies(tmp_path / "v.epub", textmodell=None)

    assert [k.titel for k in dok.kapitel] == ["Nav Eins", "Nav Zwei"]


def test_ncx_wenn_die_nav_kein_verzeichnis_hat(tmp_path):
    """Eine nav nur mit Landmarks ist kein Inhaltsverzeichnis: dann gilt das NCX."""
    seiten = {n: s for n, s in _SEITEN.items() if n.startswith("k")}
    epub_mit_verzeichnis(
        tmp_path / "w.epub",
        seiten,
        ncx_eintraege=[("Ncx Eins", "k1.xhtml#k1", []), ("Ncx Zwei", "k2.xhtml#k2", [])],
        nav_eintraege=[],
    )

    dok = lies(tmp_path / "w.epub", textmodell=None)

    assert [k.titel for k in dok.kapitel] == ["Ncx Eins", "Ncx Zwei"]


def test_zwei_kapitel_in_einer_datei_am_anker(tmp_path):
    beide = xhtml(
        '<p class="ch-title1" id="a">Teil Eins</p><p>Text eins.</p>'
        '<p class="ch-title1" id="b">Teil Zwei</p><p>Text zwei.</p><p>Noch mehr.</p>'
    )
    epub_mit_verzeichnis(
        tmp_path / "z.epub",
        {"beide.xhtml": beide},
        ncx_eintraege=[("Eins", "beide.xhtml#a", []), ("Zwei", "beide.xhtml#b", [])],
    )

    dok = lies(tmp_path / "z.epub", textmodell=None)

    assert [k.titel for k in dok.kapitel] == ["Eins", "Zwei"]
    assert dok.kapitel[0].absaetze == ("Text eins.",)
    assert dok.kapitel[1].absaetze == ("Text zwei.", "Noch mehr.")


def test_verschachtelte_eintraege_kein_eigenes_kapitel(tmp_path):
    seite = _kap("k1", "Der Anfang", "Erster Text.").replace(
        "</div>", '<p class="ch-title2" id="u1">Unterpunkt</p><p>Text darunter.</p></div>'
    )
    verz = [("Der Anfang", "k1.xhtml#k1", [("Unterpunkt", "k1.xhtml#u1", [])])]
    epub_mit_verzeichnis(tmp_path / "s.epub", {"k1.xhtml": seite}, ncx_eintraege=verz)
    epub_mit_verzeichnis(tmp_path / "s3.epub", {"k1.xhtml": seite}, nav_eintraege=verz)

    for name in ("s.epub", "s3.epub"):
        dok = lies(tmp_path / name, textmodell=None)

        assert [k.titel for k in dok.kapitel] == ["Der Anfang"]
        # Die Unterueberschrift bleibt im Text und wird mitgesprochen.
        assert dok.kapitel[0].absaetze == ("Erster Text.", "Unterpunkt", "Text darunter.")


def test_titel_nicht_doppelt(tmp_path):
    """Das Ueberschriften-Element ist der Kapiteltitel, nicht zusaetzlich erster Absatz."""
    epub_mit_verzeichnis(
        tmp_path / "d.epub",
        {
            "a.xhtml": xhtml('<h1 id="a">Mit Ueberschrift</h1><p>Text a.</p>'),
            "b.xhtml": _kap("b", "Mit Klasse", "Text b."),
        },
        ncx_eintraege=[("Mit Ueberschrift", "a.xhtml", []), ("Mit Klasse", "b.xhtml#b", [])],
    )

    dok = lies(tmp_path / "d.epub", textmodell=None)

    assert [k.absaetze for k in dok.kapitel] == [("Text a.",), ("Text b.",)]


def test_text_vor_dem_ersten_eintrag_geht_ins_naechste_kapitel(tmp_path):
    seite = xhtml(
        '<p>Ein Satz vor dem Anker.</p><p class="ch-title1" id="a">Erstes</p><p>Inhalt.</p>'
    )
    epub_mit_verzeichnis(
        tmp_path / "vor.epub", {"a.xhtml": seite}, ncx_eintraege=[("Erstes", "a.xhtml#a", [])]
    )

    dok = lies(tmp_path / "vor.epub", textmodell=None)

    assert [k.titel for k in dok.kapitel] == ["Erstes"]
    assert dok.kapitel[0].absaetze == ("Ein Satz vor dem Anker.", "Inhalt.")


def test_datei_ausserhalb_des_verzeichnisses_bleibt_eigenes_kapitel(tmp_path):
    seiten = {
        "k1.xhtml": _kap("k1", "Der Anfang", "Erster Text."),
        "anhang.xhtml": xhtml("<h1>Nachwort</h1><p>Zum Schluss.</p>"),
    }
    epub_mit_verzeichnis(
        tmp_path / "o.epub", seiten, ncx_eintraege=[("Der Anfang", "k1.xhtml#k1", [])]
    )

    dok = lies(tmp_path / "o.epub", textmodell=None)

    assert [k.titel for k in dok.kapitel] == ["Der Anfang", "Nachwort"]
    assert dok.kapitel[0].absaetze == ("Erster Text.",)


def test_datei_ohne_titel_ausserhalb_des_verzeichnisses_setzt_das_kapitel_fort(tmp_path):
    seiten = {
        "k1.xhtml": _kap("k1", "Der Anfang", "Erster Text."),
        "weiter.xhtml": xhtml("<p>Der Text geht in der naechsten Datei weiter.</p>"),
        "k2.xhtml": _kap("k2", "Das Ende", "Letzter Text."),
    }
    verz = [("Der Anfang", "k1.xhtml#k1", []), ("Das Ende", "k2.xhtml#k2", [])]
    epub_mit_verzeichnis(tmp_path / "fort.epub", seiten, ncx_eintraege=verz)

    dok = lies(tmp_path / "fort.epub", textmodell=None)

    assert [k.titel for k in dok.kapitel] == ["Der Anfang", "Das Ende"]
    assert dok.kapitel[0].absaetze == (
        "Erster Text.",
        "Der Text geht in der naechsten Datei weiter.",
    )


def test_verzeichnis_mit_fehlendem_anker_oder_ziel_wird_gemeldet(tmp_path):
    verz = [
        ("Der Anfang", "k1.xhtml#k1", []),
        ("Ohne Anker", "k1.xhtml#gibtsnicht", []),
        ("Ohne Datei", "weg.xhtml", []),
    ]
    epub_mit_verzeichnis(
        tmp_path / "f.epub", {"k1.xhtml": _kap("k1", "Der Anfang", "Text.")}, ncx_eintraege=verz
    )

    dok = lies(tmp_path / "f.epub", textmodell=None)

    assert [k.titel for k in dok.kapitel] == ["Der Anfang"]
    assert any("Anker fehlt" in w and "Ohne Anker" in w for w in dok.warnungen)
    assert any("nicht in der Lesefolge" in w and "Ohne Datei" in w for w in dok.warnungen)


def test_unbrauchbares_verzeichnis_faellt_auf_dateien_zurueck(tmp_path):
    epub_mit_verzeichnis(
        tmp_path / "u.epub",
        {"k1.xhtml": _kap("k1", "Der Anfang", "Text.")},
        ncx_eintraege=[("Nirgends", "weg.xhtml", [])],
    )

    dok = lies(tmp_path / "u.epub", textmodell=None)

    assert [k.titel for k in dok.kapitel] == ["Der Anfang"]


def test_ohne_toc_je_datei_ein_kapitel_mit_klassen_titel(tmp_path):
    epub_mit_kapiteln(
        tmp_path / "k.epub",
        {
            "01_Eins.xhtml": _kap("e", "Aus der Klasse", "Text eins."),
            "02_Zwei.xhtml": xhtml(
                '<h2>Aus der Ueberschrift</h2><p class="chapter">Text zwei.</p>'
            ),
            "03_Drei.xhtml": xhtml("<p>Text ohne jede Ueberschrift.</p>"),
            "04_Vier.xhtml": xhtml(
                '<p class="titel-seite">Vorn</p><p>Text.</p><h1>Mitten</h1><p>Weiter.</p>'
            ),
        },
    )

    dok = lies(tmp_path / "k.epub", textmodell=None)

    assert [k.titel for k in dok.kapitel] == [
        "Aus der Klasse",
        "Aus der Ueberschrift",
        "03_Drei",
        "Vorn",
        "Mitten",
    ]
    assert dok.kapitel[0].absaetze == ("Text eins.",)  # Titel nicht doppelt
    assert dok.kapitel[3].absaetze == ("Text.",)
    assert dok.kapitel[4].absaetze == ("Weiter.",)


@pytest.mark.parametrize(
    "titel",
    ["Anmerkungen, Quellen und Weiterführendes", "Quellen und Literatur", "Literatur & Links"],
)
def test_anhang_mit_zusammengesetztem_titel_ist_beiwerk(tmp_path, titel):
    # Ein Anhang mit Fundstellen waere vorgelesen Tausende Woerter Seitenzahlen.
    epub_mit_kapiteln(
        tmp_path / "a.epub",
        {
            "a.xhtml": xhtml("<h1>Erstes Kapitel</h1><p>Inhalt des Kapitels.</p>"),
            "b.xhtml": xhtml(f"<h1>{titel}</h1><p>Seite 12, Fundstelle.</p>"),
        },
    )
    dok = lies(tmp_path / "a.epub", textmodell=None)
    assert [k.titel for k in dok.kapitel] == ["Erstes Kapitel"]
    assert any(titel in w for w in dok.warnungen)


def test_kapitel_das_mit_quellen_beginnt_bleibt(tmp_path):
    # Nur der Anhang faellt weg, nicht ein Kapitel, dessen Titel zufaellig so anfaengt.
    epub_mit_kapiteln(
        tmp_path / "b.epub",
        {"a.xhtml": xhtml("<h1>Quellenkunde im Mittelalter</h1><p>Inhalt.</p>")},
    )
    assert [k.titel for k in lies(tmp_path / "b.epub", textmodell=None).kapitel] == [
        "Quellenkunde im Mittelalter"
    ]


def test_epub_fussnoten_verweise_fallen_weg_hochzahlen_bleiben(tmp_path):
    # Kapitel 1 des Hoerbuchs (24.10.): <sup>4</sup> wurde zu "Islam4", ein <sup>1</sup> nach
    # einem Fragezeichen zum eigenen Stueck "Eins.".
    epub_mit_kapiteln(
        tmp_path / "f.epub",
        {
            "a.xhtml": xhtml(
                "<h1>Glaube</h1><p>Das Judentum und der Islam<sup>4</sup> zeigen es."
                " Wer weiß das?<sup>1</sup> Die Fläche misst 3 m<sup>2</sup>.</p>"
            )
        },
    )
    dok = lies(tmp_path / "f.epub", textmodell=None)
    assert dok.kapitel[0].absaetze == (
        "Das Judentum und der Islam zeigen es. Wer weiß das? Die Fläche misst 3 m2.",
    )


def test_epub_noteref_faellt_samt_hochstellung_weg_und_wird_gezaehlt(tmp_path):
    epub_mit_kapiteln(
        tmp_path / "n.epub",
        {
            "a.xhtml": xhtml(
                '<h1>Glaube</h1><p>Erster Satz<sup><a epub:type="noteref" href="#n1">a</a></sup>.'
                ' Zweiter Satz<a role="doc-noteref" href="#n2">[2]</a>.</p>'
            )
        },
    )
    dok = lies(tmp_path / "n.epub", textmodell=None)
    assert dok.kapitel[0].absaetze == ("Erster Satz. Zweiter Satz.",)
    assert "weggelassen: Fußnoten-Verweise (2)" in dok.warnungen
