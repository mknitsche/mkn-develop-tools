"""Der Sprecher: ein Weg zur Stimme hinter einer Schnittstelle (Spec 6.2).

Der Lauf kennt keine Engine. Er buendelt die Stuecke zu **Bloecken** (`buendle`), nennt je
Block den Ton-Schluessel (`ton_schluessel`), laesst die offenen Bloecke sprechen
(`sprich_viele`) und prueft das Ergebnis. Wie gebuendelt, gesprochen und parallel vergeben
wird, ist Sache des Wegs: `SprecherLokal` kapselt den Chatterbox-Arbeiter (ein Block je
Stueck, seriell), `SprecherGemini` spricht ueber das Netz.

**Der Ton-Schluessel gehoert dem Weg.** Unter ihm liegen WAV und Messwerte eines Blocks im
Arbeitsverzeichnis; wer ihn aendert, laesst jedes begonnene Buch von vorn sprechen. Darum
ist der lokale Schluessel byte-gleich zu dem vor der Sprecher-Schnittstelle.

**Fehler eines Blocks sind Werte, keine Ausnahmen.** `sprich_viele` liefert zu jedem Block
Messwerte oder einen `SprecherFehler`; was daraus wird (Stille mit Befund, Abbruch nach zu
vielen Ausfaellen in Folge), entscheidet der Lauf, nicht der Sprecher.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from mkn_audio.arbeiter_client import Arbeiter, ArbeiterFehler
from mkn_audio.arbeitsverzeichnis import datei_hash, fingerabdruck
from mkn_audio.stimmen import Stimme, WegKonfig
from mkn_audio.typen import Mp4Fehler, Stueck

PROBE_SATZ = "Dies ist ein kurzer Probesatz."
"""Der feste Satz der Startprobe: kein Quellinhalt."""

ERSATZ_ZEICHEN_JE_S = 16.0
"""Sprechrate (Zeichen/s) ohne Median des Laufs: Median des PoC mit Gemini (16,3)."""

Messwerte = dict[str, Any]
"""Was das Sprechen eines Blocks misst. Pflicht: `dauer` (s), `sprechrate` (Zeichen/s),
`versuche`; ein Weg darf weitere Felder haengen (lokal `zu_kurz`, gemini Token)."""


def sprich_zweimal(
    arbeiter: Arbeiter, text: str, *, sprache: str, stimme: Stimme, ziel: Path
) -> Messwerte:
    """Spricht `text` nach `ziel`; bei `ArbeiterFehler` EIN neuer Versuch, dessen Fehler gilt.

    Nach Tod oder Zeitgrenze startet der Client den Arbeiter beim naechsten Auftrag frisch;
    nach einer Fehlerantwort lebt der Prozess weiter und bekommt denselben Auftrag noch
    einmal. Mehr Versuche wuerden ein Gift-Stueck nur teurer machen. Der Weg gilt fuer das
    Sprechen im Lauf wie fuer das Neusprechen der Pruefung: ein Ausfall soll an beiden
    Stellen gleich behandelt werden.
    """

    def versuch() -> Messwerte:
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


def erste_woerter(text: str, anzahl: int = 8) -> str:
    """Die ersten Woerter eines Textes: die Stelle, die eine Fehlermeldung nennt."""
    return " ".join(text.split()[:anzahl])


@dataclass(frozen=True)
class Block:
    """Die Ton-Einheit eines Laufs: ein oder mehrere ganze Stuecke eines Kapitels.

    `nr` ist die Nummer des Blocks im Lauf (lokal die des Stuecks) und der Schluessel der
    Messwerte im Lauf; `stueck_nrs` sind die Stuecke darin, `ansage` sagt, ob die Ansage-Stimme
    spricht.
    """

    nr: int
    stueck_nrs: tuple[int, ...]
    text: str
    kapitel: int
    ansage: bool


@dataclass(frozen=True)
class Auftrag:
    """Ein Block, die Stimme, die ihn spricht, und die WAV, in die er kommt."""

    block: Block
    stimme: Stimme
    ziel: Path


@dataclass(frozen=True)
class Verbrauch:
    """Was ein Lauf bei einem bezahlten Weg verbraucht hat (nur dieser Aufruf)."""

    anfragen: int
    tokens_text: int | None
    tokens_audio: int | None


@dataclass(frozen=True)
class Ausweis:
    """Was ein Weg ueber seinen Lauf zu sagen hat: Zeilen fuer den Bericht und Warnungen.

    `zeilen` stehen im Bericht-Abschnitt des Wegs (Modell, Token, Kosten, Sperren ...),
    `warnungen` gehoeren zu den Hinweisen des Laufs. Der lokale Weg hat nichts zu sagen.
    """

    zeilen: tuple[str, ...] = ()
    warnungen: tuple[str, ...] = ()


class SprecherFehler(Mp4Fehler):
    """Ein Block ist nicht gesprochen worden.

    `klasse` nennt die Art in einem Wort: `Sperre`, `Limit`, `Fehlerantwort`, `Ausreisser`,
    `Zugang` (Gemini) oder die Klasse des Arbeiters (`Tod`, `Zeitgrenze` ...). Der Bericht
    schreibt sie neben den Block, damit wer ihn liest den Grund sieht.
    """

    def __init__(self, meldung: str, klasse: str = "Fehler") -> None:
        super().__init__(meldung)
        self.klasse = klasse


class Sprecher(Protocol):
    """Ein Weg zur Stimme: buendeln, Schluessel nennen, sprechen, probieren."""

    weg: str
    modell: str
    arbeiter: Arbeiter | None

    def buendle(self, stuecke: Sequence[Stueck]) -> tuple[Block, ...]: ...

    def ton_schluessel(self, block: Block, stimme: Stimme) -> str: ...

    def sprich(self, block: Block, stimme: Stimme, ziel: Path) -> Messwerte: ...

    def sprich_viele(
        self,
        auftraege: Sequence[Auftrag],
        *,
        soll_weichen: Callable[[], bool],
        fortschritt: Callable[[str], None],
    ) -> Iterator[tuple[Block, Messwerte | SprecherFehler]]: ...

    def startprobe(self, stimmen: Sequence[Stimme]) -> None: ...

    def kann_hoeren(self) -> bool: ...

    def verbrauch(self) -> Verbrauch | None: ...

    def ausweis(self) -> Ausweis: ...

    def schaetzung(self, zeichen: int) -> str | None: ...


class SprecherLokal:
    """Der Chatterbox-Arbeiter hinter der Sprecher-Schnittstelle.

    Ein Block ist ein Stueck; gesprochen wird seriell, jeder Block bei einem Ausfall mit
    einem zweiten Versuch (`sprich_zweimal`). Ein Ausfall nach beiden Versuchen kommt als
    `SprecherFehler` mit der Klasse des Arbeiters zurueck.
    """

    weg = "local"

    def __init__(self, arbeiter: Arbeiter, konfig: WegKonfig) -> None:
        self.arbeiter: Arbeiter | None = arbeiter
        self.modell = konfig.modell
        self._vorlagen: dict[Path, str] = {}

    def buendle(self, stuecke: Sequence[Stueck]) -> tuple[Block, ...]:
        return tuple(Block(s.nr, (s.nr,), s.text, s.kapitel, s.ansage) for s in stuecke)

    def _vorlage_hash(self, stimme: Stimme) -> str:
        """Der Hash der Vorlage, je Pfad einmal; ein Fehler nennt die Stimme."""
        if stimme.vorlage is None:
            raise Mp4Fehler(f"Stimme '{stimme.name}' hat keine Vorlage (Weg {stimme.weg})")
        if stimme.vorlage not in self._vorlagen:
            try:
                self._vorlagen[stimme.vorlage] = datei_hash(stimme.vorlage)
            except Mp4Fehler as fehler:
                raise Mp4Fehler(f"Vorlage der Stimme '{stimme.name}': {fehler}") from fehler
        return self._vorlagen[stimme.vorlage]

    def ton_schluessel(self, block: Block, stimme: Stimme) -> str:
        return fingerabdruck(
            "ton",
            block.text,
            self.modell,
            stimme.sprache,
            self._vorlage_hash(stimme),
            stimme.exaggeration,
            stimme.cfg_weight,
            stimme.temperature,
            stimme.pausen_kuerzen,
        )[:16]

    def sprich(self, block: Block, stimme: Stimme, ziel: Path) -> Messwerte:
        assert self.arbeiter is not None
        try:
            return sprich_zweimal(
                self.arbeiter, block.text, sprache=stimme.sprache, stimme=stimme, ziel=ziel
            )
        except ArbeiterFehler as fehler:
            raise SprecherFehler(str(fehler), fehler.klasse) from fehler

    def sprich_viele(
        self,
        auftraege: Sequence[Auftrag],
        *,
        soll_weichen: Callable[[], bool],
        fortschritt: Callable[[str], None],
    ) -> Iterator[tuple[Block, Messwerte | SprecherFehler]]:
        """Seriell in Reihenfolge; vor jedem Block fragt `soll_weichen`, wahr beendet die Folge."""
        for auftrag in auftraege:
            if soll_weichen():
                return
            try:
                ergebnis: Messwerte | SprecherFehler = self.sprich(
                    auftrag.block, auftrag.stimme, auftrag.ziel
                )
            except SprecherFehler as fehler:
                ergebnis = fehler
            yield auftrag.block, ergebnis

    def startprobe(self, stimmen: Sequence[Stimme]) -> None:
        """Prueft alle Vorlagen, dann spricht der Arbeiter den Probesatz je Stimme.

        `Popen` gelingt auch in einer kaputten Umgebung; Chatterbox laedt erst beim ersten
        Sprechen. Ohne Probe erschiene ein Ladefehler als Fehlerantwort je Quelle. Alle
        Vorlagen werden VOR dem ersten Sprechen geprueft: eine fehlende liesse sonst jede
        Quelle mit einem Fehler des Pakets scheitern.
        """
        assert self.arbeiter is not None
        for stimme in stimmen:
            if stimme.vorlage is None or not Path(stimme.vorlage).is_file():
                raise Mp4Fehler(f"Startprobe: Vorlage der Stimme '{stimme.name}' fehlt")
        with tempfile.TemporaryDirectory(prefix="probe-") as tmp:
            for stimme in stimmen:
                try:
                    self.arbeiter.sprich(
                        PROBE_SATZ,
                        sprache=stimme.sprache,
                        vorlage=stimme.vorlage,
                        exaggeration=stimme.exaggeration,
                        cfg_weight=stimme.cfg_weight,
                        temperature=stimme.temperature,
                        ziel=Path(tmp) / "probe.wav",
                    )
                except ArbeiterFehler as fehler:
                    raise SprecherFehler(
                        f"Startprobe des Arbeiters gescheitert (Stimme '{stimme.name}'): {fehler}",
                        fehler.klasse,
                    ) from fehler

    def kann_hoeren(self) -> bool:
        return self.arbeiter is not None

    def verbrauch(self) -> Verbrauch | None:
        return None

    def ausweis(self) -> Ausweis:
        return Ausweis()

    def schaetzung(self, zeichen: int) -> str | None:
        return None
