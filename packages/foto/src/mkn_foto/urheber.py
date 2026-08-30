"""Wer das Bild gemacht hat — und wie man ihn erreicht.

**Warum die Angaben nicht im Code stehen.** Dieses Paket ist oeffentlich. Ein
Name, ein Wohnort und eine Mailadresse im Quelltext waeren fuer jeden lesbar,
fuer immer, und in der Git-Historie auch dann noch, wenn die Zeile geloescht
ist. Deshalb gilt hier dieselbe Regel wie beim API-Schluessel: **das Werkzeug
kennt den Platz, nicht den Wert.**

Der Anwender traegt sie in seine Konfiguration ein (`mkn_foto.konfig`), unter
`urheber`. **Nichts zu schreiben ist ein gueltiges Ergebnis:** wer seinen Namen
nicht in den Bildern haben will, bekommt ihn nicht hinein.

**Warum drei Traeger fuer denselben Namen** (Spec-Logik wie beim Ort): XMP,
IPTC/IIM und EXIF sind drei getrennte Karteien in derselben Datei, und die
Programme lesen unterschiedliche. Wer nur ``XMP-dc:Creator`` setzt, ist in
Capture Ones IPTC-Ansicht und in jedem EXIF-Betrachter namenlos.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Urheber:
    """Die Angaben, die an jedes Bild geschrieben werden."""

    name: str
    stadt: str = ""
    land: str = ""
    email: str = ""
    website: str = ""
    rechte_url: str = ""
    nutzungsbedingungen: str = ""

    def argumente(self, *, jahr: int | None, eingebettet: bool) -> list[str]:
        """Baut die exiftool-Argumente.

        `jahr` ist das AUFNAHMEjahr, nicht das heutige: ein Bild von 2019 traegt
        2019. Fehlt es, bleibt der Rechtevermerk weg — ein Copyright ohne Jahr
        ist ungenauer als keines.
        """
        args = [f"-XMP-dc:Creator={self.name}", f"-EXIF:Artist={self.name}"]

        if jahr is not None:
            # KURZ, und das ist der Fachstandard, nicht Sparsamkeit: der
            # Vermerk soll lesbar bleiben. Erreichbarkeit gehoert in die
            # Kontaktfelder, Rechtssprache in UsageTerms -- ein
            # vollgestopfter Copyright-String ist fuer Menschen muehsam
            # und fuer Maschinen wertlos, weil keine Auswertung ihn zerlegt.
            vermerk = f"© {jahr} {self.name}"
            args += [f"-XMP-dc:Rights={vermerk}", f"-EXIF:Copyright={vermerk}"]

        if self.email:
            args.append(f"-XMP-iptcCore:CreatorWorkEmail={self.email}")
        if self.stadt:
            args.append(f"-XMP-iptcCore:CreatorCity={self.stadt}")
        if self.land:
            args.append(f"-XMP-iptcCore:CreatorCountry={self.land}")
        if self.website:
            args.append(f"-XMP-iptcCore:CreatorWorkURL={self.website}")

        # `Marked` ist die Aussage "dieses Bild ist geschuetzt" -- ohne sie
        # bleibt der Rechtestatus formal UNBEKANNT, auch wenn ein Vermerk
        # danebensteht. Suchmaschinen werten genau dieses Feld aus.
        args.append("-XMP-xmpRights:Marked=True")
        if self.rechte_url:
            args.append(f"-XMP-xmpRights:WebStatement={self.rechte_url}")
        if self.nutzungsbedingungen:
            args.append(f"-XMP-xmpRights:UsageTerms={self.nutzungsbedingungen}")

        if eingebettet:
            # IIM traegt nur ein eingebettetes Format; im XMP-Sidecar meldet
            # exiftool dafuer "Nothing to write" -- dieselbe Grenze wie beim Ort.
            args.append(f"-IPTC:By-line={self.name}")
            if jahr is not None:
                args.append(f"-IPTC:CopyrightNotice=© {jahr} {self.name}")

        return args
