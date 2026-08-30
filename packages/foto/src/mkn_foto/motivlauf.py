"""Fuehrt Vorschau, Modell und Urteil ueber den ganzen Bestand.

**Die Wiederaufnahme laeuft ueber das ERGEBNIS, nicht ueber ein Journal.** Wer
schon ein Urteil hat, wird uebersprungen. Ein Journal waere ein zweiter Zustand
neben dem Ergebnis, und die beiden driften, sobald ein Lauf abbricht — genau in
dem Moment, in dem man sich auf die Wiederaufnahme verlassen muss (HC-1).

**Ein Abbruch ist der Normalfall.** 630 Modellaufrufe dauern Stunden; dazwischen
faellt das Netz aus, greift ein Limit, geht der Deckel zu. Der Lauf macht danach
dort weiter, wo er war, ohne dass jemand aufraeumt.

**Eine Serie kostet EINEN Aufruf.** Sie ist per Definition ein Motiv; ihre
Mitglieder erben das Urteil vom Kontaktbogen. Das ist der Unterschied zwischen
rund 630 und 1.293 Aufrufen — etwa 7 statt 13 Euro (Spec § 10a).

**Ohne Bild wird nicht angefragt.** Ein Aufruf ohne Bild kostet dasselbe und
liefert eine fluessige, vollstaendig erfundene Antwort. Die sieht man ihr nicht
an, und sie landete sonst als Stichwort in einer Datei.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from mkn_foto import bildurteil, kontaktbogen, vorschau
from mkn_kern import anfrage, modelle

_LOG = logging.getLogger(__name__)

#: (Vertreter, Mitglieder) — `None` als Mitglieder heisst Einzelbild.
Eintrag = tuple[Path, Sequence[Path] | None]


@dataclass
class Ergebnis:
    """Was der Lauf gesehen hat. Zahlen und Gruende, keine Behauptungen."""

    urteile: dict[Path, bildurteil.Urteil] = field(default_factory=dict)
    """Je VERTRETER ein Urteil. Mitglieder finden es ueber `fuer()`."""

    mitglieder: dict[Path, Path] = field(default_factory=dict, repr=False)
    """Mitglied -> Vertreter."""

    fehler: list[tuple[Path, str]] = field(default_factory=list)
    aufrufe: int = 0

    def fuer(self, bild: Path) -> bildurteil.Urteil | None:
        """Das Urteil zu diesem Bild — auch, wenn es Mitglied einer Serie ist."""
        vertreter = self.mitglieder.get(bild, bild)
        return self.urteile.get(vertreter)


def fahre(
    eintraege: Sequence[Eintrag],
    wahl: modelle.Wahl,
    *,
    schluessel: str | None = None,
    transport: anfrage.Transport | None = None,
    vorhandene: Ergebnis | None = None,
) -> Ergebnis:
    """Holt fuer jeden Eintrag ein Bildurteil.

    `vorhandene` traegt die Urteile eines frueheren Laufs; was dort schon steht,
    wird nicht noch einmal angefragt.
    """
    ergebnis = vorhandene or Ergebnis()
    kopf = _kopf(wahl, schluessel)
    ziel = modelle.ANBIETER[wahl.anbieter].basis_url

    with tempfile.TemporaryDirectory(prefix="mkn-foto-motiv-") as arbeitsraum:
        raum = Path(arbeitsraum)
        for nummer, (vertreter, gruppe) in enumerate(eintraege):
            for m in gruppe or ():
                ergebnis.mitglieder[m] = vertreter
            if vertreter in ergebnis.urteile:
                continue  # schon beurteilt -- die Wiederaufnahme

            bild = _bildvorlage(vertreter, gruppe, raum / f"{nummer:05d}.jpg")
            if bild is None:
                ergebnis.fehler.append((vertreter, "keine lesbare Vorschau"))
                continue

            koerper = wahl.baue_anfrage(bildurteil.prompt(), bilder=[bild])
            try:
                antwort = anfrage.sende(ziel, koerper, kopf, transport=transport)
            except anfrage.AnfrageFehler as exc:
                # Ein Fehler darf die anderen 629 nicht mitnehmen -- aber er muss
                # im Ergebnis stehen, nicht im Nichts.
                _LOG.warning("Bildurteil fehlgeschlagen: %s (%s)", vertreter.name, exc)
                ergebnis.fehler.append((vertreter, str(exc)))
                continue

            ergebnis.aufrufe += 1
            ergebnis.urteile[vertreter] = bildurteil.aus_antwort(antwort)

    return ergebnis


def _bildvorlage(vertreter: Path, gruppe: Sequence[Path] | None, ziel: Path) -> Path | None:
    """Kontaktbogen fuer eine Serie, sonst die Vorschau des Einzelbildes."""
    if gruppe and len(gruppe) > 1:
        vorschauen = []
        for i, m in enumerate(gruppe):
            v = _als_bild(m, ziel.with_name(f"{ziel.stem}-{i:03d}.jpg"))
            if v is not None:
                vorschauen.append(v)
        if not vorschauen:
            return None
        return kontaktbogen.baue(vorschauen, ziel)
    return _als_bild(vertreter, ziel)


def _als_bild(quelle: Path, ziel: Path) -> Path | None:
    """Ein anzeigbares JPEG — direkt oder als eingebettete Vorschau.

    Ein JPEG ist schon eines; eine RAW-Datei traegt ihres eingebettet.
    """
    if quelle.suffix.upper() in (".JPG", ".JPEG"):
        return quelle if vorschau.ist_brauchbar(quelle) else None
    return vorschau.hole(quelle, ziel)


def _kopf(wahl: modelle.Wahl, schluessel: str | None) -> dict[str, str]:
    profil = modelle.ANBIETER[wahl.anbieter]
    if profil.schluessel_variable is None:
        return {}
    wert = schluessel or wahl.schluessel() or ""
    if wahl.anbieter == "anthropic":
        return {"x-api-key": wert, "anthropic-version": "2023-06-01"}
    return {"authorization": f"Bearer {wert}"}


MOTIV_MARKE = "Motiv|"
"""Woran ein bereits beurteiltes Bild zu erkennen ist. Der Baum IST der Zustand
— ein Journal daneben waere ein zweiter, und die beiden driften genau dann,
wenn ein Lauf abbricht (HC-1)."""


def aus_baum(bilder: Sequence[Path]) -> Ergebnis:
    """Liest den Stand eines frueheren Laufs aus den Sidecars.

    Geprueft wird nur die ANWESENHEIT eines Motiv-Stichworts, nicht sein Inhalt:
    was einmal geschrieben wurde, ist beurteilt. Wer den Inhalt neu bewerten
    will, loescht den Sidecar — das ist eine bewusste Handlung und soll eine
    bleiben.
    """
    ergebnis = Ergebnis()
    for bild in bilder:
        seite = bild.with_suffix(".xmp")
        if not seite.exists():
            continue
        try:
            inhalt = seite.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            _LOG.warning("Sidecar unlesbar, gilt als offen: %s (%s)", seite.name, exc)
            continue
        if MOTIV_MARKE in inhalt:
            # Der genaue Inhalt steht in der Datei; hier zaehlt nur "erledigt".
            ergebnis.urteile[bild] = bildurteil.Urteil(sicher=True, fehler="aus dem Baum")
    return ergebnis
