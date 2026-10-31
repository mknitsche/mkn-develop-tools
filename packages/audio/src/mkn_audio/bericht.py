"""Bericht: ein kurzes Markdown neben dem Hoerstueck, das sagt, was darin NICHT stimmt.

**Warum es ihn gibt.** Der Lauf fragt nie zurueck (Spec 6): was nicht gelesen, weggelassen
oder nicht sauber gesprochen werden konnte, steht hier, damit der Hoerer es wissen kann.
Deshalb gehen die Warnungen des Dokuments nie verloren, auch wenn der Aufrufer sie nicht
selbst hereinreicht, und ein leerer Abschnitt sagt ausdruecklich "keine" -- ein fehlender
Abschnitt waere von einem nicht geprueften nicht zu unterscheiden.

Der Bericht nennt nur Dateinamen, keine Pfade: er wandert mit der Datei auf ein anderes
Geraet, und ein Pfad des Rechners, der ihn schrieb, sagt dort nichts.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path

from mkn_audio.mastern import atomar
from mkn_audio.sprecher import Verbrauch
from mkn_audio.stimmen import Stimme
from mkn_audio.typen import Dokument
from mkn_audio.vertraulich import Hinweis

_MESSWERTE = {
    "f0_median": ("Tonlage", "Hz", 1),
    "streuung_ht": ("Melodie-Streuung", "Halbtöne", 1),
    "woerter_je_minute": ("Sprechtempo", "Wörter je Minute", 0),
}
"""Bekannte Messwerte: Anzeigename, Einheit, Nachkommastellen. Die Schluessel sind die
Namen der `miss`-Antwort des Arbeiters; ein unbekannter Schluessel wird trotzdem mit
seinem Namen aufgefuehrt (nie still weggelassen)."""

_STRICH = "—"


def _zahl(wert: float, stellen: int) -> str:
    return f"{wert:.{stellen}f}".replace(".", ",")


def _uhr(sekunden: float) -> str:
    """`h:mm:ss`."""
    s = round(sekunden)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _zeit(sekunden: float | None) -> str:
    """`mm:ss`, ab einer Stunde `h:mm:ss`; ohne Zeitstempel ein Strich."""
    if sekunden is None:
        return _STRICH
    s = round(sekunden)
    return _uhr(s) if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def _stimme(stimme: Stimme, hauptstimme: Stimme | None = None) -> str:
    """`name_v01`; ist es die Hauptstimme selbst, steht das dabei."""
    name = f"{stimme.name}_v{stimme.version:02d}"
    gleich = hauptstimme is not None and stimme.name == hauptstimme.name
    return f"{name} (gleiche Stimme)" if gleich else name


def _verbrauch(v: Verbrauch) -> str:
    """`N Anfragen`, dazu Token, wo der Weg sie meldet."""
    teile = [f"{v.anfragen} Anfragen"]
    if v.tokens_text is not None:
        teile.append(f"{v.tokens_text} Text-Token")
    if v.tokens_audio is not None:
        teile.append(f"{v.tokens_audio} Audio-Token")
    return ", ".join(teile)


def _zeile(text: str) -> str:
    return " ".join(text.split())


def schreibe_bericht(
    ziel: Path,
    *,
    quelle: Path,
    stimme: Stimme,
    tabellen_stand: str,
    dok: Dokument,
    dateien: Sequence[Path],
    dauer_s: float,
    warnungen: Sequence[str],
    befunde: Sequence[tuple[int, str, float | None]],
    messwerte: Mapping[str, float] | None,
    ansage_stimme: Stimme | None = None,
    weg: str | None = None,
    modell: str | None = None,
    bloecke: int | None = None,
    verbrauch: Verbrauch | None = None,
    weg_zeilen: Sequence[str] = (),
    datenschutz: Sequence[Hinweis] = (),
) -> Path:
    """Schreibt den Bericht (Markdown, deutsch) atomar nach `ziel`.

    `warnungen` sind die des Laufs; die des Dokuments (`dok.warnungen`) kommen davor
    dazu, doppelte nur einmal. `befunde` sind `(Block-Nr, Grund, Sekunden im Hoerstueck
    oder None)`; `messwerte` die Kennzahlen der Stimme (Schluessel wie in `_MESSWERTE`).
    `weg`, `modell`, `bloecke` und `verbrauch` (Anfragen und Token eines bezahlten Wegs)
    stehen im Kopf, wenn sie gegeben sind; `weg_zeilen` (Modell, Token, Kosten, Sperren ...)
    bilden den Abschnitt des Wegs. `datenschutz` sind die Hinweise vor dem Versand an Google
    (Klasse, Anzahl, maskiertes Beispiel); ohne Hinweise gibt es den Abschnitt nicht.
    `ansage_stimme` ist die Stimme der Regie-Ansagen, wenn das Hoerstueck welche enthaelt;
    sie steht unter der Hauptstimme, damit sichtbar bleibt, wer die neu formulierten
    Teile spricht.
    """
    nfc = unicodedata.normalize
    zeilen = [
        f"# Bericht — {_zeile(dok.titel)}",
        "",
        f"- **Quelle:** {nfc('NFC', quelle.name)}",
        f"- **Titel:** {_zeile(dok.titel)}",
        f"- **Autor:** {_zeile(dok.autor) if dok.autor else _STRICH}",
        f"- **Stimme:** {_stimme(stimme)} (Tabellen-Stand {tabellen_stand})",
        *(
            [f"- **Ansage-Stimme:** {_stimme(ansage_stimme, stimme)}"]
            if ansage_stimme is not None
            else []
        ),
        *(
            [f"- **Weg:** {weg}" + (f" · Modell {modell}" if modell else "")]
            if weg is not None
            else []
        ),
        *([f"- **Blöcke:** {bloecke}"] if bloecke is not None else []),
        *([f"- **Verbrauch:** {_verbrauch(verbrauch)}"] if verbrauch is not None else []),
        f"- **Spieldauer:** {_uhr(dauer_s)}",
        f"- **Kapitel:** {len(dok.kapitel)}",
        "- **Dateien:**",
        *[f"  - {nfc('NFC', d.name)}" for d in dateien],
        "",
        "## Hinweise",
        "",
    ]
    hinweise = list(dict.fromkeys(_zeile(w) for w in (*dok.warnungen, *warnungen)))
    zeilen += [f"- {h}" for h in hinweise] if hinweise else ["keine"]
    zeilen += ["", "## Auffällige Stellen", ""]
    zeilen += (
        [f"- Stück {nr} · {_zeile(grund)} · bei {_zeit(zeit)}" for nr, grund, zeit in befunde]
        if befunde
        else ["keine"]
    )
    if messwerte:
        zeilen += ["", "## Messwerte", ""]
        for schluessel, wert in messwerte.items():
            name, einheit, stellen = _MESSWERTE.get(schluessel, (schluessel, "", 2))
            zeilen.append(f"- {name}: {_zahl(wert, stellen)} {einheit}".rstrip())
    if weg_zeilen:
        zeilen += ["", f"## Weg {weg}" if weg else "## Weg", ""]
        zeilen += [f"- {_zeile(z)}" for z in weg_zeilen]
    if datenschutz:
        zeilen += ["", "## Datenschutz-Hinweise", ""]
        zeilen += [
            f"- {h.klasse}: {h.anzahl} (Beispiel: {_zeile(h.beispiel)})" for h in datenschutz
        ]
        zeilen += [
            f"- Datenschutz-Hinweise: {len(datenschutz)}, Freigabe durch Aufrufer; die Erkennung "
            "ist eine Untergrenze (Namen werden nicht erkannt)"
        ]
    with atomar(ziel) as tmp:
        tmp.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    return ziel
