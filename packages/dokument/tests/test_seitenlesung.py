"""Seitenlesung: Auftrag mit Fach-Angaben, Formpruefung, Abgleich von Kopf, Texten und Diagrammen, Lauf.

Alle Inhalte erfunden.
"""

import json
import stat
from datetime import date

import pytest

from conftest import ScheinLeser, schreibe_pdf
from mkn_dokument import seitenlesung
from mkn_dokument.auftrag import AntwortUngueltig
from mkn_dokument.leser import LeserFehler


def _antwort(**anders):
    a = {
        "seitenart": "inhalt", "aussteller": "Probelabor Nord", "datum": "01.02.2020",
        "datum_bezeichnung": "Probendatum", "inhaltsart": "labor", "texte": [], "diagramme": [],
    }  # fmt: skip
    return a | anders


def _block(text, ueberschrift=None, art="absatz"):
    return {"ueberschrift": ueberschrift, "art": art, "text": text}


def _diagramm(titel="Verlauf Probewert", typ="linie", x="Zeit", y="Wert", **anders):
    return {
        "titel": titel,
        "typ": typ,
        "x_achse": x,
        "y_achse": y,
        "reihen": ["Reihe 1"],
        "werte_gedruckt": False,
    } | anders


# --- Auftrag -------------------------------------------------------------------------------------------------------


def test_auftrag_ohne_fach_nennt_allgemeine_vorgaben():
    text = seitenlesung.auftrag()
    assert text.startswith("Du liest eine Seite eines Dokuments vom Seitenbild.")
    assert "Erfasse NICHT die Tabellenwerte" in text
    assert "seitenart: eines von [leer, deckblatt, inhalt, brief, formular, sonstiges]" in text
    assert "datum: das Datum, auf das sich der Inhalt bezieht" in text
    assert "inhaltsart: eines von" not in text  # frei, ohne Liste
    assert "typ (linie, balken, punkte, flaeche, kreis, sonstiges)" in text
    assert text.rstrip().endswith("}")
    json.loads(text[text.index("{") :])  # die Vorlage am Ende ist gueltiges JSON


def test_auftrag_mit_fach_setzt_woerter_und_datumssatz_ein():
    fach = seitenlesung.Fach(
        dokumentart="eines Probebelegs",
        seitenarten=("leer", "deckblatt", "befund", "sonstiges"),
        inhaltsarten=("labor", "bildgebung"),
        textarten=("befundtext", "beurteilung"),
        datum_hinweis="der Tag der Probe, genau wie gedruckt; NICHT das Druckdatum",
    )
    text = seitenlesung.auftrag(fach)
    assert text.startswith("Du liest eine Seite eines Probebelegs vom Seitenbild.")
    assert "seitenart: eines von [leer, deckblatt, befund, sonstiges]" in text
    assert "datum: der Tag der Probe, genau wie gedruckt; NICHT das Druckdatum. Leer, wenn" in text
    assert "inhaltsart: eines von [labor, bildgebung]" in text
    assert "art (eines von [befundtext, beurteilung])" in text
    assert seitenlesung.auftrag(fach) != seitenlesung.auftrag()


@pytest.mark.parametrize(
    "fach",
    [
        {"seitenarten": ()},
        {"seitenarten": ("leer", "")},
        {"inhaltsarten": ("a, b",)},  # ein Komma zerbraeche die Liste im Auftrag
        {"dokumentart": " "},
        {"datum_hinweis": ""},
    ],
)
def test_fach_mit_leeren_oder_kaputten_woertern_wird_abgewiesen(fach):
    with pytest.raises(ValueError):
        seitenlesung.Fach(**fach)


def test_schema_verlangt_alle_felder():
    schema = seitenlesung.SCHEMA
    assert set(schema["required"]) == {*seitenlesung.ANTWORT_KOPF, "texte", "diagramme"}
    assert schema["properties"]["diagramme"]["items"]["properties"]["werte_gedruckt"] == {"type": "boolean"}


# --- Formpruefung --------------------------------------------------------------------------------------------------


def test_gueltige_antwort_kommt_zurueck_leere_fremde_felder_entfallen():
    roh = _antwort(texte=[_block("Ein Satz.") | {"notiz": ""}], diagramme=[_diagramm()], extra=None)
    geprueft = seitenlesung.pruefe_antwort(roh)
    assert "extra" not in geprueft and "notiz" not in geprueft["texte"][0]
    assert geprueft["diagramme"] == [_diagramm()]


@pytest.mark.parametrize(
    "kaputt",
    [
        [],
        {"seitenart": "x"},  # Felder fehlen
        _antwort(datum=5),  # Zahl statt Text
        _antwort(texte={}),
        _antwort(texte=[_block("")]),  # Text leer
        _antwort(texte=[_block("Satz.", art=None)]),
        _antwort(texte=["Satz."]),
        _antwort(diagramme=[_diagramm(reihen="R")]),
        _antwort(diagramme=[_diagramm(werte_gedruckt="ja")]),
        _antwort(diagramme=[{"titel": "nur Titel"}]),
        _antwort(zusatz="Inhalt, der still verloren ginge"),
    ],
)
def test_falsche_form_bricht_laut(kaputt):
    with pytest.raises(AntwortUngueltig):
        seitenlesung.pruefe_antwort(kaputt)


# --- Abgleich: Kopf ------------------------------------------------------------------------------------------------


def test_beide_leser_einig_fuellt_den_kopf():
    s = seitenlesung.gleiche_ab(_antwort(), _antwort())
    assert s["ausgang"] == "zwei_leser"
    assert (s["seitenart"], s["aussteller"], s["datum"], s["inhaltsart"], s["uneins"]) == (
        "inhalt",
        "Probelabor Nord",
        "2020-02-01",
        "labor",
        [],
    )


@pytest.mark.parametrize(
    ("a", "b", "tag"),
    [
        ("01.02.2020", "Probe vom 1.2.20", "2020-02-01"),
        ("32.13.2020, dann 05.06.2021", "05.06.2021", "2021-06-05"),
        ("05.06.85", "05.06.1985", "1985-06-05"),
        ("05.06.2021, Kontrolle am 2021-06-05", "5. Juni 2021", "2021-06-05"),
    ],
)
def test_datum_genau_ein_gueltiger_tag_gleich(a, b, tag):
    s = seitenlesung.gleiche_ab(_antwort(datum=a), _antwort(datum=b))
    assert (s["datum"], s["uneins"]) == (tag, [])


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("01.02.2020", "02.02.2020"),
        ("01.02.2020", ""),
        ("", "kein Datum"),
        ("Eingang 05.06.2021 Bericht 07.06.2021", "05.06.2021"),
        ("05.06.2021 und 07.06.2021", "05.06.2021 und 07.06.2021"),
        ("01/02/2020", "01/02/2020"),
    ],
)
def test_verschiedener_einseitiger_oder_unlesbarer_tag_ist_uneins(a, b):
    s = seitenlesung.gleiche_ab(_antwort(datum=a), _antwort(datum=b))
    assert (s["datum"], s["uneins"]) == (None, ["datum"])


@pytest.mark.parametrize(("a", "b"), [("", ""), (" ", "-"), (None, "")])
def test_beide_leer_ist_kein_tag_und_nicht_uneins(a, b):
    s = seitenlesung.gleiche_ab(_antwort(datum=a), _antwort(datum=b))
    assert (s["datum"], s["uneins"]) == (None, [])


@pytest.mark.parametrize(
    ("text", "tag"),
    [
        ("Datum: 05.12.2024.", date(2024, 12, 5)),
        ("Probe 05. Dez. 2024.", date(2024, 12, 5)),
        ("5 December 2024", date(2024, 12, 5)),
        ("3. Maerz 2021", date(2021, 3, 3)),
        ("31. Februar 2021, dann 2021-03-01", date(2021, 3, 1)),
        ("1.2024.12.05", None),
        ("05/12/2024", None),
        ("5. Dezember", None),
        ("Typ 19-9", None),
    ],
)
def test_tag_in_liest_nur_eindeutige_schreibweisen(text, tag):
    assert seitenlesung.tag_in(text) == tag


def test_aussteller_enthalten_genuegt_die_kuerzere_gilt():
    s = seitenlesung.gleiche_ab(
        _antwort(aussteller="Probelabor Nord GmbH, Musterweg 1"), _antwort(aussteller="Probelabor Nord")
    )
    assert (s["aussteller"], s["uneins"]) == ("Probelabor Nord", [])
    s = seitenlesung.gleiche_ab(_antwort(aussteller="Probelabor Nord"), _antwort(aussteller="Praxis Sued"))
    assert (s["aussteller"], s["uneins"]) == (None, ["aussteller"])


@pytest.mark.parametrize("feld", ["seitenart", "inhaltsart"])
def test_woerter_gleich_nur_bei_gleichem_wort(feld):
    s = seitenlesung.gleiche_ab(_antwort(**{feld: "Labor-Befund."}), _antwort(**{feld: " labor befund"}))
    assert (s[feld], s["uneins"]) == ("labor befund", [])
    s = seitenlesung.gleiche_ab(_antwort(**{feld: "labor"}), _antwort(**{feld: "laborbefund"}))
    assert (s[feld], s["uneins"]) == (None, [feld])


def test_uneins_in_fester_reihenfolge_und_leser_traegt_den_kopf():
    a = _antwort(texte=[_block("Ein Satz.")])
    b = _antwort(seitenart="brief", aussteller="Praxis Sued", datum="03.03.2020", inhaltsart="check")
    s = seitenlesung.gleiche_ab(a, b)
    assert s["uneins"] == ["seitenart", "aussteller", "datum", "inhaltsart"]
    assert s["leser"]["a"] == {k: v for k, v in a.items() if k not in ("texte", "diagramme")}


# --- Abgleich: Texte und Diagramme ---------------------------------------------------------------------------------


def _texte(a, b):
    s = seitenlesung.gleiche_ab(_antwort(texte=a), _antwort(texte=b))
    return [(t["leser"], t["ausgang"], t["text"]) for t in s["texte"]]


def test_block_von_a_uebernommen_wenn_b_jeden_satz_hat():
    assert _texte([_block("Erster Satz. Zweiter Satz!")], [_block("erster  Satz."), _block("Zweiter Satz")]) == [
        ("a", "uebernommen", "Erster Satz. Zweiter Satz!")
    ]
    assert _texte([_block("Erster Satz. Nur bei a.")], [_block("Erster Satz.")]) == [
        ("a", "klaerliste", "Erster Satz. Nur bei a.")
    ]
    assert _texte([_block("Erster Satz.")], [_block("Erster Satz."), _block("Nur bei b.")]) == [
        ("a", "uebernommen", "Erster Satz."),
        ("b", "klaerliste", "Nur bei b."),
    ]


def test_saetze_als_mehrfachmenge_und_block_ohne_satz():
    assert _texte([_block("Satz. Satz.")], [_block("Satz.")]) == [("a", "klaerliste", "Satz. Satz.")]
    assert _texte([_block("— —")], []) == [("a", "klaerliste", "— —")]


def test_diagramme_gepaart_nach_reihenfolge_typ_und_titel_oder_achsen():
    a = [_diagramm(reihen=["A1"], werte_gedruckt=True), _diagramm(titel="Bild A", x="Zeit (Jahre)")]
    b = [_diagramm(titel="verlauf probewert", werte_gedruckt=False), _diagramm(titel="Grafik B", x="Zeit")]
    s = seitenlesung.gleiche_ab(_antwort(diagramme=a), _antwort(diagramme=b))
    assert [d["ausgang"] for d in s["diagramme"]] == ["uebernommen", "uebernommen"]
    assert (s["diagramme"][0]["reihen"], s["diagramme"][0]["werte_gedruckt"]) == (["A1"], None)
    assert s["diagramme"][0]["leser"] == {"a": a[0], "b": b[0]}


def test_diagramme_ohne_passung_oder_mit_anderer_zahl_auf_der_klaerliste():
    s = seitenlesung.gleiche_ab(
        _antwort(diagramme=[_diagramm(typ="linie")]), _antwort(diagramme=[_diagramm(typ="balken")])
    )
    assert [(d["ausgang"], sorted(d["leser"])) for d in s["diagramme"]] == [
        ("klaerliste", ["a"]),
        ("klaerliste", ["b"]),
    ]
    s = seitenlesung.gleiche_ab(_antwort(diagramme=[_diagramm(), _diagramm()]), _antwort(diagramme=[_diagramm()]))
    assert [d["ausgang"] for d in s["diagramme"]] == ["klaerliste"] * 3


@pytest.mark.parametrize("fehlt", ["a", "b"])
def test_ein_leser_kopf_leer_alles_auf_der_klaerliste(fehlt):
    antwort = _antwort(texte=[_block("Ein Satz.")], diagramme=[_diagramm()])
    a, b = (None, antwort) if fehlt == "a" else (antwort, None)
    s = seitenlesung.gleiche_ab(a, b)
    da = "b" if fehlt == "a" else "a"
    assert s["ausgang"] == "ein_leser"
    assert [s[f] for f in seitenlesung.KOPFFELDER] == [None] * 4 and s["uneins"] == []
    assert [(t["leser"], t["ausgang"]) for t in s["texte"]] == [(da, "klaerliste")]


def test_ohne_leser_bricht():
    with pytest.raises(ValueError):
        seitenlesung.gleiche_ab(None, None)


# --- Lauf ----------------------------------------------------------------------------------------------------------


def test_lauf_liest_jede_seite_gleicht_ab_und_legt_seiten_json_ab(tmp_path):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf", seiten=2)
    a = ScheinLeser("a", [_antwort(texte=[_block("Ein Satz.")]), _antwort(seitenart="leer")])
    b = ScheinLeser("b", [_antwort(texte=[_block("Ein Satz.")]), _antwort(seitenart="brief")])
    ergebnis = seitenlesung.lies_seiten(pdf, tmp_path / "aus", a, b)
    assert (ergebnis["funktion"], ergebnis["quelle"]["seiten"], ergebnis["leser"]) == (
        "seiten",
        2,
        {"a": "a", "b": "b"},
    )
    erste, zweite = ergebnis["seiten"]
    assert (erste["seite"], erste["datum"], erste["texte"][0]["ausgang"]) == (1, "2020-02-01", "uebernommen")
    assert (zweite["seite"], zweite["uneins"]) == (2, ["seitenart"])
    assert erste["antworten"]["b"] == b.antworten[0]  # die rohen Antworten bleiben
    datei = tmp_path / "aus" / seitenlesung.ERGEBNIS
    assert json.loads(datei.read_text()) == ergebnis
    assert stat.S_IMODE(datei.stat().st_mode) == 0o600
    assert seitenlesung.zaehle(ergebnis) == {
        "seiten": 2,
        "kopf_uneins": 1,
        "texte_uebernommen": 1,
        "texte_klaerliste": 0,
        "diagramme_uebernommen": 0,
        "diagramme_klaerliste": 0,
    }


def test_zweiter_lauf_aus_der_mitschrift_anderes_fach_ist_eine_neue_lesung(tmp_path):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf")
    seitenlesung.lies_seiten(pdf, tmp_path / "aus", ScheinLeser("a", [_antwort()]), ScheinLeser("b", [_antwort()]))
    a, b = ScheinLeser("a", []), ScheinLeser("b", [])
    seitenlesung.lies_seiten(pdf, tmp_path / "aus", a, b)
    assert a.aufrufe == [] and b.aufrufe == []
    a, b = ScheinLeser("a", [_antwort()]), ScheinLeser("b", [_antwort()])
    seitenlesung.lies_seiten(pdf, tmp_path / "aus", a, b, fach=seitenlesung.Fach(dokumentart="eines Probebelegs"))
    assert len(a.aufrufe) == 1 and len(b.aufrufe) == 1


def test_ungueltige_antwort_oder_leserfehler_bricht_den_lauf(tmp_path):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf")
    with pytest.raises(AntwortUngueltig):
        seitenlesung.lies_seiten(pdf, tmp_path / "aus", ScheinLeser("a", [_antwort()]), ScheinLeser("b", [{"x": 1}]))
    with pytest.raises(LeserFehler):
        seitenlesung.lies_seiten(pdf, tmp_path / "aus2", ScheinLeser("a", [LeserFehler("aus")]), ScheinLeser("b", []))
    assert not (tmp_path / "aus" / seitenlesung.ERGEBNIS).exists()
    assert not (tmp_path / "aus2" / seitenlesung.ERGEBNIS).exists()
    with pytest.raises(ValueError, match="derselbe"):
        seitenlesung.lies_seiten(pdf, tmp_path / "aus", ScheinLeser("a", []), ScheinLeser("a", []))


def test_meldung_kuerzt_unbekannte_feldnamen_auf_30_zeichen():
    lang = "x" * 80
    with pytest.raises(AntwortUngueltig) as fehler:
        seitenlesung.pruefe_antwort(_antwort(**{lang: "Inhalt"}))
    assert "x" * 30 in str(fehler.value)
    assert "x" * 31 not in str(fehler.value)
