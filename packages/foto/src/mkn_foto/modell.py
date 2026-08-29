"""Datenklassen der Foto-Anreicherung.

Reine Traeger ohne Verhalten. Die Einheit ist die AUFNAHME, nicht die Datei:
eine Belichtung liegt oft als RAW und JPEG vor, und beide beschreiben denselben
Moment. Wer stattdessen Dateien zaehlt, zaehlt Belichtungen doppelt und
schreibt widerspruechliche Metadaten in zwei Haelften derselben Sache.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Aufnahme:
    """Eine Belichtung — ob als RAW, JPEG oder beides."""

    zeitpunkt: datetime
    """Lokale Kamerazeit, absichtlich tz-naiv: so und nicht anders steht sie im
    EXIF. Eine erfundene Zeitzone waere eine Behauptung ueber den Aufnahmeort,
    die genau dann falsch ist, wenn sie gebraucht wird — auf Reisen."""

    kamera: str
    """Kuerzel der Notation: `D850`, `XE5`, `iP16Pro`."""

    stamm: str
    """Originalname ohne Endung, z.B. `DSCF3541`. Er bleibt erhalten, damit
    eine Datei nach dem Umbenennen noch zu ihrem Kamera-Original zurueckfindet."""

    dateien: dict[str, Path]
    """Endung (gross, mit Punkt) auf Pfad: `{".RAF": ..., ".JPG": ...}`."""

    exif: dict[str, Any]
    """EXIF der Leitdatei (RAW, sonst JPEG)."""

    # Die dict-Felder machen die Klasse unhashbar. Serien und Pipeline
    # identifizieren Aufnahmen deshalb ueber id() statt ueber ein set —
    # Absicht, kein Versehen.


@dataclass(frozen=True)
class Anker:
    """Eine bekannte Position zu einer bekannten Zeit.

    Der gemeinsame Nenner aller Ortsquellen: die GPS-Spur, die benannten
    Wegpunkte und die Handybilder liefern dasselbe — wo jemand wann war. Der
    Typ lebt deshalb hier und nicht in einem der Leser; sonst muesste die
    Mediathek aus dem GPX-Modul importieren und behaupten, ein Handybild sei
    ein Spurpunkt.
    """

    zeit: datetime
    """Immer tz-bewusste UTC."""

    lat: float
    lon: float

    name: str | None
    """Nur benannte Wegpunkte tragen einen. Ein benannter Ort schlaegt jede
    berechnete Koordinate — er benennt den Ort, statt ihn zu vermessen."""


@dataclass(frozen=True)
class Spot:
    """Eine zusammenhaengende Foto-Session an einem Ort.

    Die Einheit der Ortsbestimmung ist der Spot, NICHT das einzelne Bild. An
    einem Fleck koennen Stunden vergehen und zwischen zwei Aufnahmen zwoelf
    Minuten liegen — das ist kein fehlender Beleg, sondern der Beleg fuers
    Bleiben. Wer jedes Bild einzeln fragt „wo warst du in dieser Sekunde",
    laesst mitten in einer dreistuendigen Session Bilder unbestimmt, die von
    hundert anderen mit demselben Ort umgeben sind.
    """

    aufnahmen: tuple[Aufnahme, ...]

    @property
    def von(self) -> datetime:
        return self.aufnahmen[0].zeitpunkt

    @property
    def bis(self) -> datetime:
        return self.aufnahmen[-1].zeitpunkt


@dataclass(frozen=True)
class Serie:
    """Mehrere Aufnahmen mit einem gemeinsamen Zweck."""

    typ: str
    """`hdr` | `pan` | `foc` | `iso` | `wb`."""

    nummer: int
    """1-basiert, je Tag und Typ."""

    aufnahmen: tuple[Aufnahme, ...]

    quelle: str
    """`kamera` | `heuristik` | `bild` — woher die Serienaussage stammt."""

    sicher: bool
    """Nur `True`, wenn die Kamera es selbst gesagt hat. Eine Heuristik darf
    sich nie als Tatsache ausgeben; der Unterschied muss bis in den Bericht
    tragen, sonst wird aus einer Vermutung nach zwei Laeufen eine Gewissheit."""


@dataclass(frozen=True)
class Ort:
    """Eine Koordinate, die ihre eigene Belastbarkeit mitfuehrt."""

    lat: float
    lon: float

    radius_m: int
    """Geht als `GPSHPositioningError` mit in die Datei. Eine Koordinate ohne
    Fehlerangabe behauptet Genauigkeit, die sie nicht hat.

    Der Zweifel steht NICHT hier, sondern in `quelle`: ein Ort, der nicht
    belegt ist, traegt dort `vorschlag` und wird nicht geschrieben. Zwei
    Felder fuer dieselbe Aussage waeren zwei Zustaende ueber eine Sache —
    eine fruehere Fassung liess `radius_m=None` dasselbe bedeuten, was nur
    noetig war, solange der Radius aus einer Geschwindigkeit folgte."""

    name: str | None
    quelle: str
    """`gpx` | `schild` | `anker` | `vorschlag`."""
