"""Ein Leser beantwortet den Leseauftrag zu einem Seitenbild.

**Der Leser ist eine Schnittstelle, kein Modell.** Welche zwei Modelle lesen, waehlt
der Anwender — dieses Paket nennt keines. Wer eine eigene Anbindung hat (Abrechnung,
Protokoll, Vertraulichkeitsregeln), gibt zwei eigene Leser hinein; fuer alle anderen
gibt es ``KernLeser`` ueber ``mkn-kern``.

Zwei Leser derselben Herkunft irren gemeinsam. Die Uebereinstimmung traegt nur, wenn
sie von verschiedenen Anbietern kommen.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol

from mkn_kern import anfrage, modelle

from mkn_dokument import seiten


class LeserFehler(RuntimeError):
    """Der Leser hat keine verwertbare Antwort geliefert."""


class Leser(Protocol):
    """Was der Lauf von einem Leser braucht."""

    kennung: str
    """Anbieter, Modell und Einstellungen: was ausser Auftrag und Bild die Antwort bestimmt (Teil der Mitschrift)."""

    def lies(self, auftrag: str, bild: Path) -> dict[str, Any]:
        """Die Antwort als JSON-Objekt; bricht laut, wenn keine kommt."""
        ...


def json_objekt(text: str) -> dict[str, Any]:
    """Das JSON-Objekt einer Modellantwort, auch wenn es in einem Code-Block steht."""
    t = text.strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", t, flags=re.DOTALL)
    if m:
        t = m.group(1)
    try:
        objekt = json.loads(t)
    except json.JSONDecodeError as exc:
        raise LeserFehler(f"Antwort ist kein JSON: {exc}") from exc
    if not isinstance(objekt, dict):
        raise LeserFehler("Antwort ist kein JSON-Objekt")
    return objekt


_GRENZEN: dict[str, tuple[int | None, int | None]] = {
    # Anthropic: hoechstens 5 MB je Bild in Base64 (rund 3,7 MB roh); groessere Kanten verkleinert der Anbieter selbst.
    "anthropic": (2576, 3_700_000),
    "gemini": (None, 15_000_000),
}


class KernLeser:
    """Leser ueber ``mkn-kern``: Anbieter und Modell aus der Wahl des Anwenders, Schluessel aus seiner Umgebung."""

    def __init__(
        self,
        wahl: modelle.Wahl,
        *,
        max_tokens: int = 32000,
        zeitgrenze: float = 600.0,
        transport: anfrage.Transport | None = None,
    ) -> None:
        self.wahl = wahl
        self.max_tokens = max_tokens
        self.zeitgrenze = zeitgrenze
        self.transport = transport
        self.kennung = f"{wahl.anbieter}:{wahl.modell}:{max_tokens}"

    def _kopf(self) -> dict[str, str]:
        if modelle.ANBIETER[self.wahl.anbieter].schluessel_variable is None:
            return {}
        schluessel = self.wahl.schluessel()
        if not schluessel:
            raise modelle.KeinSchluessel(f"Kein Schluessel fuer Anbieter {self.wahl.anbieter!r}")
        if self.wahl.anbieter == "anthropic":
            return {"x-api-key": schluessel, "anthropic-version": "2023-06-01"}
        if self.wahl.anbieter == "gemini":
            return {"x-goog-api-key": schluessel}
        return {"authorization": f"Bearer {schluessel}"}

    def lies(self, auftrag: str, bild: Path) -> dict[str, Any]:
        kante, groesse = _GRENZEN.get(self.wahl.anbieter, (None, None))
        koerper = self.wahl.baue_anfrage(
            auftrag, bilder=[seiten.verkleinert(bild, kante, groesse)], max_tokens=self.max_tokens
        )
        if self.wahl.anbieter == "gemini":
            koerper["generationConfig"] |= {
                "responseMimeType": "application/json",
                "temperature": 0,
            }
        antwort = anfrage.sende(
            self.wahl.url(),
            koerper,
            self._kopf(),
            zeitgrenze=self.zeitgrenze,
            transport=self.transport,
        )
        return json_objekt(_antworttext(antwort))


def _antworttext(antwort: dict[str, Any]) -> str:
    """Der Text der Antwort in der Form des jeweiligen Anbieters; abgeschnittene Antworten brechen laut."""
    if antwort.get("stop_reason") == "max_tokens":
        raise LeserFehler("Antwort am Ausgabe-Deckel abgeschnitten")
    inhalt = antwort.get("content")  # Anthropic
    if isinstance(inhalt, list):
        return "".join(t.get("text", "") for t in inhalt if isinstance(t, dict) and t.get("type") == "text")
    kandidaten = antwort.get("candidates")  # Gemini
    if isinstance(kandidaten, list) and kandidaten:
        if kandidaten[0].get("finishReason") == "MAX_TOKENS":
            raise LeserFehler("Antwort am Ausgabe-Deckel abgeschnitten")
        teile = (kandidaten[0].get("content") or {}).get("parts") or []
        return "".join(t.get("text", "") for t in teile if isinstance(t, dict) and not t.get("thought"))
    wahlen = antwort.get("choices")  # OpenAI-Form
    if isinstance(wahlen, list) and wahlen:
        if wahlen[0].get("finish_reason") == "length":
            raise LeserFehler("Antwort am Ausgabe-Deckel abgeschnitten")
        return str((wahlen[0].get("message") or {}).get("content") or "")
    nachricht = antwort.get("message")  # Ollama
    if isinstance(nachricht, dict) and "content" in nachricht:
        return str(nachricht["content"] or "")
    raise LeserFehler("Antwort enthaelt keinen Text (unbekannte Form)")
