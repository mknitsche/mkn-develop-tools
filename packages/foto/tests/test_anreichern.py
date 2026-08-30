"""Das Modul, das dem Baum seinen Namen gibt.

**Warum es diese Datei gibt.** Am 2026-08-30 lief die Pipeline ueber 1.293
Aufnahmen und schrieb 2.520 Dateien in einen Ordner namens "03 Bilder
angereichert". Darin lagen 1.227 RAW-Dateien und **139 XMP-Sidecars** — die 139,
die schon vorher existierten. Kein einziger neuer. Die gesamte Ortsarbeit lag im
Arbeitsspeicher und war mit dem Prozessende weg.

KT-1: *"bei den dateien auf 1tb fehlen systemisch die xmps ... es müsste ja zu
jeder raw ein jpeg und ein xmp geben"*. Er hat recht, und die Spec sagt es auch
(§ 6, § 10): RAW bekommt einen Sidecar, JPEG bekommt die Daten eingebettet.

Der Baum hiess "angereichert" und enthielt keine Anreicherung. Eine Zahl wie
"91 % verortet" ist wahr ueber die Rechnung und wertlos ueber das Ergebnis,
solange sie in keiner Datei steht.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import mkn_foto
import pytest
from mkn_foto import anreichern, urheber
from mkn_foto.modell import Aufnahme, Ort, Serie

pytestmark = pytest.mark.skipif(
    shutil.which("exiftool") is None, reason="exiftool nicht verfuegbar"
)

ORT = Ort(lat=47.68, lon=11.57, radius_m=250, name="Lenggries", quelle="schild")


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


def _aufnahme(ordner: Path, stamm: str, endungen=(".RAF",)) -> Aufnahme:
    ordner.mkdir(parents=True, exist_ok=True)
    dateien = {}
    for e in endungen:
        p = ordner / f"{stamm}{e}"
        if e in (".JPG", ".JPEG"):
            # Ein echtes, minimal gueltiges JPEG -- in eine Attrappe kann
            # exiftool nicht schreiben, und der Test pruefte dann sich selbst.
            subprocess.run(
                ["exiftool", "-q", "-o", str(p), "-n", "-IFD0:Make=Test"],
                capture_output=True,
                check=False,
            )
            if not p.exists():
                p.write_bytes(
                    bytes.fromhex(
                        "ffd8ffe000104a46494600010100000100010000ffdb004300"
                        + "08" * 64
                        + "ffc0000b080001000101011100ffc4001f00"
                        + "00" * 28
                        + "ffda0008010100003f00d2cf20ffd9"
                    )
                )
        else:
            p.write_bytes(b"roh-inhalt")
        dateien[e] = p
    return Aufnahme(
        zeitpunkt=datetime(2026, 8, 24, 6, 19, 0),
        kamera="XE5",
        stamm=stamm,
        dateien=dateien,
        exif={},
    )


def test_raw_bekommt_einen_sidecar(tmp_path):
    """Die Zusicherung, die am 2026-08-30 fehlte: zu jeder RAW ein XMP."""
    a = _aufnahme(tmp_path, "DSCF3541", (".RAF",))

    ergebnis = anreichern.schreibe([(a, ORT)])

    sidecar = tmp_path / "DSCF3541.xmp"
    assert sidecar.exists(), f"kein Sidecar angelegt: {sorted(p.name for p in tmp_path.iterdir())}"
    assert ergebnis.sidecars == 1


def test_das_raw_bleibt_bitgleich(tmp_path):
    """Ein Sidecar ist genau deshalb der richtige Weg: das undokumentierte
    Hersteller-Format wird nicht angefasst.

    Die Testdatei traegt die RAW-Endung, hat aber BESCHREIBBAREN Inhalt. Das ist
    der Punkt: mit einer Attrappe waere die Zusicherung hohl gewesen — exiftool
    haette ohnehin nicht hineinschreiben koennen, und der Test haette auch dann
    bestanden, wenn der Code den Einbettungs-Weg genommen haette. Firsthand
    gemessen: die Mutation ueberlebte ihn. Der Code entscheidet nach ENDUNG, der
    Inhalt darf deshalb ein anderer sein.
    """
    a = _aufnahme(tmp_path, "DSCF3541", (".JPG",))
    beschreibbar = a.dateien.pop(".JPG").rename(tmp_path / "DSCF3541.RAF")
    a.dateien[".RAF"] = beschreibbar
    vorher = beschreibbar.read_bytes()

    anreichern.schreibe([(a, ORT)])

    assert beschreibbar.read_bytes() == vorher, (
        "die RAW-Datei wurde veraendert — der Code hat eingebettet statt einen Sidecar zu schreiben"
    )
    assert (tmp_path / "DSCF3541.xmp").exists(), "und der Sidecar fehlt auch noch"


def test_der_ort_steht_wirklich_drin(tmp_path):
    """Nicht "exiftool wurde aufgerufen", sondern: was steht in der Datei?"""
    a = _aufnahme(tmp_path, "DSCF3541", (".RAF",))

    anreichern.schreibe([(a, ORT)])

    f = _lies(
        tmp_path / "DSCF3541.xmp", "GPSLatitude", "GPSLongitude", "GPSHPositioningError", "Location"
    )
    # Der Spot gehoert nach iptcCore:Location, nicht nach City -- das traegt das
    # GEBIET (Spec § 6 Traeger-Tabelle, seit macb-S314 richtig gebaut).
    assert f["Location"] == "Lenggries"
    assert "47" in f["GPSLatitude"] and "40" in f["GPSLatitude"]
    assert f["GPSHPositioningError"].startswith("250")


def test_ohne_ort_wird_kein_ort_geschrieben(tmp_path):
    """Die oberste Regel: im Zweifel nicht schreiben. Ein Spot ohne belegten Ort
    darf keine Koordinate bekommen — auch keine ungefaehre."""
    a = _aufnahme(tmp_path, "DSCF3541", (".RAF",))

    anreichern.schreibe([(a, None)])

    sidecar = tmp_path / "DSCF3541.xmp"
    assert sidecar.exists(), (
        "auch ohne Ort muss ein Sidecar entstehen -- sonst fehlen genau bei den "
        "Bildern die XMPs, die weder Ort noch Serie haben (nach dem Lauf vom "
        "2026-08-30 waeren das rund 112 gewesen)"
    )
    f = _lies(sidecar, "GPSLatitude", "City")
    assert not f.get("GPSLatitude"), f"Koordinate erfunden: {f}"
    assert not f.get("City"), f"Ortsname erfunden: {f}"


def test_jpeg_bekommt_die_daten_eingebettet(tmp_path):
    """Fuer JPEG gibt es keine Sidecar-Konvention (Spec § 10) — und niemals
    beides fuer dieselbe Datei, das waeren zwei Zustaende ueber eine Sache."""
    a = _aufnahme(tmp_path, "DSCF3542", (".JPG",))

    ergebnis = anreichern.schreibe([(a, ORT)])

    assert not (tmp_path / "DSCF3542.xmp").exists(), (
        "fuer ein JPEG wurde ein Sidecar angelegt statt einzubetten"
    )
    f = _lies(a.dateien[".JPG"], "Location")
    assert f.get("Location") == "Lenggries", f"nichts eingebettet: {f}"
    assert ergebnis.eingebettet == 1


def test_paar_bekommt_beides_getrennt(tmp_path):
    """Ein RAW+JPEG-Paar: der Sidecar gehoert zur RAW, die Einbettung ins JPEG."""
    a = _aufnahme(tmp_path, "DSCF3543", (".RAF", ".JPG"))

    ergebnis = anreichern.schreibe([(a, ORT)])

    assert (tmp_path / "DSCF3543.xmp").exists(), "der Sidecar zur RAW fehlt"
    assert _lies(a.dateien[".JPG"], "Location").get("Location") == "Lenggries"
    assert ergebnis.sidecars == 1 and ergebnis.eingebettet == 1


def test_serie_wird_zum_stichwort(tmp_path):
    """Ohne diese Zusicherung waere ein Schreiber, der nur den Ort schreibt und
    die Serien-Zugehoerigkeit verwirft, genauso gruen."""
    a1 = _aufnahme(tmp_path, "DSCF3544", (".RAF",))
    a2 = _aufnahme(tmp_path, "DSCF3545", (".RAF",))
    serie = Serie(typ="pan", nummer=1, aufnahmen=(a1, a2), quelle="kamera", sicher=True)

    anreichern.schreibe([(a1, ORT), (a2, ORT)], serien=[serie])

    f = _lies(tmp_path / "DSCF3544.xmp", "Subject", "HierarchicalSubject")
    # Mit Datum: `2026-08-24-pan01` (Spec-Schreibweise). Ohne es kollidieren
    # gleichnamige Serien verschiedener Tage im Stichwortbaum.
    assert "2026-08-24-pan01" in f.get("Subject", ""), f"Serienstichwort fehlt: {f}"
    assert "Serie|2026-08-24-pan01" in f.get("HierarchicalSubject", ""), (
        f"nicht hierarchisch oder ohne Datum: {f}"
    )


def test_der_urheber_landet_an_jeder_datei(tmp_path: Path, monkeypatch) -> None:
    """Die Verdrahtung, nicht das Modul.

    Dreimal in einer Nacht hat genau diese Naht gehalten und trotzdem nichts
    getan: `geotag` war gebaut und wurde nie gerufen, `motivlauf` ebenso, und
    `melde` kam im aeusseren Aufruf nicht an. Ein Modul in der Modulliste ist
    kein Aufruf im Ablauf — also wird hier der WEG geprueft, nicht das Ziel.
    """
    import dataclasses

    aufnahme = dataclasses.replace(
        _aufnahme(tmp_path, "DSC_1", (".RAF",)), zeitpunkt=datetime(2019, 5, 4, 12, 0)
    )
    gerufen: list[list[str]] = []
    monkeypatch.setattr(
        anreichern, "_ruf_exiftool", lambda args, ziel: gerufen.append(args) or True
    )

    anreichern.schreibe(
        [(aufnahme, None)],
        urheber_angaben=urheber.Urheber(name="Erika Muster", email="e@m.de"),
    )

    assert gerufen, "exiftool wurde gar nicht gerufen"
    assert "-XMP-dc:Creator=Erika Muster" in gerufen[0]
    # Das Aufnahmejahr, nicht das heutige.
    assert "-XMP-dc:Rights=© 2019 Erika Muster" in gerufen[0]


def test_jede_datei_nennt_den_stand_der_sie_geschrieben_hat(tmp_path, monkeypatch) -> None:
    """Provenienz — KT-1s eigentliche Sorge hinter der Versionsfrage.

    Woertlich (2026-08-30): *"nicht das alte staende der sw die duemmer waren
    als die aktuellen versionen die gesamte arbeit negativ beeinflussen"* --
    und die Frage danach: *"hast du eine saubere versionierung der sw?"*

    Eine Versionsnummer im Repository beantwortet das NICHT. Sie sagt, was
    heute gilt; sie sagt nicht, welcher Stand die Datei vor drei Wochen
    angefasst hat. Ohne diese Angabe ist ein Baum aus mehreren Laeufen nicht
    auseinanderzuhalten -- und genau deshalb musste heute alles geloescht
    werden: es war nicht erkennbar, was von welchem Stand stammte.

    `xmp:CreatorTool` ist das dafuer vorgesehene Feld (IPTC/XMP), kein
    Eigenbau.
    """
    aufnahme = _aufnahme(tmp_path, "DSC_9", (".RAF",))
    gerufen: list[list[str]] = []
    monkeypatch.setattr(
        anreichern, "_ruf_exiftool", lambda args, ziel: gerufen.append(args) or True
    )

    anreichern.schreibe([(aufnahme, None)])

    assert gerufen
    stand = [a for a in gerufen[0] if a.startswith("-XMP-xmp:CreatorTool=")]
    assert stand, "keine Angabe, welcher Stand die Datei geschrieben hat"
    assert mkn_foto.__version__ in stand[0]
    assert "mkn-foto" in stand[0]


def test_neben_dem_sidecar_bleibt_keine_kopie_liegen(tmp_path) -> None:
    """**KT-1s Verzeichnis, 2026-08-30: 1.228 Dateien Muell.**

    Beim Schreiben in einen VORHANDENEN Sidecar fehlte `-overwrite_original` --
    also legte exiftool jedes Mal eine `.xmp_original` daneben. Nach einem Lauf
    ueber 1.234 Aufnahmen lagen 1.228 Sicherungskopien zwischen den Bildern.

    Klein (2,5 MB), aber genau das, was KT-1 verboten hatte: *"und muelle nicht
    den mac oder die 1tb hdd zu"*. Und schlimmer als ihre Groesse ist die
    Verwirrung: wer den Ordner oeffnet, sieht doppelt so viele Dateien wie
    Bilder.

    Die Sicherungskopie ist hier auch sachlich ueberfluessig: der Zielbaum ist
    selbst schon die Kopie, die Originale werden nie angefasst.
    """
    aufnahme = _aufnahme(tmp_path, "DSCF7", (".RAF",))
    sidecar = tmp_path / "DSCF7.xmp"
    sidecar.write_text(
        '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about=""/></rdf:RDF></x:xmpmeta><?xpacket end="w"?>',
        encoding="utf-8",
    )

    anreichern.schreibe([(aufnahme, ORT)])

    assert sidecar.exists(), "der vorhandene Sidecar muss ergaenzt werden"
    uebrig = list(tmp_path.glob("*_original"))
    assert not uebrig, f"Sicherungskopien liegen geblieben: {[p.name for p in uebrig]}"


def test_die_farbnamen_werden_bis_in_die_datei_durchgereicht(tmp_path, monkeypatch) -> None:
    """Die Einstellung muss ankommen, nicht nur existieren.

    Der Weg geht ueber vier Stationen: Konfigurationsdatei -> `Konfig` ->
    `pipeline.fahre` -> `anreichern.schreibe` -> exiftool. Reisst er an EINER,
    sieht KT-1 weiterhin weisse Kaesten -- und die Einstellung, die er gesetzt
    hat, waere ein Feld ohne Wirkung.
    """
    aufnahme = _aufnahme(tmp_path, "DSCF8", (".RAF",))
    serie = Serie(typ="pan", nummer=1, aufnahmen=(aufnahme,), quelle="heuristik", sicher=True)
    gerufen: list[list[str]] = []
    monkeypatch.setattr(
        anreichern, "_ruf_exiftool", lambda args, ziel: gerufen.append(args) or True
    )

    anreichern.schreibe([(aufnahme, ORT)], serien=[serie], farbe_serie="Blau")

    assert "-XMP:Label=Blau" in gerufen[0]
    # Die Zahl bleibt: sie ist sprachunabhaengig, und Capture One liest sie.
    assert "-XMP-photoshop:Urgency=3" in gerufen[0]


def test_auch_die_unklar_farbe_ist_einstellbar(tmp_path, monkeypatch) -> None:
    aufnahme = _aufnahme(tmp_path, "DSCF9", (".RAF",))
    gerufen: list[list[str]] = []
    monkeypatch.setattr(
        anreichern, "_ruf_exiftool", lambda args, ziel: gerufen.append(args) or True
    )

    anreichern.schreibe([(aufnahme, ORT)], unklar={id(aufnahme): "Ort"}, farbe_unklar="Violett")

    # ueber ALLE Aufrufe: eine Aufnahme kann mehrere Dateien haben, und welche
    # zuerst drankommt, ist keine Zusicherung wert.
    alle = [x for ruf in gerufen for x in ruf]
    assert "-XMP:Label=Violett" in alle
    assert "-XMP-photoshop:Urgency=5" in alle
