"""Holt das eingebettete JPEG aus einer RAW-Datei — fuer den Blick des Modells.

Eine RAW-Datei zu dekodieren kostet Sekunden; das eingebettete JPEG liegt fertig
darin und ist in Millisekunden da. KT-1 hat darauf hingewiesen, die Spec § 10
nennt es, und es ist die Grundlage der ganzen Bildanalyse.

**Drei Fallen, alle firsthand belegt:**

1. **Der Tag-Name ist herstellerabhaengig.** Nikon traegt das grosse JPEG in
   `JpgFromRaw` (2,3 MB), `PreviewImage` ist dort nur ein Bildchen (124 KB). Fuji
   kennt `JpgFromRaw` GAR NICHT — dort traegt `PreviewImage` die 3,4 MB. Wer
   einen Namen fest verdrahtet, bekommt je nach Kamera etwas anderes oder nichts.
   Deshalb wird der GROESSTE Auszug genommen, nicht der benannte.

2. **exiftool meldet bei fehlendem Tag Exit 0 mit leerer Ausgabe.** Eine Kette,
   die den Rueckgabewert prueft, meldet Erfolg ueber einer 0-Byte-Datei. Geprueft
   wird die GROESSE und die JPEG-Klammer — und zwar beide Enden: ein
   abgeschnittener Auszug traegt den Kopf `ffd8ff` ebenso wie ein ganzer und
   besteht jede reine Groessenpruefung (cld1, 2026-08-30).

3. **Die Extraktion wirft alle Aufnahmedaten weg** (cld1, 2026-08-30): von zehn
   Testbildern trug die Vorschau danach genau EINES eine Brennweite. Ein leeres
   Feld sieht aus wie „kein Treffer", nicht wie Datenverlust. Die Herkunft wird
   deshalb zurueckgeschrieben — **ohne die Ausrichtung**, sonst dreht der
   Betrachter das bereits gedrehte Bild ein zweites Mal.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

_LOG = logging.getLogger(__name__)

KANDIDATEN = ("JpgFromRaw", "PreviewImage", "OtherImage", "ThumbnailImage")
"""Bild-Tags in der Reihenfolge, in der sie geprueft werden. Genommen wird nicht
der erste, sondern der GROESSTE — die Reihenfolge entscheidet nur bei Gleichstand."""

MIN_BYTES = 1000
"""Darunter ist es kein Bild, sondern ein Rest."""

MAX_KANTE_PX = 1568
"""Laengste Kante der Vorschau, die an das Modell geht.

**Diese Zahl entscheidet ueber den Preis des ganzen Laufs.** Gemessen am
2026-08-30: eine Nikon-Vorschau ist 8256x5504 Pixel — nach Anthropics Formel
(Pixel/750) sind das 60.588 Bild-Tokens fuer EIN Bild. Bei 890 Einzelaufnahmen
waeren das 54 Millionen Tokens allein an Bilddaten.

1568 px ist das Mass, auf das Anthropic intern ohnehin verkleinert; was darueber
hinausgeht, wird uebertragen und weggeworfen. Wer es vorher tut, zahlt fuer
rund 2.185 statt 60.588 Tokens je Bild — Faktor 28."""


def hole(quelle: Path, ziel: Path) -> Path | None:
    """Schreibt die groesste eingebettete Vorschau nach `ziel`.

    Gibt `None` zurueck, wenn die Datei keine brauchbare Vorschau hat — laut
    genug fuer das Protokoll, leise genug, um den Lauf nicht abzureissen.
    """
    quelle, ziel = Path(quelle), Path(ziel)
    groessen = _groessen(quelle)
    if not groessen:
        _LOG.warning("keine eingebettete Vorschau: %s", quelle.name)
        return None

    ziel.parent.mkdir(parents=True, exist_ok=True)
    for tag, _ in sorted(groessen.items(), key=lambda x: -x[1]):
        roh = subprocess.run(
            ["exiftool", "-b", f"-{tag}", str(quelle)],
            capture_output=True,
            check=False,
        ).stdout
        ziel.write_bytes(roh)
        if ist_brauchbar(ziel):
            verkleinere(ziel, ziel)
            _uebernimm_herkunft(quelle, ziel)
            return ziel

    _LOG.warning("kein brauchbarer Auszug aus %s (geprueft: %s)", quelle.name, list(groessen))
    ziel.unlink(missing_ok=True)
    return None


def ist_brauchbar(pfad: Path) -> bool:
    """Groesse UND beide Klammern — der Exit-Code sagt hier nichts.

    Der Kopf allein reicht nicht: ein abgeschnittener Auszug traegt ihn ebenso
    wie ein vollstaendiges Bild.
    """
    if not pfad.exists() or pfad.stat().st_size < MIN_BYTES:
        return False
    roh = pfad.read_bytes()
    return roh[:3] == b"\xff\xd8\xff" and roh[-2:] == b"\xff\xd9"


def _groessen(quelle: Path) -> dict[str, int]:
    """Welche Bild-Tags die Datei traegt und wie gross sie sind."""
    felder = [f"-{t}#" for t in KANDIDATEN]
    roh = subprocess.run(
        ["exiftool", "-q", "-s", "-s", "-n", *[f"-{t}" for t in KANDIDATEN], str(quelle)],
        capture_output=True,
        text=True,
        check=False,
    )
    _ = felder
    if roh.returncode != 0:
        return {}
    # exiftool meldet die Binaerdaten als "(Binary data N bytes, use -b ...)".
    gefunden: dict[str, int] = {}
    ausgabe = subprocess.run(
        ["exiftool", "-q", *[f"-{t}" for t in KANDIDATEN], str(quelle)],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    for zeile in ausgabe.splitlines():
        if "Binary data" not in zeile:
            continue
        name = zeile.split(":", 1)[0].strip().replace(" ", "")
        teile = zeile.split("Binary data", 1)[1].split()
        if teile and teile[0].isdigit():
            gefunden[_tag_name(name)] = int(teile[0])
    return gefunden


def _tag_name(anzeige: str) -> str:
    """exiftool zeigt `JpgFromRaw` als `Jpg From Raw` — zurueck auf den Tag-Namen."""
    for t in KANDIDATEN:
        if anzeige.lower() == t.lower():
            return t
    return anzeige


def _uebernimm_herkunft(quelle: Path, ziel: Path) -> None:
    """Schreibt die Aufnahmedaten aus dem Original in die Vorschau.

    **Die Ausrichtung bleibt ausgenommen — aber aus einem feineren Grund, als
    zunaechst angenommen.** cld1s Warnung lautete: ein uebernommener
    Orientation-Wert dreht ein bereits gedrehtes Bild ein zweites Mal. Gemessen
    ist die Lage anders: der Fuji-Auszug eines Hochformat-Bildes ist QUER
    gespeichert (4416x2944) und traegt seine Drehungsangabe bereits SELBST. Sie
    kommt aus dem Auszug, nicht aus dem Original — und sie muss dort bleiben,
    sonst zeigt jeder Betrachter das Bild liegend.

    `-Orientation=` sorgt also nicht dafuer, dass keine Drehung dasteht, sondern
    dafuer, dass die des ORIGINALS nicht ueber die des Auszugs geschrieben wird.
    Die beiden koennen sich unterscheiden, und der Auszug weiss es besser.
    """
    subprocess.run(
        [
            "exiftool",
            "-q",
            "-m",
            "-overwrite_original",
            "-TagsFromFile",
            str(quelle),
            "-all:all",
            "-Orientation=",
            str(ziel),
        ],
        capture_output=True,
        check=False,
    )


def verkleinere(quelle: Path, ziel: Path, *, max_kante: int = MAX_KANTE_PX) -> Path:
    """Bringt ein Bild auf Modellmass — und laesst kleine Bilder in Ruhe.

    Ein Thumbnail hochzurechnen kostet Tokens und bringt kein einziges
    Bildmerkmal dazu; `Image.thumbnail` vergroessert deshalb nie.

    Das Seitenverhaeltnis bleibt: ein gequetschtes Bild waere auch klein, aber
    das Modell saehe ein verzerrtes Motiv.
    """
    from PIL import Image

    with Image.open(quelle) as bild:
        if max(bild.width, bild.height) <= max_kante:
            if quelle != ziel:
                bild.save(ziel, quality=88)
            return ziel
        kopie = bild.convert("RGB")
        kopie.thumbnail((max_kante, max_kante), Image.LANCZOS)
        kopie.save(ziel, quality=88)
    return ziel
