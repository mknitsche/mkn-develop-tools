"""Die Vorschau, die an das Modell geht — und die Falle darin.

Zwei Befunde stecken in diesem Modul, beide firsthand:

**1. Der Tag-Name ist herstellerabhaengig.** Bei Nikon traegt `JpgFromRaw` das
grosse eingebettete JPEG (2,3 MB), `PreviewImage` nur ein Bildchen (124 KB). Bei
Fuji gibt es `JpgFromRaw` GAR NICHT — dort traegt `PreviewImage` die 3,4 MB. Wer
einen Namen fest verdrahtet, bekommt je nach Kamera etwas anderes oder nichts.

**2. exiftool meldet bei fehlendem Tag Exit 0 mit leerer Ausgabe.** Eine Kette,
die den Rueckgabewert prueft, meldet dann Erfolg ueber einer 0-Byte-Datei. Genau
das ist mir am 2026-08-30 passiert. Geprueft wird deshalb die GROESSE und die
JPEG-Klammer (ffd8ff … ffd9) — cld1s Verschaerfung: ein abgeschnittener Auszug
traegt den Kopf ebenfalls und besteht jede reine Groessenpruefung.

**3. Die Extraktion wirft alle Aufnahmedaten weg** (cld1, 2026-08-30): von zehn
Testbildern trug die Vorschau danach genau EINES eine Brennweite. Ein leeres Feld
sieht aus wie „kein Treffer", nicht wie Datenverlust. Eine Vorschau traegt
deshalb entweder ihre Herkunft oder sie ist ein Wegwerfstueck — kein
Zwischenzustand, in dem sie aussieht wie eine Aufnahme.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from mkn_foto import vorschau

pytestmark = pytest.mark.skipif(
    shutil.which("exiftool") is None, reason="exiftool nicht verfuegbar"
)

#: Echte Reisebilder, eine je Hersteller. Sie liegen ausserhalb des Repos —
#: fehlen sie, wird uebersprungen statt falsch bestanden.
NIKON = Path(
    "/Users/mkn1972/Pictures/01 Bilder von Camera/"
    "2026-08-24.29 FotoUrlaubMittenwald/2026-08-26/D850/D85_2560.NEF"
)
FUJI = Path(
    "/Users/mkn1972/Pictures/01 Bilder von Camera/"
    "2026-08-24.29 FotoUrlaubMittenwald/2026-08-26/X-E5/DSCF3512.RAF"
)
#: HOCHFORMAT (Orientation=8). Nur an einem gedrehten Bild kann die
#: Ausrichtungs-Falle zuschlagen -- bei Orientation=1 aendert ein
#: mituebernommener Wert nichts, und der Test bleibt gruen, ohne etwas zu sagen.
FUJI_HOCH = Path(
    "/Users/mkn1972/Pictures/01 Bilder von Camera/"
    "2026-08-24.29 FotoUrlaubMittenwald/2026-08-26/X-E5/DSCF3277.RAF"
)


def _ist_gueltiges_jpeg(p: Path) -> bool:
    roh = p.read_bytes()
    return len(roh) > 1000 and roh[:3] == b"\xff\xd8\xff" and roh[-2:] == b"\xff\xd9"


@pytest.mark.parametrize("quelle", [NIKON, FUJI], ids=["nikon", "fuji"])
def test_beide_hersteller_liefern_eine_gueltige_vorschau(quelle, tmp_path):
    """Der Kern: die Kaskade muss BEIDE Container koennen."""
    if not quelle.exists():
        pytest.skip(f"Testbild fehlt: {quelle.name}")

    ziel = vorschau.hole(quelle, tmp_path / "v.jpg")

    assert ziel is not None, f"keine Vorschau aus {quelle.suffix}"
    assert _ist_gueltiges_jpeg(ziel), "kein gueltiges JPEG (Kopf/Ende/Groesse)"


def test_ein_abgeschnittener_auszug_gilt_nicht_als_vorschau(tmp_path):
    """cld1s Verschaerfung: der Kopf allein reicht nicht.

    Ein halbes Bild traegt `ffd8ff` genauso wie ein ganzes und besteht jede
    Groessenpruefung — nur die Endklammer `ffd9` fehlt.
    """
    halb = tmp_path / "halb.jpg"
    halb.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 5000)

    assert not vorschau.ist_brauchbar(halb), "ein abgeschnittenes JPEG wurde akzeptiert"


def test_eine_leere_datei_gilt_nicht_als_vorschau(tmp_path):
    """exiftool meldet bei fehlendem Tag Exit 0 mit leerer Ausgabe. Wer den
    Rueckgabewert prueft, meldet Erfolg ueber einer 0-Byte-Datei."""
    leer = tmp_path / "leer.jpg"
    leer.write_bytes(b"")

    assert not vorschau.ist_brauchbar(leer)


def test_eine_fremde_datei_liefert_nichts_statt_zu_werfen(tmp_path):
    """Untergrenze: eine Datei ohne eingebettete Vorschau muss sauber `None`
    liefern — sonst reisst ein einzelnes kaputtes Bild den ganzen Lauf ab."""
    fremd = tmp_path / "kein-bild.txt"
    fremd.write_text("kein Bild")

    assert vorschau.hole(fremd, tmp_path / "v.jpg") is None


@pytest.mark.parametrize("quelle", [NIKON, FUJI], ids=["nikon", "fuji"])
def test_die_vorschau_traegt_ihre_herkunft(quelle, tmp_path):
    """cld1s Befund vom 2026-08-30: die reine Extraktion wirft ALLE
    Aufnahmedaten weg — von zehn Testbildern trug danach genau eines eine
    Brennweite. Ein Filter darueber faende 90 % nicht, und zwar lautlos.
    """
    if not quelle.exists():
        pytest.skip(f"Testbild fehlt: {quelle.name}")

    ziel = vorschau.hole(quelle, tmp_path / "v.jpg")
    assert ziel is not None

    felder = subprocess.run(
        ["exiftool", "-json", "-s", "-FocalLength", "-Model", "-DateTimeOriginal", str(ziel)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    import json as _json

    d = _json.loads(felder)[0]
    assert d.get("FocalLength"), f"die Brennweite ist verlorengegangen: {d}"
    assert d.get("Model"), f"das Kameramodell ist verlorengegangen: {d}"


def test_die_vorschau_wird_nicht_doppelt_gedreht(tmp_path):
    """cld1s Hinweis, praezisiert an der Messung.

    Sein Punkt: `-all:all` zurueckschreiben und die Ausrichtung nicht ausnehmen,
    dreht ein bereits gedrehtes Bild ein zweites Mal.

    Gemessen ist die Lage feiner: der Fuji-Auszug eines Hochformat-Bildes ist
    QUER gespeichert (4416x2944) und traegt selbst „Rotate 270 CW" — die Angabe
    gehoert also dorthin, sie darf nicht geloescht werden, sonst zeigt jeder
    Betrachter das Bild liegend.

    Falsch waere der andere Fall: ein Auszug, der bereits HOCHKANT gespeichert
    ist und zusaetzlich eine Drehung traegt. Genau diese Kombination pruefen wir
    — sie ist die Doppeldrehung, nicht die blosse Anwesenheit des Feldes.
    """
    quelle = FUJI_HOCH
    if not quelle.exists():
        pytest.skip(f"Testbild fehlt: {quelle.name}")

    import json as _json

    original = _json.loads(
        subprocess.run(
            ["exiftool", "-json", "-s", "-n", "-Orientation", str(quelle)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )[0]
    assert original.get("Orientation") in (6, 8), (
        f"das Testbild ist nicht gedreht ({original.get('Orientation')}) — "
        "die Falle kann daran gar nicht zuschlagen"
    )

    ziel = vorschau.hole(quelle, tmp_path / "v.jpg")
    assert ziel is not None

    d = _json.loads(
        subprocess.run(
            [
                "exiftool",
                "-json",
                "-s",
                "-n",
                "-Orientation",
                "-ImageWidth",
                "-ImageHeight",
                str(ziel),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )[0]

    quer_gespeichert = d["ImageWidth"] > d["ImageHeight"]
    traegt_drehung = d.get("Orientation") in (6, 8)

    assert quer_gespeichert, (
        f"der Auszug ist bereits hochkant gespeichert ({d['ImageWidth']}x"
        f"{d['ImageHeight']}) — dann waere jede Drehungsangabe eine zweite Drehung"
    )
    assert traegt_drehung, (
        "die Drehungsangabe fehlt — ein quer gespeichertes Hochformat-Bild wird "
        "damit liegend angezeigt"
    )


@pytest.mark.parametrize("quelle", [NIKON, FUJI], ids=["nikon", "fuji"])
def test_der_groesste_auszug_wird_genommen(quelle, tmp_path):
    """Nicht der erste, sondern der GROESSTE.

    In einem Nikon-Bild liegen drei Auszuege: 2,3 MB, 721 KB und 124 KB. Wer den
    erstbesten nimmt, bekommt je nach Reihenfolge ein Bildchen — gross genug, um
    jede Gueltigkeitspruefung zu bestehen, zu klein, damit ein Modell etwas
    erkennt.
    """
    if not quelle.exists():
        pytest.skip(f"Testbild fehlt: {quelle.name}")

    from PIL import Image

    ziel = vorschau.hole(quelle, tmp_path / "v.jpg")

    assert ziel is not None
    # PIXEL, nicht Bytes: seit der Verkleinerung sagt die Dateigroesse nichts
    # mehr darueber, WELCHER Auszug genommen wurde -- ein Vorschaubildchen
    # bliebe nach dem Verkleinern klein, und der Test schlaege aus dem falschen
    # Grund an. Ein Bildchen faellt an seiner Kantenlaenge auf.
    with Image.open(ziel) as b:
        laengste = max(b.width, b.height)
    assert laengste >= 1000, (
        f"nur {b.width}x{b.height} — das ist ein Vorschaubildchen, nicht der grosse Auszug"
    )


def test_ein_winziges_aber_gueltiges_jpeg_zaehlt_nicht(tmp_path):
    """Untergrenze zur Groessenpruefung, die sonst redundant zur Klammer waere.

    Eine 0-Byte-Datei faengt schon die Kopf-Pruefung ab — die Groesse traegt erst
    HIER etwas bei: ein winziges, formal gueltiges JPEG (etwa ein 8x8-Thumbnail)
    ist als Vorlage fuer ein Bildurteil wertlos.
    """
    winzig = tmp_path / "winzig.jpg"
    winzig.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 200 + b"\xff\xd9")

    assert not vorschau.ist_brauchbar(winzig), (
        f"ein {winzig.stat().st_size}-Byte-JPEG wurde als Vorschau akzeptiert"
    )


def test_der_auszug_behaelt_seine_eigene_ausrichtung(tmp_path):
    """Die Ausrichtung des Auszugs gehoert dem Auszug, nicht dem Original.

    Firsthand gemessen: bei `D85_2560.NEF` traegt das ORIGINAL `Orientation=1`,
    der eingebettete Auszug dagegen GAR KEINE. Ohne die Ausnahme schriebe
    `-all:all` den Wert des Originals hinein.

    Hier ist der Schaden gering (1 heisst „nicht drehen"), aber der Mechanismus
    ist derselbe, der bei einem gedrehten Original eine falsche Drehung
    erzeugte. Der Auszug weiss es besser: er kennt seinen eigenen Zustand, das
    Original kennt nur seinen.
    """
    if not NIKON.exists():
        pytest.skip(f"Testbild fehlt: {NIKON.name}")

    import json as _json

    roh = tmp_path / "roh.jpg"
    roh.write_bytes(
        subprocess.run(
            ["exiftool", "-b", "-PreviewImage", str(NIKON)],
            capture_output=True,
            check=False,
        ).stdout
    )
    vorher = _json.loads(
        subprocess.run(
            ["exiftool", "-json", "-s", "-n", "-Orientation", str(roh)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )[0].get("Orientation")

    original = _json.loads(
        subprocess.run(
            ["exiftool", "-json", "-s", "-n", "-Orientation", str(NIKON)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )[0].get("Orientation")

    assert vorher != original, (
        f"Auszug und Original tragen denselben Wert ({vorher}) — an diesem Bild "
        "kann die Zusicherung nichts zeigen"
    )

    ziel = vorschau.hole(NIKON, tmp_path / "v.jpg")
    nachher = _json.loads(
        subprocess.run(
            ["exiftool", "-json", "-s", "-n", "-Orientation", str(ziel)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )[0].get("Orientation")

    assert nachher == vorher, (
        f"die Ausrichtung des Originals ({original}) hat die des Auszugs "
        f"({vorher}) ueberschrieben — jetzt steht dort {nachher}"
    )


# ---------------------------------------------------------------------------
# Die Verkleinerung — sie entscheidet ueber den Preis des ganzen Laufs.
#
# Gemessen am 2026-08-30, VOR dem ersten bezahlten Lauf: eine Nikon-Vorschau ist
# 8256x5504 Pixel. Nach Anthropics Formel (Pixel/750) sind das **60.588
# Bild-Tokens** — fuer EIN Bild. Bei 890 Einzelaufnahmen waeren das 54 Millionen
# Tokens allein an Bilddaten.
#
# Anthropic verkleinert intern ohnehin auf 1568 px laengste Kante; was darueber
# hinausgeht, wird uebertragen und weggeworfen. Wer es vorher tut, zahlt fuer
# 2.185 statt 60.588 Tokens je Bild — Faktor 28.
#
# Der Plan sah die Verkleinerung vor ("exiftool-Extraktion mit Format-Kaskade +
# Pillow-Verkleinerung"). Ich hatte sie nicht gebaut. Aufgefallen erst beim
# Durchrechnen der Kosten, nicht beim Bauen.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("quelle", [NIKON, FUJI], ids=["nikon", "fuji"])
def test_die_vorschau_wird_auf_modellmass_verkleinert(quelle, tmp_path):
    if not quelle.exists():
        pytest.skip(f"Testbild fehlt: {quelle.name}")
    from PIL import Image

    ziel = vorschau.hole(quelle, tmp_path / "v.jpg")

    with Image.open(ziel) as b:
        laengste = max(b.width, b.height)
    assert laengste <= vorschau.MAX_KANTE_PX, (
        f"{b.width}x{b.height} — das sind {b.width * b.height // 750} Bild-Tokens "
        f"statt hoechstens {vorschau.MAX_KANTE_PX**2 // 750}"
    )


@pytest.mark.parametrize("quelle", [NIKON, FUJI], ids=["nikon", "fuji"])
def test_das_seitenverhaeltnis_bleibt(quelle, tmp_path):
    """Untergrenze: ein auf 1568x1568 gequetschtes Bild waere auch klein — und
    das Modell saehe ein verzerrtes Motiv."""
    if not quelle.exists():
        pytest.skip(f"Testbild fehlt: {quelle.name}")
    import io

    from PIL import Image

    # Der AUSZUG ist der Bezug, nicht die RAW-Datei: das eingebettete JPEG hat
    # ein eigenes Seitenverhaeltnis (bei der Nikon 1,50 gegen 1,33 im Original).
    # Die erste Fassung verglich RAW mit verkleinerter Vorschau und mass damit
    # einen Unterschied, den die Verkleinerung gar nicht verursacht hat.
    roh_bytes = subprocess.run(
        ["exiftool", "-b", "-JpgFromRaw", "-PreviewImage", str(quelle)],
        capture_output=True,
        check=False,
    ).stdout
    with Image.open(io.BytesIO(roh_bytes)) as auszug:
        vorher = auszug.width / auszug.height

    ziel = vorschau.hole(quelle, tmp_path / "v.jpg")
    with Image.open(ziel) as b:
        nachher = b.width / b.height

    assert abs(vorher - nachher) < 0.05, (
        f"das Seitenverhaeltnis hat sich geaendert: {vorher:.3f} -> {nachher:.3f}"
    )


def test_ein_kleines_bild_wird_nicht_neu_komprimiert(tmp_path):
    """Untergrenze zur Verkleinerung — und sie schuetzt etwas anderes, als sie
    zunaechst zu schuetzen schien.

    Gegen das VERGROESSERN braucht es keinen Riegel: `Image.thumbnail` tut es
    von sich aus nie, und die Mutation, die den Fruehausstieg entfernte,
    ueberlebte den Test deshalb. Was der Ausstieg wirklich verhindert, ist das
    NEU-KOMPRIMIEREN: jedes Speichern eines JPEG verliert Bildinformation, und
    bei einer Datei, die schon klein genug ist, gaebe es dafuer keinen Gegenwert.
    """
    from PIL import Image

    klein = tmp_path / "klein.jpg"
    Image.new("RGB", (800, 600), (50, 100, 150)).save(klein, quality=95)
    vorher = klein.read_bytes()

    ergebnis = vorschau.verkleinere(klein, klein)

    with Image.open(ergebnis) as b:
        assert (b.width, b.height) == (800, 600), f"vergroessert auf {b.width}x{b.height}"
    assert klein.read_bytes() == vorher, (
        "das Bild wurde neu komprimiert, obwohl es klein genug war — jedes "
        "Speichern kostet Bildinformation ohne Gegenwert"
    )
