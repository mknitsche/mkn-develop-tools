"""Wer das Bild gemacht hat — und wie man ihn erreicht.

**Warum die Angaben nicht im Code stehen.** Dieses Paket ist oeffentlich. Ein
Name, ein Wohnort und eine Mailadresse im Quelltext waeren fuer jeden lesbar,
fuer immer, und in der Git-Historie auch dann noch, wenn die Zeile geloescht
ist. Deshalb gilt hier dieselbe Regel wie beim API-Schluessel: **das Werkzeug
kennt den Platz, nicht den Wert.**

Der Anwender legt eine kleine JSON-Datei an::

    {"name": "...", "stadt": "...", "land": "...", "email": "..."}

und nennt ihren Pfad ueber ``MKN_FOTO_URHEBER_DATEI``. Sagt er nichts, sucht
das Werkzeug an einer einzigen naheliegenden Stelle nach — und schreibt sonst
keinen Urheber. **Nichts zu schreiben ist ein gueltiges Ergebnis:** wer seinen
Namen nicht in den Bildern haben will, bekommt ihn nicht hinein.

**Warum drei Traeger fuer denselben Namen** (Spec-Logik wie beim Ort): XMP,
IPTC/IIM und EXIF sind drei getrennte Karteien in derselben Datei, und die
Programme lesen unterschiedliche. Wer nur ``XMP-dc:Creator`` setzt, ist in
Capture Ones IPTC-Ansicht und in jedem EXIF-Betrachter namenlos.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DATEI_VARIABLE = "MKN_FOTO_URHEBER_DATEI"
"""Zeigt auf die JSON-Datei mit den Angaben des Anwenders."""

STANDARD_ORT = Path.home() / ".config" / "mkn-foto" / "urheber.json"
"""Die eine Stelle, an der ohne Umgebungsvariable nachgesehen wird."""


@dataclass(frozen=True)
class Urheber:
    """Die Angaben, die an jedes Bild geschrieben werden."""

    name: str
    stadt: str = ""
    land: str = ""
    email: str = ""

    def argumente(self, *, jahr: int | None, eingebettet: bool) -> list[str]:
        """Baut die exiftool-Argumente.

        `jahr` ist das AUFNAHMEjahr, nicht das heutige: ein Bild von 2019 traegt
        2019. Fehlt es, bleibt der Rechtevermerk weg — ein Copyright ohne Jahr
        ist ungenauer als keines.
        """
        args = [f"-XMP-dc:Creator={self.name}", f"-EXIF:Artist={self.name}"]

        if jahr is not None:
            # Bewusst "(C)" statt des Zeichens: exiftool nimmt beides, aber der
            # Umweg ueber die Shell-Kodierung ist eine Fehlerquelle, die dem
            # Vermerk nichts hinzufuegt.
            vermerk = f"(C) {jahr} {self.name}"
            args += [f"-XMP-dc:Rights={vermerk}", f"-EXIF:Copyright={vermerk}"]

        if self.email:
            args.append(f"-XMP-iptcCore:CreatorWorkEmail={self.email}")
        if self.stadt:
            args.append(f"-XMP-iptcCore:CreatorCity={self.stadt}")
        if self.land:
            args.append(f"-XMP-iptcCore:CreatorCountry={self.land}")

        if eingebettet:
            # IIM traegt nur ein eingebettetes Format; im XMP-Sidecar meldet
            # exiftool dafuer "Nothing to write" -- dieselbe Grenze wie beim Ort.
            args.append(f"-IPTC:By-line={self.name}")
            if jahr is not None:
                args.append(f"-IPTC:CopyrightNotice=(C) {jahr} {self.name}")

        return args


def lade(pfad: Path | None = None) -> Urheber | None:
    """Liest die Angaben — oder gibt `None` zurueck, wenn es keine gibt.

    Eine fehlende oder unlesbare Datei ist kein Absturz: sie bedeutet schlicht
    "kein Urheber". Ein fehlender ``name`` ebenso — ohne ihn ergaeben Stadt und
    Mailadresse keinen Sinn.
    """
    if pfad is None:
        genannt = os.environ.get(DATEI_VARIABLE)
        pfad = Path(genannt) if genannt else STANDARD_ORT

    try:
        rohdaten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(rohdaten, dict) or not rohdaten.get("name"):
        return None

    return Urheber(
        name=str(rohdaten["name"]),
        stadt=str(rohdaten.get("stadt", "")),
        land=str(rohdaten.get("land", "")),
        email=str(rohdaten.get("email", "")),
    )
