"""Der Urheber steht in der Datei des Anwenders, nie im Code.

`mkn-develop-tools` ist ein OEFFENTLICHES Repository. Ein Name, ein Wohnort und
eine Mailadresse im Quelltext waeren dort fuer jeden lesbar — und in KT-1s
Regelwerk ist das ein HC-3-Verstoss (im Repo lebt Status, keine
personenbezogenen Daten). Die Loesung ist dieselbe wie beim API-Schluessel:
**das Werkzeug kennt den Platz, nicht den Wert.**
"""

from __future__ import annotations

import json
from pathlib import Path

from mkn_foto import urheber


def test_die_angaben_kommen_aus_der_datei_des_anwenders(tmp_path: Path) -> None:
    datei = tmp_path / "urheber.json"
    datei.write_text(
        json.dumps({"name": "Erika Muster", "stadt": "M", "land": "Germany", "email": "e@m.de"}),
        encoding="utf-8",
    )

    wer = urheber.lade(datei)

    assert wer is not None
    assert wer.name == "Erika Muster"
    assert wer.email == "e@m.de"


def test_ohne_datei_wird_nichts_geschrieben_statt_zu_raten(tmp_path: Path) -> None:
    """Keine Angaben ist ein gueltiger Zustand — nicht jeder will seinen Namen
    in den Bildern. Das Werkzeug erfindet dann nichts."""
    assert urheber.lade(tmp_path / "gibtsnicht.json") is None


def test_der_name_steht_in_allen_drei_traegern(tmp_path: Path) -> None:
    """XMP, IPTC und EXIF fuehren den Urheber je eigen. Wer nur einen setzt,
    ist in der Haelfte der Programme namenlos."""
    wer = urheber.Urheber(name="Erika Muster", stadt="M", land="Germany", email="e@m.de")

    args = wer.argumente(jahr=2026, eingebettet=True)

    assert "-XMP-dc:Creator=Erika Muster" in args
    assert "-EXIF:Artist=Erika Muster" in args
    assert "-IPTC:By-line=Erika Muster" in args


def test_das_iim_feld_bleibt_dem_sidecar_fern(tmp_path: Path) -> None:
    """IIM (`-IPTC:`) traegt nur ein eingebettetes Format. Im XMP-Sidecar
    meldet exiftool dafuer "Nothing to write" — dieselbe Grenze wie beim Ort."""
    wer = urheber.Urheber(name="Erika Muster", stadt="M", land="Germany", email="e@m.de")

    args = wer.argumente(jahr=2026, eingebettet=False)

    assert not [a for a in args if a.startswith("-IPTC:")]
    assert "-XMP-dc:Creator=Erika Muster" in args


def test_das_copyright_traegt_das_aufnahmejahr(tmp_path: Path) -> None:
    """Ein Bild von 2019 traegt nicht die Jahreszahl des Tages, an dem es
    sortiert wurde."""
    wer = urheber.Urheber(name="Erika Muster", stadt="M", land="Germany", email="e@m.de")

    args = wer.argumente(jahr=2019, eingebettet=False)

    assert "-XMP-dc:Rights=(C) 2019 Erika Muster" in args


def test_die_erreichbarkeit_steht_in_den_kontaktfeldern(tmp_path: Path) -> None:
    """Wozu der Name ohne Weg dorthin? Genau dafuer hat IPTC die
    Creator-Contact-Felder."""
    wer = urheber.Urheber(name="Erika Muster", stadt="M", land="Germany", email="e@m.de")

    args = wer.argumente(jahr=2026, eingebettet=False)

    assert "-XMP-iptcCore:CreatorWorkEmail=e@m.de" in args
    assert "-XMP-iptcCore:CreatorCity=M" in args
    assert "-XMP-iptcCore:CreatorCountry=Germany" in args


def test_eine_datei_ohne_namen_ist_wie_keine_datei(tmp_path: Path) -> None:
    """Halb ausgefuellt ist nicht halb gueltig.

    Ohne Namen ergeben Stadt und Mailadresse keinen Urheber — und ein Absturz
    mitten im Lauf waere die schlechteste aller Antworten auf eine Datei, die
    der Anwender selbst angelegt hat.
    """
    datei = tmp_path / "urheber.json"
    datei.write_text('{"stadt": "M", "email": "e@m.de"}', encoding="utf-8")

    assert urheber.lade(datei) is None


def test_kaputtes_json_stuerzt_nicht_ab(tmp_path: Path) -> None:
    datei = tmp_path / "urheber.json"
    datei.write_text("{kein json", encoding="utf-8")

    assert urheber.lade(datei) is None
