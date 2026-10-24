"""Arbeitsverzeichnis: was zwischen den Stufen abgelegt wird, kommt unverloren wieder heraus.

Der Fall, der zaehlt: `Kapitel.arten` (Regie) und `Stueck.ansage`. Gingen sie beim
Zwischenspeichern verloren, spraeche ein fortgesetzter Lauf die Ansagen mit der Haupt-
stimme -- und niemand wuerde es merken, weil der erste Lauf noch richtig klang.
"""

from __future__ import annotations

from mkn_audio.arbeitsverzeichnis import (
    Arbeitsverzeichnis,
    dokument_aus_json,
    dokument_zu_json,
    stuecke_aus_json,
    stuecke_zu_json,
)
from mkn_audio.typen import Dokument, Kapitel, Stueck

DOK = Dokument(
    titel="Buch",
    autor=None,
    sprache="de",
    kapitel=(
        Kapitel("", ("Sie hören ein Buch.",), ("vorspann",)),
        Kapitel("Eins", ("Text.", "Weiter."), ("wortlaut", "ueberleitung")),
        Kapitel("Zwei", ("Ohne Regie.",)),
    ),
)


def test_arten_ueberleben_das_zwischenspeichern(tmp_path):
    verz = Arbeitsverzeichnis(tmp_path / "a", "x" * 64)
    verz.schreibe_stufe("regie", "fp", dokument_zu_json(DOK))

    geladen = dokument_aus_json(verz.lies_stufe("regie", "fp"))

    assert [k.arten for k in geladen.kapitel] == [("vorspann",), ("wortlaut", "ueberleitung"), ()]
    assert geladen == DOK


def test_lesetext_aus_aelterem_lauf_ohne_arten_bleibt_lesbar():
    """Ein gespeicherter Lesetext kennt `arten` nicht (es gab sie nicht): leer, nicht Fehler."""
    alt = dokument_zu_json(DOK)
    for kapitel in alt["kapitel"]:
        del kapitel["arten"]

    assert all(k.arten == () for k in dokument_aus_json(alt).kapitel)


def test_ansage_ueberlebt_das_zwischenspeichern_der_stuecke():
    stuecke = (
        Stueck(0, 0, 0, "Sie hören ein Buch.", "text", ansage=True),
        Stueck(1, -1, 1, "Eins", "titel"),
    )

    geladen = stuecke_aus_json(stuecke_zu_json(stuecke))

    assert geladen == stuecke
    assert [s.ansage for s in geladen] == [True, False]
