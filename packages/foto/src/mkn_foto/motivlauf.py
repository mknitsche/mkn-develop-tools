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
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from mkn_foto import bildurteil, kontaktbogen, messung, vorschau
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

    messung: messung.Protokoll = field(default_factory=messung.Protokoll)
    """Tokens, Dauer und Kosten je Aufruf. Die Zahlen liefert die API frei Haus
    -- sie wegzuwerfen und hinterher zu schaetzen waere die teuerste Art, an
    Daten zu kommen, die man schon hatte (KT-1 vor dem ersten Lauf)."""

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
    melde: Callable[[str], None] | None = None,
    melde_alle: int = 25,
) -> Ergebnis:
    """Holt fuer jeden Eintrag ein Bildurteil.

    `vorhandene` traegt die Urteile eines frueheren Laufs; was dort schon steht,
    wird nicht noch einmal angefragt.
    """
    ergebnis = vorhandene or Ergebnis()
    offen = sum(1 for v, _ in eintraege if v not in ergebnis.urteile)
    getan = 0
    begonnen_gesamt = time.monotonic()
    kopf = _kopf(wahl, schluessel)
    ziel = wahl.url()

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

            art = "serie" if gruppe and len(gruppe) > 1 else "einzel"
            koerper = wahl.baue_anfrage(bildurteil.prompt(), bilder=[bild])
            begonnen = time.monotonic()
            try:
                antwort = anfrage.sende(ziel, koerper, kopf, transport=transport)
            except anfrage.AnfrageFehler as exc:
                # Ein Fehler darf die anderen nicht mitnehmen -- aber er muss im
                # Ergebnis stehen, nicht im Nichts. Und er wird GEMESSEN: er hat
                # Zeit gekostet, und ein Lauf ohne seine Fehlschlaege sieht
                # schneller aus, als er war.
                _LOG.warning("Bildurteil fehlgeschlagen: %s (%s)", vertreter.name, exc)
                ergebnis.fehler.append((vertreter, str(exc)))
                ergebnis.messung.nimm(
                    messung.Messwert(
                        name=vertreter.name,
                        dauer_s=time.monotonic() - begonnen,
                        art=art,
                        fehler=str(exc),
                    )
                )
                continue

            ergebnis.aufrufe += 1
            ergebnis.messung.nimm(
                messung.Messwert.aus_antwort(
                    vertreter.name, antwort, dauer_s=time.monotonic() - begonnen, art=art
                )
            )
            ergebnis.urteile[vertreter] = bildurteil.aus_antwort(antwort)

            getan += 1
            if melde is not None and (getan % melde_alle == 0 or getan == offen):
                melde(_fortschritt(getan, offen, ergebnis, begonnen_gesamt))

    return ergebnis


def _fortschritt(getan: int, offen: int, ergebnis: Ergebnis, begonnen: float) -> str:
    """Wo der Lauf steht, was er bisher gekostet hat, wie lange es noch dauert.

    "Bild 400 von 969" allein ist eine Zahl ohne Folge. Erst mit Verbrauch und
    Hochrechnung kann jemand entscheiden, ob er den Lauf weiterlaufen laesst --
    und genau das ist der Sinn einer Zwischenmeldung (KT-1: "zeit auch messen
    und auch fortschritt").
    """
    vergangen = time.monotonic() - begonnen
    je_stueck = vergangen / max(getan, 1)
    rest_s = je_stueck * max(offen - getan, 0)
    kosten = ergebnis.messung.kosten_eur(preis_ein=PREIS_EIN, preis_aus=PREIS_AUS)
    return (
        f"{getan}/{offen} · {vergangen / 60:.0f} min gelaufen, "
        f"noch ~{rest_s / 60:.0f} min · "
        f"{ergebnis.messung.tokens_ein:,} Tokens · {kosten:.2f} EUR"
        + (f" · {len(ergebnis.fehler)} Fehler" if ergebnis.fehler else "")
    ).replace(",", ".")


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
    """Ein anzeigbares JPEG auf Modellmass — direkt oder als eingebettete Vorschau.

    Eine RAW-Datei traegt ihre Vorschau eingebettet; ein JPEG ist schon ein
    Bild. **Beide muessen aber auf Modellmass**, und genau daran fehlte es:

    Die erste Fassung reichte ein JPEG unveraendert durch ("ist ja schon ein
    Bild"). Bei einer D850 sind das 6192x4128 Pixel -- rund 34.000 Tokens statt
    2.185, das Fuenfzehnfache, je Bild. Kein Bildurteil braucht 25 Megapixel.

    Es ist derselbe Fehler wie einen Tag zuvor im RAW-Zweig (dort gingen die
    Vorschauen in Originalgroesse hinaus: 60.588 Tokens je Bild, 252 EUR statt
    16). Der RAW-Zweig wurde repariert, dieser blieb -- weil niemand nach dem
    zweiten Zweig gefragt hat. Ein Fix ist erst fertig, wenn er ALLE Wege
    erreicht, die das Problem haben.

    Das Original bleibt unberuehrt: verkleinert wird in den Arbeitsraum.
    """
    if quelle.suffix.upper() in (".JPG", ".JPEG"):
        if not vorschau.ist_brauchbar(quelle):
            return None
        ziel.parent.mkdir(parents=True, exist_ok=True)
        return vorschau.verkleinere(quelle, ziel)
    return vorschau.hole(quelle, ziel)


def _kopf(wahl: modelle.Wahl, schluessel: str | None) -> dict[str, str]:
    profil = modelle.ANBIETER[wahl.anbieter]
    if profil.schluessel_variable is None:
        return {}
    wert = schluessel or wahl.schluessel() or ""
    if wahl.anbieter == "anthropic":
        return {"x-api-key": wert, "anthropic-version": "2023-06-01"}
    if wahl.anbieter == "gemini":
        # Google nimmt kein `Bearer`. Haette die Adresse gestimmt, waere dies
        # der naechste 401 gewesen -- und ein gefaelschter Transport findet
        # weder das eine noch das andere, weil er sich nirgends anmeldet.
        return {"x-goog-api-key": wert}
    return {"authorization": f"Bearer {wert}"}


PREIS_EIN = 4.63
PREIS_AUS = 23.15
"""Opus, EUR je Million Tokens (Stand 2026-08). Nur fuer die Hochrechnung in der
Fortschrittsmeldung -- die Abrechnung macht der Anbieter."""

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
