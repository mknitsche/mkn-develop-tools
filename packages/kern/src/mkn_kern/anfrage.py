"""Schickt eine Anfrage an einen Anbieter — und bricht laut ab, wenn etwas fehlt.

**Der Transport ist ein Parameter, kein fester Bestandteil.** Kein Test dieses
Repos braucht Netz oder einen Schluessel: ein Test gegen einen echten Anbieter
kostet Geld, haengt an fremder Verfuegbarkeit und beweist am Ende die
Verfuegbarkeit statt den Code.

**Drei Faelle muessen laut sein**, weil sie sonst als stiller Teilerfolg enden —
und ein stiller Teilerfolg in einer Kette ueber 1.293 Aufnahmen faellt erst am
Ergebnis auf, wenn die Arbeit schon getan ist:

- ein Fehlerstatus (die Meldung des Anbieters gehoert in die Ausnahme, sonst
  sucht man im Blinden),
- eine Zeitueberschreitung (ohne Grenze haengt der Lauf an EINEM Bild fuer
  immer),
- eine Antwort, die kein JSON ist (ein HTML-Body mit Status 200 kommt vor:
  Zwischen-Server, Anmeldeseite).

Nur stdlib: `urllib` genuegt fuer eine POST-Anfrage mit JSON, und ein
veroeffentlichtes Werkzeug soll nicht an einer Abhaengigkeit haengen, die der
Anwender erst installieren muss.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

ZEITGRENZE_S = 120.0
"""Grosszuegig: ein Bildurteil mit grossem Modell braucht Sekunden, nicht
Millisekunden. Aber endlich — das ist der Punkt."""

Transport = Callable[[str, bytes, dict[str, str], float], tuple[int, bytes]]
"""(url, koerper, kopf, zeitgrenze) -> (status, rohe Antwort)."""


class AnfrageFehler(RuntimeError):
    """Die Anfrage ist nicht durchgekommen oder die Antwort war unbrauchbar.

    `status` ist der HTTP-Status, `code` der `error.code` des Antwortkoerpers
    (als Text). Beide sind `None`, wo es sie nicht gibt: Zeitueberschreitung,
    Verbindungsfehler, Antwort ohne JSON. Ein Aufrufer, der auf eine Sperre
    anders antwortet als auf ein Limit, liest sie hier statt im Meldungstext.
    """

    def __init__(self, meldung: str, *, status: int | None = None, code: str | None = None):
        super().__init__(meldung)
        self.status = status
        self.code = code


def sende(
    url: str,
    koerper: dict[str, Any],
    kopf: dict[str, str],
    *,
    zeitgrenze: float = ZEITGRENZE_S,
    transport: Transport | None = None,
) -> dict[str, Any]:
    """Schickt `koerper` als JSON und gibt die geparste Antwort zurueck."""
    transport = transport or _urllib_transport
    roh = json.dumps(koerper).encode()
    vollstaendig = {"content-type": "application/json", **kopf}

    try:
        status, antwort = transport(url, roh, vollstaendig, zeitgrenze)
    except TimeoutError as exc:
        raise AnfrageFehler(
            f"Zeitueberschreitung nach {zeitgrenze:.0f} s bei {url}: {exc}"
        ) from exc

    if status != 200:
        raise AnfrageFehler(
            f"Status {status} von {url}: {_meldung(antwort)}",
            status=status,
            code=_fehlercode(antwort),
        )

    try:
        return json.loads(antwort)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AnfrageFehler(
            f"Antwort von {url} ist kein JSON ({len(antwort)} Bytes): {antwort[:200]!r}"
        ) from exc


def _meldung(antwort: bytes) -> str:
    """Die Fehlermeldung des Anbieters, wenn sie sich finden laesst.

    Sie gehoert in die Ausnahme: "Status 429" allein sagt nicht, ob es das
    Minuten- oder das Tageslimit war.
    """
    try:
        d = json.loads(antwort)
    except Exception:
        return antwort[:200].decode("utf-8", "replace")
    if not isinstance(d, dict):
        return str(d)[:200]
    fehler = d.get("error")
    if isinstance(fehler, dict):
        return str(fehler.get("message") or fehler)
    return str(fehler or d)[:200]


def _fehlercode(antwort: bytes) -> str | None:
    """Der `error.code` des Koerpers als Text, sonst `None`."""
    try:
        d = json.loads(antwort)
    except Exception:
        return None
    fehler = d.get("error") if isinstance(d, dict) else None
    code = fehler.get("code") if isinstance(fehler, dict) else None
    return None if code is None else str(code)


def _urllib_transport(
    url: str, koerper: bytes, kopf: dict[str, str], zeitgrenze: float
) -> tuple[int, bytes]:
    anfrage = urllib.request.Request(url, data=koerper, headers=kopf, method="POST")
    try:
        with urllib.request.urlopen(anfrage, timeout=zeitgrenze) as antwort:
            return antwort.status, antwort.read()
    except urllib.error.HTTPError as exc:
        # Ein Fehlerstatus ist eine ANTWORT, keine Ausnahme -- der Koerper traegt
        # die Begruendung, und die wollen wir sehen.
        return exc.code, exc.read()
    except TimeoutError:
        raise
    except OSError as exc:
        raise AnfrageFehler(f"Verbindung zu {url} fehlgeschlagen: {exc}") from exc
