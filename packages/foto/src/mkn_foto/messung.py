"""Was ein Lauf hinterlaesst, damit man ihn hinterher auswerten kann.

KT-1 vor dem ersten bezahlten Lauf: *"hast du eine umfangreiche, stabile
observibility ... nicht dass wir durchlaufen und uns dann messwerte token pro
aktion, pro bild usw fehlen?"*

Die ehrliche Antwort war nein — es gab einen Zaehler. Nach 969 Aufrufen haette
man gewusst, DASS es 969 waren, nicht wo die Kosten herkamen.

**Die Zahlen liefert die API frei Haus.** Jede Antwort traegt ein `usage`-Feld.
Sie wegzuwerfen und hinterher zu schaetzen waere die teuerste Art, an Daten zu
kommen, die man schon hatte.

Drei Dinge, die dieses Modul deshalb unterscheidet:

- **`None` ist nicht `0`.** "Nicht gemessen" und "null Tokens" sind zwei
  verschiedene Aussagen; wer sie zusammenwirft, rechnet eine zu kleine Summe
  und merkt es nicht.
- **Ein Fehlschlag ist ein Messwert.** Er hat Zeit gekostet und vielleicht
  Tokens. Wer nur die gelungenen misst, sieht einen Lauf, der schneller und
  billiger war, als er wirklich war.
- **Der Mittelwert allein sagt nichts.** Bei 969 Aufrufen ist die Frage, WELCHE
  teuer waren — sonst sucht man beim naechsten Mal wieder im Ganzen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Messwert:
    """Was ein einzelner Aufruf gekostet hat."""

    name: str
    tokens_ein: int | None = None
    tokens_aus: int | None = None
    dauer_s: float = 0.0
    art: str = "einzel"
    """`einzel` oder `serie` — sie kosten verschieden viel, und der Unterschied
    ist der Grund fuer den Kontaktbogen."""

    fehler: str = ""

    @property
    def gemessen(self) -> bool:
        """Ob ueberhaupt Tokens gemeldet wurden."""
        return self.tokens_ein is not None

    def kosten_eur(self, *, preis_ein: float, preis_aus: float) -> float:
        """Preise je Million Tokens. Ungemessenes zaehlt als null — aber
        `gemessen` sagt, dass es das war."""
        ein = (self.tokens_ein or 0) / 1e6 * preis_ein
        aus = (self.tokens_aus or 0) / 1e6 * preis_aus
        return ein + aus

    @classmethod
    def aus_antwort(
        cls, name: str, antwort: dict[str, Any], *, dauer_s: float = 0.0, art: str = "einzel"
    ) -> Messwert:
        """Liest die Nutzungsangabe — ueber die Formen der Anbieter hinweg.

        Anthropic nennt sie `usage.input_tokens`, Gemini
        `usageMetadata.promptTokenCount`, OpenAI-kompatible
        `usage.prompt_tokens`. Wer nur eine Form kennt, misst bei zwei von drei
        Anbietern nichts — und meldet dabei null statt "nicht gemessen".
        """
        ein = aus = None
        nutzung = antwort.get("usage")
        if isinstance(nutzung, dict):
            ein = nutzung.get("input_tokens", nutzung.get("prompt_tokens"))
            aus = nutzung.get("output_tokens", nutzung.get("completion_tokens"))
        else:
            google = antwort.get("usageMetadata")
            if isinstance(google, dict):
                ein = google.get("promptTokenCount")
                aus = google.get("candidatesTokenCount")
        return cls(name=name, tokens_ein=ein, tokens_aus=aus, dauer_s=dauer_s, art=art)


@dataclass
class Protokoll:
    """Alle Messwerte eines Laufs, mit Summen und Ausreissern."""

    werte: list[Messwert] = field(default_factory=list)
    geschaetzt_eur: float | None = None
    """Die Vorhersage vor dem Lauf. Ohne sie im Protokoll muesste man den
    Vergleich von Hand nachrechnen — und dann tut es niemand."""

    def nimm(self, wert: Messwert) -> None:
        self.werte.append(wert)

    @property
    def aufrufe(self) -> int:
        return len(self.werte)

    @property
    def gescheitert(self) -> int:
        return sum(1 for w in self.werte if w.fehler)

    @property
    def ungemessen(self) -> int:
        return sum(1 for w in self.werte if not w.gemessen and not w.fehler)

    @property
    def tokens_ein(self) -> int:
        return sum(w.tokens_ein or 0 for w in self.werte)

    @property
    def tokens_aus(self) -> int:
        return sum(w.tokens_aus or 0 for w in self.werte)

    @property
    def dauer_s(self) -> float:
        return sum(w.dauer_s for w in self.werte)

    def kosten_eur(self, *, preis_ein: float, preis_aus: float) -> float:
        return sum(w.kosten_eur(preis_ein=preis_ein, preis_aus=preis_aus) for w in self.werte)

    def teuerste(self, anzahl: int = 10) -> list[Messwert]:
        """Die groessten Eingabe-Posten. Sie sind die Antwort auf 'warum so viel'."""
        return sorted(self.werte, key=lambda w: -(w.tokens_ein or 0))[:anzahl]

    def zusammenfassung(self, *, preis_ein: float, preis_aus: float) -> str:
        ist = self.kosten_eur(preis_ein=preis_ein, preis_aus=preis_aus)
        zeilen = [
            "## Modell-Lauf",
            "",
            f"- Aufrufe: **{self.aufrufe}**"
            + (f", davon {self.gescheitert} gescheitert" if self.gescheitert else "")
            + (f", {self.ungemessen} ohne Nutzungsangabe" if self.ungemessen else ""),
            f"- Tokens: {self.tokens_ein:,} ein · {self.tokens_aus:,} aus".replace(",", "."),
            f"- Dauer: {self.dauer_s / 60:.1f} min",
            f"- **Kosten: {ist:.2f} EUR**",
        ]
        if self.geschaetzt_eur is not None:
            ab = ist - self.geschaetzt_eur
            richtung = "darueber" if ab > 0 else "darunter"
            zeilen.append(
                f"- Geschaetzt waren **{self.geschaetzt_eur:.2f} EUR** — "
                f"{abs(ab):.2f} EUR {richtung} "
                f"({abs(ab) / self.geschaetzt_eur * 100:.0f} %)"
            )

        nach_art: dict[str, list[Messwert]] = {}
        for w in self.werte:
            nach_art.setdefault(w.art, []).append(w)
        if len(nach_art) > 1:
            zeilen += ["", "| Art | Aufrufe | Tokens ein | Kosten |", "|---|---:|---:|---:|"]
            for art, gruppe in sorted(nach_art.items()):
                t = sum(w.tokens_ein or 0 for w in gruppe)
                k = sum(w.kosten_eur(preis_ein=preis_ein, preis_aus=preis_aus) for w in gruppe)
                zeilen.append(f"| {art} | {len(gruppe)} | {t:,} | {k:.2f} EUR |".replace(",", "."))

        teuer = self.teuerste(5)
        if teuer and teuer[0].gemessen:
            zeilen += ["", "Die fuenf groessten Posten:", ""]
            zeilen += [f"- `{w.name}` — {w.tokens_ein:,} Tokens".replace(",", ".") for w in teuer]

        if self.gescheitert:
            zeilen += ["", "Gescheitert:", ""]
            zeilen += [f"- `{w.name}` — {w.fehler}" for w in self.werte if w.fehler]

        return "\n".join(zeilen)
