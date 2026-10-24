"""Bericht: was gelesen, weggelassen und nicht sauber gesprochen wurde, in Markdown."""

from __future__ import annotations

from pathlib import Path

from mkn_audio.bericht import schreibe_bericht
from mkn_audio.stimmen import Stimme
from mkn_audio.typen import Dokument, Kapitel

STIMME = Stimme(
    name="deutsch-maennlich",
    beschreibung="Teststimme",
    vorlage=Path("v.wav"),
    exaggeration=0.45,
    cfg_weight=0.45,
    temperature=0.75,
    tempo=0.9,
    version=2,
    stand="probe",
)
DOK = Dokument(
    titel="Testbuch",
    autor="Erika Muster",
    sprache="de",
    kapitel=(Kapitel("Eins", ("a",)), Kapitel("Zwei", ("b",))),
    warnungen=("Impressum weggelassen",),
)


def bericht(tmp_path, **ueber) -> str:
    felder = dict(
        quelle=tmp_path / "Eingang" / "Testbuch.epub",
        stimme=STIMME,
        tabellen_stand="ab12cd34",
        dok=DOK,
        dateien=[tmp_path / "2026-10-24 Testbuch_v01.m4b"],
        dauer_s=3725.4,
        warnungen=["Tabelle auf Seite 4 ausgelassen"],
        befunde=[(12, "zu kurz gesprochen", 205.0), (40, "lange Stille", None)],
        messwerte={"f0_median": 118.46, "streuung_ht": 3.2, "woerter_je_minute": 151.0},
    )
    felder.update(ueber)
    ziel = tmp_path / "2026-10-24 Testbuch Bericht_v01.md"
    ergebnis = schreibe_bericht(ziel, **felder)
    assert ergebnis == ziel
    return ziel.read_text(encoding="utf-8")


def test_bericht_kopf(tmp_path):
    text = bericht(tmp_path)

    assert "Testbuch.epub" in text
    assert "Erika Muster" in text
    assert "deutsch-maennlich_v02" in text
    assert "ab12cd34" in text
    assert "1:02:05" in text
    assert "2026-10-24 Testbuch_v01.m4b" in text
    assert str(tmp_path) not in text  # nur Dateinamen, keine Pfade


def test_bericht_nennt_warnungen_und_befunde(tmp_path):
    text = bericht(tmp_path)

    hinweise = text.split("## Hinweise")[1].split("## ")[0]
    assert "Tabelle auf Seite 4 ausgelassen" in hinweise
    # Warnungen des Dokuments gehen nie verloren, auch wenn der Aufrufer sie nicht reicht
    assert "Impressum weggelassen" in hinweise
    stellen = text.split("## Auff\u00e4llige Stellen")[1].split("## ")[0]
    assert "St\u00fcck 12" in stellen
    assert "zu kurz gesprochen" in stellen
    assert "03:25" in stellen
    assert "St\u00fcck 40" in stellen
    assert "\u2014" in stellen  # kein Zeitstempel


def test_bericht_doppelte_warnung_nur_einmal(tmp_path):
    text = bericht(tmp_path, warnungen=["Impressum weggelassen"])

    assert text.count("Impressum weggelassen") == 1


def test_bericht_ohne_warnungen_und_befunde_sagt_keine(tmp_path):
    ohne = Dokument(titel="T", autor=None, sprache="de", kapitel=())

    text = bericht(tmp_path, dok=ohne, warnungen=[], befunde=[], messwerte=None)

    assert text.split("## Hinweise")[1].split("## ")[0].strip() == "keine"
    assert text.split("## Auff\u00e4llige Stellen")[1].split("## ")[0].strip() == "keine"
    assert "## Messwerte" not in text
    assert "Autor" in text  # Zeile bleibt, Wert ist ein Strich


def test_bericht_messwerte(tmp_path):
    text = bericht(tmp_path)

    werte = text.split("## Messwerte")[1]
    assert "118,5 Hz" in werte
    assert "3,2 Halbt\u00f6ne" in werte
    assert "151 W\u00f6rter je Minute" in werte


def test_bericht_unbekannter_messwert_wird_nicht_verschluckt(tmp_path):
    text = bericht(tmp_path, messwerte={"pause_anteil": 0.12})

    assert "pause_anteil" in text
    assert "0,12" in text


def test_bericht_zeitstempel_ueber_einer_stunde(tmp_path):
    text = bericht(tmp_path, befunde=[(1, "x", 3725.0)])

    assert "1:02:05" in text.split("## Auff\u00e4llige Stellen")[1]


def test_bericht_atomar_und_ueberschreibbar(tmp_path):
    bericht(tmp_path)

    assert [p.name for p in tmp_path.glob("*.teil")] == []
    assert len(list(tmp_path.glob("*Bericht*"))) == 1
