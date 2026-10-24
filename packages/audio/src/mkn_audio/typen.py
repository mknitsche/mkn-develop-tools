"""Die Dinge, die zwischen den Stufen wandern.

**Warum eigene Typen.** Die Stufen (Lesen, Hoertext, Gliedern, Sprechen ...) kennen
einander nicht, sie reichen nur diese unveraenderlichen Werte weiter. Dadurch laesst
sich jede Stufe einzeln testen und ihr Ergebnis als Fingerabdruck-Eingabe der
naechsten verwenden: ein Wert, der sich nachtraeglich aendern kann, waere ein
Fingerabdruck, der luegt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal


class Mp4Fehler(RuntimeError):
    """Basis aller Fehler dieses Pakets.

    Ein Fehler bricht laut ab (Ausnahme, Exit != 0). Er wird nie in einen leisen
    Ersatzweg umgewandelt: ein Hoerstueck, das stillschweigend etwas anderes sagt
    als die Quelle, ist schlimmer als gar keins.
    """


ARTEN = ("vorspann", "wortlaut", "ueberleitung", "abspann")
"""Die Herkunft eines Absatzes in der Hoerfassung (`Kapitel.arten`)."""


@dataclass(frozen=True)
class Kapitel:
    """Ein Abschnitt der Quelle mit Titel und seinen Absaetzen in Lesereihenfolge.

    `arten` sagt je Absatz, woher er stammt (Regie): `wortlaut` steht so in
    der Quelle, `vorspann`, `ueberleitung` und `abspann` hat ein Sprachmodell NEU
    formuliert. Leer heisst "alles Wortlaut" -- so bleibt jede Stufe ohne Regie, wie
    sie war. Die Laenge wird geprueft: eine Art, die zu keinem Absatz gehoert (oder
    umgekehrt), wuerde beim Sprechen einem falschen Absatz die Ansage-Stimme geben.
    """

    titel: str
    absaetze: tuple[str, ...]
    arten: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.arten and len(self.arten) != len(self.absaetze):
            raise Mp4Fehler(
                f"Kapitel »{self.titel}«: arten ({len(self.arten)}) und absaetze "
                f"({len(self.absaetze)}) muessen gleich lang sein"
            )
        unbekannt = [art for art in self.arten if art not in ARTEN]
        if unbekannt:
            raise Mp4Fehler(
                f"Kapitel »{self.titel}«: unbekannte Art {unbekannt[0]!r} "
                f"(erlaubt: {', '.join(ARTEN)})"
            )


@dataclass(frozen=True)
class Dokument:
    """Eine gelesene Quelle, unabhaengig von ihrem Format.

    `warnungen` sammelt, was beim Lesen weggelassen oder unsicher war (Impressum,
    Seitenzahlen ...). Sie gehoeren in den Bericht: wer das Hoerstueck hoert, soll
    wissen koennen, was in ihm fehlt.
    """

    titel: str
    autor: str | None
    sprache: str
    kapitel: tuple[Kapitel, ...]
    warnungen: tuple[str, ...] = ()
    cover: bytes | None = None


@dataclass(frozen=True)
class Stueck:
    """Ein Satz (oder Satzteil) und die kleinste Einheit, die gesprochen wird.

    `kapitel` und `absatz` zaehlen ab 0 und bestimmen die Pause danach; `nr` zaehlt
    ueber das ganze Dokument und ist der Schluessel, unter dem die Aufnahme liegt.
    `art="titel"` ist die Kapitelueberschrift, die vor dem Text gesprochen wird.
    `ansage` ist wahr, wenn das Stueck aus einem Absatz stammt, den die Regie neu
    formuliert hat (Vorspann, Ueberleitung, Abspann): es wird mit der Ansage-Stimme
    gesprochen. Titel sind nie Ansagen -- sie stehen so in der Quelle.
    """

    kapitel: int
    absatz: int
    nr: int
    text: str
    art: Literal["text", "titel"]
    ansage: bool = False


Textmodell = Callable[[str, tuple[tuple[str, bytes], ...]], str]
"""Ein Sprachmodell als Funktion: Prompt und Bilder `(mime, bytes)` hinein, Text heraus.

Das Paket kennt weder Anbieter noch Modell; wer es aufruft, reicht die Funktion herein.
Ohne sie arbeiten die Stufen rein regelbasiert."""
