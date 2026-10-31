"""Dokument-Verstehen und Regie: Rollen bestimmen, Hoerfassung bauen, Erfinden abfangen.

Alle Tests laufen mit einem Schein-Modell, das feste JSON-Antworten liefert; die Inhalte
sind erfunden (HC-3). Zwei Muster-Dokumente tragen die Faelle: eine zweispaltige
Programmseite und eine Zusammenfassung mit Bewertungs- und Kaufknopf-Zeilen.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from mkn_audio import regie
from mkn_audio.regie import (
    PROMPT_INSZENIEREN,
    PROMPT_VERSTEHEN,
    ROLLEN,
    Rollenbild,
    inszeniere,
    verstehe,
)
from mkn_audio.regie import (
    regie as mache_regie,
)
from mkn_audio.typen import QUELL_ARTEN, Dokument, Kapitel, Mp4Fehler


class Modell:
    """Schein-Textmodell: feste Antworten der Reihe nach, merkt sich jeden Aufruf."""

    def __init__(self, *antworten):
        self.antworten = list(antworten)
        self.aufrufe: list[tuple[str, tuple]] = []

    def __call__(self, prompt, bilder):
        self.aufrufe.append((prompt, bilder))
        antwort = self.antworten.pop(0)
        if isinstance(antwort, Exception):
            raise antwort
        return antwort if isinstance(antwort, str) else json.dumps(antwort, ensure_ascii=False)

    @property
    def prompts(self):
        return [p for p, _ in self.aufrufe]


class Weiche:
    """Schein-Modell fuer die ganze Regie: antwortet je nach Aufgabe des Prompts."""

    def __init__(self, rollen, inszenierung):
        self.rollen, self.inszenierung = rollen, inszenierung
        self.aufrufe: list[str] = []

    def __call__(self, prompt, bilder):
        self.aufrufe.append(prompt)
        antwort = self.rollen if prompt.startswith(PROMPT_VERSTEHEN) else self.inszenierung
        return json.dumps(antwort, ensure_ascii=False)


# ---- Muster-Dokumente (erfunden) -----------------------------------------------------

PROGRAMM = Dokument(
    titel="Sommerkonzert im Schlosshof",
    autor=None,
    sprache="de",
    kapitel=(
        Kapitel(
            "Sommerkonzert im Schlosshof",
            (
                "Kammerorchester Musica Vera",  # 0 metadaten
                "Samstag, 12. Juli, Schlosshof Wiesenburg",  # 1 metadaten
                "Erster Teil",  # 2 ueberschrift
                "Die Sinfonie Nr. 3 eröffnet den Abend mit einem ruhigen Satz, "
                "den die Streicher allein tragen.",  # 3 haupttext
                "Foto: Der Schlosshof bei Abendlicht",  # 4 bildunterschrift
                "Zweiter Teil",  # 5 ueberschrift
                "Nach der Pause spielt das Orchester ein Werk für Bläser und Harfe, "
                "das der Komponist im Garten seines Hauses schrieb.",  # 6 haupttext
                "Foto: Die Harfenistin beim Einstimmen",  # 7 bildunterschrift
                "12",  # 8 seitenzahl
            ),
        ),
    ),
)
PROGRAMM_ROLLEN = {
    "dokumentart": "Programmheft eines Konzerts",
    "rollen": {
        "0.0": "metadaten",
        "0.1": "metadaten",
        "0.2": "ueberschrift",
        "0.3": "haupttext",
        "0.4": "bildunterschrift",
        "0.5": "ueberschrift",
        "0.6": "haupttext",
        "0.7": "bildunterschrift",
        "0.8": "seitenzahl",
    },
}

ZUSAMMENFASSUNG = Dokument(
    titel="Die Kunst des Zuhörens",
    autor="Erika Beispiel",
    sprache="de",
    kapitel=(
        Kapitel(
            "Worum es geht",
            (
                "Bewertung: 4 von 5 Sternen",  # 0 bedienelement
                "Buch kaufen",  # 1 bedienelement
                "Das lernen Sie: wie man zuhört, ohne zu unterbrechen.",  # 2 uebersicht
                "Wer zuhört, versteht mehr, als wer redet. Diese These zieht sich durch "
                "das ganze Buch und wird an vielen Beispielen belegt.",  # 3 haupttext
                "Zuhören ist eine Haltung, keine Technik.",  # 4 zitatkasten
            ),
        ),
        Kapitel(
            "Was daraus folgt",
            (
                "Die Autorin empfiehlt, Gespräche mit einer Frage zu beginnen und "
                "die Antwort abzuwarten. Wer so beginnt, hört zuerst die Sorgen des anderen "
                "und danach die Lösungen, die er sich wünscht.",  # 0 haupttext
                "Zuhören ist eine Haltung, keine Technik.",  # 1 zitatkasten
                "Kernaussage: Fragen vor Antworten.",  # 2 uebersicht
            ),
        ),
    ),
)
ZUSAMMENFASSUNG_ROLLEN = {
    "dokumentart": "Zusammenfassung eines Sachbuchs",
    "rollen": {
        "0.0": "bedienelement",
        "0.1": "bedienelement",
        "0.2": "uebersicht",
        "0.3": "haupttext",
        "0.4": "zitatkasten",
        "1.0": "haupttext",
        "1.1": "zitatkasten",
        "1.2": "uebersicht",
    },
}


# Dasselbe Programm, dessen Zwischenueberschriften schlichter Text sind: ohne Ueberschrift gibt es
# keinen Rueckfall-Titel, und die Tests, in denen es nicht um den Titel geht, bleiben davon frei.
PROGRAMM_OHNE_UEBERSCHRIFT = {
    stelle: ("haupttext" if rolle == "ueberschrift" else rolle)
    for stelle, rolle in PROGRAMM_ROLLEN["rollen"].items()
}


def rollenbild(rollen: dict, art: str = "Test") -> Rollenbild:
    return Rollenbild(
        dokumentart=art,
        rollen={(int(k.split(".")[0]), int(k.split(".")[1])): v for k, v in rollen.items()},
    )


# ---- verstehe ------------------------------------------------------------------------


def test_prompt_ist_allgemein_und_schuetzt_vor_eingeschleusten_anweisungen():
    assert "Anweisung" in PROMPT_VERSTEHEN
    assert "Anweisung" in PROMPT_INSZENIEREN
    for rolle in ROLLEN:
        assert rolle in PROMPT_VERSTEHEN
    # Funktion fuer den Zuhoerer, nicht Auszeichnung; keine Quelle und kein Verlag genannt.
    assert "Funktion" in PROMPT_VERSTEHEN
    for verboten in ("Verlag X", "EPUB", "PDF"):
        assert verboten not in PROMPT_VERSTEHEN + PROMPT_INSZENIEREN


def test_rollen_aus_json():
    modell = Modell(ZUSAMMENFASSUNG_ROLLEN)
    bild = verstehe(ZUSAMMENFASSUNG, textmodell=modell)
    assert bild.dokumentart == "Zusammenfassung eines Sachbuchs"
    assert bild.rollen[(0, 0)] == "bedienelement"
    assert bild.rollen[(0, 3)] == "haupttext"
    assert bild.rollen[(1, 1)] == "zitatkasten"
    assert len(bild.rollen) == 8
    assert len(modell.aufrufe) == 1
    prompt = modell.prompts[0]
    assert prompt.startswith(PROMPT_VERSTEHEN)
    assert "[0.0] Bewertung: 4 von 5 Sternen" in prompt
    assert "[1.2] Kernaussage: Fragen vor Antworten." in prompt
    assert prompt.index("TEXT:") < prompt.index("[0.0]")


def test_fehlende_absaetze_gelten_als_haupttext_und_json_im_codeblock_geht():
    antwort = '```json\n{"dokumentart": "Brief", "rollen": {"0.4": "zitatkasten"}}\n```'
    bild = verstehe(ZUSAMMENFASSUNG, textmodell=Modell(antwort))
    assert bild.rollen[(0, 4)] == "zitatkasten"
    assert bild.rollen[(0, 0)] == "haupttext"
    assert bild.rollen[(1, 2)] == "haupttext"
    assert bild.warnungen == ()


def test_kaputtes_json_einmal_nachfragen_dann_rueckfall():
    modell = Modell("das ist kein JSON", "{auch kaputt")
    bild = verstehe(ZUSAMMENFASSUNG, textmodell=modell)
    assert len(modell.aufrufe) == 2  # genau eine Nachfrage
    assert "nicht verwendbar" in modell.prompts[1]
    assert set(bild.rollen.values()) == {"haupttext"}
    assert len(bild.rollen) == 8
    assert len(bild.warnungen) == 1
    assert "alles als Haupttext" in bild.warnungen[0]


def test_unbekannte_rolle_wird_nachgefragt_und_die_zweite_antwort_gilt():
    falsch = {"dokumentart": "x", "rollen": {"0.0": "werbung"}}
    modell = Modell(falsch, ZUSAMMENFASSUNG_ROLLEN)
    bild = verstehe(ZUSAMMENFASSUNG, textmodell=modell)
    assert len(modell.aufrufe) == 2
    assert "werbung" in modell.prompts[1]
    assert bild.rollen[(0, 0)] == "bedienelement"
    assert bild.warnungen == ()


def test_absatz_den_es_nicht_gibt_ist_eine_unbrauchbare_antwort():
    falsch = {"dokumentart": "x", "rollen": {"9.9": "haupttext"}}
    modell = Modell(falsch, falsch)
    bild = verstehe(ZUSAMMENFASSUNG, textmodell=modell)
    assert len(modell.aufrufe) == 2
    assert bild.warnungen


def test_bilder_gehen_mit_in_den_aufruf():
    modell = Modell(PROGRAMM_ROLLEN)
    seite = ("image/jpeg", b"\xff\xd8\xff-seite")
    verstehe(PROGRAMM, textmodell=modell, bilder=(seite,))
    assert modell.aufrufe[0][1] == (seite,)
    assert "Bilder" in modell.prompts[0]


def test_langes_dokument_kapitelweise():
    absatz = "Ein langer Absatz mit vielen Worten. " * 40  # ca. 1500 Zeichen
    lang = Dokument(
        "Langes Werk",
        None,
        "de",
        tuple(Kapitel(f"Teil {n}", (absatz,) * 4) for n in ("A", "B", "C")),
    )
    modell = Modell(
        {"dokumentart": "Sachbuch", "rollen": {"0.1": "zitatkasten"}},
        {"dokumentart": "ignoriert", "rollen": {"1.2": "fussnote"}},
        {"rollen": {}},
    )
    seite = ("image/png", b"\x89PNG-x")
    bild = verstehe(lang, textmodell=modell, bilder=(seite,))
    assert len(modell.aufrufe) == 3  # je Kapitel ein Aufruf
    assert bild.dokumentart == "Sachbuch"  # aus dem ersten Aufruf
    assert "Sachbuch" in modell.prompts[1] and "Sachbuch" in modell.prompts[2]
    # Jeder Aufruf zeigt nur sein Kapitel, mit den Nummern des ganzen Dokuments.
    assert "[0.0]" in modell.prompts[0] and "[1.0]" not in modell.prompts[0]
    assert "[1.0]" in modell.prompts[1] and "[0.0]" not in modell.prompts[1]
    assert "[2.3]" in modell.prompts[2]
    assert modell.aufrufe[0][1] == (seite,) and modell.aufrufe[1][1] == ()
    assert bild.rollen[(0, 1)] == "zitatkasten"
    assert bild.rollen[(1, 2)] == "fussnote"
    assert bild.rollen[(2, 0)] == "haupttext"
    assert len(bild.rollen) == 12


def test_kapitel_mit_kaputter_antwort_faellt_allein_zurueck():
    absatz = "Ein langer Absatz mit vielen Worten. " * 40
    lang = Dokument(
        "Langes Werk", None, "de", tuple(Kapitel(f"Teil {n}", (absatz,) * 5) for n in "AB")
    )
    modell = Modell(
        {"dokumentart": "Sachbuch", "rollen": {"0.0": "fussnote"}},
        "Unsinn",
        "Unsinn",
    )
    bild = verstehe(lang, textmodell=modell)
    assert bild.rollen[(0, 0)] == "fussnote"
    assert bild.rollen[(1, 0)] == "haupttext"
    assert len(bild.warnungen) == 1 and "Teil B" in bild.warnungen[0]


def test_modellfehler_bricht_laut():
    with pytest.raises(ConnectionError):
        verstehe(PROGRAMM, textmodell=Modell(ConnectionError("Netz weg")))
    with pytest.raises(ConnectionError):
        mache_regie(PROGRAMM, textmodell=Modell(ConnectionError("Netz weg")))
    # Auch in der zweiten Stufe (Ansagen) wird nichts verschluckt.
    modell = Modell(PROGRAMM_ROLLEN, PermissionError("Schluessel"))
    with pytest.raises(PermissionError):
        mache_regie(PROGRAMM, textmodell=modell)


# ---- inszeniere ----------------------------------------------------------------------


KEINE_ANSAGEN = {"ueberleitungen": {}, "abspann": ""}


def kopf(**felder):
    """Eine Ansagen-Antwort des Modells: nur die Felder der Kopfseite, dazu leere Reste."""
    return {"ueberleitungen": {}, "abspann": "", **felder}


def kopfseite_von(neu):
    """Die Zeilen der gesprochenen Kopfseite (Absaetze der Art `vorspann`), sonst leer."""
    return tuple(
        a
        for k in neu.kapitel
        for a, art in zip(k.absaetze, k.arten or ("wortlaut",) * len(k.absaetze), strict=True)
        if art == "vorspann"
    )


def test_bildunterschrift_und_bedienelement_weggelassen_und_gezaehlt():
    bild = rollenbild(PROGRAMM_ROLLEN["rollen"])
    neu, warnungen = inszeniere(PROGRAMM, bild, textmodell=Modell(KEINE_ANSAGEN))
    assert "weggelassen: Bildunterschriften (2)" in warnungen
    assert "weggelassen: Metadaten (2)" in warnungen
    assert "weggelassen: Seitenzahlen (1)" in warnungen
    alle = " ".join(a for k in neu.kapitel for a in k.absaetze)
    assert "Foto:" not in alle and "Kammerorchester" not in alle

    zus, warnungen = inszeniere(
        ZUSAMMENFASSUNG,
        rollenbild(ZUSAMMENFASSUNG_ROLLEN["rollen"]),
        textmodell=Modell(KEINE_ANSAGEN),
    )
    assert "weggelassen: Bedienelemente (2)" in warnungen
    assert "weggelassen: Zitatkästen (2)" in warnungen
    assert "weggelassen: Übersichten (2)" in warnungen
    assert not any("Metadaten" in w for w in warnungen)  # null wird nicht gemeldet
    assert "Buch kaufen" not in " ".join(a for k in zus.kapitel for a in k.absaetze)


def test_plural_im_wortlaut_je_rolle():
    erwartet = {
        "metadaten": "Metadaten",
        "uebersicht": "Übersichten",
        "bildunterschrift": "Bildunterschriften",
        "zitatkasten": "Zitatkästen",
        "bedienelement": "Bedienelemente",
        "fussnote": "Fußnoten",
        "tabelle": "Tabellen",
        "seitenzahl": "Seitenzahlen",
    }
    assert erwartet == regie.PLURAL
    for rolle in ROLLEN:
        assert rolle in erwartet or rolle in ("haupttext", "ueberschrift")


def test_wortlaut_bleibt_unveraendert():
    bild = rollenbild(PROGRAMM_ROLLEN["rollen"])
    neu, _ = inszeniere(
        PROGRAMM, bild, textmodell=Modell(kopf(titel="Sommerkonzert im Schlosshof"))
    )
    quelle = set(PROGRAMM.kapitel[0].absaetze)
    wortlaut = [
        a
        for k in neu.kapitel
        for a, art in zip(k.absaetze, k.arten, strict=True)
        if art in QUELL_ARTEN  # Haupttext und Zwischenueberschrift stammen aus der Quelle
    ]
    assert wortlaut == [
        PROGRAMM.kapitel[0].absaetze[i] for i in (2, 3, 5, 6)
    ]  # Lesereihenfolge, Text identisch
    assert all(a in quelle for a in wortlaut)
    assert neu.kapitel[-1].titel == PROGRAMM.kapitel[0].titel
    assert neu.titel == PROGRAMM.titel and neu.sprache == PROGRAMM.sprache


def test_zusicherung_wortlaut_bricht_laut_bei_veraendertem_absatz():
    verfaelscht = Dokument(
        "T", None, "de", (Kapitel("K", ("Anderer Satz.",), arten=("wortlaut",)),)
    )
    with pytest.raises(Mp4Fehler, match="wortlaut"):
        regie.pruefe_wortlaut(verfaelscht, PROGRAMM)


def test_kopfseite_vor_dem_ersten_kapitel():
    modell = Modell(
        kopf(
            dokumentart="ein Programmheft",
            titel="Sommerkonzert im Schlosshof",
            herkunft="Kammerorchester Musica Vera",
            datum="Samstag, 12. Juli",
        )
    )
    neu, warnungen = inszeniere(
        PROGRAMM, rollenbild(PROGRAMM_ROLLEN["rollen"], "Programmheft"), textmodell=modell
    )
    assert len(neu.kapitel) == 2
    erstes = neu.kapitel[0]
    assert erstes.titel == "" and erstes.absaetze[0].startswith("Sie hören ein Programmheft")
    assert set(erstes.arten) == {"vorspann"} and len(erstes.arten) == len(erstes.absaetze)
    assert neu.kapitel[1].titel == "Sommerkonzert im Schlosshof"
    assert f"neu formuliert (vorspann): „{' '.join(erstes.absaetze)}“" in warnungen
    # Der Auftrag nennt Dokumentart, Titel und das Material aus metadaten/uebersicht.
    prompt = modell.prompts[0]
    assert prompt.startswith(PROMPT_INSZENIEREN)
    assert "Programmheft" in prompt and "Kammerorchester Musica Vera" in prompt
    assert "Samstag, 12. Juli" in prompt


def test_ueberleitung_steht_am_ende_des_vorigen_kapitels_und_abspann_am_schluss():
    antwort = {
        "dokumentart": "eine Zusammenfassung",
        "ueberleitungen": {"1": "Es folgt, was daraus folgt."},
        "abspann": "Das war die Zusammenfassung. Die Kernaussage lautet: Fragen vor Antworten.",
    }
    neu, warnungen = inszeniere(
        ZUSAMMENFASSUNG,
        rollenbild(ZUSAMMENFASSUNG_ROLLEN["rollen"], "Zusammenfassung"),
        textmodell=Modell(antwort),
    )
    assert [k.titel for k in neu.kapitel] == ["", "Worum es geht", "Was daraus folgt", ""]
    assert neu.kapitel[1].absaetze[-1] == "Es folgt, was daraus folgt."
    assert neu.kapitel[1].arten == ("wortlaut", "ueberleitung")
    assert neu.kapitel[2].arten == ("wortlaut",)
    assert neu.kapitel[3].arten == ("abspann",)
    assert "neu formuliert (ueberleitung): „Es folgt, was daraus folgt.“" in warnungen
    assert any(w.startswith("neu formuliert (abspann)") for w in warnungen)


def test_ueberleitung_vor_dem_ersten_kapitel_wird_verworfen():
    antwort = {"ueberleitungen": {"0": "Los geht es."}, "abspann": ""}
    neu, warnungen = inszeniere(
        ZUSAMMENFASSUNG,
        rollenbild(ZUSAMMENFASSUNG_ROLLEN["rollen"]),
        textmodell=Modell(antwort),
    )
    assert all("ueberleitung" not in k.arten for k in neu.kapitel)
    assert any("verworfen (ueberleitung)" in w for w in warnungen)


def test_saetze_werden_auf_die_obergrenze_gekuerzt():
    viel = "Eins ist es. Zwei ist es. Drei ist es. Vier ist es. Fünf ist es."
    antwort = {"thema": viel, "ueberleitungen": {"1": viel}, "abspann": viel}
    quelle = Dokument(
        "T",
        None,
        "de",
        (
            Kapitel("A", ("Eins ist es. Zwei ist es. Drei ist es. Vier ist es. Fünf ist es.",)),
            Kapitel("B", ("Anderer Text hier.",)),
        ),
    )
    neu, _ = inszeniere(quelle, Rollenbild("x", {}), textmodell=Modell(antwort))
    assert neu.kapitel[0].absaetze[0] == "Eins ist es. Zwei ist es."  # Thema: zwei Saetze
    assert neu.kapitel[1].absaetze[-1] == "Eins ist es."
    assert neu.kapitel[-1].absaetze[0] == "Eins ist es. Zwei ist es. Drei ist es. Vier ist es."


def test_neu_formuliert_mit_fremder_zahl_wird_verworfen():
    antwort = {
        "thema": "Es geht um den 13. Juli.",  # 13 steht nicht in der Quelle
        "ueberleitungen": {},
        "abspann": "Es spielten dreißig Streicher.",  # Zahlwort, nicht in der Quelle
    }
    neu, warnungen = inszeniere(
        PROGRAMM, rollenbild(PROGRAMM_OHNE_UEBERSCHRIFT), textmodell=Modell(antwort)
    )
    assert len(neu.kapitel) == 1 and neu.kapitel[0].arten[0] == "wortlaut"
    verworfen = [w for w in warnungen if "verworfen" in w]
    assert len(verworfen) == 2
    assert "13" in verworfen[0] and "dreißig" in verworfen[1]
    assert not any(w.startswith("neu formuliert (") for w in warnungen)


def test_zahl_aus_der_quelle_ist_erlaubt():
    antwort = {"thema": "Es ist Seite 12, die Sinfonie Nr. 3.", "ueberleitungen": {}}
    neu, _ = inszeniere(PROGRAMM, rollenbild(PROGRAMM_ROLLEN["rollen"]), textmodell=Modell(antwort))
    assert "Es ist Seite 12, die Sinfonie Nr. 3." in kopfseite_von(neu)


def test_unbrauchbare_ansagen_antwort_einmal_nachfragen_dann_ohne_ansagen():
    modell = Modell("kein json", {"titel": 5})
    neu, warnungen = inszeniere(PROGRAMM, rollenbild(PROGRAMM_ROLLEN["rollen"]), textmodell=modell)
    assert len(modell.aufrufe) == 2
    assert neu.kapitel[0].arten[0] in QUELL_ARTEN  # der Wortlaut bleibt, nur ohne Ansagen
    assert any("Ansagen" in w for w in warnungen)


def test_zu_viel_weggelassen_faellt_zurueck():
    # Mehr als die Haelfte aller Woerter ist als Bildunterschrift ausgezeichnet.
    rollen = dict(PROGRAMM_ROLLEN["rollen"])
    rollen["0.3"] = "bildunterschrift"
    rollen["0.6"] = "bildunterschrift"
    rollen["0.2"] = "haupttext"
    modell = Modell(KEINE_ANSAGEN)
    neu, warnungen = inszeniere(PROGRAMM, rollenbild(rollen), textmodell=modell)
    assert neu == PROGRAMM
    assert neu.kapitel[0].arten == ()
    assert any("Rückfall" in w and "50" in w for w in warnungen)
    assert modell.aufrufe == []  # nach dem Rueckfall wird nichts mehr gefragt


def test_ohne_haupttext_faellt_zurueck():
    rollen = {k: "ueberschrift" for k in PROGRAMM_ROLLEN["rollen"]}
    neu, warnungen = inszeniere(PROGRAMM, rollenbild(rollen), textmodell=Modell(KEINE_ANSAGEN))
    assert neu == PROGRAMM
    assert any("Rückfall" in w and "Haupttext" in w for w in warnungen)


def test_kapitel_ohne_sprechbaren_text_entfaellt_mit_warnung():
    quelle = Dokument(
        "T",
        None,
        "de",
        (
            Kapitel("Erster Teil", ("Ein langer Absatz mit genug Worten zum Vorlesen hier.",)),
            Kapitel("Anhang", ("Kurze Notiz.",)),
        ),
    )
    bild = Rollenbild("x", {(1, 0): "fussnote"})
    neu, warnungen = inszeniere(quelle, bild, textmodell=Modell(KEINE_ANSAGEN))
    assert [k.titel for k in neu.kapitel] == ["Erster Teil"]
    assert any("Anhang" in w for w in warnungen)


def test_warnungen_des_verstehens_werden_weitergereicht():
    bild = Rollenbild("x", {}, warnungen=("Rollen nicht erkannt: Test",))
    _, warnungen = inszeniere(PROGRAMM, bild, textmodell=Modell(KEINE_ANSAGEN))
    assert warnungen[0] == "Rollen nicht erkannt: Test"


# ---- regie ---------------------------------------------------------------------------


def test_ohne_modell_unveraendert_mit_warnung():
    neu, warnungen = mache_regie(PROGRAMM, textmodell=None)
    assert neu is PROGRAMM
    assert warnungen == ("Ohne Sprachmodell: keine Regie",)


def test_regie_beides_zusammen():
    weiche = Weiche(
        ZUSAMMENFASSUNG_ROLLEN,
        kopf(dokumentart="eine Zusammenfassung"),
    )
    neu, warnungen = mache_regie(ZUSAMMENFASSUNG, textmodell=weiche)
    assert len(weiche.aufrufe) == 2
    assert kopfseite_von(neu)[0] == "Sie hören eine Zusammenfassung."
    assert neu.warnungen == ZUSAMMENFASSUNG.warnungen
    assert "weggelassen: Bedienelemente (2)" in warnungen
    assert isinstance(warnungen, tuple)


# ---- typen: Kapitel.arten --------------------------------------------------------------


def test_arten_laenge_wird_geprueft():
    assert Kapitel("K", ("a", "b")).arten == ()  # leer heisst: alles Wortlaut
    assert Kapitel("K", ("a", "b"), arten=("vorspann", "wortlaut")).arten == (
        "vorspann",
        "wortlaut",
    )
    with pytest.raises(Mp4Fehler, match="arten"):
        Kapitel("K", ("a", "b"), arten=("wortlaut",))
    with pytest.raises(Mp4Fehler, match="arten"):
        Kapitel("K", ("a",), arten=("wortlaut", "wortlaut"))


def test_unbekannte_art_wird_abgewiesen():
    with pytest.raises(Mp4Fehler, match="Art"):
        Kapitel("K", ("a",), arten=("werbung",))


def test_ordnungszahl_bis_kapitelzahl_erlaubt():
    """„das zweite Kapitel“ ist Ansage, keine Erfindung -- aber nur bis zur Kapitelzahl."""
    antwort = {
        "thema": "Es folgen zwei Teile.",  # Grundzahl, nicht in der Quelle: streng
        "ueberleitungen": {"1": "Hören wir nun das zweite Kapitel."},
        "abspann": "Das war das dritte Kapitel.",  # es gibt nur zwei gesprochene
    }
    neu, warnungen = inszeniere(
        ZUSAMMENFASSUNG, rollenbild(ZUSAMMENFASSUNG_ROLLEN["rollen"]), textmodell=Modell(antwort)
    )

    assert neu.kapitel[0].absaetze[-1] == "Hören wir nun das zweite Kapitel."
    assert neu.kapitel[0].arten == ("wortlaut", "ueberleitung")
    verworfen = [w for w in warnungen if "verworfen" in w]
    assert len(verworfen) == 2
    assert "zwei" in verworfen[0] and "dritte" in verworfen[1]


@pytest.mark.parametrize(
    "wort", ["erste", "ersten", "zweiter", "fünftes", "zwölfte", "zwanzigsten"]
)
def test_ordnungszahlwoerter_in_allen_endungen(wort):
    kapitel = tuple(Kapitel(f"K{i}", (f"Text Nummer {i} hier.",)) for i in range(20))
    quelle = Dokument("T", None, "de", kapitel)
    antwort = {"thema": f"Das ist das {wort} Kapitel.", "ueberleitungen": {}, "abspann": ""}

    neu, warnungen = inszeniere(quelle, Rollenbild("x", {}), textmodell=Modell(antwort))

    assert f"Das ist das {wort} Kapitel." in kopfseite_von(neu), warnungen


# ---- gesprochene Kopfseite ---------------------------------------------------------------

# 70 Woerter Haupttext in zwei Kapiteln: rund eine Minute bei 140 Woertern je Minute.


def viele_worte(n: int) -> str:
    """Ein Absatz aus genau n Woertern, die keine Zahlen sind."""
    return " ".join(["Wort"] * n)


def dokument_mit_umfang(*woerter_je_kapitel: int, titel: str = "Muster") -> Dokument:
    kapitel = tuple(
        Kapitel(f"Teil {chr(65 + i)}", (viele_worte(n),)) for i, n in enumerate(woerter_je_kapitel)
    )
    return Dokument(titel, None, "de", kapitel)


def test_kopfseite_feste_reihenfolge():
    modell = Modell(
        kopf(
            dokumentart="eine Buchzusammenfassung",
            titel="Die Kunst des Zuhörens",
            herkunft="Erika Beispiel",
            thema="Es geht um das Zuhören. Wer zuhört, versteht mehr.",
        )
    )
    neu, _ = inszeniere(
        ZUSAMMENFASSUNG,
        rollenbild(ZUSAMMENFASSUNG_ROLLEN["rollen"], "Zusammenfassung"),
        textmodell=modell,
    )

    assert kopfseite_von(neu) == (
        "Sie hören eine Buchzusammenfassung „Die Kunst des Zuhörens“ von Erika Beispiel.",
        "Es geht um das Zuhören. Wer zuhört, versteht mehr.",
        "Es dauert rund eine Minute und hat zwei Abschnitte: „Worum es geht“ und "
        "„Was daraus folgt“.",
    )
    assert neu.kapitel[0].titel == ""  # die Kopfseite ist ein eigenes Kapitel vor dem Text


def test_kopfseite_herkunft_datum_ort_mit_komma():
    antwort = kopf(
        dokumentart="ein Programmheft",
        titel="Sommerkonzert",
        herkunft="Kammerorchester Musica Vera",
        datum="Samstag, 12. Juli",
        ort="Schlosshof Wiesenburg",
    )
    neu, _ = inszeniere(PROGRAMM, rollenbild(PROGRAMM_ROLLEN["rollen"]), textmodell=Modell(antwort))
    assert kopfseite_von(neu)[0] == (
        "Sie hören ein Programmheft „Sommerkonzert“ von Kammerorchester Musica Vera, "
        "Samstag, 12. Juli, Schlosshof Wiesenburg."
    )
    # Nur der Ort belegt: kein "von" fuer die fehlende Herkunft.
    neu, _ = inszeniere(
        PROGRAMM,
        rollenbild(PROGRAMM_ROLLEN["rollen"]),
        textmodell=Modell(kopf(titel="Sommerkonzert", ort="Schlosshof Wiesenburg")),
    )
    assert kopfseite_von(neu)[0] == "Sie hören „Sommerkonzert“, Schlosshof Wiesenburg."


def test_kopfseite_unbelegtes_feld_entfaellt():
    antwort = kopf(
        dokumentart="ein Programmheft",
        titel="Sommerkonzert",
        herkunft="Kammerorchester Musica Vera",
        datum="Samstag, 13. Juli",  # 13 steht nicht in der Quelle
        ort="",  # leer: entfaellt ohne Meldung
        thema="Es spielen dreißig Musiker.",  # Zahlwort, nicht in der Quelle
    )
    neu, warnungen = inszeniere(
        PROGRAMM, rollenbild(PROGRAMM_ROLLEN["rollen"]), textmodell=Modell(antwort)
    )

    zeilen = kopfseite_von(neu)
    assert (
        zeilen[0] == "Sie hören ein Programmheft „Sommerkonzert“ von Kammerorchester Musica Vera."
    )
    text = " ".join(zeilen)
    assert "13" not in text and "dreißig" not in text
    verworfen = [w for w in warnungen if "verworfen" in w]
    assert len(verworfen) == 2
    assert "datum" in verworfen[0] and "13" in verworfen[0]
    assert "thema" in verworfen[1] and "dreißig" in verworfen[1]
    assert not any("ort" in w for w in verworfen)


def test_kopfseite_ohne_belegte_felder_gibt_keine_kopfseite():
    neu, _ = inszeniere(
        PROGRAMM, rollenbild(PROGRAMM_OHNE_UEBERSCHRIFT), textmodell=Modell(KEINE_ANSAGEN)
    )
    assert kopfseite_von(neu) == ()
    assert neu.kapitel[0].titel == PROGRAMM.kapitel[0].titel


@pytest.mark.parametrize(
    ("woerter", "erwartet"),
    [
        (20, "eine Minute"),  # nie unter einer Minute
        (140, "eine Minute"),
        (210, "zwei Minuten"),  # 1,5 rundet auf
        (1260, "neun Minuten"),  # unter 10: auf 1
        (1400, "zehn Minuten"),
        (1540, "zehn Minuten"),  # ab 10: auf 5 (11 -> 10)
        (1820, "fünfzehn Minuten"),  # 13 -> 15
    ],
)
def test_kopfseite_umfang_gerundet(woerter, erwartet):
    quelle = dokument_mit_umfang(woerter)
    neu, _ = inszeniere(quelle, Rollenbild("x", {}), textmodell=Modell(kopf(titel="Muster")))
    assert kopfseite_von(neu)[1] == f"Es dauert rund {erwartet}."


def test_kopfseite_umfang_und_gliederung():
    quelle = dokument_mit_umfang(140, 70, 70)  # drei Abschnitte, 280 Woerter = zwei Minuten
    neu, _ = inszeniere(
        quelle, Rollenbild("x", {}), textmodell=Modell(kopf(dokumentart="einen Text"))
    )
    assert kopfseite_von(neu) == (
        "Sie hören einen Text.",
        "Es dauert rund zwei Minuten und hat drei Abschnitte: „Teil A“, „Teil B“ und „Teil C“.",
    )


def test_kopfseite_viele_abschnitte_nur_zahl():
    sechs = dokument_mit_umfang(*[40] * 6)
    sieben = dokument_mit_umfang(*[40] * 7)
    modell = lambda: Modell(kopf(dokumentart="einen Text"))  # noqa: E731
    neu6, _ = inszeniere(sechs, Rollenbild("x", {}), textmodell=modell())
    neu7, _ = inszeniere(sieben, Rollenbild("x", {}), textmodell=modell())

    assert kopfseite_von(neu6)[1] == (
        "Es dauert rund zwei Minuten und hat sechs Abschnitte: „Teil A“, „Teil B“, „Teil C“, "
        "„Teil D“, „Teil E“ und „Teil F“."
    )
    assert kopfseite_von(neu7)[1:] == (
        "Es dauert rund zwei Minuten und hat sieben Abschnitte.",
        "Es beginnt mit „Teil A“.",
    )


def test_kopfseite_ein_abschnitt_ohne_gliederung_und_ohne_doppelten_titel():
    # Ein einziger Abschnitt traegt den Titel des Dokuments: weder Gliederung noch "mit ...".
    quelle = Dokument("Muster", None, "de", (Kapitel("Muster", (viele_worte(70),)),))
    neu, _ = inszeniere(quelle, Rollenbild("x", {}), textmodell=Modell(kopf(titel="Muster")))
    assert kopfseite_von(neu) == ("Sie hören „Muster“.", "Es dauert rund eine Minute.")


def test_kopfseite_abschnitt_ohne_titel_beginnt_ohne_namen():
    quelle = Dokument("Muster", None, "de", (Kapitel("", (viele_worte(70),)),))
    neu, _ = inszeniere(
        quelle, Rollenbild("x", {}), textmodell=Modell(kopf(dokumentart="einen Text"))
    )
    assert kopfseite_von(neu)[-1] == "Es dauert rund eine Minute."


def test_kopfseite_hoechstens_hundert_woerter_thema_wird_ein_satz():
    satz = " ".join(["Wort"] * 59)
    thema = f"Anfang {satz}. Schluss {satz}."  # zwei Saetze zu je 60 Woertern
    neu, _ = inszeniere(
        dokument_mit_umfang(70),
        Rollenbild("x", {}),
        textmodell=Modell(kopf(dokumentart="einen Text", thema=thema)),
    )
    zeilen = kopfseite_von(neu)
    assert f"Anfang {satz}." in zeilen and "Schluss" not in " ".join(zeilen)
    # Passen beide Saetze noch hinein, bleiben beide.
    kurz = "Es geht um Wort. Und um mehr."
    neu, _ = inszeniere(
        dokument_mit_umfang(70),
        Rollenbild("x", {}),
        textmodell=Modell(kopf(dokumentart="einen Text", thema=kurz)),
    )
    assert kurz in kopfseite_von(neu)


def test_kopfseite_titel_ohne_anfuehrungszeichen_der_vorlage_doppelt():
    neu, _ = inszeniere(
        dokument_mit_umfang(70),
        Rollenbild("x", {}),
        textmodell=Modell(kopf(dokumentart="einen Text", titel="„Muster“")),
    )
    assert kopfseite_von(neu)[0] == "Sie hören einen Text „Muster“."


def test_prompt_nennt_die_felder_der_kopfseite():
    for feld in ("dokumentart", "titel", "herkunft", "datum", "ort", "thema"):
        assert f'"{feld}"' in PROMPT_INSZENIEREN
    assert '"vorspann"' not in PROMPT_INSZENIEREN


# ---- verwaiste Ueberschriften ------------------------------------------------------------


def test_ueberschrift_ohne_gesprochenen_text_faellt_weg():
    quelle = Dokument(
        "T",
        None,
        "de",
        (
            Kapitel(
                "K",
                (
                    "Erste Überschrift",  # 0 gefolgt von einer Ueberschrift: verwaist
                    "Zweite Überschrift",  # 1 Text folgt: bleibt
                    "Ein Absatz Haupttext, den man hören soll.",  # 2
                    "Dritte Überschrift",  # 3 nur Beiwerk dazwischen, dann Ende: verwaist
                    "Foto: etwas",  # 4
                    "Vierte Überschrift",  # 5 Kapitelende: verwaist
                ),
            ),
        ),
    )
    rollen = {
        (0, 0): "ueberschrift",
        (0, 1): "ueberschrift",
        (0, 2): "haupttext",
        (0, 3): "ueberschrift",
        (0, 4): "bildunterschrift",
        (0, 5): "ueberschrift",
    }
    modell = Modell(kopf(titel="Ein eigener Titel"))
    neu, warnungen = inszeniere(quelle, Rollenbild("x", rollen), textmodell=modell)

    assert neu.kapitel[-1].absaetze == (
        "Zweite Überschrift",
        "Ein Absatz Haupttext, den man hören soll.",
    )
    assert "weggelassen: Überschriften ohne Text (3)" in warnungen
    assert "weggelassen: Bildunterschriften (1)" in warnungen


def test_verwaiste_leser_ueberschrift_faellt_weg_wie_die_der_regie():
    """Vorrang (Plan A1): die Verwaist-Erkennung folgt der Art des Lesers, nicht nur der Rolle.

    Das Rollenbild kennt keine Ueberschrift (alles Haupttext); die Ueberschriften kommen vom
    Leser. Eine auf eine Ueberschrift folgende und eine am Kapitelende stehende ist verwaist --
    genau wie bei einer Ueberschrift der Regie.
    """
    quelle = Dokument(
        "T",
        None,
        "de",
        (
            Kapitel(
                "K",
                (
                    "Erste Überschrift",  # folgt eine Ueberschrift: verwaist
                    "Zweite Überschrift",  # Text folgt: bleibt
                    "Ein Absatz Haupttext, den man hören soll.",
                    "Ein Ausblick",  # Kapitelende: verwaist
                ),
                ("ueberschrift", "ueberschrift", "wortlaut", "ueberschrift"),
            ),
        ),
    )

    neu, warnungen = inszeniere(
        quelle, Rollenbild("x", {}), textmodell=Modell(kopf(titel="Ein eigener Titel"))
    )

    assert neu.kapitel[-1].absaetze == (
        "Zweite Überschrift",
        "Ein Absatz Haupttext, den man hören soll.",
    )
    assert neu.kapitel[-1].arten == ("ueberschrift", "wortlaut")
    assert "weggelassen: Überschriften ohne Text (2)" in warnungen


def test_ueberschriften_mit_text_erzeugen_keine_meldung():
    bild = rollenbild(PROGRAMM_ROLLEN["rollen"])
    _, warnungen = inszeniere(PROGRAMM, bild, textmodell=Modell(KEINE_ANSAGEN))
    assert not any("Überschriften ohne Text" in w for w in warnungen)


# ---- Titel nicht doppelt -----------------------------------------------------------------


def titel_dokument(erste_zeile: str) -> Dokument:
    return Dokument(
        "Das Muster-Prinzip",
        None,
        "de",
        (
            Kapitel(
                "Das Muster-Prinzip",
                (erste_zeile, "Ein Absatz Haupttext, den man hören soll.", erste_zeile),
            ),
        ),
    )


ROLLEN_TITEL = {(0, 0): "ueberschrift", (0, 1): "haupttext", (0, 2): "haupttext"}


@pytest.mark.parametrize(
    "zeile", ["Das Muster-Prinzip", "BUCH Das Muster-Prinzip", "BUCH SERIE Das Muster-Prinzip"]
)
def test_titelzeile_nicht_doppelt_nach_kopfseite(zeile):
    quelle = titel_dokument(zeile)
    modell = Modell(kopf(dokumentart="ein Buch", titel="Das Muster-Prinzip"))
    neu, warnungen = inszeniere(quelle, Rollenbild("x", ROLLEN_TITEL), textmodell=modell)

    wortlaut = [
        a
        for k in neu.kapitel
        for a, art in zip(k.absaetze, k.arten, strict=True)
        if art == "wortlaut"
    ]
    # Nur die ERSTE Zeile entfaellt; die Wiederholung am Ende steht in der Quelle und bleibt.
    assert wortlaut == ["Ein Absatz Haupttext, den man hören soll.", zeile]
    assert any("Titelzeile" in w for w in warnungen)


def test_titelzeile_bleibt_ohne_titel_in_der_kopfseite():
    # Ohne Ueberschrift-Rolle gibt es auch keinen Rueckfall-Titel: die Zeile bleibt Text.
    quelle = titel_dokument("Das Muster-Prinzip")
    neu, _ = inszeniere(
        quelle, Rollenbild("x", {}), textmodell=Modell(kopf(dokumentart="ein Buch"))
    )
    assert neu.kapitel[1].absaetze[0] == "Das Muster-Prinzip"


def test_titelzeile_bleibt_wenn_sie_mehr_ist_als_der_titel():
    quelle = titel_dokument("Das Muster-Prinzip und seine Folgen")
    modell = Modell(kopf(titel="Das Muster-Prinzip"))
    neu, _ = inszeniere(quelle, Rollenbild("x", ROLLEN_TITEL), textmodell=modell)
    assert neu.kapitel[1].absaetze[0] == "Das Muster-Prinzip und seine Folgen"


# ---- Ordnungszahlen ----------------------------------------------------------------------


def test_ordnungszahl_aus_ziffer_der_quelle_erlaubt():
    # In der Quelle steht "Nr. 3" und "12.": "dritte" und "zwölfte" nennen Zahlen der Quelle.
    # Die Kapitelzahl (hier 1) ist dafuer nicht noetig.
    antwort = kopf(
        thema="Im Schlosshof steht die dritte Sinfonie.",
        abspann="Das war die zwölfte Sinfonie.",
    )
    neu, warnungen = inszeniere(
        PROGRAMM, rollenbild(PROGRAMM_ROLLEN["rollen"]), textmodell=Modell(antwort)
    )
    assert "Im Schlosshof steht die dritte Sinfonie." in kopfseite_von(neu)
    assert neu.kapitel[-1].absaetze == ("Das war die zwölfte Sinfonie.",)
    assert not any("verworfen" in w for w in warnungen)


def test_ordnungszahl_ohne_ziffer_in_der_quelle_bleibt_streng():
    # Oberhalb der kleinen Zaehlwoerter (bis zwoelf) und ohne Ziffer in der Quelle.
    antwort = kopf(
        thema="Hören wir die siebzehnte Sinfonie.", abspann="Das war die neunzehnte Sinfonie."
    )
    neu, warnungen = inszeniere(
        PROGRAMM, rollenbild(PROGRAMM_OHNE_UEBERSCHRIFT), textmodell=Modell(antwort)
    )
    assert kopfseite_von(neu) == ()
    verworfen = [w for w in warnungen if "verworfen" in w]
    assert len(verworfen) == 2
    assert "siebzehnte" in verworfen[0] and "neunzehnte" in verworfen[1]


# ---- kleine Zaehlwoerter in Ansagen --------------------------------------------------------


def test_kleines_zaehlwort_erlaubt():
    # "zwei" und "vierte" stehen nicht in der Quelle, sind aber Zaehlwoerter ohne Einheit.
    antwort = kopf(
        thema="Das Orchester stellt zwei Sinfonien vor, das vierte folgt nach der Pause."
    )
    neu, warnungen = inszeniere(
        PROGRAMM, rollenbild(PROGRAMM_OHNE_UEBERSCHRIFT), textmodell=Modell(antwort)
    )
    assert (
        "Das Orchester stellt zwei Sinfonien vor, das vierte folgt nach der Pause."
        in kopfseite_von(neu)
    )
    assert not any("verworfen" in w for w in warnungen)


@pytest.mark.parametrize(
    "thema",
    [
        "Der Eintritt kostet zwei Euro.",
        "Es kommen zwei Millionen Gäste.",
        "Das Werk entstand vor vier Jahren.",
        "Der Abend beginnt um acht Uhr.",
        "Das Heft wiegt drei Kilogramm.",
        "Die Preise steigen um fünf Prozent.",
        "Der Eintritt kostet zwei €.",
    ],
)
def test_zaehlwort_mit_einheit_bleibt_streng(thema):
    neu, warnungen = inszeniere(
        PROGRAMM, rollenbild(PROGRAMM_OHNE_UEBERSCHRIFT), textmodell=Modell(kopf(thema=thema))
    )
    assert kopfseite_von(neu) == ()
    verworfen = [w for w in warnungen if "verworfen" in w]
    assert len(verworfen) == 1 and "Zahl nicht in der Quelle" in verworfen[0]


@pytest.mark.parametrize(
    "thema",
    [
        "Das Konzert findet am vierten Juli statt.",
        "Es geht am sechsten Dezember los.",
        "Am zehnten März ist Premiere.",
    ],
)
def test_zaehlwort_als_datum_bleibt_streng(thema):
    neu, warnungen = inszeniere(
        PROGRAMM, rollenbild(PROGRAMM_OHNE_UEBERSCHRIFT), textmodell=Modell(kopf(thema=thema))
    )
    assert kopfseite_von(neu) == ()
    assert len([w for w in warnungen if "verworfen" in w]) == 1


def test_datum_mit_ordnungszahl_unter_der_kapitelzahl_bleibt_streng():
    # Zwei gesprochene Kapitel: "zweiten" waere als Kapitelverweis erlaubt, als Datum nicht.
    ohne = kopf(thema="Hören wir nun das zweite Kapitel.")
    mit = kopf(thema="Hören wir am zweiten Juli das Kapitel.")
    rollen = rollenbild(ZUSAMMENFASSUNG_ROLLEN["rollen"])
    neu_ohne, _ = inszeniere(ZUSAMMENFASSUNG, rollen, textmodell=Modell(ohne))
    neu_mit, warnungen = inszeniere(ZUSAMMENFASSUNG, rollen, textmodell=Modell(mit))
    assert "Hören wir nun das zweite Kapitel." in kopfseite_von(neu_ohne)
    assert kopfseite_von(neu_mit) == ()
    assert len([w for w in warnungen if "verworfen" in w]) == 1


def test_zaehlwort_als_kapitelzahl_bleibt_an_die_hoerfassung_gebunden():
    # "zwei Abschnitte" nennt eine Zahl der Gliederung, die der Code rechnet, nicht das Modell.
    antwort = kopf(thema="Es folgen zwei Abschnitte.")
    neu, warnungen = inszeniere(
        PROGRAMM, rollenbild(PROGRAMM_OHNE_UEBERSCHRIFT), textmodell=Modell(antwort)
    )
    assert kopfseite_von(neu) == ()
    assert len([w for w in warnungen if "verworfen" in w]) == 1


def test_ziffer_bleibt_streng_auch_als_zaehlwort_stelle():
    antwort = kopf(thema="Das Heft stellt 2 Werke vor.")
    neu, warnungen = inszeniere(
        PROGRAMM, rollenbild(PROGRAMM_OHNE_UEBERSCHRIFT), textmodell=Modell(antwort)
    )
    assert kopfseite_von(neu) == ()
    assert any("verworfen" in w and "2" in w for w in warnungen)


# ---- Titel und Gliederung aus den Ueberschriften -----------------------------------------


def ueberschriften_dokument(*zeilen: str, dateiname: str = "scan_0042") -> Dokument:
    """Ein Kapitel; jede Zeile "# Text" ist eine Ueberschrift, jede andere Haupttext."""
    return Dokument(
        dateiname, None, "de", (Kapitel(dateiname, tuple(z.lstrip("# ") for z in zeilen)),)
    )


def rollen_der(*zeilen: str) -> Rollenbild:
    return Rollenbild(
        "x",
        {
            (0, i): "ueberschrift" if z.startswith("# ") else "haupttext"
            for i, z in enumerate(zeilen)
        },
    )


def test_kopfseite_titel_aus_erster_ueberschrift():
    zeilen = ("# Der Klang der Dämmerung!", viele_worte(70))
    modell = Modell(kopf(dokumentart="einen Text"))  # das Modell nennt keinen Titel
    neu, warnungen = inszeniere(
        ueberschriften_dokument(*zeilen), rollen_der(*zeilen), textmodell=modell
    )
    assert kopfseite_von(neu)[0] == "Sie hören einen Text „Der Klang der Dämmerung“."
    assert "scan_0042" not in " ".join(kopfseite_von(neu))
    # Die Titelzeile steht nun in der Kopfseite und nicht noch einmal im Text.
    assert neu.kapitel[1].absaetze == (viele_worte(70),)
    assert any("ersten Überschrift" in w for w in warnungen)
    # Der Auftrag zeigt dem Modell die Ueberschrift und sagt, dass sie Titel sein darf.
    assert "Der Klang der Dämmerung" in modell.prompts[0]


def test_kopfseite_titel_aus_leser_ueberschrift_die_das_modell_haupttext_nennt():
    """Vorrang (Plan A1): die erste Ueberschrift der Vorlage folgt der Art des Lesers.

    Das Rollenbild nennt die Zeile Haupttext; der Leser kennt sie aus dem Layout als
    Ueberschrift -- sie ist der Titel, nicht die naechste Ueberschrift oder gar keine.
    """
    quelle = Dokument(
        "T",
        None,
        "de",
        (
            Kapitel(
                "K",
                ("Der Klang der Dämmerung", viele_worte(70)),
                ("ueberschrift", "wortlaut"),
            ),
        ),
    )
    rollen = Rollenbild("x", {(0, 0): "haupttext", (0, 1): "haupttext"})
    modell = Modell(kopf(dokumentart="einen Text"))  # das Modell nennt keinen Titel

    neu, warnungen = inszeniere(quelle, rollen, textmodell=modell)

    assert kopfseite_von(neu)[0] == "Sie hören einen Text „Der Klang der Dämmerung“."
    assert "Der Klang der Dämmerung" in modell.prompts[0]
    assert any("ersten Überschrift" in w for w in warnungen)


def test_kopfseite_titel_des_modells_hat_vorrang_vor_der_ueberschrift():
    zeilen = ("# Erste Überschrift", viele_worte(70))
    modell = Modell(kopf(dokumentart="einen Text", titel="Erste Überschrift Wort"))
    neu, _ = inszeniere(ueberschriften_dokument(*zeilen), rollen_der(*zeilen), textmodell=modell)
    assert kopfseite_von(neu)[0] == "Sie hören einen Text „Erste Überschrift Wort“."


def test_kopfseite_ohne_ueberschrift_hat_keinen_titel_und_nie_den_dateinamen():
    zeilen = (viele_worte(70),)
    modell = Modell(kopf(dokumentart="einen Text"))
    neu, _ = inszeniere(ueberschriften_dokument(*zeilen), rollen_der(*zeilen), textmodell=modell)
    assert kopfseite_von(neu)[0] == "Sie hören einen Text."


def test_kopfseite_gliederung_aus_zwischenueberschriften():
    zeilen = (
        "# Der Klang der Dämmerung",
        "# Die Anfänge",
        viele_worte(40),
        "# Die Folgen",
        viele_worte(30),
    )
    modell = Modell(kopf(dokumentart="einen Text"))
    neu, _ = inszeniere(ueberschriften_dokument(*zeilen), rollen_der(*zeilen), textmodell=modell)
    assert kopfseite_von(neu) == (
        "Sie hören einen Text „Der Klang der Dämmerung“.",
        "Es dauert rund eine Minute und hat zwei Abschnitte: „Die Anfänge“ und „Die Folgen“.",
    )


def test_gliederung_aus_ueberschriften_auch_wenn_text_davor_steht():
    zeilen = (
        "# Der Klang der Dämmerung",
        viele_worte(20),
        "# Die Anfänge",
        viele_worte(20),
        "# Die Folgen",
        viele_worte(30),
    )
    modell = Modell(kopf(dokumentart="einen Text"))
    neu, _ = inszeniere(ueberschriften_dokument(*zeilen), rollen_der(*zeilen), textmodell=modell)
    assert kopfseite_von(neu)[1:] == (
        "Es dauert rund eine Minute und hat zwei Abschnitte: „Die Anfänge“ und „Die Folgen“.",
    )


@pytest.mark.parametrize("anzahl", [1, 7])
def test_gliederung_aus_ueberschriften_nur_von_zwei_bis_sechs(anzahl):
    zeilen = ["# Der Klang der Dämmerung"]
    for i in range(anzahl):
        zeilen += [f"# Abschnitt {chr(65 + i)}", viele_worte(20)]
    modell = Modell(kopf(dokumentart="einen Text"))
    neu, _ = inszeniere(ueberschriften_dokument(*zeilen), rollen_der(*zeilen), textmodell=modell)
    # Ein Kapitel, also kein Abschnittswechsel: weder Titel noch Zahl der Ueberschriften.
    assert "Abschnitten" not in " ".join(kopfseite_von(neu))


def test_mehrere_kapitel_behalten_ihre_gliederung_nach_kapiteln():
    quelle = dokument_mit_umfang(70, 70)
    rollen = Rollenbild("x", {})
    neu, _ = inszeniere(quelle, rollen, textmodell=Modell(kopf(dokumentart="einen Text")))
    assert kopfseite_von(neu)[1] == (
        "Es dauert rund eine Minute und hat zwei Abschnitte: „Teil A“ und „Teil B“."
    )


# ---- Beleg der Ansagen gegen Erfinden --------------------------------------------------------

ERFUNDEN = Dokument(
    titel="Muster",
    autor=None,
    sprache="de",
    kapitel=(
        Kapitel(
            "Erstes",
            (
                "Der Fluss fließt ruhig durch das Tal und die Vögel singen am Morgen.",
                "Die Bewohner gehen zur Arbeit, und abends kehren sie zurück.",
            ),
        ),
        Kapitel("Zweites", ("Im Winter liegt Schnee auf den Dächern, und die Kinder spielen.",)),
    ),
)


def test_erfundene_namen_orte_und_aussagen_werden_verworfen():
    """Die Probe des Pruefers: nichts davon steht in der Quelle, nichts davon wird gesprochen."""
    antwort = {
        "dokumentart": "ein Roman des Nobelpreisträgers",
        "titel": "Der Zauberberg",
        "herkunft": "Thomas Mann, S. Fischer Verlag",
        "datum": "im Juli",
        "ort": "Davos",
        "thema": "Der Autor wurde wegen Betrugs verurteilt. Drei Menschen starben im Tal.",
        "ueberleitungen": {"1": "Hören wir nun das zweite Kapitel, in dem zwei Mörder auftreten."},
        "abspann": "Der Verlag empfiehlt den Kauf. Es gab sieben Tote.",
    }
    neu, warnungen = inszeniere(ERFUNDEN, Rollenbild("ein Text", {}), textmodell=Modell(antwort))

    gesprochen = " ".join(a for k in neu.kapitel for a in k.absaetze)
    for erfunden in (
        "Zauberberg", "Thomas", "Fischer", "Davos", "Juli", "Nobelpreis", "Betrug", "Menschen",
        "Mörder", "Verlag", "Tote", "Autor",
    ):  # fmt: skip
        assert erfunden not in gesprochen, erfunden
    assert all(art == "wortlaut" for k in neu.kapitel for art in k.arten)
    assert len(neu.kapitel) == 2  # keine Kopfseite, kein Abspann: nichts war belegt
    verworfen = [w for w in warnungen if w.startswith("Ansage verworfen")]
    assert all("nicht in der Quelle belegt (" in w for w in verworfen)
    for erfunden in ("Zauberberg", "Thomas", "Davos", "Juli", "Menschen", "Mörder", "Verlag"):
        assert any(erfunden in w for w in verworfen), erfunden
    assert not any(w.startswith("neu formuliert") for w in warnungen)


BELEGT = Dokument(
    titel="Der Zauberwald",
    autor="Erika Beispiel",
    sprache="de",
    kapitel=(
        Kapitel(
            "Wiesenburg im Juli",
            (
                "Im Juli war Wiesenburg voller Gäste. Der Verlag Lindenblatt druckte das Heft.",
                "Die Bewohnern des Zauberwalds erzählen vom Winter.",
            ),
        ),
        Kapitel("Der Winter", ("Im Winter liegt Schnee auf den Dächern von Wiesenburg.",)),
    ),
)


def test_belegte_ansage_bleibt():
    """Erfundene, aber im Material belegte Angaben sind Sprache der Quelle -- sie bleiben."""
    antwort = {
        "dokumentart": "ein Heft",
        "titel": "Der Zauberwald",
        "herkunft": "Erika Beispiel, Verlag Lindenblatt",
        "datum": "im Juli",
        "ort": "Wiesenburg",
        "thema": "Es geht um den Zauberwald und die Bewohner von Wiesenburg.",
        "ueberleitungen": {"1": "Hören wir nun das zweite Kapitel über den Winter."},
        "abspann": "Das war der Zauberwald.",
    }
    neu, warnungen = inszeniere(BELEGT, Rollenbild("Heft", {}), textmodell=Modell(antwort))
    zeilen = kopfseite_von(neu)
    assert zeilen[0] == (
        "Sie hören ein Heft „Der Zauberwald“ von Erika Beispiel, Verlag Lindenblatt, im Juli, "
        "Wiesenburg."
    )
    assert zeilen[1] == "Es geht um den Zauberwald und die Bewohner von Wiesenburg."
    assert neu.kapitel[1].absaetze[-1] == "Hören wir nun das zweite Kapitel über den Winter."
    assert neu.kapitel[-1].absaetze == ("Das war der Zauberwald.",)
    assert not any("verworfen" in w for w in warnungen)


def test_unbelegter_satz_nimmt_nur_sich_mit():
    antwort = kopf(
        dokumentart="ein Heft",
        thema="Es geht um den Winter. Der Verleger lobt das Heft. Es geht auch um Wiesenburg.",
    )
    neu, warnungen = inszeniere(BELEGT, Rollenbild("Heft", {}), textmodell=Modell(antwort))
    assert "Es geht um den Winter. Es geht auch um Wiesenburg." in kopfseite_von(neu)
    (verworfen,) = [w for w in warnungen if w.startswith("Ansage verworfen")]
    assert "Verleger" in verworfen and "Winter" not in verworfen


def test_beugung_und_satzanfang_zaehlen_nicht_als_erfindung():
    # "Bewohnern" steht als "Bewohnern", "Bewohner" ist Beugung eines langen Wortes (Praefix);
    # "Heute" steht am Satzanfang und ist kein inhaltstragendes Wort.
    antwort = kopf(thema="Heute sprechen die Bewohner. Sie erzählen vom Zauberwald.")
    neu, warnungen = inszeniere(BELEGT, Rollenbild("Heft", {}), textmodell=Modell(antwort))
    assert "Heute sprechen die Bewohner. Sie erzählen vom Zauberwald." in kopfseite_von(neu)
    assert not any("verworfen" in w for w in warnungen)


def test_jedes_wort_von_titel_herkunft_ort_muss_belegt_sein():
    antwort = kopf(
        dokumentart="ein Heft",
        titel="Der große Zauberwald",  # "große" steht nirgends
        herkunft="Erika Beispiel und Freunde",  # "Freunde" steht nirgends
        ort="Wiesenburg",
    )
    neu, warnungen = inszeniere(BELEGT, Rollenbild("Heft", {}), textmodell=Modell(antwort))
    zeilen = kopfseite_von(neu)
    assert zeilen[0] == "Sie hören ein Heft, Wiesenburg."
    assert len([w for w in warnungen if w.startswith("Ansage verworfen")]) == 2


# ---- Regie-Modus ------------------------------------------------------------------------------


def test_regie_modus_buch_laesst_nur_unhoerbares_weg():
    modell = Modell(kopf(dokumentart="ein Programmheft", titel="Sommerkonzert im Schlosshof"))
    neu, warnungen = inszeniere(
        PROGRAMM, rollenbild(PROGRAMM_ROLLEN["rollen"], "Programmheft"), textmodell=modell,
        modus="buch",
    )  # fmt: skip
    gesprochen = [a for k in neu.kapitel for a in k.absaetze]
    # Metadaten bleiben Wortlaut (ein Buch hat sie im Text); Bildunterschrift und Seitenzahl nicht.
    assert "Kammerorchester Musica Vera" in gesprochen
    assert "Samstag, 12. Juli, Schlosshof Wiesenburg" in gesprochen
    assert not any(a.startswith("Foto:") for a in gesprochen) and "12" not in gesprochen
    assert "weggelassen: Bildunterschriften (2)" in warnungen
    assert "weggelassen: Seitenzahlen (1)" in warnungen
    assert not any("Metadaten" in w for w in warnungen)
    assert kopfseite_von(neu)  # die Kopfseite gibt es auch im Buch

    zus, warnungen = inszeniere(
        ZUSAMMENFASSUNG,
        rollenbild(ZUSAMMENFASSUNG_ROLLEN["rollen"], "Zusammenfassung"),
        textmodell=Modell(
            kopf(
                dokumentart="eine Zusammenfassung",
                ueberleitungen={"1": "Es folgt, was daraus folgt."},
            )
        ),
        modus="buch",
    )
    text = [a for k in zus.kapitel for a in k.absaetze]
    assert "Buch kaufen" not in text and "Bewertung: 4 von 5 Sternen" not in text
    assert "Zuhören ist eine Haltung, keine Technik." in text  # Zitatkasten bleibt Wortlaut
    assert "Kernaussage: Fragen vor Antworten." in text  # Uebersicht auch
    assert "weggelassen: Bedienelemente (2)" in warnungen
    assert all("ueberleitung" not in k.arten for k in zus.kapitel)  # keine Ueberleitungen im Buch


def test_regie_modus_buch_haelt_die_grenze_fuer_unhoerbares():
    rollen = {k: "fussnote" for k in PROGRAMM_ROLLEN["rollen"]}
    rollen["0.3"] = "haupttext"
    neu, warnungen = inszeniere(
        PROGRAMM, rollenbild(rollen), textmodell=Modell(KEINE_ANSAGEN), modus="buch"
    )
    assert neu == PROGRAMM
    assert any("Rückfall" in w for w in warnungen)


def test_regie_modus_aus():
    modell = Modell()  # jeder Aufruf waere ein Fehler
    neu, warnungen = inszeniere(
        PROGRAMM, rollenbild(PROGRAMM_ROLLEN["rollen"]), textmodell=modell, modus="aus"
    )
    assert neu == PROGRAMM and neu.kapitel[0].arten == ()
    assert warnungen == ("Regie ausgeschaltet: das Dokument wird unverändert gelesen",)
    neu, warnungen = mache_regie(PROGRAMM, textmodell=modell, modus="aus")
    assert neu == PROGRAMM and modell.aufrufe == []
    assert any("ausgeschaltet" in w for w in warnungen)


def test_regie_modus_unbekannt_bricht_laut():
    with pytest.raises(Mp4Fehler, match="Regie-Modus"):
        inszeniere(PROGRAMM, rollenbild({}), textmodell=Modell(), modus="halb")


# ---- Die Kopfseite ist hart begrenzt -----------------------------------------------------------


def _kopf_woerter(neu) -> int:
    return len(" ".join(kopfseite_von(neu)).split())


def _dokument_mit_langen_abschnitten(anzahl: int = 6, woerter_je_titel: int = 10) -> Dokument:
    titel = [f"Teil{i} " + viele_worte(woerter_je_titel - 1) for i in range(anzahl)]
    return Dokument("Muster", None, "de", tuple(Kapitel(t, (viele_worte(80),)) for t in titel))


def _satz(n: int) -> str:
    return viele_worte(n) + "."


def test_kopfseite_hart_begrenzt():
    """Reihenfolge der Kuerzung: Gliederung auf die Zahl, dann Thema auf einen Satz, dann weg."""
    dok = _dokument_mit_langen_abschnitten()

    # 1. Zwei Saetze Thema passen, die Titel der Gliederung nicht: nur die Zahl bleibt.
    thema = f"{_satz(20)} {_satz(20)}"
    modell = Modell(kopf(dokumentart="einen Text", thema=thema))
    neu, warnungen = inszeniere(dok, Rollenbild("x", {}), textmodell=modell)
    zeilen = " ".join(kopfseite_von(neu))
    assert _kopf_woerter(neu) <= 100
    assert thema in kopfseite_von(neu)  # beide Saetze bleiben
    assert "Teil1" not in zeilen and "und hat sechs Abschnitte." in zeilen
    assert any(w.startswith("Kopfseite gekürzt") and "Gliederung" in w for w in warnungen)

    # 2. Reicht das nicht, schrumpft das Thema auf EINEN Satz.
    thema = f"{_satz(50)} {_satz(50)}"
    neu, warnungen = inszeniere(
        dok, Rollenbild("x", {}), textmodell=Modell(kopf(dokumentart="einen Text", thema=thema))
    )
    assert _kopf_woerter(neu) <= 100
    assert _satz(50) in kopfseite_von(neu) and thema not in kopfseite_von(neu)
    assert any("Thema auf einen Satz" in w for w in warnungen)

    # 3. Ein einziger Satz, der allein zu lang ist: das Thema entfaellt.
    neu, warnungen = inszeniere(
        dok,
        Rollenbild("x", {}),
        textmodell=Modell(kopf(dokumentart="einen Text", thema=_satz(120))),
    )
    assert _kopf_woerter(neu) <= 100
    assert _satz(120) not in " ".join(kopfseite_von(neu))
    assert kopfseite_von(neu)[0] == "Sie hören einen Text."
    assert any("Thema entfällt" in w for w in warnungen)


def test_ausgeschriebene_kuerzel_der_quelle_belegen_die_ansage():
    # Die Quelle schreibt "SA 17. OKT", die Ansage "Samstag, 17. Oktober": die Belegpruefung
    # kennt die Quelle auch so, wie der Hoertext sie ausspricht.
    kurz = replace(
        PROGRAMM,
        kapitel=(
            replace(
                PROGRAMM.kapitel[0],
                absaetze=(
                    PROGRAMM.kapitel[0].absaetze[0],
                    "SA 17. OKT, Schlosshof Wiesenburg",
                    *PROGRAMM.kapitel[0].absaetze[2:],
                ),
            ),
        ),
    )
    antwort = kopf(titel="Sommerkonzert", datum="Samstag, 17. Oktober")
    neu, warnungen = inszeniere(
        kurz, rollenbild(PROGRAMM_ROLLEN["rollen"]), textmodell=Modell(antwort)
    )
    assert "Sie hören „Sommerkonzert“, Samstag, 17. Oktober." in kopfseite_von(neu)
    assert not [w for w in warnungen if "verworfen" in w]

    # Gegenprobe: ein Monat, den die Quelle in keiner Form nennt, faellt weiter heraus.
    neu, warnungen = inszeniere(
        kurz,
        rollenbild(PROGRAMM_ROLLEN["rollen"]),
        textmodell=Modell(kopf(titel="Sommerkonzert", datum="Samstag, 17. November")),
    )
    assert "November" not in " ".join(kopfseite_von(neu))
    assert any("datum" in w and "November" in w for w in warnungen if "verworfen" in w)


def test_kategorie_marke_faellt_aus_dem_titel_nicht_aber_ein_teil_des_titels():
    mit_marke = replace(
        PROGRAMM,
        titel="HEFT Sommerkonzert im Schlosshof",
        kapitel=(replace(PROGRAMM.kapitel[0], titel="HEFT Sommerkonzert im Schlosshof"),),
    )
    neu, _ = inszeniere(
        mit_marke,
        rollenbild(PROGRAMM_ROLLEN["rollen"]),
        textmodell=Modell(kopf(titel="Sommerkonzert im Schlosshof")),
    )
    assert neu.titel == "Sommerkonzert im Schlosshof"
    # Probe 24.10.: auch die gleichnamige Kapitelueberschrift (gesprochen) verliert sie.
    assert all("HEFT" not in k.titel for k in neu.kapitel)
    # Ein kuerzerer belegter Titel kuerzt den Titel der Quelle nicht.
    neu, _ = inszeniere(
        PROGRAMM,
        rollenbild(PROGRAMM_ROLLEN["rollen"]),
        textmodell=Modell(kopf(titel="Sommerkonzert")),
    )
    assert neu.titel == "Sommerkonzert im Schlosshof"


def test_versaltitel_verliert_kein_wort_an_die_marken_regel():
    # Critic 24.10.: "DIE ZEIT" mit belegtem "ZEIT" darf nicht zu "ZEIT" werden.
    assert regie._ohne_marke("DIE ZEIT", "ZEIT") == "DIE ZEIT"
    assert regie._ohne_marke("DIE Zeit", "Zeit") == "DIE Zeit"
    assert regie._ohne_marke("BUCH Das Musterbuch", "Das Musterbuch") == "Das Musterbuch"


def test_technischer_dateiname_als_titel_wird_der_belegte_titel():
    # Programmheft-Foto 24.10.: Datei und Kapitel hiessen "IMG_4474", gesprochen als Ueberschrift.
    foto = replace(
        PROGRAMM,
        titel="IMG_4474",
        kapitel=(replace(PROGRAMM.kapitel[0], titel="IMG_4474"),),
    )
    neu, _ = inszeniere(
        foto,
        rollenbild(PROGRAMM_ROLLEN["rollen"]),
        textmodell=Modell(kopf(titel="Kammerorchester Musica Vera")),  # im Text belegt
    )
    assert neu.titel == "Kammerorchester Musica Vera"
    assert all(k.titel != "IMG_4474" for k in neu.kapitel)


def test_kopfseite_spricht_ganze_saetze_wie_ein_mensch():
    # Die runde Form der Hoerprobe: Was und Woher in einem Satz, Umfang als Satz mit Verb,
    # Abschnittstitel in Anfuehrungszeichen, kein "Es beginnt", wenn die Gliederung schon
    # alle Abschnitte genannt hat. Bruchstuecke ("Erika Beispiel.") klangen abgehackt.
    zeilen = regie.baue_kopfseite(
        {
            "dokumentart": "ein Kapitel aus dem Sachbuch",
            "titel": "Wie Muster entstehen",
            "herkunft": "Erika Beispiel",
            "thema": "Es geht um Muster.",
        },
        wortzahl=30 * regie.WOERTER_JE_MINUTE,
        abschnitte=["Der Anfang", "Die Mitte", "Das Ende"],
    )
    assert zeilen == (
        "Sie hören ein Kapitel aus dem Sachbuch „Wie Muster entstehen“ von Erika Beispiel.",
        "Es geht um Muster.",
        "Es dauert rund dreißig Minuten und hat drei Abschnitte: „Der Anfang“, „Die Mitte“ "
        "und „Das Ende“.",
    )


def test_kopfseite_ohne_genannte_gliederung_nennt_den_ersten_abschnitt():
    zeilen = regie.baue_kopfseite(
        {"dokumentart": "ein Heft", "datum": "im Juli", "ort": "Wiesenburg"},
        wortzahl=2 * regie.WOERTER_JE_MINUTE,
        abschnitte=[f"Teil {b}" for b in "ABCDEFG"],
    )
    assert zeilen == (
        "Sie hören ein Heft, im Juli, Wiesenburg.",
        "Es dauert rund zwei Minuten und hat sieben Abschnitte.",
        "Es beginnt mit „Teil A“.",
    )


def test_kopfseite_nur_herkunft_hat_einen_satzgegenstand():
    zeilen = regie.baue_kopfseite(
        {"herkunft": "dem Kammerorchester Musica Vera"}, wortzahl=10, abschnitte=[]
    )
    assert zeilen[0] == "Sie hören einen Text vom Kammerorchester Musica Vera."


def test_gekuerzte_kopfseite_nennt_im_uebergang_keinen_titel():
    zeilen = regie.baue_kopfseite(
        {"dokumentart": "ein Heft"},
        wortzahl=10,
        abschnitte=[f"Teil {b}" for b in "ABCDEFG"],
        mit_titeln=False,
    )
    assert zeilen == (
        "Sie hören ein Heft.",
        "Es dauert rund eine Minute und hat sieben Abschnitte.",
    )


def test_artikel_der_herkunft_brauchen_keinen_beleg():
    # Die Herkunft kommt so, wie sie nach "von" steht; eine englische Quelle kennt "der" nicht.
    quelle = Dokument("Report", "The New York Times", "en", (Kapitel("", ("News today.",)),))
    beleg = regie._Beleg.aus(quelle, "ein Bericht")
    assert regie._unbelegte("der New York Times", beleg, "alle") == []
    assert regie._unbelegte("der Washington Post", beleg, "alle") == ["Washington", "Post"]


# ---- Zwischenueberschriften als eigene Art -----------------------------------------------


def leser_dokument() -> Dokument:
    """Ein Dokument, in dem der Leser eine Zwischenueberschrift gesetzt hat (Layout-Beleg)."""
    return Dokument(
        "Ein Musterheft",
        None,
        "de",
        (
            Kapitel(
                "Ein Musterheft",
                (
                    "Ein erster Abschnitt",
                    "Ein Absatz Haupttext, den man hören soll.",
                    "Noch ein Absatz Haupttext, der dazugehört.",
                ),
                ("ueberschrift", "wortlaut", "wortlaut"),
            ),
        ),
    )


def arten_je_absatz(neu: Dokument) -> dict[str, str]:
    return {
        a: art
        for k in neu.kapitel
        for a, art in zip(k.absaetze, k.arten or ("wortlaut",) * len(k.absaetze), strict=True)
    }


def test_regie_rolle_ueberschrift_wird_art_ueberschrift():
    """Die Regie-Rolle `ueberschrift` wird Art `ueberschrift`; Haupttext bleibt `wortlaut`."""
    bild = rollenbild(PROGRAMM_ROLLEN["rollen"])
    neu, _ = inszeniere(
        PROGRAMM, bild, textmodell=Modell(kopf(titel="Sommerkonzert im Schlosshof"))
    )

    absaetze = PROGRAMM.kapitel[0].absaetze
    arten = arten_je_absatz(neu)
    assert [arten[absaetze[i]] for i in (2, 3, 5, 6)] == [
        "ueberschrift",
        "wortlaut",
        "ueberschrift",
        "wortlaut",
    ]


def test_leser_ueberschrift_gewinnt_gegen_rollenbild_haupttext():
    """Das Layout ist Beleg: sagt der Leser Ueberschrift, das Modell Haupttext, gilt der Leser."""
    quelle = leser_dokument()
    # Das Modell nennt den Titel des Dokuments: die erste Ueberschrift bleibt Zwischenueberschrift.
    neu, _ = inszeniere(
        quelle, Rollenbild("x", {}), textmodell=Modell(kopf(titel="Ein Musterheft"))
    )

    arten = arten_je_absatz(neu)
    assert arten["Ein erster Abschnitt"] == "ueberschrift"
    assert arten["Ein Absatz Haupttext, den man hören soll."] == "wortlaut"
    assert arten["Noch ein Absatz Haupttext, der dazugehört."] == "wortlaut"


def test_regie_aus_behaelt_leser_arten():
    quelle = leser_dokument()
    erwartet = ("ueberschrift", "wortlaut", "wortlaut")

    aus, _ = mache_regie(quelle, textmodell=Modell(), modus="aus")
    ohne_modell, _ = mache_regie(quelle, textmodell=None)
    direkt, _ = inszeniere(quelle, Rollenbild("x", {}), textmodell=Modell(), modus="aus")

    for dok in (aus, ohne_modell, direkt):
        assert dok.kapitel[0].arten == erwartet


def test_uebernahmepruefung_deckt_ueberschrift():
    """Eine Ueberschrift ist Quelltext: steht sie nicht in der Quelle, bricht die Zusicherung."""
    haupttext = PROGRAMM.kapitel[0].absaetze[3]
    erfunden = Dokument(
        "T",
        None,
        "de",
        (Kapitel("K", ("Ein erfundener Zwischentitel", haupttext), ("ueberschrift", "wortlaut")),),
    )
    belegt = Dokument(
        "T", None, "de", (Kapitel("K", ("Erster Teil", haupttext), ("ueberschrift", "wortlaut")),)
    )

    with pytest.raises(Mp4Fehler, match="nicht in der Quelle"):
        regie.pruefe_wortlaut(erfunden, PROGRAMM)
    regie.pruefe_wortlaut(belegt, PROGRAMM)  # Ueberschrift aus der Quelle: kein Fehler


def test_wortzahl_zaehlt_ueberschriften_wie_heute():
    """Der Umfang der Kopfseite zaehlt Ueberschriften mit, egal ob Regie oder Leser sie setzt.

    200 Woerter Haupttext allein sind eine Minute, mit 20 Woertern Ueberschrift zwei.
    """
    ueberschrift, text = viele_worte(20), viele_worte(200)
    modell = lambda: Modell(kopf(titel="Muster"))  # noqa: E731

    aus_regie = Dokument("Muster", None, "de", (Kapitel("Teil A", (ueberschrift, text)),))
    neu, _ = inszeniere(aus_regie, Rollenbild("x", {(0, 0): "ueberschrift"}), textmodell=modell())
    assert "rund zwei Minuten" in " ".join(kopfseite_von(neu))

    aus_leser = Dokument(
        "Muster",
        None,
        "de",
        (Kapitel("Teil A", (ueberschrift, text), ("ueberschrift", "wortlaut")),),
    )
    neu, _ = inszeniere(aus_leser, Rollenbild("x", {}), textmodell=modell())
    assert "rund zwei Minuten" in " ".join(kopfseite_von(neu))


def test_kopfseite_gliedert_nach_leser_ueberschriften():
    """Vorrang (Plan A1): eine Leser-Ueberschrift gliedert die Kopfseite wie eine der Regie.

    Das Rollenbild kennt keine Ueberschrift (alles Haupttext); die Arten kommen vom Leser.
    """
    quelle = Dokument(
        "T",
        None,
        "de",
        (
            Kapitel(
                "Ein Musterheft",
                ("Die Anfänge", viele_worte(40), "Die Folgen", viele_worte(30)),
                ("ueberschrift", "wortlaut", "ueberschrift", "wortlaut"),
            ),
        ),
    )

    neu, _ = inszeniere(
        quelle,
        Rollenbild("x", {}),
        textmodell=Modell(kopf(dokumentart="einen Text", titel="Ein Musterheft")),
    )

    assert "zwei Abschnitte: „Die Anfänge“ und „Die Folgen“" in " ".join(kopfseite_von(neu))
