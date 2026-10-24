"""Schein-Arbeiter fuer die Tests: dasselbe Protokoll wie `arbeiter.py`, ohne Stimm-Software.

**Warum ein eigenes Skript.** Der Client wird gegen einen echten Kindprozess mit echten
Pipes geprueft -- Zeitgrenze und Absturz lassen sich nur so beweisen. Dafuer braucht der
Schein-Arbeiter Fehlfaelle auf Zuruf; die stehen hier, nicht im Produktionscode:
`[fehler]` im Text -> Fehlerantwort, `[tod]` -> Absturz mit Meldung auf stderr,
`[haengt]` -> antwortet nie. Sonst schreibt `sprich` eine Sinus-WAV der Laenge
`len(text) / 14` Sekunden. Nur Standardbibliothek.

**Ausfaelle auf Zuruf der Umgebung.** Ein Lauf-Test kann den Text nicht mit Marken
spicken (er kommt aus einer EPUB). Darum zwei Schalter, die der Test per Umgebung setzt
und der Kindprozess erbt: `SCHEIN_FEHLER_BEI=<Textteil>` -> jede `sprich`-Anfrage mit
diesem Textteil bekommt eine Fehlerantwort (ein "Gift-Stueck"); `SCHEIN_TOD_BEI=<Textteil>`
mit `SCHEIN_TOD_MARKE=<Pfad>` -> der Prozess stirbt beim ersten solchen Stueck und legt
die Marke an; der frisch gestartete Nachfolger sieht die Marke und spricht normal. Ohne
die Variablen aendert sich nichts.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import wave
from array import array

RATE = 24_000


def schreibe_sinus(pfad: str, sekunden: float) -> None:
    n = int(sekunden * RATE)
    ton = array("h", (int(8000 * math.sin(2 * math.pi * 220 * i / RATE)) for i in range(n)))
    with wave.open(pfad, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(ton.tobytes())


def antworte(anfrage: dict) -> dict:
    befehl = anfrage["befehl"]
    text = anfrage.get("text", "")
    if "[fehler]" in text:
        return {"fehler": "Schein-Fehler"}
    if "[speicher]" in text:
        return {"fehler": "RuntimeError: MPS backend out of memory (Schein)"}
    if "[tod]" in text:
        print("Schein-Absturz: Speicher voll", file=sys.stderr, flush=True)
        sys.exit(3)
    if "[haengt]" in text:
        time.sleep(60)
    if befehl == "sprich":
        fehler_bei = os.environ.get("SCHEIN_FEHLER_BEI")
        if fehler_bei and fehler_bei in text:
            return {"fehler": "Schein-Fehler (Umgebung)"}
        tod_bei = os.environ.get("SCHEIN_TOD_BEI")
        marke = os.environ.get("SCHEIN_TOD_MARKE")
        if tod_bei and marke and tod_bei in text and not os.path.exists(marke):
            open(marke, "w").close()
            print("Schein-Absturz (Umgebung): Speicher voll", file=sys.stderr, flush=True)
            sys.exit(3)
        sekunden = len(text) / 14
        schreibe_sinus(anfrage["ziel"], sekunden)
        return {"dauer": sekunden, "sprechrate": 14.0, "versuche": 1, "zu_kurz": False}
    if befehl == "miss":
        return {"f0_median": 120.0, "streuung_ht": 3.0, "pause_anteil": 0.1, "dauer": 1.0}
    if befehl == "hoere":
        return {"text": "schein"}
    if befehl == "vorlage":
        schreibe_sinus(anfrage["ziel"], anfrage["dauer"])
        return {"start": 0.0, "streuung_ht": 3.0}
    return {"fehler": f"unbekannter Befehl {befehl}"}


def haupt() -> None:
    for zeile in sys.stdin:
        if zeile.strip():
            print(json.dumps(antworte(json.loads(zeile))), flush=True)


if __name__ == "__main__":
    haupt()
