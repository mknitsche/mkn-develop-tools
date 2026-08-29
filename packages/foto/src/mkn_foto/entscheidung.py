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

NOTIZ = "ort.md"
"""Je Ordner eine Notiz zum Hineinschreiben. Geschrieben wird dort, wo die
Bilder liegen — nicht in einer zentralen Liste, die veraltet, sobald jemand
zwei Ordner zu einem Spot zusammenfasst."""

_SIGNATUR = "_so-gehts.md"
"""Liegt diese Datei im Ziel, stammt der Ordner von einem frueheren Lauf und
darf geraeumt werden. Sie enthaelt nur das Verfahren, keine Sessiondaten —
sonst waere sie ein zweiter Zustand neben den Notizen und wuerde veralten."""


_UEBERSCHRIFT = "## Ort"


class ZielNichtLeer(RuntimeError):
    """Im Zielordner liegt etwas, das nicht von einem frueheren Lauf stammt."""


class NotizenVorhanden(RuntimeError):
    """Im Zielordner stehen ausgefuellte Notizen — die waeren sonst weg."""


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
    """Legt je Session einen Ordner mit Bildern und einer Notiz an.

    Der Ordner heisst nach Datum und Zeitspanne, OHNE laufende Nummer: mit ihr
    laesst sich weder etwas zusammenfassen noch verschieben, ohne dass die
    Reihenfolge luegt. Ohne sie sortieren sich die Ordner von selbst
    chronologisch.

    `eintraege` sind die offenen Sessions mit dem, was ueber sie bekannt ist —
    ein Vorschlag mit Name und Radius ist eine Frage, die sich mit Ja
    beantworten laesst, eine leere Zeile ist Arbeit.
    """
    ziel = Path(ziel)
    _raeume_frueheren_lauf(ziel)
    ziel.mkdir(parents=True, exist_ok=True)

    for spot, ort in eintraege:
        ordner = ziel / f"{spot.von:%Y-%m-%d_%H%M}-{spot.bis:%H%M}"
        ordner.mkdir(exist_ok=True)

        kopiert = 0
        for aufnahme in waehle(spot, anzahl):
            for endung, pfad in aufnahme.dateien.items():
                if endung in (".JPG", ".JPEG") and pfad is not None:
                    shutil.copy2(pfad, ordner / pfad.name)
                    kopiert += 1

        (ordner / NOTIZ).write_text(_notiz(spot, ort, kopiert), encoding="utf-8")

    (ziel / _SIGNATUR).write_text(_verfahren(len(eintraege)), encoding="utf-8")
    return ziel


def _notiz(spot: Spot, ort: Ort | None, kopiert: int) -> str:
    zeilen = [
        f"# {spot.von:%Y-%m-%d} {spot.von:%H:%M} bis {spot.bis:%H:%M}",
        "",
        f"- {len(spot.aufnahmen)} Aufnahmen in dieser Session",
    ]
    if kopiert:
        zeilen.append(f"- {kopiert} davon liegen hier zum Ansehen")
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
    zeilen += ["", "## Ort", "", "", "## Gehoert zusammen mit", "", ""]
    return "\n".join(zeilen)


def _verfahren(anzahl: int) -> str:
    return "\n".join(
        [
            "# So geht es",
            "",
            f"{anzahl} Sessions warten auf eine Entscheidung. Je Ordner liegen ein paar",
            "Bilder und eine `ort.md`.",
            "",
            "1. Ordner oeffnen, Bilder ansehen.",
            f"2. In `{NOTIZ}` unter **Ort** hineinschreiben, wo das war.",
            "3. Ist es derselbe Spot wie ein anderer Ordner, den anderen Ordnernamen",
            "   unter **Gehoert zusammen mit** eintragen — oder die Ordner",
            "   zusammenschieben, wie es bequemer ist.",
            "",
            "Die Ordner tragen keine Nummern, damit beides moeglich ist. Sie sortieren",
            "sich nach Datum von selbst.",
            "",
            "Diese Datei enthaelt keine Sessiondaten und veraltet deshalb nicht. Ein",
            "neuer Lauf raeumt diesen Ordner allerdings — vorher die Notizen sichern.",
            "",
        ]
    )


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
    beschrieben = sorted(n.parent.name for n in ziel.glob(f"*/{NOTIZ}") if _ist_beschrieben(n))
    if beschrieben:
        raise NotizenVorhanden(
            f"In {ziel} sind {len(beschrieben)} Notizen ausgefuellt "
            f"({', '.join(beschrieben[:3])}{' …' if len(beschrieben) > 3 else ''}). "
            "Ein neuer Lauf wuerde sie loeschen. Bitte den Ordner erst sichern "
            "oder umbenennen."
        )
    if not (ziel / _SIGNATUR).exists():
        raise ZielNichtLeer(
            f"{ziel} ist nicht leer und stammt nicht aus einem frueheren Lauf "
            f"(kein {_SIGNATUR}). Bitte einen anderen Zielordner waehlen."
        )
    for eintrag in inhalt:
        if eintrag.is_dir():
            shutil.rmtree(eintrag)
        else:
            eintrag.unlink()


def _ist_beschrieben(notiz: Path) -> bool:
    """Steht unter der Ort-Ueberschrift etwas, das nicht vom Werkzeug stammt?

    Nur der Abschnitt zaehlt, in den geschrieben wird — die Zeilen darueber
    schreibt das Werkzeug selbst, und sie waeren sonst jedes Mal ein Hindernis.
    """
    text = notiz.read_text(encoding="utf-8")
    if _UEBERSCHRIFT not in text:
        return False
    dahinter = text.split(_UEBERSCHRIFT, 1)[1]
    return any(zeile.strip() and not zeile.startswith("#") for zeile in dahinter.splitlines())
