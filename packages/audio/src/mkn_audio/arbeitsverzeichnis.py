"""Arbeitsverzeichnis: wo ein Lauf seine Zwischenergebnisse haelt, damit er fortsetzen kann.

**Warum es das gibt.** Ein Buch zu sprechen dauert Stunden bis Tage. Ein Neustart, ein
Stromausfall oder ein Platzmachen fuer eine kuerzere Quelle darf nicht bedeuten, dass
alles von vorn beginnt. Jede Stufe legt deshalb ihr Ergebnis hier ab; ein spaeterer Lauf
nimmt es, wenn es noch zu seinen Eingaben passt, und rechnet sonst neu.

**Ein Ordner je Quelle.** Der Name ist der Anfang des SHA-256 der Quell-BYTES, nicht des
Dateinamens: dieselbe Datei unter anderem Namen findet ihren Ordner und ihre Aufnahmen
wieder, eine geaenderte Datei unter gleichem Namen nicht. Die Stufen ab dem Lesen rechnen
bei neuem Namen dennoch neu, weil ein Leser den Namen als Titel nehmen kann -- das kostet
bei einer Umbenennung einen Lauf des Sprachmodells, gesprochen wird nur, was sich aendert.

**Fingerabdruck statt Zeitstempel.** Jede JSON-Stufe traegt `{"fingerabdruck", "daten"}`;
der Fingerabdruck ist ein Hash aus dem der Vorstufe und den Parametern, die genau diese
Stufe nutzt. So rechnet ein anderer Stimm-Regler nur ab dem Sprechen neu, nicht den
Lesetext, und ein geaenderter Lesetext rechnet alles dahinter neu -- ohne dass irgendwo
eine Liste gepflegt werden muss, was wovon abhaengt.

**Aufnahmen liegen unter dem Hash ihres Inhalts** (`ton/<hash>.wav`, Text plus alles, was
den Klang bestimmt): so ist eine Aufnahme unabhaengig davon fertig oder nicht, in welcher
Stufe oder Reihenfolge sie entstand. Fertig ist sie erst, wenn WAV UND `.json` mit den
Messwerten da sind.

**Atomar und gesichert.** Geschrieben wird nach `<ziel>.tmp`, auf die Platte gesichert
(`fsync`) und dann umbenannt: nach einem Stromausfall liegt unter dem Zielnamen entweder
die alte oder die vollstaendige neue Datei, nie eine halbe. Eine `.tmp`-Datei zaehlt nie.

**Kaputtes bricht laut.** Eine Zwischendatei, die nicht lesbar ist, kann nach atomarem
Schreiben nur von aussen beschaedigt worden sein; sie still neu zu rechnen verdeckt, dass
der Datentraeger Probleme hat. Die Meldung nennt die Datei.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from mkn_audio.typen import Dokument, Kapitel, Mp4Fehler, Stueck

_BLOCK = 1 << 20


def fingerabdruck(*teile: object) -> str:
    """SHA-256 (32 Hex-Zeichen) ueber die Teile; Reihenfolge und Wert zaehlen, Typ nicht.

    JSON mit sortierten Schluesseln, damit gleiche Werte immer gleiche Bytes ergeben.
    """
    roh = json.dumps(teile, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(roh).hexdigest()[:32]


def datei_hash(pfad: Path) -> str:
    """SHA-256 der Dateibytes, in Bloecken gelesen (Quellen koennen hunderte MB haben)."""
    summe = hashlib.sha256()
    try:
        with pfad.open("rb") as datei:
            while block := datei.read(_BLOCK):
                summe.update(block)
    except OSError as fehler:
        raise Mp4Fehler(f"Datei nicht lesbar: {pfad.name} ({fehler})") from fehler
    return summe.hexdigest()


def schreibe_atomar(ziel: Path, daten: bytes) -> None:
    """Schreibt `daten` nach `ziel`: temporaer, gesichert, dann umbenannt."""
    ziel.parent.mkdir(parents=True, exist_ok=True)
    tmp = ziel.with_name(ziel.name + ".tmp")
    try:
        with tmp.open("wb") as datei:
            datei.write(daten)
            datei.flush()
            os.fsync(datei.fileno())
        os.replace(tmp, ziel)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _lies_json(pfad: Path) -> Any:
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError) as fehler:
        raise Mp4Fehler(
            f"Zwischenergebnis unlesbar: {pfad} ({fehler}) -- das Arbeitsverzeichnis "
            "dieser Quelle loeschen, dann rechnet der naechste Lauf neu"
        ) from fehler


# -- Dokument und Stueck als JSON -----------------------------------------------------


def dokument_zu_json(dok: Dokument) -> dict[str, Any]:
    return {
        "titel": dok.titel,
        "autor": dok.autor,
        "sprache": dok.sprache,
        "kapitel": [
            {"titel": k.titel, "absaetze": list(k.absaetze), "arten": list(k.arten)}
            for k in dok.kapitel
        ],
        "warnungen": list(dok.warnungen),
        "cover": base64.b64encode(dok.cover).decode("ascii") if dok.cover is not None else None,
    }


def dokument_aus_json(daten: dict[str, Any]) -> Dokument:
    return Dokument(
        titel=daten["titel"],
        autor=daten["autor"],
        sprache=daten["sprache"],
        # `arten` fehlt in Lesetexten aus der Zeit vor der Regie: das heisst "alles Wortlaut",
        # genau wie ein Kapitel ohne Arten -- kein Verlust, also kein Fehler.
        kapitel=tuple(
            Kapitel(k["titel"], tuple(k["absaetze"]), tuple(k.get("arten", ())))
            for k in daten["kapitel"]
        ),
        warnungen=tuple(daten["warnungen"]),
        cover=base64.b64decode(daten["cover"]) if daten["cover"] is not None else None,
    )


def stuecke_zu_json(stuecke: tuple[Stueck, ...]) -> list[dict[str, Any]]:
    return [
        {
            "kapitel": s.kapitel,
            "absatz": s.absatz,
            "nr": s.nr,
            "text": s.text,
            "art": s.art,
            "ansage": s.ansage,
        }
        for s in stuecke
    ]


def stuecke_aus_json(daten: list[dict[str, Any]]) -> tuple[Stueck, ...]:
    return tuple(
        Stueck(d["kapitel"], d["absatz"], d["nr"], d["text"], d["art"], d["ansage"]) for d in daten
    )


# -- Das Verzeichnis ------------------------------------------------------------------


class Arbeitsverzeichnis:
    """Der Ordner einer Quelle: Stufenergebnisse, Aufnahmen, Kapitel-WAVs."""

    def __init__(self, wurzel: Path, quelle_hash: str) -> None:
        self.wurzel = wurzel
        self.quelle_hash = quelle_hash
        # `ton/` gibt es von Anfang an: der Arbeiter schreibt seine WAV selbst dorthin und
        # legt keine Ordner an.
        (wurzel / "ton").mkdir(parents=True, exist_ok=True)
        (wurzel / "kapitel").mkdir(exist_ok=True)

    @classmethod
    def fuer_quelle(cls, arbeitsort: Path, quelle: Path) -> Arbeitsverzeichnis:
        gesamt = datei_hash(quelle)
        return cls(arbeitsort / gesamt[:16], gesamt)

    # -- Stufen ---------------------------------------------------------------------

    def _stufe(self, name: str) -> Path:
        return self.wurzel / f"{name}.json"

    def lies_stufe(self, name: str, fp: str) -> Any | None:
        """Die Daten der Stufe, wenn ihr Fingerabdruck passt; sonst `None` (neu rechnen)."""
        pfad = self._stufe(name)
        if not pfad.is_file():
            return None
        inhalt = _lies_json(pfad)
        if not isinstance(inhalt, dict) or "fingerabdruck" not in inhalt or "daten" not in inhalt:
            raise Mp4Fehler(f"Zwischenergebnis hat nicht die erwartete Form: {pfad}")
        return inhalt["daten"] if inhalt["fingerabdruck"] == fp else None

    def schreibe_stufe(self, name: str, fp: str, daten: Any) -> None:
        text = json.dumps({"fingerabdruck": fp, "daten": daten}, ensure_ascii=False)
        schreibe_atomar(self._stufe(name), text.encode("utf-8"))

    # -- Aufnahmen ------------------------------------------------------------------

    def ton_wav(self, schluessel: str) -> Path:
        return self.wurzel / "ton" / f"{schluessel}.wav"

    def lies_ton(self, schluessel: str) -> dict[str, Any] | None:
        """Die Messwerte der Aufnahme, wenn sie fertig ist (WAV und JSON da), sonst `None`."""
        info = self.wurzel / "ton" / f"{schluessel}.json"
        if not (info.is_file() and self.ton_wav(schluessel).is_file()):
            return None
        antwort = _lies_json(info)
        if not isinstance(antwort, dict):
            raise Mp4Fehler(f"Zwischenergebnis hat nicht die erwartete Form: {info}")
        return antwort

    def schreibe_ton(self, schluessel: str, antwort: dict[str, Any]) -> None:
        """Legt die Messwerte ab. Erst nach der WAV: die JSON macht die Aufnahme fertig."""
        info = self.wurzel / "ton" / f"{schluessel}.json"
        schreibe_atomar(info, json.dumps(antwort, ensure_ascii=False).encode("utf-8"))

    # -- Kapitel --------------------------------------------------------------------

    def kapitel_wav(self, nr: int) -> Path:
        return self.wurzel / "kapitel" / f"{nr:02d}.wav"

    def kapitel_roh(self, nr: int) -> Path:
        return self.wurzel / "kapitel" / f"{nr:02d}-roh.wav"

    def kapitel_stufe(self, nr: int) -> str:
        return f"kapitel/{nr:02d}"
