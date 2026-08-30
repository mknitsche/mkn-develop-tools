"""Ein Bild statt fuenfzehn — alle Aufnahmen einer Serie im Raster.

Spec § 4a: *"Alle Bilder der Serie als ein Bild, nummeriert, im Raster. Reines
Pillow, kein LLM-Aufruf. Er ist zugleich das Werkzeug, mit dem Stufe 3 urteilt —
statt fuenfzehn Einzelbildern ein Blick. Firsthand erprobt: am Kontaktbogen der
Zugspitzen-Serie war die Reihenstruktur sofort lesbar, an den Einzelbildern
nicht."*

Er ist auch der Grund, warum die Bildanalyse bezahlbar bleibt: eine Serie ist per
Definition EIN Motiv. Rund 630 Modellaufrufe statt 1.293 — etwa 7 € statt 13.

**Die Nummern sind kein Schmuck.** Das Modell soll sagen koennen „Bild 3 bis 7
gehoeren nicht dazu"; ohne Nummern kann es die Stelle nicht benennen, und die
Antwort ist unbrauchbar.

**Ein unlesbares Bild reisst den Bogen nicht ab.** Bei 1.293 Aufnahmen ist eine
kaputte Datei normal — sie fehlt dann eben. Fehlen ALLE, entsteht kein Bogen:
ein leeres Bild kostet beim Modell dasselbe wie ein volles und sagt nichts.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageDraw

from mkn_foto import vorschau

_LOG = logging.getLogger(__name__)

MAX_KACHELN = 20
"""Mehr wird unlesbar — und teurer, weil der Bogen als Bild an das Modell geht.
Bei laengeren Reihen wird gleichmaessig ausgeduennt, Anfang und Ende bleiben."""

KACHEL_PX = 400
"""Kantenlaenge einer Kachel. Gross genug, dass ein Modell das Motiv erkennt,
klein genug, dass zwanzig davon in ein Bild passen."""

RAND_PX = 4


def gezeigte(anzahl: int) -> int:
    """Wie viele Kacheln ein Bogen fuer `anzahl` Bilder haette."""
    return min(anzahl, MAX_KACHELN)


def auswahl(pfade: Sequence[Path]) -> list[Path]:
    """Duennt gleichmaessig aus — Anfang und Ende bleiben immer.

    Sie tragen den Beginn und das Ende der Reihe, und genau darauf kommt es beim
    Beurteilen einer Serie an: wo faengt sie an, wo hoert sie auf, gehoert das
    letzte Bild noch dazu.
    """
    if len(pfade) <= MAX_KACHELN:
        return list(pfade)
    schritt = (len(pfade) - 1) / (MAX_KACHELN - 1)
    return [pfade[round(i * schritt)] for i in range(MAX_KACHELN)]


def baue(
    pfade: Sequence[Path],
    ziel: Path,
    *,
    rand: int = RAND_PX,
    beschriftung: bool = True,
) -> Path | None:
    """Setzt die Bilder zu einem Bogen zusammen. `None`, wenn keines lesbar war."""
    gewaehlt = auswahl(pfade)
    kacheln: list[tuple[int, Image.Image]] = []

    for nummer, pfad in enumerate(gewaehlt, start=1):
        try:
            with Image.open(pfad) as bild:
                kopie = bild.convert("RGB")
                kopie.thumbnail((KACHEL_PX, KACHEL_PX))
                kacheln.append((nummer, kopie.copy()))
        except Exception as exc:  # eine kaputte Datei ist kein Grund aufzuhoeren
            _LOG.warning("Bild fuer den Kontaktbogen unlesbar, uebersprungen: %s (%s)", pfad, exc)

    if not kacheln:
        _LOG.warning("kein einziges lesbares Bild — kein Kontaktbogen fuer %s", ziel.name)
        return None

    spalten = math.ceil(math.sqrt(len(kacheln)))
    zeilen = math.ceil(len(kacheln) / spalten)
    breite = spalten * (KACHEL_PX + rand) + rand
    hoehe = zeilen * (KACHEL_PX + rand) + rand

    bogen = Image.new("RGB", (breite, hoehe), (24, 24, 24))
    zeichner = ImageDraw.Draw(bogen)

    for i, (nummer, kachel) in enumerate(kacheln):
        x = rand + (i % spalten) * (KACHEL_PX + rand)
        y = rand + (i // spalten) * (KACHEL_PX + rand)
        bogen.paste(kachel, (x, y))
        if beschriftung:
            # Dunkler Kasten unter der Zahl: auf hellem Himmel waere weisse
            # Schrift sonst unlesbar, und dann kann das Modell die Stelle nicht
            # benennen.
            zeichner.rectangle([x, y, x + 34, y + 22], fill=(0, 0, 0))
            zeichner.text((x + 6, y + 5), str(nummer), fill=(255, 255, 255))

    # Auch der fertige Bogen bleibt auf Modellmass. Zwanzig Kacheln ergeben
    # 2024x1620 -- darueber skaliert der Anbieter selbst, und seine Skalierung
    # ist schlechter als eine gerechnete: die Kacheln werden unnoetig unscharf,
    # und genau ihre Details soll das Modell ja beurteilen.
    if max(bogen.width, bogen.height) > vorschau.MAX_KANTE_PX:
        bogen.thumbnail((vorschau.MAX_KANTE_PX, vorschau.MAX_KANTE_PX), Image.LANCZOS)

    ziel.parent.mkdir(parents=True, exist_ok=True)
    bogen.save(ziel, quality=85)
    return ziel
