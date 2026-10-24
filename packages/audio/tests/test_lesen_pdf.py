"""PDF lesen: Textebene, Kopf-/Fusszeilen, Seiten ohne Text."""

from __future__ import annotations

import pytest

from mkn_audio.lesen import bild, lies
from mkn_audio.lesen.text import KeinText
from mkn_audio.typen import Mp4Fehler
from muster_quellen import (
    muster_pdf_kopf_fuss,
    muster_pdf_leer,
    muster_pdf_mit_gliederung,
    muster_pdf_scan,
    muster_pdf_zwei_spalten,
)

PNG = b"\x89PNG\r\n\x1a\n"


def _absaetze(dok) -> list[str]:
    return [a for k in dok.kapitel for a in k.absaetze]


def test_pdf_kopf_fusszeilen_seitenzahlen_urls(tmp_path):
    dok = lies(muster_pdf_kopf_fuss(tmp_path / "m.pdf"), textmodell=None)

    text = "\n".join(_absaetze(dok))
    assert "Kopfzeile" not in text
    assert "https" not in text and "beispiel.example" not in text
    # Seitenzahlen: kein Absatz besteht nur aus einer Zahl.
    assert not [a for a in _absaetze(dok) if a.strip().isdigit()]
    # Absaetze bleiben: je Seite zwei, mit zusammengefuegter Silbentrennung.
    assert len(_absaetze(dok)) == 6
    assert _absaetze(dok)[0] == "Erster Absatz auf Seite 1. Er hat zwei Saetze."
    assert _absaetze(dok)[1].startswith("Zweiter Absatz mit Silbentrennung am Zeilenende")
    assert _absaetze(dok)[1].endswith("und einer Adresse im Text.")
    warnungen = "\n".join(dok.warnungen)
    assert "weggelassen: Kopf- und Fusszeilen" in warnungen
    assert "Webadressen (3)" in warnungen


def test_pdf_einzelne_seite_behaelt_ihre_kopfzeile(tmp_path):
    """Wiederkehr braucht mehrere Seiten: auf einer Seite ist eine Zeile oben kein Kopf."""
    import pymupdf

    pfad = tmp_path / "e.pdf"
    doc = pymupdf.open()
    seite = doc.new_page()
    seite.insert_text((72, 40), "Eine Ueberschrift ganz oben", fontsize=14)
    seite.insert_textbox(pymupdf.Rect(72, 100, 520, 160), "Darunter ein Absatz.", fontsize=11)
    doc.save(pfad)

    dok = lies(pfad, textmodell=None)

    assert "Eine Ueberschrift ganz oben" in _absaetze(dok)


def test_pdf_zwei_spalten_in_lesereihenfolge(tmp_path):
    dok = lies(muster_pdf_zwei_spalten(tmp_path / "s.pdf"), textmodell=None)

    assert _absaetze(dok) == [
        "Linke Spalte oben.",
        "Linke Spalte unten.",
        "Rechte Spalte oben.",
        "Rechte Spalte unten.",
    ]


def test_pdf_lesezeichen_sind_kapitel(tmp_path):
    dok = lies(muster_pdf_mit_gliederung(tmp_path / "g.pdf"), textmodell=None)

    assert [k.titel for k in dok.kapitel] == ["Eins", "Zwei"]
    assert dok.kapitel[0].absaetze == (
        "Text auf Seite 1 des Musterbuchs.",
        "Text auf Seite 2 des Musterbuchs.",
    )
    assert dok.kapitel[1].absaetze[0] == "Text auf Seite 3 des Musterbuchs."


def test_pdf_ohne_textebene_geht_ans_bildmodell(tmp_path, monkeypatch):
    aufrufe = []

    def modell(prompt, bilder):
        aufrufe.append((prompt, bilder))
        return "Gelesen vom Modell.\n\nZweiter Absatz."

    def ocr_darf_nicht_laufen(*_a, **_k):
        raise AssertionError("tesseract darf bei bis zu 20 Seiten nicht laufen")

    monkeypatch.setattr(bild, "ocr", ocr_darf_nicht_laufen)

    dok = lies(muster_pdf_scan(tmp_path / "scan.pdf", seiten=2), textmodell=modell)

    assert len(aufrufe) == 2
    prompt, bilder = aufrufe[0]
    assert len(bilder) == 1 and bilder[0][0] == "image/png" and bilder[0][1].startswith(PNG)
    assert "Lesereihenfolge" in prompt
    assert _absaetze(dok) == ["Gelesen vom Modell.", "Zweiter Absatz."] * 2
    assert any("Bildmodell" in w and "Seiten 1-2" in w for w in dok.warnungen)


def test_pdf_ueber_grenze_geht_an_tesseract(tmp_path, monkeypatch):
    gerufen = []

    def ocr(png, sprache):
        gerufen.append((png[:8], sprache))
        return f"Erkannter Text {len(gerufen)}."

    def modell(*_a):
        raise AssertionError("ab 21 Seiten liest das Bildmodell nicht")

    monkeypatch.setattr(bild, "ocr", ocr)

    dok = lies(muster_pdf_scan(tmp_path / "buch.pdf", seiten=21), textmodell=modell)

    assert len(gerufen) == 21
    assert {s for _, s in gerufen} == {"deu"}
    assert _absaetze(dok)[0] == "Erkannter Text 1."
    assert any("Texterkennung" in w for w in dok.warnungen)


def test_pdf_grenze_ist_einstellbar_und_ohne_modell_wird_erkannt(tmp_path, monkeypatch):
    monkeypatch.setattr(bild, "ocr", lambda png, sprache: f"Text in {sprache}.")

    dok = lies(
        muster_pdf_scan(tmp_path / "s.pdf", seiten=2),
        textmodell=None,
        ocr_sprache="eng",
    )

    assert _absaetze(dok) == ["Text in eng.", "Text in eng."]


def test_pdf_ohne_textebene_und_ohne_tesseract_bricht(tmp_path, monkeypatch):
    def nicht_installiert(*_a, **_k):
        raise FileNotFoundError("tesseract")

    monkeypatch.setattr(bild.subprocess, "run", nicht_installiert)

    with pytest.raises(Mp4Fehler, match="tesseract"):
        lies(muster_pdf_scan(tmp_path / "s.pdf", seiten=21), textmodell=None)


def test_pdf_leeres_dokument_bricht(tmp_path):
    with pytest.raises(KeinText):
        lies(muster_pdf_leer(tmp_path / "leer.pdf"), textmodell=None)


def test_pdf_scan_dessen_modell_nichts_liefert_bricht(tmp_path):
    with pytest.raises(KeinText):
        lies(muster_pdf_scan(tmp_path / "s.pdf"), textmodell=lambda p, b: "  ")


def test_pdf_kaputt_und_leere_datei_brechen(tmp_path):
    kaputt = tmp_path / "k.pdf"
    kaputt.write_bytes(b"%PDF-1.4 kaputt")
    with pytest.raises(Mp4Fehler, match="PDF"):
        lies(kaputt, textmodell=None)
    leer = tmp_path / "null.pdf"
    leer.write_bytes(b"")
    with pytest.raises(Mp4Fehler, match="PDF"):
        lies(leer, textmodell=None)


def test_pdf_mit_passwort_bricht(tmp_path):
    import pymupdf

    pfad = tmp_path / "geheim.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "Geheim.", fontsize=11)
    doc.save(pfad, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="eigentuemer", user_pw="nutzer")

    with pytest.raises(Mp4Fehler, match="Passwort"):
        lies(pfad, textmodell=None)


def _pdf(pfad, seiten, *, titel=None, toc=None):
    """Schreibt ein PDF aus Seiten von `(x, y, text, groesse, schrift)`-Zeilen.

    Jede Zeile steht fuer sich; zwischen Zeilen mit mehr als ~1,5 Zeilen Abstand beginnt
    MuPDF einen neuen Block -- das ist der Fall, um den es in diesen Tests geht.
    """
    import pymupdf

    doc = pymupdf.open()
    for zeilen in seiten:
        seite = doc.new_page()
        for x, y, text, groesse, schrift in zeilen:
            seite.insert_text((x, y), text, fontsize=groesse, fontname=schrift)
    if toc:
        doc.set_toc(toc)
    if titel:
        doc.set_metadata({"title": titel})
    doc.save(pfad)
    return pfad


def _zeile(y, text, *, x=72, groesse=11, schrift="helv"):
    return (x, y, text, groesse, schrift)


def test_pdf_absatz_ueber_blockgrenze_wird_zusammengefuegt(tmp_path):
    """Der Satz laeuft ueber die Blockgrenze weiter, die Fortsetzung beginnt gross."""
    pfad = _pdf(
        tmp_path / "b.pdf",
        [
            [
                _zeile(100, "Wir muessen die Ergebnisse pruefen und unsere"),
                _zeile(130, "Ziele zu ueberpruefen, bevor wir weitermachen."),
                _zeile(220, "Ein neuer Absatz mit eigenem Satz."),
            ]
        ],
    )

    dok = lies(pfad, textmodell=None)

    assert _absaetze(dok) == [
        "Wir muessen die Ergebnisse pruefen und unsere Ziele zu ueberpruefen, "
        "bevor wir weitermachen.",
        "Ein neuer Absatz mit eigenem Satz.",
    ]


def test_pdf_absatz_ueber_seitengrenze_wird_zusammengefuegt(tmp_path):
    pfad = _pdf(
        tmp_path / "s.pdf",
        [
            [_zeile(700, "Das Ergebnis haengt davon ab, ob wir unsere")],
            [_zeile(100, "Ziele rechtzeitig pruefen koennen.")],
        ],
    )

    assert _absaetze(lies(pfad, textmodell=None)) == [
        "Das Ergebnis haengt davon ab, ob wir unsere Ziele rechtzeitig pruefen koennen."
    ]


def test_pdf_einzug_beginnt_einen_neuen_absatz(tmp_path):
    """Ohne Satzzeichen am Ende, aber mit Einzug am Anfang: ein neuer Absatz."""
    pfad = _pdf(
        tmp_path / "e.pdf",
        [
            [
                _zeile(100, "Ein Absatz ohne Satzzeichen am Ende"),
                _zeile(130, "Eingerueckter Neuanfang des naechsten Absatzes.", x=90),
            ]
        ],
    )

    assert _absaetze(lies(pfad, textmodell=None)) == [
        "Ein Absatz ohne Satzzeichen am Ende",
        "Eingerueckter Neuanfang des naechsten Absatzes.",
    ]


def test_pdf_ueberschrift_wird_nicht_an_den_fliesstext_gehaengt(tmp_path):
    """Eine fette Zeile ohne Satzpunkt ist eine Ueberschrift, kein halber Satz."""
    pfad = _pdf(
        tmp_path / "u.pdf",
        [
            [
                _zeile(100, "Einleitung zum Thema", schrift="hebo"),
                _zeile(130, "Der Text beginnt ohne Einzug und endet mit einem Punkt."),
            ]
        ],
    )

    assert _absaetze(lies(pfad, textmodell=None)) == [
        "Einleitung zum Thema",
        "Der Text beginnt ohne Einzug und endet mit einem Punkt.",
    ]


def test_pdf_absatz_wird_nicht_ueber_kapitelgrenze_gefuegt(tmp_path):
    """Der Satz bleibt im Kapitel, in dem er beginnt; das neue Kapitel behaelt seinen Anfang."""
    pfad = _pdf(
        tmp_path / "k.pdf",
        [
            [_zeile(100, "Der letzte Satz des ersten Kapitels bricht ab und")],
            [_zeile(100, "ziele zu ueberpruefen, steht im zweiten.")],
        ],
        toc=[[1, "Eins", 1], [1, "Zwei", 2]],
    )

    dok = lies(pfad, textmodell=None)

    assert [k.titel for k in dok.kapitel] == ["Eins", "Zwei"]
    assert dok.kapitel[0].absaetze == ("Der letzte Satz des ersten Kapitels bricht ab und",)
    assert dok.kapitel[1].absaetze == ("ziele zu ueberpruefen, steht im zweiten.",)


def test_zwei_lesezeichen_auf_einer_seite_das_spaetere_gilt(tmp_path):
    pfad = _pdf(
        tmp_path / "z.pdf",
        [[_zeile(100, "Text auf Seite 1.")], [_zeile(100, "Text auf Seite 2.")]],
        toc=[[1, "Eins", 1], [1, "Zwei", 1], [1, "Drei", 2]],
    )

    dok = lies(pfad, textmodell=None)

    # Der Text der Seite 1 gehoert zum spaeteren Lesezeichen; das fruehere wird gemeldet.
    assert [k.titel for k in dok.kapitel] == ["Zwei", "Drei"]
    assert dok.kapitel[0].absaetze == ("Text auf Seite 1.",)
    assert any("Ueberschrift ohne Text: Eins" in w for w in dok.warnungen)
    assert not any("Zwei" in w for w in dok.warnungen)


def test_pdf_titel_aus_groesster_schrift(tmp_path):
    pfad = _pdf(
        tmp_path / "das-wendemuster-beispiel-de-12345.pdf",
        [
            [
                _zeile(80, "Das Wendemuster", groesse=24, schrift="hebo"),
                _zeile(110, "Eine erfundene Unterzeile", groesse=14),
                _zeile(200, "Der Fliesstext beginnt hier und ist deutlich kleiner."),
                _zeile(230, "Er geht weiter bis zum Ende des Absatzes."),
            ]
        ],
    )

    dok = lies(pfad, textmodell=None)

    assert dok.titel == "Das Wendemuster"
    assert dok.kapitel[0].titel == "Das Wendemuster"


def test_pdf_titel_metadaten_gehen_vor_der_schrift(tmp_path):
    pfad = _pdf(
        tmp_path / "x.pdf",
        [[_zeile(80, "Grosse Zeile", groesse=24), _zeile(200, "Fliesstext, der klein ist.")]],
        titel="Der Metadaten-Titel",
    )

    assert lies(pfad, textmodell=None).titel == "Der Metadaten-Titel"


@pytest.mark.parametrize(
    ("dateiname", "seite", "erwartet"),
    [
        # Alles gleich gross: die erste Zeile ist kein Titel, es bleibt der Dateiname.
        (
            "das-wendemuster-beispiel-de-12345.pdf",
            [_zeile(100, "Erster Satz."), _zeile(130, "Zweiter Satz.")],
            "das wendemuster beispiel de",
        ),
        # Mehr als zwei Zeilen in der groessten Schrift: ein Zitat, kein Titel.
        (
            "mein_buch_2026.pdf",
            [
                _zeile(80, "Zeile eins", groesse=24),
                _zeile(120, "Zeile zwei", groesse=24),
                _zeile(160, "Zeile drei", groesse=24),
                _zeile(300, "Fliesstext, der klein ist."),
            ],
            "mein buch",
        ),
        # Kurze Zahlen gehoeren zum Titel.
        ("Kapitel-12.pdf", [_zeile(100, "Ein Satz.")], "Kapitel 12"),
        # Nur eine Kennung: bleibt, wie sie ist.
        ("44179.pdf", [_zeile(100, "Ein Satz.")], "44179"),
    ],
)
def test_pdf_titel_aus_dem_dateinamen(tmp_path, dateiname, seite, erwartet):
    dok = lies(_pdf(tmp_path / dateiname, [seite]), textmodell=None)

    assert dok.titel == erwartet


def test_satz_der_auf_funktionswort_oder_komma_endet_geht_ueber_spalten_weiter():
    # Probe Buchzusammenfassung 24.10.: "... vorüberziehen wie" | "Wolken." -- ein eigenes Stueck
    # "Wolken.", an dem die Stimme scheiterte. Auf "wie" oder ein Komma endet keine Ueberschrift.
    from mkn_audio.lesen import pdf as pdf_modul

    def absatz(text, spalte):
        block = pdf_modul._Block(0, 0, 0, 100, 10, text, 0, spalte, 10.0, False)
        return pdf_modul._Absatz(0, text, block)

    alt = absatz("Gefühle ziehen vorüber wie", "links")
    assert pdf_modul._setzt_fort(alt, absatz("Wolken.", "rechts"))
    assert pdf_modul._setzt_fort(
        absatz("Erst kurz, dann lang,", "links"), absatz("Danach.", "rechts")
    )
    # Eine Ueberschrift ohne Satzzeichen bleibt eine Ueberschrift.
    assert not pdf_modul._setzt_fort(
        absatz("Geistige Flexibilität", "links"), absatz("Wer sie hat.", "rechts")
    )
