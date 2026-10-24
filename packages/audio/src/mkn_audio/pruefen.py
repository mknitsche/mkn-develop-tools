"""Pruefen: ein Stueck, das nicht sagt, was es sagen soll, faellt auf -- billig, dann genau.

**Warum zweistufig.** Spracherkennung auf jedem Stueck waere das Teuerste im ganzen Lauf.
Die meisten Fehler der Synthese verraten sich aber schon an der Aufnahme selbst: sie ist
viel zu kurz (das Modell hat mittendrin aufgehoert), viel zu lang (es hat sich in einer
Wiederholung verfangen) oder enthaelt eine lange Stille. Nur dort, und bei einer
Stichprobe der unauffaelligen Stuecke als Gegenprobe fuer den Verdacht, den die billigen
Merkmale nicht sehen, wird mit Whisper nachgehoert.

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
Neusprechen denselben Weg wie das Sprechen im Lauf (`sprich_zweimal`: ein neuer Versuch),
und scheitert es dennoch, bleibt der alte Ton und das Stueck steht als Befund "nicht neu
gesprochen" im Bericht. Scheitert das Hoeren, ist das Stueck nicht beurteilt, und auch das
steht als Befund ("nicht gehoert") da: nie gilt ein Stueck deshalb still als in Ordnung.

**Was weiter laut abbricht.** Ein fehlender Messwert und ein gescheiterter ffmpeg-Lauf
sind kein Ausfall des Arbeiters, sondern ein Defekt der Umgebung oder des Laufs selbst;
sie gehen als Ausnahme nach oben.
"""

from __future__ import annotations

import math
import random
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mkn_audio.arbeiter_client import Arbeiter, ArbeiterFehler
from mkn_audio.hoertext import _ist_deutsch, deterministisch
from mkn_audio.stimmen import Stimme
from mkn_audio.typen import Mp4Fehler, Stueck

ZEICHEN_JE_SEKUNDE = 14.0
"""Erwartete Sprechgeschwindigkeit (Zeichen je Sekunde), Mass des Prototyps."""

DAUER_MIN = 0.55
DAUER_MAX = 2.5
"""Verdacht, wenn die Dauer unter 55 % oder ueber 250 % der erwarteten liegt."""

STILLE_S = 2.5
"""Stille ab dieser Laenge im Stueck ist Verdacht."""

FEHLERRATE_MAX = 0.30
"""Wortfehlerrate, ab der (strikt darueber) ein Stueck als falsch gesprochen gilt."""

TITEL_MIN_WOERTER = 4

_STILLE_START = re.compile(r"silence_start:\s*(-?[0-9.]+)")
_WORT = re.compile(r"\w+")
_FFMPEG_ZEIT_S = 120


@dataclass(frozen=True)
class Befund:
    """Ein Stueck, das nach dem Neusprechen noch auffaellig ist.

    `zeit_s` ist die Stelle IM Stueck (Sekunden ab dessen Anfang), wenn es eine gibt
    -- der Beginn einer Stille; die Stelle im ganzen Hoerstueck kennt erst, wer die
    Stuecke aneinandergelegt hat. Ohne erkennbare Stelle `None`.
    """

    stueck_nr: int
    grund: str
    zeit_s: float | None


@dataclass(frozen=True)
class Pruefung:
    """Ergebnis der Pruefung.

    `gehoert` zaehlt Stuecke, nicht Hoer-Aufrufe (ein neu gesprochenes Stueck wird
    zweimal gehoert und zaehlt einmal). `neuer_ton` enthaelt die Antwort des Arbeiters
    fuer jedes neu gesprochene Stueck: die Aufnahme wurde ersetzt, die Messwerte des
    Aufrufers (Dauer, Sprechrate) gelten fuer sie nicht mehr.
    """

    auffaellig: tuple[Befund, ...]
    gehoert: int
    neu_gesprochen: int
    neuer_ton: Mapping[int, dict[str, Any]] = field(default_factory=dict)


def sprich_zweimal(
    arbeiter: Arbeiter, text: str, *, sprache: str, stimme: Stimme, ziel: Path
) -> dict[str, Any]:
    """Spricht `text` nach `ziel`; bei `ArbeiterFehler` EIN neuer Versuch, dessen Fehler gilt.

    Nach Tod oder Zeitgrenze startet der Client den Arbeiter beim naechsten Auftrag frisch;
    nach einer Fehlerantwort lebt der Prozess weiter und bekommt denselben Auftrag noch
    einmal. Mehr Versuche wuerden ein Gift-Stueck nur teurer machen. Der Weg gilt fuer das
    Sprechen im Lauf wie fuer das Neusprechen der Pruefung: ein Ausfall soll an beiden
    Stellen gleich behandelt werden.
    """

    def versuch() -> dict[str, Any]:
        return arbeiter.sprich(
            text,
            sprache=sprache,
            vorlage=stimme.vorlage,
            exaggeration=stimme.exaggeration,
            cfg_weight=stimme.cfg_weight,
            temperature=stimme.temperature,
            ziel=ziel,
            pausen_kuerzen=stimme.pausen_kuerzen,
        )

    try:
        return versuch()
    except ArbeiterFehler:
        return versuch()


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


def _ist_kurzer_titel(stueck: Stueck) -> bool:
    return stueck.art == "titel" and len(_woerter(stueck.text)) < TITEL_MIN_WOERTER


def _verdacht(
    stueck: Stueck, messung: Mapping[str, Any], wav: Path
) -> tuple[list[str], float | None]:
    """Gruende des akustischen Verdachts und Beginn einer Stille (falls es eine gibt)."""
    gruende: list[str] = []
    if messung["zu_kurz"]:
        gruende.append("Arbeiter meldet zu kurz")
    erwartet = len(stueck.text) / ZEICHEN_JE_SEKUNDE
    verhaeltnis = messung["dauer"] / erwartet
    if verhaeltnis < DAUER_MIN:
        gruende.append(f"Dauer nur {verhaeltnis * 100:.0f} % der erwarteten")
    elif verhaeltnis > DAUER_MAX:
        gruende.append(f"Dauer {verhaeltnis * 100:.0f} % der erwarteten")
    stille = _erste_stille(wav)
    if stille is not None:
        gruende.append(f"Stille von mehr als {STILLE_S:g} s".replace(".", ","))
    return gruende, stille


def _nicht_gehoert(
    nr: int,
    fehler: ArbeiterFehler,
    gruende: list[str],
    stille: float | None,
    *,
    nach_neusprechen: bool,
) -> Befund:
    """Der Befund fuer ein Stueck, das nicht beurteilt werden konnte, weil das Hoeren ausfiel."""
    wann = " nach erneutem Sprechen" if nach_neusprechen else ""
    return Befund(
        stueck_nr=nr,
        grund=f"nicht gehört ({fehler.klasse}){wann}; Anlass: {'; '.join(gruende)}",
        zeit_s=stille,
    )


def pruefe(
    stuecke: Sequence[Stueck],
    ton: Mapping[int, dict[str, Any]],
    *,
    arbeiter: Arbeiter,
    sprache: str,
    stimme: Stimme,
    wav_pfad: Callable[[Stueck], Path],
    stichprobe: float = 0.05,
    zufall: random.Random,
    ansage_stimme: Stimme | None = None,
) -> Pruefung:
    """Prueft alle Stuecke; hoert verdaechtige und eine Stichprobe der uebrigen.

    `ton` bildet `Stueck.nr` auf die Antwort des Arbeiters beim Sprechen ab (`dauer`,
    `zu_kurz` ...). `stimme` liefert die Regler fuer das Neusprechen; Ansage-Stuecke
    (`Stueck.ansage`) spricht `ansage_stimme` neu, wenn es sie gibt -- sonst wuerde ein
    misslungener Vorspann beim zweiten Wurf mit der falschen Stimme gesprochen. Die Stichprobe
    zieht `round(stichprobe * Anzahl der Stuecke)` Stuecke (mindestens eines, wenn
    `stichprobe > 0`) aus den unauffaelligen mit `zufall`, damit sie mit festem Seed
    reproduzierbar ist.
    """
    zu_pruefen = [s for s in stuecke if not _ist_kurzer_titel(s)]

    verdaechtig: dict[int, tuple[list[str], float | None]] = {}
    for s in zu_pruefen:
        if s.nr not in ton:
            raise Mp4Fehler(f"Stueck {s.nr}: keine Messwerte vom Sprechen vorhanden")
        gruende, stille = _verdacht(s, ton[s.nr], wav_pfad(s))
        if gruende:
            verdaechtig[s.nr] = (gruende, stille)

    unauffaellig = [s for s in zu_pruefen if s.nr not in verdaechtig]
    anzahl = round(stichprobe * len(stuecke))
    if stichprobe > 0:
        anzahl = max(1, anzahl)
    gezogen = {s.nr for s in zufall.sample(unauffaellig, min(anzahl, len(unauffaellig)))}

    befunde: list[Befund] = []
    gehoert = 0
    neu_gesprochen = 0
    neuer_ton: dict[int, dict[str, Any]] = {}

    for s in zu_pruefen:
        if s.nr not in verdaechtig and s.nr not in gezogen:
            continue
        gruende, stille = verdaechtig.get(s.nr, (["Stichprobe"], None))
        soll = _woerter(s.text)
        if not soll:  # nichts Sprechbares im Text: es gibt nichts zu vergleichen
            continue
        wav = wav_pfad(s)
        sprecher, s_sprache = (
            (ansage_stimme, ansage_stimme.sprache)
            if s.ansage and ansage_stimme is not None
            else (stimme, sprache)
        )

        try:
            abschrift = arbeiter.hoere(wav, s_sprache)
        except ArbeiterFehler as fehler:
            befunde.append(_nicht_gehoert(s.nr, fehler, gruende, stille, nach_neusprechen=False))
            continue
        gehoert += 1
        rate = _wortfehlerrate(soll, _abschrift_woerter(abschrift, s_sprache))
        if rate <= FEHLERRATE_MAX:
            continue

        # Einmal neu sprechen: die Synthese ist zufaellig, ein zweiter Wurf gelingt oft.
        # Scheitert auch das, bleibt der alte Ton (der Arbeiter schreibt atomar) und das Stueck
        # steht als Befund da.
        try:
            neuer_ton[s.nr] = sprich_zweimal(
                arbeiter, s.text, sprache=s_sprache, stimme=sprecher, ziel=wav
            )
        except ArbeiterFehler as fehler:
            prozent = math.floor(rate * 100 + 0.5)
            befunde.append(
                Befund(
                    stueck_nr=s.nr,
                    grund=(
                        f"nicht neu gesprochen ({fehler.klasse}); Wortfehlerrate {prozent} % "
                        f"(Anlass: {'; '.join(gruende)})"
                    ),
                    zeit_s=stille,
                )
            )
            continue
        neu_gesprochen += 1
        try:
            abschrift = arbeiter.hoere(wav, s_sprache)
        except ArbeiterFehler as fehler:
            befunde.append(_nicht_gehoert(s.nr, fehler, gruende, stille, nach_neusprechen=True))
            continue
        rate = _wortfehlerrate(soll, _abschrift_woerter(abschrift, s_sprache))
        if rate <= FEHLERRATE_MAX:
            continue

        # Die Stelle der Stille gilt fuer die neue Aufnahme neu bestimmt, nicht die alte.
        stille = _erste_stille(wav) if stille is not None else None
        befunde.append(
            Befund(
                stueck_nr=s.nr,
                grund=(
                    f"Wortfehlerrate {math.floor(rate * 100 + 0.5)} % nach erneutem Sprechen "
                    f"(Anlass: {'; '.join(gruende)})"
                ),
                zeit_s=stille,
            )
        )

    return Pruefung(
        auffaellig=tuple(befunde),
        gehoert=gehoert,
        neu_gesprochen=neu_gesprochen,
        neuer_ton=neuer_ton,
    )
