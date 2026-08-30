"""Kopiert die Aufnahmen in den angereicherten Baum und benennt sie dabei um.

Der dritte Baum entsteht NEBEN dem Original, nie darin (Design § "Der dritte
Baum"). Das Werkzeug liest die Kamerabilder und schreibt eine Kopie — es fasst
die Originale niemals schreibend an. Der Grund ist nicht Vorsicht, sondern eine
gemessene Gefahr: `foto-karten-import` faehrt als letzte Stufe ein `rsync` ueber
den gesamten Baum Mac → SSD. Eine Aenderung am Original haette Groesse und
Zeitstempel veraendert und beim naechsten Import die unberuehrte SSD-Kopie
ueberschrieben — waehrend die Karten laengst formatiert sind.

Drei Dinge, die dieser Schritt leisten muss und die man ihm nicht ansieht:

- **Sidecars wandern mit.** `.xmp` steht nicht in `inventar.BILD_ENDUNGEN` und
  ist fuer das Inventar unsichtbar. Wer nur die inventarisierten Dateien kopiert,
  laesst die Bearbeitung zurueck. Regel aus dem Design: RAW und Sidecar nie
  getrennt bewegen.
- **Der Platz wird VORHER geprueft.** Ein Abbruch mitten im Lauf hinterlaesst
  einen halben Baum, dem man das nicht ansieht.
- **Ein zweiter Lauf legt nichts doppelt an.** Nur so bleibt der Baum ableitbar
  und das Experimentieren zulaessig.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from mkn_foto.modell import Aufnahme, Serie
from mkn_foto.namen import archiv_name, ist_schon_da, vorhandene_kopien

SIDECAR = ".xmp"
"""Die Endung, die neben einer RAW-Datei leben darf, ohne im Inventar zu stehen."""

_SICHERHEIT = 1.2
"""Aufschlag auf die geschaetzte Zielgroesse. Der Baum bekommt Sidecars und
Metadaten dazu; ein Lauf, der bei 100,1 % scheitert, hilft niemandem."""


class ZuWenigPlatz(RuntimeError):
    """Das Ziel fasst den Baum nicht — gemeldet VOR der ersten Kopie."""


@dataclass
class Ergebnis:
    """Was ein Lauf getan hat. Zahlen, keine Behauptungen."""

    kopiert: int = 0
    sidecars: int = 0
    uebersprungen: int = 0
    ziele: list[Path] = field(default_factory=list)

    kopien: list[tuple[int, dict[str, Path]]] = field(default_factory=list)
    """Aufnahme-Identitaet -> ihre neuen Pfade im Zielbaum.

    Die Anreicherung schreibt in den ZIELbaum, nie in die Originale, und braucht
    dafuer diese Zuordnung. Eine flache Liste aller Ziele reicht nicht: sie sagt
    nicht, welche Datei zu welcher Aufnahme gehoert -- die Anreicherung schriebe
    dann den Ort der einen Session an das Bild der anderen."""


def kopiere(
    aufnahmen: Sequence[Aufnahme],
    ziel_wurzel: Path,
    *,
    serien: Iterable[Serie] = (),
) -> Ergebnis:
    """Legt je Aufnahme eine umbenannte Kopie im Tagesordner ab.

    `serien` ordnet Aufnahmen ihrem Serien-Abschnitt zu; was in keiner Serie
    steht, wird `std`. Die Zuordnung laeuft ueber die Identitaet der Aufnahme,
    nicht ueber ihren Namen — eine Serie kennt ihre Mitglieder selbst.
    """
    ziel_wurzel = Path(ziel_wurzel)
    _pruefe_platz(aufnahmen, ziel_wurzel)

    abschnitt = _serien_abschnitte(serien)
    ergebnis = Ergebnis()

    for a in aufnahmen:
        ziel_tag = ziel_wurzel / f"{a.zeitpunkt:%Y-%m-%d}"
        if ist_schon_da(ziel_tag, a):
            # Uebersprungen heisst NICHT abwesend. Die Dateien liegen da, und
            # die Anreicherung braucht ihre Pfade -- sonst tut ein zweiter Lauf
            # ueber denselben Baum nichts und meldet trotzdem Erfolg. Genau das
            # geschah am 2026-08-30 um 07:30: 1.293 Aufnahmen, 0 Sidecars,
            # 0 Modellaufrufe, "FERTIG" nach 36 Sekunden.
            ergebnis.uebersprungen += 1
            vorhanden = vorhandene_kopien(ziel_tag, a)
            if vorhanden:
                ergebnis.kopien.append((id(a), vorhanden))
            continue

        ziel_tag.mkdir(parents=True, exist_ok=True)
        merkmale = abschnitt.get(id(a), {"typ": "std"})

        sidecar_getan = False
        neue_pfade: dict[str, Path] = {}
        for endung, quelle in a.dateien.items():
            ziel = ziel_tag / archiv_name(a, endung, **merkmale)
            shutil.copy2(quelle, ziel)
            ergebnis.kopiert += 1
            ergebnis.ziele.append(ziel)
            neue_pfade[endung] = ziel

            # EIN Sidecar je Aufnahme, nicht je Endung: RAW und JPEG desselben
            # Ausloesers teilen sich einen, und beide Kopien landen ohnehin auf
            # demselben Zielnamen. Die erste Fassung tat es zweimal -- kein
            # Datenverlust, aber doppelte Arbeit und ein Zaehler, der luegt: der
            # Lauf ueber die echte Reise meldete 272 Sidecars, im Ziel lagen 139.
            begleiter = quelle.with_suffix(SIDECAR)
            if not sidecar_getan and begleiter.exists():
                shutil.copy2(begleiter, ziel.with_suffix(SIDECAR))
                ergebnis.sidecars += 1
                sidecar_getan = True

        ergebnis.kopien.append((id(a), neue_pfade))

    return ergebnis


def _serien_abschnitte(serien: Iterable[Serie]) -> dict[int, dict[str, object]]:
    """Bildet Aufnahme-Identitaet auf ihre Namensmerkmale ab."""
    zuordnung: dict[int, dict[str, object]] = {}
    for s in serien:
        gesamt = len(s.aufnahmen)
        for pos, a in enumerate(s.aufnahmen, start=1):
            zuordnung[id(a)] = {
                "typ": s.typ,
                "serie": s.nummer,
                "pos": pos,
                "gesamt": gesamt,
            }
    return zuordnung


def _pruefe_platz(aufnahmen: Sequence[Aufnahme], ziel_wurzel: Path) -> None:
    """Bricht ab, BEVOR die erste Datei geschrieben ist.

    Gemessen wird gegen den naechsten existierenden Elternpfad: das Ziel selbst
    gibt es beim ersten Lauf noch nicht, und `statvfs` auf einen fehlenden Pfad
    wirft — der Lauf waere dann an der Platzpruefung gescheitert statt am Platz.
    """
    noetig = sum(p.stat().st_size for a in aufnahmen for p in a.dateien.values() if p.exists())
    if not noetig:
        return

    bezug = ziel_wurzel
    while not bezug.exists() and bezug != bezug.parent:
        bezug = bezug.parent

    frei = os.statvfs(bezug)
    verfuegbar = frei.f_bavail * frei.f_frsize
    if verfuegbar < noetig * _SICHERHEIT:
        raise ZuWenigPlatz(
            f"{ziel_wurzel} hat {verfuegbar} Byte frei, gebraucht werden rund "
            f"{int(noetig * _SICHERHEIT)} Byte fuer {len(aufnahmen)} Aufnahmen. "
            "Abbruch vor der ersten Kopie — ein halber Baum ist schlimmer als keiner."
        )
