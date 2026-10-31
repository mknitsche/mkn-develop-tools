"""Pruefen: ein Stueck, das nicht sagt, was es sagen soll, faellt auf -- billig, dann genau.

**Warum zweistufig.** Spracherkennung auf jedem Stueck waere das Teuerste im ganzen Lauf.
Die meisten Fehler der Synthese verraten sich aber schon an der Aufnahme selbst: sie ist
viel zu kurz (das Modell hat mittendrin aufgehoert), viel zu lang (es hat sich in einer
Wiederholung verfangen) oder enthaelt eine lange Stille. Nur dort, und bei einer
Stichprobe der unauffaelligen Stuecke als Gegenprobe fuer den Verdacht, den die billigen
Merkmale nicht sehen, wird mit Whisper nachgehoert.

**Die Einheit ist der Block** (`sprecher.Block`): lokal ein Stueck, bei Gemini mehrere Saetze.
Das **Pruefband** (gemessene gegen erwartete Dauer) ist ein Wert des Wegs (`stimmen.WEGE`).

**Was als falsch gilt.** Die Wortfehlerrate (Levenshtein auf Woertern, klein und ohne
Satzzeichen, damit Gross-/Kleinschreibung und Zeichensetzung des Erkenners nichts
kosten) gegen den Text des Stuecks. **Die Abschrift wird vorher wie der Hoertext
aufbereitet** (`deterministisch`: Zahlen und Abkuerzungen ausschreiben): Whisper schreibt
"1990" und "3,5 Prozent", der Hoertext sagt "neunzehnhundertneunzig" und "drei Komma
fuenf Prozent" -- dieselbe Aussage, die ohne diesen Schritt als Fehler zaehlte und ein
einwandfreies Stueck neu sprechen liess. Nur fuer Deutsch: nur dort schreibt der Hoertext
Zahlen aus; in jeder anderen Sprache stehen Ziffern auf beiden Seiten. Ueber 30 % wird
das Stueck einmal neu gesprochen -- die Synthese ist zufaellig, ein zweiter Wurf gelingt
oft -- und neu gehoert. Bleibt es darueber, steht es als Befund im Bericht. **Kein
Abbruch:** ein einzelnes schlechtes Stueck soll das Hoerstueck eines ganzen Buches nicht
verhindern, aber wer es hoert, muss wissen koennen, wo die Stelle ist.

**Kurze Titel** (unter vier Woertern) werden weder gehoert noch beurteilt: bei zwei
Woertern ist die Wortfehlerrate Zufall, und die erwartete Dauer nach Zeichenzahl
stimmt fuer sie nicht (die Stimme setzt vor und nach einem Titel Luft).

**Ein Ausfall des Arbeiters kostet ein Stueck, nicht das Buch.** Die Pruefung laeuft
NACH Stunden des Sprechens; bricht sie bei einem Tod, einer Zeitgrenze oder einer
Fehlerantwort des Arbeiters ab, ist der ganze Zwischenstand in Gefahr. Darum geht das
Neusprechen denselben Weg wie das Sprechen im Lauf (`sprecher.sprich_zweimal`: ein neuer
Versuch),
und scheitert es dennoch, bleibt der alte Ton und das Stueck steht als Befund "nicht neu
gesprochen" im Bericht. Scheitert das Hoeren, ist das Stueck nicht beurteilt, und auch das
steht als Befund ("nicht gehoert") da: nie gilt ein Stueck deshalb still als in Ordnung.

**Was weiter laut abbricht.** Ein fehlender Messwert und ein gescheiterter ffmpeg-Lauf
sind kein Ausfall des Arbeiters, sondern ein Defekt der Umgebung oder des Laufs selbst;
sie gehen als Ausnahme nach oben.
"""

from __future__ import annotations

import json
import math
import random
import re
import statistics
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mkn_audio.arbeiter_client import ArbeiterFehler
from mkn_audio.hoertext import _ist_deutsch, deterministisch
from mkn_audio.sprecher import Block, Sprecher, SprecherFehler, erste_woerter
from mkn_audio.stimmen import Stimme
from mkn_audio.typen import Mp4Fehler

ZEICHEN_JE_SEKUNDE = 14.0
"""Erwartete Sprechgeschwindigkeit (Zeichen je Sekunde) des lokalen Wegs, Mass des Prototyps."""

STILLE_S = 2.5
"""Stille ab dieser Laenge im Stueck ist Verdacht."""

FEHLERRATE_MAX = 0.30
"""Wortfehlerrate, ab der (strikt darueber) ein Stueck als falsch gesprochen gilt."""

TITEL_MIN_WOERTER = 4

MIN_ZEICHEN_BAND = 100
"""Bloecke unter dieser Laenge werden nicht gegen das relative Band geprueft."""

MIN_BLOECKE_BAND = 5
"""Weniger prueffaehige Bloecke einer Stimme geben keinen Median: das Band bleibt ungeprueft."""

TOLERANZ_MARKE_S = 0.5
"""So weit darf eine Kapitelmarke neben ihrer Pause liegen (Kodierversatz, Rundung)."""

STILLE_ANTEIL_KAPITEL = 0.8
"""Die Pause an einer Kapitelmarke muss mindestens so viel der Kapitelpause lang sein."""

_STOPPWOERTER = {
    "de": frozenset(
        [
            "und",
            "oder",
            "aber",
            "doch",
            "auch",
            "noch",
            "nur",
            "sehr",
            "etwas",
            "ganz",
            "mit",
            "ohne",
            "in",
            "im",
            "am",
            "an",
            "auf",
            "zu",
            "zum",
            "zur",
            "der",
            "die",
            "das",
            "den",
            "dem",
            "des",
            "ein",
            "eine",
            "einen",
            "einem",
            "einer",
            "eines",
            "ist",
            "sind",
            "war",
            "wie",
            "als",
            "bei",
            "von",
            "vom",
            "für",
            "fuer",
        ]
    ),
    "en": frozenset(
        [
            "and",
            "or",
            "but",
            "also",
            "very",
            "quite",
            "rather",
            "somewhat",
            "with",
            "without",
            "in",
            "on",
            "at",
            "to",
            "of",
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "as",
            "by",
            "for",
            "from",
        ]
    ),
}
"""Woerter, die in einer Stilvorgabe nichts ueber den Vortrag sagen und in jedem Text vorkommen."""

_STILLE_START = re.compile(r"silence_start:\s*(-?[0-9.]+)")
_STILLE_ENDE = re.compile(r"silence_end:\s*(-?[0-9.]+)")
_WORT = re.compile(r"\w+")
_FFMPEG_ZEIT_S = 120


@dataclass(frozen=True)
class Befund:
    """Ein Block, der nach dem Neusprechen noch auffaellig ist.

    `zeit_s` ist die Stelle IM Block (Sekunden ab dessen Anfang), wenn es eine gibt
    -- der Beginn einer Stille; die Stelle im ganzen Hoerstueck kennt erst, wer die
    Bloecke aneinandergelegt hat. Ohne erkennbare Stelle `None`.
    """

    block_nr: int
    grund: str
    zeit_s: float | None


@dataclass(frozen=True)
class Pruefung:
    """Ergebnis der Pruefung.

    `gehoert` zaehlt Bloecke, nicht Hoer-Aufrufe (ein neu gesprochener Block wird
    zweimal gehoert und zaehlt einmal). `neuer_ton` enthaelt die Messwerte jedes neu
    gesprochenen Blocks: die Aufnahme wurde ersetzt, die Messwerte des Aufrufers (Dauer,
    Sprechrate) gelten fuer sie nicht mehr. `warnungen` sagt, was die Pruefung nicht
    beurteilen konnte (kein Hoerer): nie gilt Ungeprueftes still als in Ordnung.
    """

    auffaellig: tuple[Befund, ...]
    gehoert: int
    neu_gesprochen: int
    neuer_ton: Mapping[int, dict[str, Any]] = field(default_factory=dict)
    warnungen: tuple[str, ...] = ()


def _woerter(text: str) -> list[str]:
    return _WORT.findall(text.casefold())


def _abschrift_woerter(abschrift: str, sprache: str) -> list[str]:
    """Die Woerter der Abschrift, so geschrieben wie der Hoertext (nur Deutsch)."""
    if _ist_deutsch(sprache):
        abschrift = deterministisch(abschrift)
    return _woerter(abschrift)


def _wortfehlerrate(soll: Sequence[str], ist: Sequence[str]) -> float:
    """Editierabstand der Wortfolgen geteilt durch die Zahl der Soll-Woerter."""
    vorher = list(range(len(ist) + 1))
    for i, w_soll in enumerate(soll, start=1):
        jetzt = [i]
        for j, w_ist in enumerate(ist, start=1):
            jetzt.append(
                min(vorher[j] + 1, jetzt[j - 1] + 1, vorher[j - 1] + (w_soll != w_ist)),
            )
        vorher = jetzt
    return vorher[-1] / len(soll)


def _erste_stille(wav: Path) -> float | None:
    """Beginn der ersten Stille ab `STILLE_S` im WAV, sonst `None`.

    ffmpeg meldet eine Stille erst, wenn sie die Mindestlaenge erreicht hat; jedes
    `silence_start` ist also schon eine ausreichend lange. Eine Stille bis zum Dateiende
    hat keinen `silence_end` -- darum wird nur der Beginn gelesen.
    """
    befehl = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-i",
        str(wav),
        "-af",
        f"silencedetect=noise=-40dB:d={STILLE_S}",
        "-f",
        "null",
        "-",
    ]
    try:
        lauf = subprocess.run(
            befehl, capture_output=True, text=True, timeout=_FFMPEG_ZEIT_S, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as fehler:
        raise Mp4Fehler(f"ffmpeg (Stille-Messung) scheitert fuer {wav}: {fehler}") from fehler
    if lauf.returncode != 0:
        raise Mp4Fehler(
            f"ffmpeg (Stille-Messung) scheitert fuer {wav} (Exit {lauf.returncode}): "
            f"{lauf.stderr.strip()[-500:]}"
        )
    treffer = _STILLE_START.search(lauf.stderr)
    return max(0.0, float(treffer.group(1))) if treffer else None


def _ist_kurze_ansage(block: Block) -> bool:
    """Titel und Zwischenueberschriften sind Ansagen; unter vier Woertern ist nichts zu urteilen."""
    return block.ansage and len(_woerter(block.text)) < TITEL_MIN_WOERTER


def sprechraten_median(
    bloecke: Sequence[Block],
    ton: Mapping[int, Mapping[str, Any]],
    stimme_von: Callable[[Block], Stimme],
) -> dict[str, tuple[float, int]]:
    """Median der Sprechrate (Zeichen/s) je Stimme ueber alle Bloecke ab `MIN_ZEICHEN_BAND`.

    Gerechnet aus Textlaenge und gemessener Dauer, gesprochene wie aus dem Zwischenstand
    gelesene Bloecke gleich; der Wert ist `(Median, Anzahl)`. Eine Stimme ohne solchen Block
    fehlt. Der Median haengt nicht an der Reihenfolge, in der die Bloecke fertig wurden.
    """
    raten: dict[str, list[float]] = {}
    for b in bloecke:
        if len(b.text) >= MIN_ZEICHEN_BAND and b.nr in ton and ton[b.nr]["dauer"] > 0:
            raten.setdefault(stimme_von(b).name, []).append(len(b.text) / ton[b.nr]["dauer"])
    return {name: (statistics.median(werte), len(werte)) for name, werte in raten.items()}


def _verdacht(
    block: Block,
    messung: Mapping[str, Any],
    wav: Path,
    band: tuple[float, float],
    *,
    rate: float | None = ZEICHEN_JE_SEKUNDE,
) -> tuple[list[str], float | None]:
    """Gruende des akustischen Verdachts und Beginn einer Stille (falls es eine gibt).

    Die Dauer wird gegen die Sprechrate `rate` (Zeichen/s) gemessen -- lokal die feste des
    Prototyps, bei Gemini der Median des Laufs; `band` ist das erlaubte Verhaeltnis
    gemessen/erwartet. Ohne `rate` gibt es keine Dauerpruefung.
    """
    gruende: list[str] = []
    if messung.get("zu_kurz"):
        gruende.append("Arbeiter meldet zu kurz")
    if rate is not None:
        verhaeltnis = messung["dauer"] / (len(block.text) / rate)
        if verhaeltnis < band[0]:
            gruende.append(f"Dauer nur {verhaeltnis * 100:.0f} % der erwarteten")
        elif verhaeltnis > band[1]:
            gruende.append(f"Dauer {verhaeltnis * 100:.0f} % der erwarteten")
    stille = _erste_stille(wav)
    if stille is not None:
        gruende.append(f"Stille von mehr als {STILLE_S:g} s".replace(".", ","))
    return gruende, stille


def stil_mitgesprochen(stil: str, abschrift: str, sprache: str) -> tuple[str, ...]:
    """Die Inhaltswoerter der Stilvorgabe, die in der Abschrift stehen (Spec 8.4).

    Die Vorgabe geht als Metadatum mit, nie als Text; steht ein Wort davon in der Abschrift,
    hat das Modell die Regieanweisung mitgesprochen. Stoppwoerter (und, mit, der ...) zaehlen
    nicht, sonst traefe jede Vorgabe in jedem Text. Der Vergleich ist wortgenau: eine gebeugte
    Form (ruhige) wird nicht erkannt -- die Pruefung ist eine Untergrenze.
    """
    stopp = _STOPPWOERTER.get(sprache[:2].lower(), frozenset().union(*_STOPPWOERTER.values()))
    gesprochen = set(_woerter(abschrift))
    treffer = dict.fromkeys(w for w in _woerter(stil) if w not in stopp and w in gesprochen)
    return tuple(treffer)


def _nicht_gehoert(
    nr: int,
    fehler: ArbeiterFehler | None,
    gruende: list[str],
    stille: float | None,
    *,
    nach_neusprechen: bool,
) -> Befund:
    """Der Befund fuer einen Block, der nicht beurteilt werden konnte, weil das Hoeren ausfiel.

    Ohne `fehler` kann der Sprecher gar nicht hoeren (kein Arbeiter).
    """
    wann = " nach erneutem Sprechen" if nach_neusprechen else ""
    grund = "kein Hörer" if fehler is None else fehler.klasse
    return Befund(
        block_nr=nr,
        grund=f"nicht gehört ({grund}){wann}; Anlass: {'; '.join(gruende)}",
        zeit_s=stille,
    )


def _neu_gegen_median(
    b: Block,
    wer: Stimme,
    sprecher: Sprecher,
    wav: Path,
    band: tuple[float, float],
    rate: float,
    gruende: list[str],
) -> tuple[dict[str, Any], float | None]:
    """Spricht den Ausreisser-Block einmal neu; liegt er wieder ausserhalb, bricht der Lauf ab.

    Ein 140-s-Block fuer 1100 Zeichen ist ein Wiederholungs- oder Halluzinationsverdacht, den
    niemand still durchwinken darf (Spec 8.3). Gibt die neuen Messwerte und den Beginn einer
    Stille in der neuen Aufnahme.
    """
    stelle = f"Kapitel {b.kapitel + 1}, Block {b.nr}, beginnt mit »{erste_woerter(b.text)}«"
    try:
        messung = sprecher.sprich(b, wer, wav)
    except SprecherFehler as fehler:
        raise SprecherFehler(
            f"Sprechraten-Ausreißer ({'; '.join(gruende)}) und das Neusprechen scheiterte "
            f"({fehler.klasse}): {stelle}\n{fehler}",
            "Ausreisser",
        ) from fehler
    verhaeltnis = messung["dauer"] / (len(b.text) / rate)
    if not band[0] <= verhaeltnis <= band[1]:
        raise SprecherFehler(
            f"Sprechraten-Ausreißer auch nach erneutem Sprechen: Dauer {verhaeltnis * 100:.0f} % "
            f"der erwarteten (erlaubt {band[0] * 100:.0f}-{band[1] * 100:.0f} %), {stelle}",
            "Ausreisser",
        )
    return messung, _erste_stille(wav)


def pruefe(
    bloecke: Sequence[Block],
    ton: Mapping[int, dict[str, Any]],
    *,
    sprecher: Sprecher,
    sprache: str,
    stimme: Stimme,
    wav_pfad: Callable[[Block], Path],
    stichprobe: float = 0.05,
    zufall: random.Random,
    ansage_stimme: Stimme | None = None,
    band: tuple[float, float],
    band_relativ: bool,
    verwirf: Callable[[Block], None] | None = None,
) -> Pruefung:
    """Prueft alle Bloecke; hoert verdaechtige und eine Stichprobe der uebrigen.

    `ton` bildet `Block.nr` auf die Messwerte beim Sprechen ab (`dauer`, `zu_kurz` ...).
    `stimme` liefert die Regler fuer das Neusprechen; Ansage-Bloecke (`Block.ansage`)
    spricht `ansage_stimme` neu, wenn es sie gibt -- sonst wuerde ein misslungener Vorspann
    beim zweiten Wurf mit der falschen Stimme gesprochen. `band` ist das erlaubte Verhaeltnis
    gemessener zu erwarteter Dauer (ein Wert des Wegs, `stimmen.WEGE`). Die Stichprobe zieht
    `round(stichprobe * Anzahl der Bloecke)` Bloecke (mindestens einen, wenn `stichprobe > 0`)
    aus den unauffaelligen mit `zufall`, damit sie mit festem Seed reproduzierbar ist.

    Bricht ein Block als Ausreisser den Lauf ab, ruft `pruefe` vorher `verwirf(block)`: der
    Zwischenstand des Blocks (Aufnahme des zweiten Wurfs, Messwerte des ersten) passt nicht
    zusammen und darf nicht fortgesetzt werden -- das Fortsetzen spricht ihn frisch.

    Gehoert wird nur, wenn der Sprecher es kann (`kann_hoeren`); sonst steht die Warnung
    "Abschrift: nicht geprüft (kein Arbeiter)" im Ergebnis, und jeder verdaechtige Block ist ein
    Befund -- ungeprueft ist nie in Ordnung.
    """
    zu_pruefen = [b for b in bloecke if not _ist_kurze_ansage(b)]
    kann_hoeren = sprecher.kann_hoeren()
    warnungen = [] if kann_hoeren else ["Abschrift: nicht geprüft (kein Arbeiter)"]

    def wer_spricht(b: Block) -> Stimme:
        return ansage_stimme if b.ansage and ansage_stimme is not None else stimme

    if not kann_hoeren and any(wer_spricht(b).stil for b in zu_pruefen):
        warnungen.append("Stilvorgabe: ungeprüft (kein Arbeiter)")

    # Relatives Band (Gemini): der Median je Stimme wird EINMAL aus allen Bloecken des Laufs
    # gerechnet, nach dem Sprechen, nie waehrend der parallelen Vergabe -- so haengt das
    # Ergebnis nicht von der Reihenfolge der Fertigstellung ab, und er wird beim Neusprechen
    # nicht nachgefuehrt.
    medianraten: dict[str, float] = {}
    if band_relativ:
        for name, (median, anzahl) in sprechraten_median(zu_pruefen, ton, wer_spricht).items():
            if anzahl >= MIN_BLOECKE_BAND:
                medianraten[name] = median
            else:
                warnungen.append(
                    f"Sprechraten-Band: ungeprüft (weniger als {MIN_BLOECKE_BAND} Blöcke), "
                    f"Stimme {name}"
                )

    verdaechtig: dict[int, tuple[list[str], float | None]] = {}
    befunde: list[Befund] = []
    gehoert = 0
    neu_gesprochen = 0
    neuer_ton: dict[int, dict[str, Any]] = {}
    for b in zu_pruefen:
        if b.nr not in ton:
            raise Mp4Fehler(f"Block {b.nr}: keine Messwerte vom Sprechen vorhanden")
        wav = wav_pfad(b)
        if not band_relativ:
            gruende, stille = _verdacht(b, ton[b.nr], wav, band)
        else:
            rate = medianraten.get(wer_spricht(b).name) if len(b.text) >= MIN_ZEICHEN_BAND else None
            gruende, stille = _verdacht(b, ton[b.nr], wav, band, rate=rate)
            if rate is not None and any(g.startswith("Dauer") for g in gruende):
                # Ausreisser: EINMAL neu sprechen (selbes Modell, selber Ton-Schluessel); liegt
                # auch der zweite Wurf ausserhalb, bricht der Lauf laut ab (Spec 8.3).
                try:
                    messung, stille = _neu_gegen_median(
                        b, wer_spricht(b), sprecher, wav, band, rate, gruende
                    )
                except SprecherFehler:
                    if verwirf is not None:
                        verwirf(b)
                    raise
                neuer_ton[b.nr] = messung
                neu_gesprochen += 1
                gruende = (
                    []
                    if stille is None
                    else [f"Stille von mehr als {STILLE_S:g} s".replace(".", ",")]
                )
        if gruende:
            verdaechtig[b.nr] = (gruende, stille)

    unauffaellig = [b for b in zu_pruefen if b.nr not in verdaechtig]
    anzahl = round(stichprobe * len(bloecke))
    if stichprobe > 0:
        anzahl = max(1, anzahl)
    gezogen = (
        {b.nr for b in zufall.sample(unauffaellig, min(anzahl, len(unauffaellig)))}
        if kann_hoeren
        else set()
    )

    abschriften: dict[int, tuple[str, str, Stimme]] = {}  # die letzte Abschrift je gehoertem Block
    for b in zu_pruefen:
        if b.nr not in verdaechtig and b.nr not in gezogen:
            continue
        gruende, stille = verdaechtig.get(b.nr, (["Stichprobe"], None))
        soll = _woerter(b.text)
        if not soll:  # nichts Sprechbares im Text: es gibt nichts zu vergleichen
            continue
        if not kann_hoeren:
            befunde.append(_nicht_gehoert(b.nr, None, gruende, stille, nach_neusprechen=False))
            continue
        wav = wav_pfad(b)
        wer, b_sprache = (
            (ansage_stimme, ansage_stimme.sprache)
            if b.ansage and ansage_stimme is not None
            else (stimme, sprache)
        )
        arbeiter = sprecher.arbeiter
        assert arbeiter is not None  # kann_hoeren()

        try:
            abschrift = arbeiter.hoere(wav, b_sprache)
        except ArbeiterFehler as fehler:
            befunde.append(_nicht_gehoert(b.nr, fehler, gruende, stille, nach_neusprechen=False))
            continue
        gehoert += 1
        abschriften[b.nr] = (abschrift, b_sprache, wer)
        rate = _wortfehlerrate(soll, _abschrift_woerter(abschrift, b_sprache))
        if rate <= FEHLERRATE_MAX:
            continue

        # Einmal neu sprechen: die Synthese ist zufaellig, ein zweiter Wurf gelingt oft.
        # Scheitert auch das, bleibt der alte Ton (der Sprecher schreibt atomar) und der Block
        # steht als Befund da.
        try:
            neuer_ton[b.nr] = sprecher.sprich(b, wer, wav)
        except SprecherFehler as fehler:
            prozent = math.floor(rate * 100 + 0.5)
            befunde.append(
                Befund(
                    block_nr=b.nr,
                    grund=(
                        f"nicht neu gesprochen ({fehler.klasse}); Wortfehlerrate {prozent} % "
                        f"(Anlass: {'; '.join(gruende)})"
                    ),
                    zeit_s=stille,
                )
            )
            continue
        neu_gesprochen += 1
        abschriften.pop(b.nr, None)  # die alte Aufnahme ist ersetzt: ihre Abschrift gilt nicht mehr
        try:
            abschrift = arbeiter.hoere(wav, b_sprache)
        except ArbeiterFehler as fehler:
            befunde.append(_nicht_gehoert(b.nr, fehler, gruende, stille, nach_neusprechen=True))
            continue
        abschriften[b.nr] = (abschrift, b_sprache, wer)
        rate = _wortfehlerrate(soll, _abschrift_woerter(abschrift, b_sprache))
        if rate <= FEHLERRATE_MAX:
            continue

        # Die Stelle der Stille gilt fuer die neue Aufnahme neu bestimmt, nicht die alte.
        stille = _erste_stille(wav) if stille is not None else None
        befunde.append(
            Befund(
                block_nr=b.nr,
                grund=(
                    f"Wortfehlerrate {math.floor(rate * 100 + 0.5)} % nach erneutem Sprechen "
                    f"(Anlass: {'; '.join(gruende)})"
                ),
                zeit_s=stille,
            )
        )

    # Stilvorgabe in der Abschrift (Spec 8.4): Befund, kein Neusprechen. Ein Wort, das der Text
    # selbst enthaelt (eine Vorgabe "ruhig" in einem Text ueber Ruhe), ist kein Beleg.
    blocknr = {b.nr: b for b in zu_pruefen}
    for nr, (abschrift, b_sprache, wer) in abschriften.items():
        if not wer.stil:
            continue
        eigene = set(_woerter(blocknr[nr].text))
        woerter = tuple(
            w for w in stil_mitgesprochen(wer.stil, abschrift, b_sprache) if w not in eigene
        )
        if woerter:
            befunde.append(
                Befund(
                    block_nr=nr,
                    grund=f"Stilvorgabe mitgesprochen: {', '.join(woerter)}",
                    zeit_s=None,
                )
            )

    return Pruefung(
        auffaellig=tuple(befunde),
        gehoert=gehoert,
        neu_gesprochen=neu_gesprochen,
        neuer_ton=neuer_ton,
        warnungen=tuple(warnungen),
    )


def _stillen(audio: Path, mindestens_s: float, *, zeit_s: float) -> list[tuple[float, float]]:
    """Alle Stillen ab `mindestens_s` als (Anfang, Ende); eine bis zum Dateiende bleibt weg."""
    befehl = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-i",
        str(audio),
        "-af",
        f"silencedetect=noise=-40dB:d={mindestens_s}",
        "-f",
        "null",
        "-",
    ]
    try:
        lauf = subprocess.run(befehl, capture_output=True, text=True, timeout=zeit_s, check=False)
    except (OSError, subprocess.TimeoutExpired) as fehler:
        raise Mp4Fehler(
            f"ffmpeg (Kapitelmarken-Pruefung) scheitert fuer {audio}: {fehler}"
        ) from fehler
    if lauf.returncode != 0:
        raise Mp4Fehler(
            f"ffmpeg (Kapitelmarken-Pruefung) scheitert fuer {audio} (Exit {lauf.returncode}): "
            f"{lauf.stderr.strip()[-500:]}"
        )
    # ffmpeg meldet je Stille erst `silence_start`, dann `silence_end` (Zeilenfolge in stderr).
    anfaenge = [float(m) for m in _STILLE_START.findall(lauf.stderr)]
    enden = [float(m) for m in _STILLE_ENDE.findall(lauf.stderr)]
    return list(zip(anfaenge, enden, strict=False))


def lies_kapitelmarken(audio: Path, *, zeit_s: float = 120.0) -> tuple[float, ...]:
    """Die Kapitelmarken (Start in Sekunden) der fertigen Datei, wie ffprobe sie liest.

    Ein Format ohne Kapitel liefert `()`. Scheitert ffprobe, ist das ein Defekt der Umgebung
    und geht als Ausnahme nach oben.
    """
    befehl = ["ffprobe", "-v", "error", "-show_chapters", "-of", "json", str(audio)]
    try:
        lauf = subprocess.run(befehl, capture_output=True, text=True, timeout=zeit_s, check=False)
    except (OSError, subprocess.TimeoutExpired) as fehler:
        raise Mp4Fehler(f"ffprobe (Kapitelmarken) scheitert für {audio}: {fehler}") from fehler
    if lauf.returncode != 0:
        raise Mp4Fehler(
            f"ffprobe (Kapitelmarken) scheitert für {audio} (Exit {lauf.returncode}): "
            f"{lauf.stderr.strip()[-500:]}"
        )
    try:
        kapitel = json.loads(lauf.stdout).get("chapters", [])
        return tuple(float(k["start_time"]) for k in kapitel)
    except (ValueError, KeyError, TypeError) as fehler:
        raise Mp4Fehler(
            f"ffprobe (Kapitelmarken) liefert Unlesbares für {audio}: {fehler}"
        ) from fehler


def pruefe_kapitelmarken(
    audio: Path, marken_s: Sequence[float], *, pause_kapitel: float, zeit_s: float = 600.0
) -> tuple[str, ...]:
    """Befunde zu Kapitelmarken, die nicht in einer Pause liegen.

    Die erste Marke (Anfang des Hoerstuecks) wird nicht geprueft.

    Je Marke ab der zweiten muss `ffmpeg silencedetect` eine Stille von mindestens
    `STILLE_ANTEIL_KAPITEL` x `pause_kapitel` finden, in der die Marke liegt -- mit
    `TOLERANZ_MARKE_S` Spielraum auf beiden Seiten. Sonst springt der Player an dieser Marke
    mitten in ein Wort: der Befund nennt die Marke und die Stelle (mm:ss).

    Schutzgut: falsche Information. Die Bloecke des Masterns haben den Weg von der Pause zur
    Marke laenger gemacht; ein Fehler dort bliebe sonst unhoerbar bis zum Sprung.
    """
    if len(marken_s) < 2:
        return ()
    stillen = _stillen(audio, STILLE_ANTEIL_KAPITEL * pause_kapitel, zeit_s=zeit_s)
    befunde = []
    for nr, marke in enumerate(marken_s[1:], start=2):
        liegt_in_pause = any(
            anfang - TOLERANZ_MARKE_S <= marke <= ende + TOLERANZ_MARKE_S
            for anfang, ende in stillen
        )
        if not liegt_in_pause:
            minuten, sekunden = divmod(round(marke), 60)
            befunde.append(
                f"Kapitelmarke {nr} liegt nicht in einer Pause (bei {minuten:02d}:{sekunden:02d})"
            )
    return tuple(befunde)
