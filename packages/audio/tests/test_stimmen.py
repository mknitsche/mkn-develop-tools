"""Die Stimmen-Tabelle: laden, waehlen, und laut scheitern, wenn sie nicht stimmt."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from mkn_audio.stimmen import Stimme, lade_tabelle
from mkn_audio.typen import Mp4Fehler

BEISPIEL_TABELLE = Path(__file__).resolve().parents[1] / "beispiel" / "stimmen.toml"


def test_tabelle_laedt_standard_und_hole():
    tabelle = lade_tabelle(BEISPIEL_TABELLE)

    assert tabelle.standard.name == "beispiel"
    assert tabelle.hole("beispiel") is tabelle.standard
    assert tabelle.namen() == ("beispiel",)
    vorlage = tabelle.standard.vorlage
    assert vorlage.is_absolute()
    assert vorlage == BEISPIEL_TABELLE.parent / "vorlagen" / "beispiel.wav"


def test_unbekannte_stimme_nennt_verfuegbare():
    tabelle = lade_tabelle(BEISPIEL_TABELLE)

    with pytest.raises(Mp4Fehler, match="beispiel"):
        tabelle.hole("gibtsnicht")


def test_tabelle_ohne_standard_bricht(schreibe_tabelle):
    pfad = schreibe_tabelle("a")

    with pytest.raises(Mp4Fehler, match="standard"):
        lade_tabelle(pfad)


def test_standard_muss_eine_vorhandene_stimme_nennen(schreibe_tabelle):
    pfad = schreibe_tabelle("a", standard="b")

    with pytest.raises(Mp4Fehler, match=r"'b'.*a"):
        lade_tabelle(pfad)


def test_tabelle_ohne_stimmen_bricht(schreibe_tabelle):
    pfad = schreibe_tabelle(standard="a")

    with pytest.raises(Mp4Fehler, match="stimmen"):
        lade_tabelle(pfad)


def test_fehlende_datei_bricht_mit_ort(tmp_path):
    with pytest.raises(Mp4Fehler, match=r"gibtsnicht\.toml"):
        lade_tabelle(tmp_path / "gibtsnicht.toml")


def test_kaputtes_toml_bricht_mit_ort(tmp_path):
    pfad = tmp_path / "kaputt.toml"
    pfad.write_text("standard = [", encoding="utf-8")

    with pytest.raises(Mp4Fehler, match=r"kaputt\.toml"):
        lade_tabelle(pfad)


def test_tippfehler_im_feldnamen_bricht(schreibe_tabelle):
    """Ein unbekanntes Feld waere sonst still wirkungslos: die Stimme klaenge anders."""
    pfad = schreibe_tabelle("a", standard="a", extra="exagerration = 0.7\n")

    with pytest.raises(Mp4Fehler, match="exagerration"):
        lade_tabelle(pfad)


def test_pflichtfeld_fehlt_bricht(tmp_path):
    pfad = tmp_path / "stimmen.toml"
    pfad.write_text(
        'standard = "a"\n[stimmen.a]\nbeschreibung = "x"\nvorlage = "v.wav"\n',
        encoding="utf-8",
    )

    with pytest.raises(Mp4Fehler, match="exaggeration"):
        lade_tabelle(pfad)


@pytest.mark.parametrize(
    ("zeile", "fragment"),
    [
        ('stand = "irgendwas"', "stand"),
        ("tempo = 0", "tempo"),
        ("tempo = true", "tempo"),
        ("pause_absatz = -1", "pause_absatz"),
        ("tempo_angleich = 1.5", "tempo_angleich"),
        ('klang = "highpass=f=80"', "klang"),
    ],
)
def test_ungueltige_werte_brechen(tmp_path, zeile, fragment):
    pfad = tmp_path / "stimmen.toml"
    inhalt = (
        'standard = "a"\n[stimmen.a]\nbeschreibung = "x"\nvorlage = "v.wav"\n'
        "exaggeration = 0.5\ncfg_weight = 0.5\ntemperature = 0.8\ntempo = 1.0\n"
        'stand = "probe"\n'
    )
    # Der Test-Wert ersetzt die gleichnamige Zeile oder haengt sich an.
    schluessel = zeile.split("=")[0].strip()
    zeilen = [z for z in inhalt.splitlines() if z.split("=")[0].strip() != schluessel]
    pfad.write_text("\n".join([*zeilen, zeile]) + "\n", encoding="utf-8")

    with pytest.raises(Mp4Fehler, match=fragment):
        lade_tabelle(pfad)


def test_vorgaben_und_klang_als_tupel(tmp_path):
    pfad = tmp_path / "stimmen.toml"
    pfad.write_text(
        'standard = "a"\n[stimmen.a]\nbeschreibung = "x"\nvorlage = "v/a.wav"\n'
        "exaggeration = 0.45\ncfg_weight = 0.45\ntemperature = 0.75\ntempo = 1\n"
        'stand = "standard"\nklang = ["highpass=f=80", "equalizer=f=250:t=q:w=1:g=-1.5"]\n',
        encoding="utf-8",
    )

    stimme = lade_tabelle(pfad).standard

    assert stimme.klang == ("highpass=f=80", "equalizer=f=250:t=q:w=1:g=-1.5")
    assert stimme.tempo == 1.0
    assert isinstance(stimme.tempo, float)
    assert stimme.modell == "chatterbox-multilingual"
    assert stimme.sprache == "de"
    assert (stimme.pause_stueck, stimme.pause_absatz) == (0.25, 0.6)
    assert (stimme.pause_titel, stimme.pause_kapitel) == (1.5, 2.0)
    assert stimme.pausen_kuerzen is True
    assert stimme.tempo_angleich == 0.10
    assert stimme.tonhoehe_ht == 0.0
    assert stimme.stand == "standard"


def test_stimme_ist_unveraenderlich():
    stimme = lade_tabelle(BEISPIEL_TABELLE).standard

    assert isinstance(stimme, Stimme)
    with pytest.raises(dataclasses.FrozenInstanceError):
        stimme.tempo = 2.0  # type: ignore[misc]


def test_fingerabdruck_folgt_dem_inhalt(schreibe_tabelle):
    """Der Bericht nennt den Tabellen-Stand; ein geaenderter Wert muss ihn aendern."""
    pfad = schreibe_tabelle("a", standard="a")
    vorher = lade_tabelle(pfad).fingerabdruck
    assert lade_tabelle(pfad).fingerabdruck == vorher

    pfad.write_text(pfad.read_text(encoding="utf-8").replace("0.9", "0.95"), encoding="utf-8")

    assert lade_tabelle(pfad).fingerabdruck != vorher


@pytest.mark.parametrize(
    "name", ["P28", "deutsch_maennlich", "deutsch-männlich", "-deutsch", "a--b"]
)
def test_stimmenname_ist_ordnertauglich(tmp_path, name):
    # Der Name ist zugleich ein Ordnername im Eingang; Grossbuchstaben, Umlaute
    # (NFD auf dem NAS) und Unterstriche brechen laut statt still unwaehlbar zu sein.
    pfad = tmp_path / "stimmen.toml"
    pfad.write_text(
        f'standard = "{name}"\n[stimmen."{name}"]\nbeschreibung = "x"\nvorlage = "v.wav"\n'
        "exaggeration = 0.5\ncfg_weight = 0.5\ntemperature = 0.8\ntempo = 1.0\n"
        'stand = "probe"\n',
        encoding="utf-8",
    )
    with pytest.raises(Mp4Fehler, match="Kleinbuchstaben"):
        lade_tabelle(pfad)


def test_stimmenname_nach_schema_und_version(schreibe_tabelle):
    pfad = schreibe_tabelle("deutsch-maennlich", standard="deutsch-maennlich", extra="")
    tabelle = lade_tabelle(pfad)
    assert tabelle.standard.name == "deutsch-maennlich"
    assert tabelle.standard.version == 1


@pytest.mark.parametrize("wert", ["0", "1.5", "true", '"2"'])
def test_version_ist_ganze_zahl_ab_eins(tmp_path, wert):
    pfad = tmp_path / "stimmen.toml"
    pfad.write_text(
        'standard = "a"\n[stimmen.a]\nbeschreibung = "x"\nvorlage = "v.wav"\n'
        "exaggeration = 0.5\ncfg_weight = 0.5\ntemperature = 0.8\ntempo = 1.0\n"
        f'stand = "probe"\nversion = {wert}\n',
        encoding="utf-8",
    )
    with pytest.raises(Mp4Fehler, match="version"):
        lade_tabelle(pfad)


def test_unbekanntes_stimmmodell_bricht(schreibe_tabelle):
    """Ein anderes Modell wuerde sonst still ignoriert: es sprache doch mit Chatterbox."""
    pfad = schreibe_tabelle("a", standard="a", extra='modell = "f5-tts"\n')

    with pytest.raises(Mp4Fehler, match=r"f5-tts.*chatterbox-multilingual"):
        lade_tabelle(pfad)


def test_ansage_stimme_muss_existieren(schreibe_tabelle):
    """Ein Tippfehler im Namen waere sonst erst beim Sprechen der ersten Ansage sichtbar."""
    pfad = schreibe_tabelle("a", standard="a", extra='ansage_stimme = "gibtsnicht"\n')

    with pytest.raises(Mp4Fehler, match=r"ansage_stimme.*gibtsnicht"):
        lade_tabelle(pfad)


def test_ansage_stimme_nennt_eine_andere_stimme_oder_sich_selbst(schreibe_tabelle):
    andere = lade_tabelle(
        schreibe_tabelle("b", "a", standard="a", extra='ansage_stimme = "b"\n')
    ).hole("a")
    selbst = lade_tabelle(schreibe_tabelle("a", standard="a", extra='ansage_stimme = "a"\n')).hole(
        "a"
    )
    ohne = lade_tabelle(schreibe_tabelle("a", standard="a")).hole("a")

    assert andere.ansage_stimme == "b"
    assert selbst.ansage_stimme == "a"  # gleiche Stimme erlaubt
    assert ohne.ansage_stimme is None
