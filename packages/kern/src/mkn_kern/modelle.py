"""Modell-Auswahl: welcher Anbieter, welches Modell, welcher Schluessel.

**Der Anwender waehlt, nicht der Autor.** Dieses Modul enthaelt deshalb keine
Vorgabe, welches Modell "das richtige" ist — nur die Kenntnis, wie die
unterstuetzten Anbieter angesprochen werden. Wer nichts waehlt, bekommt eine
Frage und keine Rechnung.

Aufloesung, in dieser Reihenfolge: ausdrueckliches Argument, dann Umgebung
(``MKN_LLM_ANBIETER`` / ``MKN_LLM_MODELL``). Schluessel kommen ausschliesslich
aus der Umgebung — je Anbieter eine eigene Variable, damit nie der Schluessel
des einen beim anderen landet.
"""

from __future__ import annotations

import base64
import mimetypes
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class UnbekannterAnbieter(RuntimeError):
    """Der Anbieter ist hier nicht hinterlegt."""


class KeinModellGewaehlt(RuntimeError):
    """Es wurde kein Modell angegeben — und es gibt bewusst keine Vorgabe."""


class KeinSchluessel(RuntimeError):
    """Fuer den gewaehlten Anbieter liegt kein Schluessel in der Umgebung."""


@dataclass(frozen=True)
class _Anbieter:
    schluessel_variable: str
    basis_url: str
    bildform: str  # "anthropic" | "openai"


#: Was dieses Werkzeug ansprechen kann. Bewusst NUR Anbieter-Wissen, keine
#: Modellnamen: Modelle wechseln schneller als Schnittstellen, und eine Liste
#: im Code waere am Tag ihrer Veroeffentlichung veraltet.
ANBIETER: dict[str, _Anbieter] = {
    "anthropic": _Anbieter(
        schluessel_variable="ANTHROPIC_API_KEY",
        basis_url="https://api.anthropic.com/v1/messages",
        bildform="anthropic",
    ),
    "moonshot": _Anbieter(
        schluessel_variable="MOONSHOT_API_KEY",
        basis_url="https://api.moonshot.ai/v1/chat/completions",
        bildform="openai",
    ),
}


@dataclass(frozen=True)
class Wahl:
    """Eine getroffene Wahl: Anbieter, Modell und der Weg zum Schluessel."""

    anbieter: str
    modell: str

    @property
    def _profil(self) -> _Anbieter:
        return ANBIETER[self.anbieter]

    def schluessel(self) -> str:
        """Liest den Schluessel des GEWAEHLTEN Anbieters aus der Umgebung."""
        name = self._profil.schluessel_variable
        wert = os.environ.get(name)
        if not wert:
            raise KeinSchluessel(
                f"Kein Schluessel fuer Anbieter {self.anbieter!r}: die "
                f"Umgebungsvariable {name} ist nicht gesetzt."
            )
        return wert

    def baue_anfrage(
        self, text: str, *, bilder: Sequence[Path] = (), max_tokens: int = 2048
    ) -> dict[str, Any]:
        """Baut den Anfrage-Koerper fuer den gewaehlten Anbieter.

        Bilder werden eingebettet, nicht verlinkt — ein Pfad waere fuer den
        Anbieter bedeutungslos, und ein stillschweigend weggelassenes Bild
        ergibt eine fluessige, vollstaendig erfundene Antwort.
        """
        teile: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for pfad in bilder:
            teile.append(self._bildteil(pfad))
        return {
            "model": self.modell,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": teile}],
        }

    def _bildteil(self, pfad: Path) -> dict[str, Any]:
        typ = mimetypes.guess_type(pfad.name)[0] or "image/jpeg"
        roh = base64.standard_b64encode(pfad.read_bytes()).decode()
        if self._profil.bildform == "anthropic":
            return {
                "type": "image",
                "source": {"type": "base64", "media_type": typ, "data": roh},
            }
        return {"type": "image_url", "image_url": {"url": f"data:{typ};base64,{roh}"}}


def waehle(anbieter: str | None = None, modell: str | None = None) -> Wahl:
    """Loest die Wahl auf: Argument vor Umgebung, kein eingebauter Vorgabewert."""
    anbieter = anbieter or os.environ.get("MKN_LLM_ANBIETER")
    modell = modell or os.environ.get("MKN_LLM_MODELL")

    if not anbieter:
        raise UnbekannterAnbieter(
            "Kein Anbieter gewaehlt. Setze MKN_LLM_ANBIETER oder uebergib "
            f"anbieter=. Verfuegbar: {sorted(ANBIETER)}."
        )
    if anbieter not in ANBIETER:
        raise UnbekannterAnbieter(
            f"Anbieter {anbieter!r} ist hier nicht hinterlegt. Verfuegbar: {sorted(ANBIETER)}."
        )
    if not modell:
        raise KeinModellGewaehlt(
            f"Kein Modell gewaehlt fuer Anbieter {anbieter!r}. Setze "
            "MKN_LLM_MODELL oder uebergib modell=. Es gibt bewusst keine "
            "Vorgabe — die Wahl gehoert dem Anwender."
        )
    return Wahl(anbieter=anbieter, modell=modell)
