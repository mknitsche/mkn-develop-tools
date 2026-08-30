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

import json
import logging
import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from mkn_foto import anreichern, bildurteil, kontaktbogen, messung, vorschau
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
            urteil = bildurteil.aus_antwort(antwort)
            ergebnis.urteile[vertreter] = urteil
            # SOFORT in den Baum, nicht erst am Ende. `aus_baum` liest genau
            # von hier -- aber nur, wenn waehrend des Laufs geschrieben wird.
            # Am 2026-08-30 wurde zweimal abgebrochen, und beide Male waren die
            # bezahlten Urteile weg: 3,12 EUR und 200 Aufrufe beim zweiten Mal.
            # Der Kommentar an MOTIV_MARKE sagt "Der Baum IST der Zustand"; das
            # stimmt erst mit dieser Zeile.
            _merke(vertreter, urteil)

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
Fortschrittsmeldung -- die Abrechnung macht der Anbieter.

**Die Zahl ist eine OBERGRENZE, kein Preis.** Sie ignoriert das Prompt-Caching:
der Bildurteil-Prompt ist bei jedem Aufruf identisch, und der Anbieter
berechnet wiederholte Eingaben deutlich guenstiger.

Gemessen am 2026-08-30: der Lauf rechnete sich auf 14,24 USD hoch, KT-1s
Guthaben sank im selben Zeitraum um 13,05 USD -- und darin steckte noch ein
fremder Mail-Lauf. Die Schaetzung lag also um mindestens 12 Prozent zu hoch.

Das ist die richtige Richtung fuer einen Schaetzwert (lieber zu teuer
angekuendigt als zu billig), aber es gehoert gesagt statt verschwiegen.
Genauer ginge es nur mit den `cache_read_input_tokens` aus der Antwort -- die
werden bisher nicht ausgewertet."""

SIDECAR = ".xmp"
"""Die Sidecar-Endung. Wohin ein Zwischenurteil GEHOERT, entscheidet dagegen
`anreichern.traeger` -- eine Endung ist keine Regel.

Der Kommentar hier sagte frueher "dieselbe Datei wie in `anreichern`", und genau
das stimmte nur fuer RAW. Bei einem JPEG bettet `anreichern` ein, waehrend hier
danebengeschrieben wurde: dieselbe Aussage an zwei Stellen."""

MOTIV_MARKE = "Motiv|"
"""Woran ein bereits beurteiltes Bild zu erkennen ist. Der Baum IST der Zustand
— ein Journal daneben waere ein zweiter, und die beiden driften genau dann,
wenn ein Lauf abbricht (HC-1)."""


def _merke(bild: Path, urteil: bildurteil.Urteil) -> None:
    """Schreibt die Motiv-Stichworte sofort neben das Bild.

    NUR die Marke, nicht das ganze Urteil: die eigentliche Anreicherung kommt
    spaeter und schreibt alles (Ort, Serie, Beschreibung) in einem Zug. Hier
    geht es allein darum, dass ein bezahlter Aufruf einen Abbruch ueberlebt --
    und `aus_baum` erkennt einen beurteilten Vertreter an genau dieser Marke.

    Ein Fehler beim Merken darf den Lauf nicht abreissen: er kostet im
    schlimmsten Fall EINEN doppelten Aufruf, ein Abbruch kostet alle.
    """
    if not urteil.sicher or not urteil.motive:
        # Ein unsicheres Urteil schreibt nichts -- Regel A. Es wird beim
        # naechsten Lauf erneut gefragt, und das ist richtig so.
        return
    # Die Traeger-Regel kommt aus `anreichern`, nicht aus diesem Modul: JPEG
    # traegt eingebettet, RAW bekommt einen Sidecar. Die fruehere eigene Fassung
    # (`bild.with_suffix(SIDECAR)`) kannte sie nicht und legte ihre Marke neben
    # JEDES Bild -- auch neben ein JPEG, in das `anreichern` unmittelbar danach
    # einbettet. Bei 65 JPEG ohne RAW im Bestand waren das 65 ueberzaehlige
    # Dateien und, schlimmer, dieselbe Aussage an zwei Stellen.
    ziel, eingebettet = anreichern.traeger(bild)
    args = []
    for w in urteil.motive:
        # Idempotent wie in `anreichern`: ein zweiter Lauf ueber dieselbe Datei
        # darf das Stichwort nicht verdoppeln.
        args += anreichern._setze("XMP-lr:HierarchicalSubject", f"{MOTIV_MARKE}{w}")
    befehl = ["exiftool", "-q", *args]
    if eingebettet or ziel.exists():
        befehl += ["-overwrite_original", str(ziel)]
    else:
        befehl += ["-o", str(ziel), str(bild)]
    try:
        subprocess.run(befehl, check=False, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        _LOG.warning("Urteil nicht gemerkt: %s (%s)", bild.name, exc)


def aus_baum(bilder: Sequence[Path]) -> Ergebnis:
    """Liest den Stand eines frueheren Laufs aus den Sidecars.

    Geprueft wird nur die ANWESENHEIT eines Motiv-Stichworts, nicht sein Inhalt:
    was einmal geschrieben wurde, ist beurteilt. Wer den Inhalt neu bewerten
    will, loescht den Sidecar — das ist eine bewusste Handlung und soll eine
    bleiben.
    """
    ergebnis = Ergebnis()
    eingebettete: list[Path] = []
    for bild in bilder:
        ziel, eingebettet = anreichern.traeger(bild)
        if eingebettet and ziel.exists():
            # Ein JPEG traegt seine Marke IN sich. Sie mit `read_text` zu suchen
            # hiesse, bis zu 20 MB Bilddaten je Datei zu lesen -- ueber den
            # Bestand rund 26 GB. Solche Dateien werden gesammelt und in EINEM
            # exiftool-Aufruf gefragt.
            eingebettete.append(ziel)
        # **Beim Lesen nachsichtig, beim Schreiben streng.** Auch ein JPEG wird
        # zusaetzlich auf einen Sidecar geprueft: Baeume aus frueheren Laeufen
        # tragen dort ihre Marke, weil die Traeger-Regel damals nicht galt.
        # Wer sie ignoriert, laesst einen Wiederaufnahme-Lauf jedes bezahlte
        # Urteil erneut kaufen -- teurer als der Fehler, den die Regel behebt.
        seite = bild.with_suffix(SIDECAR)
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

    marken = set(_mit_marke(eingebettete))
    for bild in bilder:
        if bild in marken:
            ergebnis.urteile[bild] = bildurteil.Urteil(sicher=True, fehler="aus dem Baum")
    return ergebnis


def _mit_marke(bilder: Sequence[Path]) -> list[Path]:
    """Welche dieser Dateien die Motiv-Marke eingebettet tragen — EIN Aufruf.

    Ein Fehlschlag gilt als "nicht beurteilt": das kostet im schlimmsten Fall
    einen doppelten Modellaufruf. Die Gegenrichtung waere teurer -- ein Bild
    faelschlich fuer erledigt zu halten, hiesse, dass es NIE ein Urteil bekommt.
    """
    if not bilder:
        return []
    try:
        roh = subprocess.run(
            ["exiftool", "-q", "-json", "-XMP-lr:HierarchicalSubject", *[str(b) for b in bilder]],
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        _LOG.warning("eingebettete Marken nicht lesbar, gelten als offen (%s)", exc)
        return []
    if not roh.strip():
        return []
    try:
        eintraege = json.loads(roh)
    except json.JSONDecodeError as exc:
        _LOG.warning("Markenabfrage unlesbar, gilt als offen (%s)", exc)
        return []
    gefunden: list[Path] = []
    for e in eintraege:
        if MOTIV_MARKE in str(e.get("HierarchicalSubject", "")):
            gefunden.append(Path(e["SourceFile"]))
    return gefunden
