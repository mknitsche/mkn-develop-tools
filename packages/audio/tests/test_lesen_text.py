"""Text und Markdown lesen, und die Dispatch-Regeln von `lies`."""

from __future__ import annotations

import unicodedata

import pytest

from mkn_audio.lesen import lies
from mkn_audio.lesen.text import KeinText
from mkn_audio.typen import Mp4Fehler


def test_markdown_ueberschriften_sind_kapitel(tmp_path):
    quelle = tmp_path / "notiz.md"
    quelle.write_text(
        "# Erstes\n\nEin **fetter** und *schiefer* Satz mit [Link](https://beispiel.example/a).\n"
        "Zeile zwei desselben Absatzes.\n\n"
        "## Zweites\n\n- Punkt eins\n- Punkt zwei mit `code`\n\n"
        "> Zitat im Block.\n\n![Bild](bild.png)\n",
        encoding="utf-8",
    )

    dok = lies(quelle, textmodell=None)

    assert [k.titel for k in dok.kapitel] == ["Erstes", "Zweites"]
    assert dok.kapitel[0].absaetze == (
        "Ein fetter und schiefer Satz mit Link. Zeile zwei desselben Absatzes.",
    )
    assert dok.kapitel[1].absaetze == ("Punkt eins", "Punkt zwei mit code", "Zitat im Block.")
    assert dok.titel == "Erstes"
    assert dok.sprache == "de"


def test_markdown_vorspann_codebloecke_und_tabellen(tmp_path):
    quelle = tmp_path / "n.md"
    quelle.write_text(
        "---\ntitle: Der Titel\n---\n\nEin Vorspann.\n\n```\nprint('x')\n```\n\n"
        "| a | b |\n|---|---|\n| eins | zwei |\n\n### Unterpunkt\n\nText.\n",
        encoding="utf-8",
    )

    dok = lies(quelle, textmodell=None)

    assert dok.titel == "Der Titel"
    assert [k.titel for k in dok.kapitel] == ["Der Titel"]
    assert dok.kapitel[0].absaetze == ("Ein Vorspann.", "a, b", "eins, zwei", "Unterpunkt", "Text.")
    warnungen = "\n".join(dok.warnungen)
    assert "Codebloecke (1)" in warnungen
    assert "Tabelle" in warnungen
    assert "print" not in "".join(dok.kapitel[0].absaetze)


def test_markdown_h3_ist_ueberschrift(tmp_path):
    """`###` und tiefer: eigener Absatz mit Art `ueberschrift`, auch nach `lies`."""
    quelle = tmp_path / "notiz.md"
    quelle.write_text(
        "# Erstes\n\nEin Absatz vorweg.\n\n### Zwischentitel\n\nText danach.\n"
        "\n#### Ausblick\n\nLetzter Text.\n",
        encoding="utf-8",
    )

    dok = lies(quelle, textmodell=None)

    (kapitel,) = dok.kapitel
    assert kapitel.absaetze == (
        "Ein Absatz vorweg.",
        "Zwischentitel",
        "Text danach.",
        "Ausblick",
        "Letzter Text.",
    )
    assert kapitel.arten == ("wortlaut", "ueberschrift", "wortlaut", "ueberschrift", "wortlaut")


def test_text_absaetze_trennstriche_und_nfc(tmp_path):
    quelle = tmp_path / "U\u0308bung.txt"  # NFD-Umlaut im Dateinamen
    quelle.write_text(
        "Erste Zeile mit Silben-\ntrennung hier.\n\nZweiter Absatz\nueber zwei Zeilen.\n\n\n"
        "Ost-\nWestfalen und vor-\nund nachher.\n",
        encoding="utf-8",
    )

    dok = lies(quelle, textmodell=None)

    assert dok.titel == "\u00dcbung"  # NFC, nicht NFD
    assert len(dok.kapitel) == 1
    assert dok.kapitel[0].titel == dok.titel
    assert dok.kapitel[0].absaetze == (
        "Erste Zeile mit Silbentrennung hier.",
        "Zweiter Absatz ueber zwei Zeilen.",
        "Ost-Westfalen und vor- und nachher.",
    )


def test_text_windows_kodierung_wird_gemeldet(tmp_path):
    quelle = tmp_path / "alt.txt"
    quelle.write_bytes("Grüße aus der Ferne.".encode("cp1252"))

    dok = lies(quelle, textmodell=None)

    assert dok.kapitel[0].absaetze == ("Grüße aus der Ferne.",)
    assert any("Windows-1252" in w for w in dok.warnungen)


def test_text_ohne_buchstaben_ist_kein_text(tmp_path):
    quelle = tmp_path / "leer.txt"
    quelle.write_text("\n  \n* * *\n", encoding="utf-8")
    with pytest.raises(KeinText):
        lies(quelle, textmodell=None)


def test_leere_quelle_bricht(tmp_path):
    quelle = tmp_path / "leer.txt"
    quelle.write_bytes(b"")
    with pytest.raises(KeinText):
        lies(quelle, textmodell=None)


def test_unbekannte_endung_und_fehlende_datei(tmp_path):
    fremd = tmp_path / "x.docx"
    fremd.write_bytes(b"x")
    with pytest.raises(Mp4Fehler, match=r"\.docx"):
        lies(fremd, textmodell=None)
    with pytest.raises(Mp4Fehler, match="nicht gefunden"):
        lies(tmp_path / "gibtsnicht.txt", textmodell=None)


def test_private_zeichen_werden_entfernt(tmp_path):
    """Symbolschriften (Private Use) und unsichtbare Formatzeichen sind nicht vorzulesen.

    Sie stehen in PDF und Programmheften als Symbol vor Rubriken und Titeln und verfaelschen
    jeden Vergleich ("BUCH Titel" ist dann nicht "Titel"); `lies` raeumt sie aus Titeln und
    Absaetzen, ohne Woerter zusammenzuschieben.
    """
    quelle = tmp_path / "n.md"
    quelle.write_text(
        "# BUCH Der Titel\n\nEin Absatz‎ mit ‪Marken‬ darin.\n\n## Teil Zwei\n\nZweiter­Absatz.\n",
        encoding="utf-8",
    )

    dok = lies(quelle, textmodell=None)

    texte = [dok.titel, dok.autor or ""]
    for k in dok.kapitel:
        texte += [k.titel, *k.absaetze]
    alle = "".join(texte)
    assert not [z for z in alle if unicodedata.category(z) in ("Co", "Cf")]
    assert dok.titel == "BUCH Der Titel"
    assert dok.kapitel[0].absaetze == ("Ein Absatz mit Marken darin.",)
    assert dok.kapitel[1].titel == "Teil Zwei"
    assert dok.kapitel[1].absaetze == ("ZweiterAbsatz.",)  # weicher Trennstrich wie bisher


# ---- Beiwerk: Quellenangaben, Literaturabschnitte, Quellvermerke -------------------------


def _lies_absaetze(tmp_path, *absaetze: str):
    quelle = tmp_path / "beiwerk.txt"
    quelle.write_text("\n\n".join(absaetze) + "\n", encoding="utf-8")
    return lies(quelle, textmodell=None)


def test_zitat_syntax_entfaellt(tmp_path):
    """Echte Zitat-Syntax in Klammern faellt weg und wird gezaehlt, nie still."""
    dok = _lies_absaetze(
        tmp_path,
        "Das Gedächtnis lernt ständig (Mustermann 2004).",
        "Gewohnheiten entstehen durch Wiederholung (vgl. Beispiel und Muster 2001, 2002) "
        "und bleiben lange.",
        "Mehrere Arbeiten stützen das (Übersicht in Probst 2006; Mustermann 2008, S. 12 f.).",
        "Neuere Befunde kommen hinzu (Lindner et al. 2019a).",
    )

    (kapitel,) = dok.kapitel
    assert kapitel.absaetze == (
        "Das Gedächtnis lernt ständig.",
        "Gewohnheiten entstehen durch Wiederholung und bleiben lange.",
        "Mehrere Arbeiten stützen das.",
        "Neuere Befunde kommen hinzu.",
    )
    assert "weggelassen: Quellenangaben in Klammern (4)" in dok.warnungen


def test_jahreszahl_allein_bleibt(tmp_path):
    """Gegenbeispiele: eine Jahreszahl allein ist keine Quellenangabe (auch nach einem Monat)."""
    absaetze = (
        "Der Krieg dauerte lange (1914\u20131918).",  # Halbgeviertstrich
        "Die Malerin (geb. 1951 in Musterstadt) stellt im Herbst aus.",
        "Die Preise gelten weiter (Stand: März 2025).",
        "Die Messe fand im Frühjahr statt (März 2025).",
        "Das Gerät kostet viel (2000 Euro).",
        "Die Strecke ist weit (ca. 1900 Kilometer).",
    )

    dok = _lies_absaetze(tmp_path, *absaetze)

    assert dok.kapitel[0].absaetze == absaetze
    assert not any("Quellenangaben" in w for w in dok.warnungen)


def test_literatur_vollmatch(tmp_path):
    """Ein Literaturabschnitt faellt bis zur naechsten Ueberschrift oder zum Kapitelende weg.

    Nur bei Voll-Match der Ueberschrift (Nummer davor, Doppelpunkt danach erlaubt); eine
    Ueberschrift, die nur so beginnt, bleibt samt ihrem Text.
    """
    quelle = tmp_path / "literatur.md"
    quelle.write_text(
        "# Erstes Kapitel\n\nEin Absatz Text.\n\n"
        "### 7. Literatur:\n\n"
        "Mustermann, G. (2004): Ein Beispielbuch. Musterverlag.\n\n"
        "Probst, A. (2006): Noch ein Beispielbuch. Musterverlag.\n\n"
        "### Ausblick\n\nDanach geht es weiter.\n\n"
        "## Quellen und Literatur\n\nBeispiel, B. (2001): Ein Aufsatz. Musterheft.\n\n"
        "## Quellen der Resilienz\n\nEin Kapitel, das bleibt.\n\n"
        "### Literatur im 19. Jahrhundert\n\nAuch dieser Abschnitt bleibt.\n",
        encoding="utf-8",
    )

    dok = lies(quelle, textmodell=None)

    assert [k.titel for k in dok.kapitel] == ["Erstes Kapitel", "Quellen der Resilienz"]
    assert dok.kapitel[0].absaetze == ("Ein Absatz Text.", "Ausblick", "Danach geht es weiter.")
    assert dok.kapitel[1].absaetze == (
        "Ein Kapitel, das bleibt.",
        "Literatur im 19. Jahrhundert",
        "Auch dieser Abschnitt bleibt.",
    )
    assert any(w.startswith("weggelassen: Literaturabschnitt") for w in dok.warnungen)


def test_quellvermerk_am_kapitelende(tmp_path):
    vermerk = "Aus: G. Mustermann, Beispielbuch, Verlag 2012, Seiten 25-34"

    dok = _lies_absaetze(tmp_path, "Erster Absatz.", "Zweiter Absatz.", vermerk)

    assert dok.kapitel[0].absaetze == ("Erster Absatz.", "Zweiter Absatz.")
    assert "weggelassen: Quellvermerk (1)" in dok.warnungen

    # Nur am Kapitelende ist es ein Quellvermerk; mitten im Kapitel bleibt die Zeile.
    mitten = _lies_absaetze(tmp_path, "Erster Absatz.", vermerk, "Zweiter Absatz.")
    assert vermerk in mitten.kapitel[0].absaetze


def test_zitat_mit_organisation_als_autor(tmp_path):
    """Ein Kuerzel in Versalien (WHO, OECD) ist als Autor einer Quellenangabe ein Name.

    Befund des Lesetests an einem echten Sachbuch (Plan A3 Step 4); Gegenbeispiele bleiben.
    """
    dok = _lies_absaetze(
        tmp_path,
        "Die Lage bessert sich langsam (WHO 2006).",
        "Daten dazu liefert eine Studie (OECD 2010, 2012; Mustermann 2004).",
        "Die Geraete kosten wenig (USB 2000 Euro).",
    )

    assert dok.kapitel[0].absaetze == (
        "Die Lage bessert sich langsam.",
        "Daten dazu liefert eine Studie.",
        "Die Geraete kosten wenig (USB 2000 Euro).",
    )
    assert "weggelassen: Quellenangaben in Klammern (2)" in dok.warnungen


def test_zitat_kuerzel_positivliste(tmp_path):
    """Nur Kuerzel der festen Liste herausgebender Organisationen sind ein Name (Critic A, N2)."""
    dok = _lies_absaetze(
        tmp_path,
        "Die Zahlen steigen (OECD 2011).",
        "Das gilt auch hier (vgl. WHO 2003, S. 4).",
    )

    assert dok.kapitel[0].absaetze == ("Die Zahlen steigen.", "Das gilt auch hier.")
    assert "weggelassen: Quellenangaben in Klammern (2)" in dok.warnungen


@pytest.mark.parametrize(
    "klammer",
    [
        pytest.param("(Mustermann 2004, Beispiel 2006)", id="a-komma-liste"),
        pytest.param("(Lindner et al 2019, Probst und Muster 2003)", id="a-komma-liste-namen"),
        pytest.param("(Lindner et al 2019)", id="b-et-al-ohne-punkt"),
        pytest.param("(Übersicht in: Probst 2006)", id="c-vorwort-doppelpunkt"),
        pytest.param("(Übersichten in: Beispiel 1995; Muster 2001)", id="c-vorwort-plural"),
        pytest.param("(vgl. Übersichten in: Beispiel 1995, Muster 2001)", id="c-zwei-vorworte"),
        pytest.param("(Muster ???, Beispiel 2003)", id="d-platzhalter"),
    ],
)
def test_zitat_luecken_der_abnahme(tmp_path, klammer):
    """Formen der Zitat-Syntax, die die Abnahme F1 im Hoertext fand (Befund B5)."""
    dok = _lies_absaetze(tmp_path, f"Das Lernen braucht Zeit {klammer} und Ruhe.")

    assert dok.kapitel[0].absaetze == ("Das Lernen braucht Zeit und Ruhe.",)
    assert "weggelassen: Quellenangaben in Klammern (1)" in dok.warnungen


@pytest.mark.parametrize(
    "klammer",
    [
        # Versal-Kuerzel ausserhalb der Positivliste
        "(DDR 1989)",
        "(EN 1990)",
        "(WM 2006)",
        "(NATO 1949)",
        "(DIN 1946)",
        "(EU 2020)",
        # Nicht-Namen der Stoppliste (grosser Anfangsbuchstabe, Jahr danach)
        "(Stand 2020)",
        "(Sommer 2020)",
        "(Auflage 2005)",
        "(Version 2024)",
        "(Ostern 2020)",
        "(Spring 2020)",
        "(Early 1990)",
        # die Stoppliste gilt fuer JEDEN Namen der Angabe
        "(Mustermann und Stand 2020)",
        # Monat in der oesterreichischen Form
        "(Jänner 2020)",
        # Komma zwischen Wort und Jahr ist keine Angabe (B5: die Komma-Liste trennt Angaben)
        "(Berlin, 1989)",
        "(März, 2025)",
        "(Muster, Beispiel, 2004)",
        # Platzhalter ohne echte Jahreszahl in der Klammer (B5)
        "(Warum ???)",
        "(Mustermann ???)",
    ],
)
def test_keine_quellenangabe_bleibt_stehen(tmp_path, klammer):
    """Gegenbeispiele (Critic A, N2): echter Text in Klammern wird nie weggelassen."""
    absatz = f"Der Satz steht hier {klammer} und geht weiter."

    dok = _lies_absaetze(tmp_path, absatz)

    assert dok.kapitel[0].absaetze == (absatz,)
    assert not any("Quellenangaben" in w for w in dok.warnungen)
