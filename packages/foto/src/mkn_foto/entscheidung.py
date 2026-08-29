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

_LISTE = "liste.md"
"""Die Liste ist zugleich die Signatur: liegt sie im Ziel, stammt der Ordner
von einem frueheren Lauf und darf geraeumt werden."""


class ZielNichtLeer(RuntimeError):
    """Im Zielordner liegt etwas, das nicht von einem frueheren Lauf stammt."""


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
    _raeume_frueheren_lauf(ziel)
    ziel.mkdir(parents=True, exist_ok=True)

    # Die schwerste Entscheidung zuerst. Wer chronologisch abarbeitet, faengt
    # bei den Streubildern an — im gemessenen Bestand sind das elf von zwanzig
    # Sessions mit zusammen 26 Aufnahmen, waehrend die neun echten Spots 410
    # tragen. Der Ordnername traegt das Datum weiterhin, die Reihenfolge also
    # die Wichtigkeit und nicht die Zeit.
    eintraege = sorted(eintraege, key=lambda e: len(e[0].aufnahmen), reverse=True)

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


def _raeume_frueheren_lauf(ziel: Path) -> None:
    """Loescht die Spuren eines frueheren Laufs — und nur die.

    Ohne das Raeumen legt der zweite Lauf seine Ordner NEBEN die alten:
    firsthand vierzig Eintraege fuer zwanzig Sessions, und einem alten Ordner
    ist nicht anzusehen, dass er von gestern ist. Besonders tueckisch, weil
    sich die Nummerierung zwischen zwei Laeufen aendern darf — dann kollidieren
    die Namen nicht einmal.

    Geraeumt wird nur, wenn die Liste dort liegt: sie ist die Signatur dieses
    Werkzeugs. Zeigt jemand versehentlich auf einen Ordner mit eigenen Dateien,
    knallt es, statt dass geraeumt wird.
    """
    if not ziel.exists():
        return
    inhalt = list(ziel.iterdir())
    if not inhalt:
        return
    if not (ziel / _LISTE).exists():
        raise ZielNichtLeer(
            f"{ziel} ist nicht leer und stammt nicht aus einem frueheren Lauf "
            f"(kein {_LISTE}). Bitte einen anderen Zielordner waehlen."
        )
    for eintrag in inhalt:
        if eintrag.is_dir():
            shutil.rmtree(eintrag)
        else:
            eintrag.unlink()
