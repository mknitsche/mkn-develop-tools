"""Der Urheber steht in der Datei des Anwenders, nie im Code.

`mkn-develop-tools` ist ein OEFFENTLICHES Repository. Ein Name, ein Wohnort und
eine Mailadresse im Quelltext waeren dort fuer jeden lesbar — und in KT-1s
Regelwerk ist das ein HC-3-Verstoss (im Repo lebt Status, keine
personenbezogenen Daten). Die Loesung ist dieselbe wie beim API-Schluessel:
**das Werkzeug kennt den Platz, nicht den Wert.**
"""

from __future__ import annotations

from pathlib import Path

from mkn_foto import urheber


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

    assert "-XMP-dc:Rights=© 2019 Erika Muster" in args


def test_die_erreichbarkeit_steht_in_den_kontaktfeldern(tmp_path: Path) -> None:
    """Wozu der Name ohne Weg dorthin? Genau dafuer hat IPTC die
    Creator-Contact-Felder."""
    wer = urheber.Urheber(name="Erika Muster", stadt="M", land="Germany", email="e@m.de")

    args = wer.argumente(jahr=2026, eingebettet=False)

    assert "-XMP-iptcCore:CreatorWorkEmail=e@m.de" in args
    assert "-XMP-iptcCore:CreatorCity=M" in args
    assert "-XMP-iptcCore:CreatorCountry=Germany" in args


def test_der_rechtevermerk_bleibt_kurz(tmp_path: Path) -> None:
    """Der IPTC-Fachstandard, nicht Sparsamkeit.

    Die Copyright Notice soll LESBAR bleiben: Zeichen, Jahr, Name. Die
    Erreichbarkeit gehoert in die Creator-Contact-Felder, ausfuehrliche
    Rechtssprache in `UsageTerms`. Ein vollgestopfter Vermerk ist fuer Menschen
    muehsam und fuer Maschinen wertlos, weil keine Auswertung ihn zerlegt.

    (Meine erste Fassung schrieb Ort und Mailadresse in denselben String. KT-1
    fragte, wie es Fotografen halten -- und die Antwort war eine andere als
    meine Annahme.)
    """
    wer = urheber.Urheber(name="Erika Muster", stadt="M", land="Germany", email="e@m.de")

    args = wer.argumente(jahr=2019, eingebettet=False)

    assert "-XMP-dc:Rights=© 2019 Erika Muster" in args
    assert not [a for a in args if a.startswith("-XMP-dc:Rights") and "e@m.de" in a]


def test_der_rechtestatus_wird_ausdruecklich_gesetzt(tmp_path: Path) -> None:
    """`Marked` ist die Aussage "dieses Bild ist geschuetzt".

    Ohne sie bleibt der Status formal UNBEKANNT, auch wenn ein Vermerk
    danebensteht -- und genau dieses Feld werten Suchmaschinen aus.
    """
    args = urheber.Urheber(name="Erika Muster").argumente(jahr=2019, eingebettet=False)

    assert "-XMP-xmpRights:Marked=True" in args
