"""Legt die Vorlage an, mit der ein Mensch die offenen Orte entscheidet.

Was das Werkzeug nicht belegen kann, entscheidet der Mensch — aber nur, wenn
er es ANSEHEN kann. Je offener Session entsteht ein Ordner mit einer Handvoll
Bildern und daneben eine Liste, die sagt, was bekannt ist und was fehlt.

Die Einheit ist auch hier die Session: 476 unbestimmte Aufnahmen sind 21
Entscheidungen, nicht 476. Eine Liste, die jedes Bild einzeln vorlegt, wird
nicht abgearbeitet, sondern weggelegt.

Zwei Regeln, die nicht verhandelbar sind:

- **Originale werden kopiert, nie angefasst.** Die Kamerabilder sind das
  Einzige, was es nur einmal gibt.
- **Nur JPEG.** Eine RAW-Datei ist vierzigmal so gross und in keinem
  Vorschauprogramm schneller zu sehen; fuer eine Ortsentscheidung reicht das
  beigelegte JPEG.
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

from mkn_foto.modell import Aufnahme, Ort, Spot

ANZAHL = 5
"""Wie viele Bilder je Session gezeigt werden."""


def waehle(spot: Spot, anzahl: int = ANZAHL) -> tuple[Aufnahme, ...]:
    """Waehlt Bilder, die ueber die Session VERTEILT liegen.

    Die ersten fuenf Bilder einer Session zeigen fuenfmal dasselbe Motiv.
    Verteilt zeigen sie, wo sie anfaengt, wohin sie geht und wo sie endet —
    nur so ist eine Session wiederzuerkennen. Erstes und letztes Bild sind
    immer dabei: das eine traegt oft die Wegmarke, das andere den Aufbruch.
    """
    alle = spot.aufnahmen
    if len(alle) <= anzahl:
        return alle
    if anzahl == 1:
        return (alle[0],)
    schritt = (len(alle) - 1) / (anzahl - 1)
    return tuple(alle[round(i * schritt)] for i in range(anzahl))


def bereite_vor(
    eintraege: Sequence[tuple[Spot, Ort | None]],
    ziel: Path,
    *,
    anzahl: int = ANZAHL,
) -> Path:
    """Legt je Eintrag einen Ordner mit Bildern an und schreibt `liste.md`.

    `eintraege` sind die offenen Sessions mit dem, was ueber sie bekannt ist —
    ein Vorschlag mit Name und Radius ist eine Frage, die sich mit Ja
    beantworten laesst, eine leere Zeile ist Arbeit.
    """
    ziel = Path(ziel)
    ziel.mkdir(parents=True, exist_ok=True)
    zeilen = [
        "# Offene Orte",
        "",
        f"{len(eintraege)} Sessions warten auf eine Entscheidung.",
        "",
    ]

    for nummer, (spot, ort) in enumerate(eintraege, start=1):
        name = f"{nummer:02d}_{spot.von:%Y-%m-%d_%H%M}-{spot.bis:%H%M}"
        ordner = ziel / name
        ordner.mkdir(exist_ok=True)

        kopiert = 0
        for aufnahme in waehle(spot, anzahl):
            for endung, pfad in aufnahme.dateien.items():
                if endung in (".JPG", ".JPEG") and pfad is not None:
                    shutil.copy2(pfad, ordner / pfad.name)
                    kopiert += 1

        zeilen.append(f"## {name}")
        zeilen.append("")
        zeilen.append(f"- {len(spot.aufnahmen)} Aufnahmen, {spot.von:%H:%M} bis {spot.bis:%H:%M}")
        if kopiert:
            zeilen.append(f"- {kopiert} Bilder zum Ansehen im Ordner")
        else:
            zeilen.append("- **kein JPEG vorhanden** — nur RAW, hier ist nichts zu sehen")
        if ort is None:
            zeilen.append("- kein Anker in der Naehe: der Ort ist voellig offen")
        else:
            benennung = f" ({ort.name})" if ort.name else ""
            zeilen.append(
                f"- Vorschlag: {ort.lat:.5f}, {ort.lon:.5f}{benennung}, "
                f"Radius {ort.radius_m} m — nicht belegt genug zum Schreiben"
            )
        zeilen.append("- **Ort:** ")
        zeilen.append("")

    (ziel / "liste.md").write_text("\n".join(zeilen), encoding="utf-8")
    return ziel
