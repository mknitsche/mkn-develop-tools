"""Stufe b: das Sprachmodell glaettet, die Pruefung haelt es in Grenzen."""

from __future__ import annotations

import pytest

from mkn_audio.hoertext.glaetten import BLOCK_MAX, PROMPT, glaette


class Modell:
    """Schein-Textmodell: eine feste Funktion, merkt sich seine Aufrufe."""

    def __init__(self, antwort=lambda text: text):
        self.antwort = antwort
        self.aufrufe: list[tuple[str, tuple]] = []

    def __call__(self, prompt, bilder):
        self.aufrufe.append((prompt, bilder))
        assert prompt.startswith(PROMPT)
        return self.antwort(prompt.removeprefix(PROMPT))

    @property
    def texte(self):
        return [p.removeprefix(PROMPT) for p, _ in self.aufrufe]


def test_prompt_nennt_die_verbote_im_wortlaut():
    for teil in (
        "Bereite den Text zum Vorlesen auf",
        "Klammern und Einschübe flüssig auflösen",
        "Aufzählungszeichen in Sätze",
        "Symbole aussprechen",
        "KEINE inhaltliche Änderung",
        "keine Zahl- oder Namensänderung",
        "nichts weglassen, nichts hinzufügen",
        "Absätze mit Leerzeile trennen",
        "nur den Text ausgeben",
    ):
        assert teil in PROMPT


def test_prompt_macht_den_text_zu_daten_nicht_zur_anweisung():
    # Ein fremdes Dokument darf dem Modell keine Anweisungen unterschieben.
    assert "Anweisung" in PROMPT
    assert PROMPT.rstrip().endswith("TEXT:")


def test_ein_aufruf_je_block_ohne_bilder():
    modell = Modell()
    absaetze = ("Erster Absatz.", "Zweiter Absatz.")
    ergebnis, warnungen = glaette(absaetze, modell, wo="Eins")
    assert ergebnis == absaetze
    assert warnungen == []
    assert len(modell.aufrufe) == 1
    assert modell.aufrufe[0][1] == ()
    assert modell.texte[0] == "Erster Absatz.\n\nZweiter Absatz."


def test_bloecke_bleiben_unter_der_grenze():
    a = "a" * 2500
    modell = Modell()
    ergebnis, _ = glaette((a, a, a), modell, wo="Eins")
    assert ergebnis == (a, a, a)
    assert [len(t) for t in modell.texte] == [2 * 2500 + 2, 2500]
    assert all(len(t) <= BLOCK_MAX for t in modell.texte)


def test_ein_riesiger_absatz_bekommt_einen_eigenen_block():
    gross = "b" * (BLOCK_MAX + 100)
    modell = Modell()
    ergebnis, _ = glaette(("kurz", gross, "kurz"), modell, wo="Eins")
    assert ergebnis == ("kurz", gross, "kurz")
    assert len(modell.aufrufe) == 3


def test_leere_absatzliste_ruft_kein_modell():
    modell = Modell()
    assert glaette((), modell, wo="Eins") == ((), [])
    assert modell.aufrufe == []


def test_geglaetteter_absatz_wird_uebernommen():
    modell = Modell(
        lambda t: t.replace("(ein roter Wagen)", ", ein roter Wagen,").replace(" ,", ",")
    )
    ergebnis, warnungen = glaette(("Das Auto (ein roter Wagen) fuhr los.",), modell, wo="Eins")
    assert ergebnis == ("Das Auto, ein roter Wagen, fuhr los.",)
    assert warnungen == []


def test_falsche_absatzzahl_verwirft_den_ganzen_block():
    modell = Modell(lambda t: t.replace("\n\n", " "))
    absaetze = ("Erster Absatz hier.", "Zweiter Absatz da.")
    ergebnis, warnungen = glaette(absaetze, modell, wo="Eins")
    assert ergebnis == absaetze
    assert len(warnungen) == 1
    assert "Aufbereitung verworfen" in warnungen[0]
    assert "Eins" in warnungen[0]
    assert "Absatzzahl" in warnungen[0]


def test_nur_der_auffaellige_absatz_faellt_zurueck():
    def antwort(text):
        erster, _, dritter = text.split("\n\n")
        return "\n\n".join([erster, "Etwas ganz anderes steht hier jetzt.", dritter])

    absaetze = ("Er kam heute an.", "Sie ging morgen fort.", "Wir blieben noch da.")
    ergebnis, warnungen = glaette(absaetze, Modell(antwort), wo="Eins")
    assert ergebnis == absaetze
    assert len(warnungen) == 1
    assert "Absatz 2" in warnungen[0]
    assert "Aufbereitung verworfen" in warnungen[0]


def test_modellfehler_bricht_laut():
    def kaputt(text):
        raise RuntimeError("Modell nicht erreichbar")

    with pytest.raises(RuntimeError, match="nicht erreichbar"):
        glaette(("Ein Absatz.",), Modell(kaputt), wo="Eins")


def test_antwort_mit_leerzeilen_voller_leerraum_zaehlt_richtig():
    modell = Modell(lambda t: "\n\n" + t.replace("\n\n", "\n \n\n") + "\n\n")
    absaetze = ("Erster Absatz hier.", "Zweiter Absatz da.")
    ergebnis, warnungen = glaette(absaetze, modell, wo="Eins")
    assert ergebnis == absaetze
    assert warnungen == []
