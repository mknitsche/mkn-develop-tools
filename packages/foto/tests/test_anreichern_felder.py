"""Die Felder, die die Spec § 6 namentlich nennt — und die ich falsch hatte.

Meine erste Fassung schrieb den Spot-Namen nach `XMP-photoshop:City`. Das ist
nach der Träger-Tabelle das Feld fuer das **Gebiet**; der Spot gehoert nach
`XMP-iptcCore:Location` (Capture-One-Anzeige gemessen, Spec § 13.10) und
`XMP-iptcExt:LocationShownSublocation`.

Dazu die Farbe, die ganz fehlte: **Blau gehoert dem Werkzeug** und heisst „gehoert
zu einer Serie". Sie muss ZWEIMAL geschrieben werden — Capture One liest
`xmp:Label` nicht, sondern die aeltere Notation `photoshop:Urgency`, und dort ist
**3** die blaue (an KT-1s Capture One 16.8.5 abgelesen). Ein Design, das nur
`xmp:Label` setzt, zeigt in Lightroom Farben und in Capture One nichts.

Firsthand geprueft (2026-08-30): alle Felder nehmen die Werte an und lesen sich
zurueck. `IPTC:Sub-location` dagegen NICHT — ein XMP-Sidecar kann kein IIM
tragen, exiftool meldet „Nothing to write". Der IIM-Teil gilt nur fuer
eingebettete Formate.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from mkn_foto import anreichern
from mkn_foto.modell import Aufnahme, Ort, Serie

pytestmark = pytest.mark.skipif(
    shutil.which("exiftool") is None, reason="exiftool nicht verfuegbar"
)

SPOT = Ort(
    lat=47.42114,
    lon=10.98439,
    radius_m=40,
    name="Bergstation Zugspitzbahn",
    quelle="gpx",
)


def _lies(pfad: Path, *felder: str) -> dict[str, str]:
    """Liest Felder ueber die JSON-Ausgabe, nicht ueber Zeilen.

    Die erste Fassung war `zip(felder, stdout.splitlines())` — exiftool laesst
    fehlende Felder aber einfach WEG, und dann rutscht die Zuordnung um eins.
    Firsthand: `Location` bekam den Wert von `LocationShownSublocation`, und die
    Mutation "Spot wieder nach City" ueberlebte den Test, der sie fangen sollte.
    Eine Zuordnung ueber die Position ist keine Zuordnung.
    """
    roh = subprocess.run(
        ["exiftool", "-json", "-s", *[f"-{f}" for f in felder], str(pfad)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    daten = json.loads(roh)[0] if roh.strip() else {}
    return {f: str(daten[f]) for f in felder if f in daten}


def _raw(ordner: Path, stamm: str = "DSCF9001") -> Aufnahme:
    ordner.mkdir(parents=True, exist_ok=True)
    p = ordner / f"{stamm}.RAF"
    p.write_bytes(b"roh")
    return Aufnahme(
        zeitpunkt=datetime(2026, 8, 26, 20, 15, 0),
        kamera="XE5",
        stamm=stamm,
        dateien={".RAF": p},
        exif={},
    )


def test_der_spotname_steht_im_location_feld_nicht_in_city(tmp_path):
    """Der Fehlgriff, den die Spec ausdrücklich benennt."""
    a = _raw(tmp_path)

    anreichern.schreibe([(a, SPOT)])

    f = _lies(tmp_path / "DSCF9001.xmp", "Location", "LocationShownSublocation", "City")
    assert f.get("Location") == "Bergstation Zugspitzbahn", (
        f"der Spot steht nicht in iptcCore:Location: {f}"
    )
    assert f.get("LocationShownSublocation") == "Bergstation Zugspitzbahn"
    assert f.get("City") != "Bergstation Zugspitzbahn", (
        "der Spot steht faelschlich im City-Feld — das traegt das GEBIET"
    )


def test_serienbilder_bekommen_blau_in_beiden_notationen(tmp_path):
    """Capture One liest `xmp:Label` NICHT. Wer nur das setzt, zeigt in Lightroom
    Farben und in Capture One nichts — bei einem Vorhaben, dessen Begruendung
    „beide Programme sind im Spiel" lautet, ist das der halbe Ausfall."""
    a1 = _raw(tmp_path, "DSCF9002")
    a2 = _raw(tmp_path, "DSCF9003")
    serie = Serie(typ="pan", nummer=1, aufnahmen=(a1, a2), quelle="kamera", sicher=True)

    anreichern.schreibe([(a1, SPOT), (a2, SPOT)], serien=[serie])

    f = _lies(tmp_path / "DSCF9002.xmp", "Label", "Urgency")
    assert f.get("Label") == "Blue", f"XMP:Label fehlt: {f}"
    assert f.get("Urgency") == "3", (
        f"photoshop:Urgency fehlt oder ist nicht 3 — Capture One zeigt dann keine Farbe: {f}"
    )


def test_ein_einzelbild_bekommt_keine_farbe(tmp_path):
    """Untergrenze: Blau heisst „gehoert zu einer Serie". Wer alles einfaerbt,
    sagt nichts mehr — und nimmt KT-1 die Farbe fuer seine eigene Bewertung weg."""
    a = _raw(tmp_path, "DSCF9004")

    anreichern.schreibe([(a, SPOT)])

    f = _lies(tmp_path / "DSCF9004.xmp", "Label", "Urgency")
    assert not f.get("Label"), f"ein Einzelbild wurde eingefaerbt: {f}"
    assert not f.get("Urgency")


def test_das_serien_stichwort_traegt_das_datum(tmp_path):
    """Spec-Schreibweise `Serie | 2026-08-26-pan01`. Ohne Datum kollidiert
    `pan01` vom 26.08. mit `pan01` vom 27.08. — und der Stichwortbaum in Capture
    One wirft beide zusammen."""
    a1 = _raw(tmp_path, "DSCF9005")
    a2 = _raw(tmp_path, "DSCF9006")
    serie = Serie(typ="pan", nummer=1, aufnahmen=(a1, a2), quelle="kamera", sicher=True)

    anreichern.schreibe([(a1, SPOT), (a2, SPOT)], serien=[serie])

    f = _lies(tmp_path / "DSCF9005.xmp", "HierarchicalSubject", "Subject")
    assert "2026-08-26-pan01" in f.get("HierarchicalSubject", ""), (
        f"das Datum fehlt im Serien-Stichwort: {f}"
    )
    assert "2026-08-26-pan01" in f.get("Subject", ""), f"flache Form fehlt: {f}"


def test_eine_beschreibung_wird_geschrieben(tmp_path):
    """`XMP-dc:Description` — der Satz, den ab V2 das Modell liefert. Der Pfad
    muss vorher stehen, sonst hat V2 nichts, wo es hineinschreiben kann."""
    a = _raw(tmp_path, "DSCF9007")

    anreichern.schreibe([(a, SPOT)], beschreibungen={id(a): "Sonnenuntergang ueber der Bergkette."})

    f = _lies(tmp_path / "DSCF9007.xmp", "Description")
    assert f.get("Description") == "Sonnenuntergang ueber der Bergkette."
