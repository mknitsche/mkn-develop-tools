"""Spracherkennung: die Stoppwort-Zaehlung und was `lies` daraus macht."""

from __future__ import annotations

import pytest

from mkn_audio.lesen import lies
from mkn_audio.sprache import erkenne
from muster_quellen import epub_schreiben, opf, xhtml

DEUTSCH = (
    "Der Hund lief durch den Garten und suchte nach dem Ball, den die Kinder am Morgen "
    "verloren hatten. Es war ein warmer Tag, und die Sonne schien auf das Dach des Hauses. "
    "Er wusste nicht, wohin er gehen sollte, aber er hoffte, dass jemand ihm helfen wuerde."
)
ENGLISCH = (
    "The dog ran through the garden and looked for the ball that the children had lost in "
    "the morning. It was a warm day, and the sun was shining on the roof of the house. He "
    "did not know where he should go, but he hoped that someone would help him with it."
)
FRANZOESISCH = (
    "Le chien courait dans le jardin et cherchait la balle que les enfants avaient perdue "
    "ce matin. Il faisait chaud, et le soleil brillait sur le toit de la maison. Il ne "
    "savait pas où aller, mais il espérait que quelqu'un pourrait l'aider avec cela."
)
SPANISCH = (
    "El perro corria por el jardin y buscaba la pelota que los ninos habian perdido por la "
    "manana. Era un dia caluroso, y el sol brillaba sobre el techo de la casa. No sabia "
    "adonde ir, pero esperaba que alguien lo ayudara con todo esto, porque estaba solo."
)
ITALIENISCH = (
    "Il cane correva per il giardino e cercava la palla che i bambini avevano perso la "
    "mattina. Era una giornata calda, e il sole splendeva sul tetto della casa. Non sapeva "
    "dove andare, ma sperava che qualcuno lo aiutasse con questo, perche era molto stanco."
)
NIEDERLAENDISCH = (
    "De hond rende door de tuin en zocht naar de bal die de kinderen die ochtend kwijt waren "
    "geraakt. Het was een warme dag, en de zon scheen op het dak van het huis. Hij wist niet "
    "waar hij heen moest, maar hij hoopte dat iemand hem zou helpen met het zoeken ervan."
)


@pytest.mark.parametrize(
    ("text", "erwartet"),
    [
        (DEUTSCH, "de"),
        (ENGLISCH, "en"),
        (FRANZOESISCH, "fr"),
        (SPANISCH, "es"),
        (ITALIENISCH, "it"),
        (NIEDERLAENDISCH, "nl"),
    ],
)
def test_erkenne_jede_sprache(text, erwartet):
    assert erkenne(text) == erwartet


def test_erkenne_zu_kurz_ist_unbekannt():
    assert erkenne("Der Hund lief durch den Garten und suchte nach dem Ball.") is None


def test_erkenne_ohne_klaren_vorsprung_ist_unbekannt():
    """Eigennamen und Zahlen enthalten keine Stoppwoerter: kein Raten."""
    namen = " ".join(["Anton Berta Caesar Dora Emil Friedrich Gustav Heinrich 1234"] * 6)

    assert erkenne(namen) is None


def _textdatei(tmp_path, inhalt):
    quelle = tmp_path / "notiz.txt"
    quelle.write_text(inhalt, encoding="utf-8")
    return quelle


def test_deutscher_text_wird_deutsch(tmp_path):
    dok = lies(_textdatei(tmp_path, DEUTSCH), textmodell=None)

    assert dok.sprache == "de"
    assert not any("Sprache" in w for w in dok.warnungen)


def test_englischer_text_wird_englisch(tmp_path):
    dok = lies(_textdatei(tmp_path, ENGLISCH), textmodell=None)

    assert dok.sprache == "en"
    assert not any("Sprache" in w for w in dok.warnungen)


def test_kurzer_text_unbekannt_mit_warnung(tmp_path):
    dok = lies(_textdatei(tmp_path, "Ein kurzer Satz."), textmodell=None)

    assert dok.sprache == "de"
    assert "Sprache nicht sicher erkannt, als Deutsch gelesen" in dok.warnungen


def _epub(tmp_path, text, *, sprache="en"):
    kapitel = xhtml(f"<h1>Kapitel</h1><p>{text}</p>", titel="Kapitel")
    inhalt = opf(
        items=[("kap1", "kap1.xhtml", "application/xhtml+xml", "")],
        spine=["kap1"],
        sprache=sprache,
    )
    return epub_schreiben(tmp_path / "b.epub", {"content.opf": inhalt, "kap1.xhtml": kapitel})


def test_epub_sprachangabe_gewinnt_mit_warnung_bei_widerspruch(tmp_path):
    # Angabe und Text stimmen ueberein: gilt, keine Warnung.
    passend = lies(_epub(tmp_path, ENGLISCH), textmodell=None)
    assert passend.sprache == "en"
    assert not any("Sprache" in w for w in passend.warnungen)

    # Die Angabe gewinnt auch gegen einen deutlich anderen Text, aber mit Warnung.
    dok = lies(_epub(tmp_path, DEUTSCH, sprache="en-GB"), textmodell=None)

    assert dok.sprache == "en"
    widerspruch = [w for w in dok.warnungen if "widerspricht" in w]
    assert len(widerspruch) == 1
    assert "en" in widerspruch[0] and "de" in widerspruch[0]


def test_epub_ohne_sprachangabe_wird_erkannt(tmp_path):
    dok = lies(_epub(tmp_path, ENGLISCH, sprache=""), textmodell=None)

    assert dok.sprache == "en"
