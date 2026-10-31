"""Die Stimmen-Tabelle: laden, waehlen, und laut scheitern, wenn sie nicht stimmt."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from mkn_audio.stimmen import Stimme, lade_tabelle
from mkn_audio.typen import Mp4Fehler

BEISPIEL_TABELLE = Path(__file__).resolve().parents[1] / "beispiel" / "stimmen.toml"


def _lokal_text(tabelle):
    """Die Text-Stimme des Wegs local fuer Deutsch (Schema 1: die Zeile von `standard`)."""
    return tabelle.standard_fuer("local", "de")[0]


def test_tabelle_laedt_standard_und_hole():
    tabelle = lade_tabelle(BEISPIEL_TABELLE)

    standard = _lokal_text(tabelle)
    assert standard.name == "beispiel"
    assert tabelle.hole("beispiel") is standard
    assert tabelle.namen("local") == ("beispiel",)
    assert tabelle.namen() == (
        "beispiel",
        "deutsch-gemini-charon",
        "deutsch-gemini-kore",
        "deutsch-gemini-sulafat",
    )
    vorlage = standard.vorlage
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

    stimme = _lokal_text(lade_tabelle(pfad))

    assert stimme.klang == ("highpass=f=80", "equalizer=f=250:t=q:w=1:g=-1.5")
    assert stimme.tempo == 1.0
    assert isinstance(stimme.tempo, float)
    assert lade_tabelle(pfad).wege["local"].modell == "chatterbox-multilingual"
    assert stimme.sprache == "de"
    assert (stimme.pause_stueck, stimme.pause_absatz) == (0.25, 0.6)
    assert (stimme.pause_titel, stimme.pause_kapitel) == (1.5, 2.0)
    assert stimme.pausen_kuerzen is True
    assert stimme.tempo_angleich == 0.10
    assert stimme.tonhoehe_ht == 0.0
    assert stimme.stand == "standard"


def test_pause_vor_und_nach_ueberschrift(schreibe_tabelle, tmp_path):
    """Zwei neue Pausenfelder: Vorgabe 1,0 / 0,7, in der Tabelle setzbar, nie negativ."""
    vorgabe = _lokal_text(lade_tabelle(schreibe_tabelle("a", standard="a")))
    assert (vorgabe.pause_vor_ueberschrift, vorgabe.pause_nach_ueberschrift) == (1.0, 0.7)

    gesetzt = _lokal_text(
        lade_tabelle(
            schreibe_tabelle(
                "a",
                standard="a",
                extra="pause_vor_ueberschrift = 1.2\npause_nach_ueberschrift = 0.5\n",
            )
        )
    )
    assert (gesetzt.pause_vor_ueberschrift, gesetzt.pause_nach_ueberschrift) == (1.2, 0.5)

    with pytest.raises(Mp4Fehler, match="pause_vor_ueberschrift"):
        lade_tabelle(schreibe_tabelle("a", standard="a", extra="pause_vor_ueberschrift = -0.1\n"))


def test_stimme_ist_unveraenderlich():
    stimme = _lokal_text(lade_tabelle(BEISPIEL_TABELLE))

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
    assert _lokal_text(tabelle).name == "deutsch-maennlich"
    assert _lokal_text(tabelle).version == 1


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
    """Schema 1: `ansage_stimme` der Standard-Zeile wird die Ansage-Rolle von `local`."""

    def ansage_von(*namen, extra=""):
        tabelle = lade_tabelle(schreibe_tabelle(*namen, standard="a", extra=extra))
        return tabelle.standard_fuer("local", "de")[1].name

    assert ansage_von("b", "a", extra='ansage_stimme = "b"\n') == "b"
    assert ansage_von("a", extra='ansage_stimme = "a"\n') == "a"  # gleiche Stimme erlaubt
    assert ansage_von("a") == "a"  # ohne Eintrag spricht die Hauptstimme


# --- Schema 2: Weg x Sprache x Rolle (Plan B1, Spec § 7) ---------------------------------

LOKAL_ZEILE = """
[stimmen.{name}]
beschreibung = "Teststimme lokal"
vorlage = "vorlagen/{name}.wav"
sprache = "{sprache}"
exaggeration = 0.45
cfg_weight = 0.45
temperature = 0.75
tempo = 0.9
stand = "probe"
"""

GEMINI_ZEILE = """
[stimmen.{name}]
weg = "gemini"
stimme = "{stimme}"
beschreibung = "Teststimme Gemini"
sprache = "{sprache}"
stand = "probe"
"""

GEMINI_WEG = '\n[wege.gemini]\nmodell = "test-tts-modell"\n'


def _schema2(tmp_path: Path, rumpf: str) -> Path:
    """Schreibt eine Tabelle im Schema 2: Kopf `schema = 2`, danach `rumpf` woertlich."""
    pfad = tmp_path / "stimmen.toml"
    pfad.write_text("schema = 2\n" + rumpf, encoding="utf-8")
    return pfad


def _zwei_wege() -> str:
    """Eine gueltige Schema-2-Tabelle: local de (Text + Ansage) und gemini de (Text, Ansage)."""
    return (
        GEMINI_WEG
        + '\n[standard.local.de]\ntext = "deutsch-lokal"\nansage = "deutsch-lokal-ansage"\n'
        + '\n[standard.gemini.de]\ntext = "deutsch-gemini-a"\nansage = "deutsch-gemini-b"\n'
        + LOKAL_ZEILE.format(name="deutsch-lokal", sprache="de")
        + LOKAL_ZEILE.format(name="deutsch-lokal-ansage", sprache="de")
        + GEMINI_ZEILE.format(name="deutsch-gemini-a", stimme="Achird", sprache="de")
        + GEMINI_ZEILE.format(name="deutsch-gemini-b", stimme="Aoede", sprache="de")
    )


def _meldung(pfad: Path) -> str:
    """Die Fehlermeldung von `lade_tabelle(pfad)` OHNE den Pfad.

    Der Pfad unter `tmp_path` traegt den Testnamen ("..._ohne_vorlage0"); ein `match` auf die
    ganze Meldung faende das Feld sonst im Pfad statt in der Diagnose (LP-35).
    """
    with pytest.raises(Mp4Fehler) as fehler:
        lade_tabelle(pfad)
    return str(fehler.value).replace(str(pfad), "<tabelle>")


def _namen(wahl: tuple[Stimme, Stimme, str | None]) -> tuple[str, str, str | None]:
    text, ansage, warnung = wahl
    return text.name, ansage.name, warnung


def test_beispieltabelle_standards():
    """Das oeffentliche Beispiel zeigt beide Wege und beide Rollen (Plan B1)."""
    tabelle = lade_tabelle(BEISPIEL_TABELLE)

    assert tabelle.schema == 2
    assert _namen(tabelle.standard_fuer("gemini", "de")) == (
        "deutsch-gemini-charon",
        "deutsch-gemini-sulafat",
        None,
    )
    assert _namen(tabelle.standard_fuer("local", "de")) == ("beispiel", "beispiel", None)
    charon = tabelle.hole("deutsch-gemini-charon")
    assert (charon.weg, charon.stimme) == ("gemini", "Charon")
    assert tabelle.hole("deutsch-gemini-kore").stimme == "Kore"
    assert tabelle.hole("deutsch-gemini-sulafat").stimme == "Sulafat"  # KT-1 2026-10-31: Ansage
    assert charon.exaggeration is None  # Chatterbox-Felder gibt es an einer Gemini-Zeile nicht
    assert tabelle.hole("beispiel").weg == "local"


def test_schema2_fehlende_sprache_faellt_auf_de_mit_warnung(tmp_path):
    """Fehlt die Dokumentsprache in `[standard.<weg>]`, spricht `de` -- mit Warnung, nie still."""
    tabelle = lade_tabelle(_schema2(tmp_path, _zwei_wege()))

    text, ansage, warnung = tabelle.standard_fuer("local", "en")

    assert (text.name, ansage.name) == ("deutsch-lokal", "deutsch-lokal-ansage")
    assert warnung is not None
    assert "en" in warnung


def test_gemini_zeile_mit_exaggeration_bricht(tmp_path):
    """Ein Chatterbox-Regler an einer Gemini-Zeile waere eine Behauptung ohne Wirkung."""
    lade_tabelle(_schema2(tmp_path, _zwei_wege()))  # Gegenprobe: ohne den Regler gueltig
    rumpf = _zwei_wege().replace('stimme = "Achird"\n', 'stimme = "Achird"\nexaggeration = 0.5\n')

    meldung = _meldung(_schema2(tmp_path, rumpf))

    assert "deutsch-gemini-a" in meldung and "exaggeration" in meldung


def test_local_zeile_ohne_vorlage_bricht(tmp_path):
    lade_tabelle(_schema2(tmp_path, _zwei_wege()))  # Gegenprobe: mit Vorlage gueltig
    rumpf = _zwei_wege().replace('vorlage = "vorlagen/deutsch-lokal.wav"\n', "")

    meldung = _meldung(_schema2(tmp_path, rumpf))

    assert "deutsch-lokal" in meldung and "vorlage" in meldung


def test_ansage_stimme_in_schema2_bricht(tmp_path):
    """Schema 2 bindet die Rolle an `[standard.<weg>.<sprache>]`, nicht an die Zeile."""
    rumpf = _zwei_wege().replace(
        'vorlage = "vorlagen/deutsch-lokal.wav"\n',
        'vorlage = "vorlagen/deutsch-lokal.wav"\nansage_stimme = "deutsch-lokal-ansage"\n',
    )
    lade_tabelle(_schema2(tmp_path, _zwei_wege()))  # Gegenprobe: ohne das Feld gueltig

    assert "ansage_stimme" in _meldung(_schema2(tmp_path, rumpf))


def test_modell_an_zeile_in_schema2_bricht(tmp_path):
    """Das Modell gehoert dem Weg: die Meldung nennt den Ort, an dem es stehen muss."""
    rumpf = _zwei_wege().replace(
        'stimme = "Achird"\n', 'stimme = "Achird"\nmodell = "test-tts-modell"\n'
    )
    lade_tabelle(_schema2(tmp_path, _zwei_wege()))  # Gegenprobe: ohne Zeilen-Modell gueltig

    meldung = _meldung(_schema2(tmp_path, rumpf))

    assert "modell" in meldung and "[wege." in meldung


def test_wege_local_modell_nur_aus_MODELLE(tmp_path):
    """Ein Modell, das der Arbeiter nicht kann, wuerde still mit Chatterbox gesprochen."""
    ohne = lade_tabelle(_schema2(tmp_path, _zwei_wege()))
    assert ohne.wege["local"].modell == "chatterbox-multilingual"  # Vorgabe ohne [wege.local]
    rumpf = '\n[wege.local]\nmodell = "f5-tts"\n' + _zwei_wege()

    meldung = _meldung(_schema2(tmp_path, rumpf))

    assert "f5-tts" in meldung and "chatterbox-multilingual" in meldung


def test_standard_verweist_auf_fremden_weg_bricht(tmp_path):
    """Eine Gemini-Zeile als lokale Text-Stimme waere ein stiller Wegwechsel."""
    rumpf = _zwei_wege().replace(
        '[standard.local.de]\ntext = "deutsch-lokal"',
        '[standard.local.de]\ntext = "deutsch-gemini-a"',
    )
    lade_tabelle(_schema2(tmp_path, _zwei_wege()))  # Gegenprobe: eigene Zeile gueltig

    meldung = _meldung(_schema2(tmp_path, rumpf))

    assert "deutsch-gemini-a" in meldung and "local" in meldung


def test_schema1_wird_abgebildet_mit_hinweis(tmp_path):
    """Die alte Tabelle laeuft weiter: `standard` + `ansage_stimme` -> `[standard.local.<spr>]`."""
    pfad = tmp_path / "stimmen.toml"
    pfad.write_text(
        'standard = "x"\n'
        + LOKAL_ZEILE.format(name="x", sprache="de")
        + 'modell = "chatterbox-multilingual"\nansage_stimme = "y"\n'
        + LOKAL_ZEILE.format(name="y", sprache="de"),
        encoding="utf-8",
    )

    tabelle = lade_tabelle(pfad)

    assert tabelle.schema == 1
    assert _namen(tabelle.standard_fuer("local", "de")) == ("x", "y", None)
    assert tabelle.wege["local"].modell == "chatterbox-multilingual"
    assert any("Schema 1" in hinweis for hinweis in tabelle.hinweise)


def test_hole_mit_weg_prueft_zugehoerigkeit(tmp_path):
    """`--stimme` mit dem Namen eines anderen Wegs ist ein Bedienfehler, kein Wegwechsel."""
    tabelle = lade_tabelle(_schema2(tmp_path, _zwei_wege()))

    assert tabelle.hole("deutsch-gemini-a", weg="gemini").stimme == "Achird"
    assert tabelle.hole("deutsch-gemini-a").weg == "gemini"
    with pytest.raises(Mp4Fehler, match="deutsch-gemini-a"):
        tabelle.hole("deutsch-gemini-a", weg="local")


def test_wegkonfig_gemini_pflicht_modell(tmp_path):
    """Sobald eine Gemini-Zeile existiert, muss `[wege.gemini].modell` stehen; Rest hat Vorgaben."""
    gemini = lade_tabelle(_schema2(tmp_path, _zwei_wege())).wege["gemini"]
    assert gemini.modell == "test-tts-modell"
    assert (gemini.parallel, gemini.block_zeichen, gemini.zeitgrenze_s) == (3, 1100, 300.0)
    assert gemini.preis_usd_je_1m_text_token is None
    assert gemini.preisstand is None

    assert "modell" in _meldung(_schema2(tmp_path, _zwei_wege().replace(GEMINI_WEG, "")))
