"""Schreibt die gewonnenen Angaben in die Dateien — der Schritt, der dem Baum
seinen Namen gibt.

**Warum dieses Modul entstanden ist.** Am 2026-08-30 lief die Pipeline ueber
1.293 Aufnahmen und legte 2.520 Dateien in einem Ordner namens "03 Bilder
angereichert" ab. Darin: 1.227 RAW-Dateien und 139 XMP-Sidecars — genau die 139,
die schon vorher existierten. Kein einziger neuer. Die gesamte Ortsarbeit lag im
Arbeitsspeicher und war mit dem Prozessende verloren. KT-1 hat es sofort gesehen:
*"bei den dateien auf 1tb fehlen systemisch die xmps"*.

Eine Zahl wie "91 % verortet" ist wahr ueber die Rechnung und wertlos ueber das
Ergebnis, solange sie in keiner Datei steht.

**Wohin geschrieben wird, entscheidet das Format** (Spec § 10):

    NEF, RAF     XMP-Sidecar daneben — das Original bleibt bitgleich
    JPEG, HEIC   eingebettet — fuer diese Formate gibt es keine Sidecar-Konvention

**Nie beides fuer dieselbe Datei.** Zwei Traeger derselben Aussage sind zwei
Zustaende ueber eine Sache. Ein RAW+JPEG-Paar bekommt deshalb einen Sidecar
(zur RAW) UND eine Einbettung (ins JPEG) — das sind zwei Dateien, nicht zwei
Traeger fuer eine.

**Ohne belegten Ort wird kein Ort geschrieben.** Serie und Technik gehen
trotzdem hinein; sie stehen fest, auch wenn der Ort offen ist.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from mkn_foto.modell import Aufnahme, Ort, Serie

SIDECAR = ".xmp"

EINGEBETTET = frozenset({".JPG", ".JPEG", ".HEIC"})
"""Formate mit eigener Metadaten-Konvention. Alles andere bekommt einen Sidecar."""

_ROH = frozenset({".NEF", ".RAF"})


class ExiftoolFehlt(RuntimeError):
    """Ohne exiftool kann nichts geschrieben werden — laut, nicht stillschweigend."""


@dataclass
class Ergebnis:
    """Was geschrieben wurde. Zahlen, keine Behauptungen."""

    sidecars: int = 0
    eingebettet: int = 0
    fehler: list[str] = field(default_factory=list)


def schreibe(
    eintraege: Sequence[tuple[Aufnahme, Ort | None]],
    *,
    serien: Iterable[Serie] = (),
) -> Ergebnis:
    """Schreibt Ort, Serie und Technik an jede Aufnahme.

    `eintraege` paart jede Aufnahme mit ihrem Ort — `None`, wenn er offen ist.
    """
    stichworte_je_aufnahme = _stichworte(eintraege, serien)
    ergebnis = Ergebnis()

    for aufnahme, ort in eintraege:
        stichworte = stichworte_je_aufnahme.get(id(aufnahme), [])
        for endung, pfad in aufnahme.dateien.items():
            argumente = _argumente(ort, stichworte)
            if not argumente:
                continue
            if endung.upper() in EINGEBETTET:
                ziel, extra = pfad, ["-overwrite_original"]
                zaehler = "eingebettet"
            else:
                ziel, extra = pfad.with_suffix(SIDECAR), []
                zaehler = "sidecars"
                # Ein vorhandener Sidecar wird ERGAENZT, nie ersetzt: dort steht
                # oft die Handarbeit aus Capture One.
                if not ziel.exists():
                    extra = ["-o", str(ziel)]
                    ziel = None

            if _ruf_exiftool(argumente + extra, ziel):
                setattr(ergebnis, zaehler, getattr(ergebnis, zaehler) + 1)
            else:
                ergebnis.fehler.append(str(pfad))

    return ergebnis


def _argumente(ort: Ort | None, stichworte: Sequence[str]) -> list[str]:
    """Baut die exiftool-Argumente. Ohne Ort keine Koordinate — im Zweifel
    schreibt das Werkzeug nichts, statt etwas Ungefaehres zu behaupten."""
    args: list[str] = []

    if ort is not None:
        args += [
            f"-GPSLatitude={abs(ort.lat)}",
            f"-GPSLatitudeRef={'N' if ort.lat >= 0 else 'S'}",
            f"-GPSLongitude={abs(ort.lon)}",
            f"-GPSLongitudeRef={'E' if ort.lon >= 0 else 'W'}",
            # Ohne Fehlerangabe behauptet eine Koordinate eine Genauigkeit, die
            # sie nicht hat.
            f"-GPSHPositioningError={ort.radius_m}",
        ]
        if ort.name:
            args.append(f"-XMP-photoshop:City={ort.name}")

    for wort in stichworte:
        args += [f"-XMP-dc:Subject+={wort.split('|')[-1]}", f"-XMP-lr:HierarchicalSubject+={wort}"]

    return args


EINZELN = "Technik|Einzelbild"
"""Das Stichwort fuer eine Aufnahme, die zu keiner Serie gehoert.

Es sorgt dafuer, dass JEDE Aufnahme etwas zu schreiben hat und damit einen
Sidecar bekommt. Ohne es blieben genau die Bilder ohne Sidecar, die weder Ort
noch Serie haben -- nach dem Lauf vom 2026-08-30 waeren das rund 112 gewesen,
und KT-1 haette zu Recht wieder "systemisch fehlen die xmps" gesagt.

Die Angabe ist wahr, nicht bloss Fuellung: ein Bild, das zu keiner Reihe
gehoert, IST ein Einzelbild, und das ist eine Technik-Aussage wie "Panorama"."""


def _stichworte(
    eintraege: Sequence[tuple[Aufnahme, Ort | None]], serien: Iterable[Serie]
) -> dict[int, list[str]]:
    """Ordnet jeder Aufnahme ihre hierarchischen Stichworte zu."""
    zuordnung: dict[int, list[str]] = {}
    for s in serien:
        marke = f"{s.typ}{s.nummer:02d}"
        for a in s.aufnahmen:
            zuordnung.setdefault(id(a), []).extend([f"Serie|{marke}", f"Technik|{s.typ}"])
    for aufnahme, _ in eintraege:
        zuordnung.setdefault(id(aufnahme), [EINZELN])
    return zuordnung


def _ruf_exiftool(argumente: list[str], ziel: Path | None) -> bool:
    befehl = ["exiftool", "-q", "-m", *argumente]
    if ziel is not None:
        befehl.append(str(ziel))
    try:
        fertig = subprocess.run(befehl, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise ExiftoolFehlt(
            "exiftool ist nicht installiert — ohne es kann nichts geschrieben werden."
        ) from exc
    return fertig.returncode == 0
