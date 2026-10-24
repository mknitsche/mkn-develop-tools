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
