"""Jede Eingabe wird zu Seitenbildern — PDF mit oder ohne Textschicht, Scan, Foto.

**Warum alles ueber das Bild geht.** Eine Textschicht kann fehlen, veraltet oder von
einer schlechten Texterkennung sein; das Bild ist, was auf dem Papier steht. Wer vom
Bild liest, braucht fuer ein digitales PDF, einen Scan und ein Handyfoto denselben Weg.
"""

from __future__ import annotations

import os
from pathlib import Path

import pymupdf

DPI = 300
"""Aufloesung, in der eine PDF-Seite gerendert wird."""

KANTE_MIN = 2400
KANTE_MAX = 3600
"""Grenzen der laengsten Bildkante: kleine Vorlagen werden vergroessert, uebergrosse verkleinert."""


class SeitenFehler(RuntimeError):
    """Die Eingabe laesst sich nicht in Seitenbilder verwandeln."""


def _schreibe(pfad: Path, daten: bytes) -> None:
    """Schreibt atomar und nur fuer den Besitzer lesbar: Seitenbilder sind so vertraulich wie das Dokument.

    Ein abgebrochener Lauf hinterlaesst nie ein halbes Bild unter dem Zielnamen, und eine schon vorhandene Datei
    mit weiteren Rechten wird durch eine neue mit 0600 ersetzt.
    """
    neu = pfad.with_name(pfad.name + ".neu")
    fd = os.open(neu, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(daten)
    os.replace(neu, pfad)


def seitenbilder(eingabe: Path, ordner: Path) -> list[Path]:
    """Rendert jede Seite von ``eingabe`` (PDF oder Bilddatei) nach ``ordner/seite-NNN.png``.

    Rueckgabe: die Bildpfade in Seitenfolge. Bricht laut, wenn die Datei fehlt, sich nicht oeffnen laesst
    oder keine Seite hat — ein leeres Ergebnis saehe aus wie ein Dokument ohne Inhalt.
    """
    eingabe = Path(eingabe)
    if not eingabe.is_file():
        raise SeitenFehler(f"Eingabe fehlt: {eingabe.name}")
    try:
        dokument = pymupdf.open(eingabe)
    except Exception as exc:
        raise SeitenFehler(f"{eingabe.name} laesst sich nicht oeffnen: {exc}") from exc
    with dokument:
        if dokument.page_count == 0:
            raise SeitenFehler(f"{eingabe.name} hat keine Seite")
        ordner.mkdir(parents=True, exist_ok=True, mode=0o700)
        bilder: list[Path] = []
        for nr, seite in enumerate(dokument, start=1):
            lang = max(seite.rect.width, seite.rect.height)
            if lang <= 0:
                raise SeitenFehler(f"{eingabe.name}: Seite {nr} hat keine Flaeche")
            zoom = min(max(DPI / 72, KANTE_MIN / lang), KANTE_MAX / lang)
            bild = seite.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            ziel = ordner / f"seite-{nr:03d}.png"
            _schreibe(ziel, bild.tobytes("png"))
            bilder.append(ziel)
    return bilder


def verkleinert(bild: Path, max_kante: int | None, max_bytes: int | None) -> Path:
    """Das Seitenbild in einer Fassung, die Kanten- und Groessengrenze eines Anbieters einhaelt.

    Haelt das Original beide Grenzen ein, kommt es selbst zurueck. Sonst entsteht daneben eine verkleinerte
    PNG-Fassung (``<name>.k<kante>.png``); sie wird bei jedem Aufruf neu geschrieben.
    """
    pixel = pymupdf.Pixmap(str(bild))
    lang = max(pixel.width, pixel.height)
    kante = min(lang, max_kante) if max_kante else lang
    if kante == lang and (max_bytes is None or bild.stat().st_size <= max_bytes):
        return bild
    with pymupdf.open(bild) as dokument:
        seite = dokument[0]
        # Die Seitenflaeche einer Bilddatei haengt an ihrer dpi-Angabe, nicht an den Bildpunkten.
        flaeche = max(seite.rect.width, seite.rect.height)
        for _ in range(8):
            # Immer neu rendern: im selben Ordner kann unter diesem Namen das Bild eines anderen Dokuments liegen.
            ziel = bild.with_name(f"{bild.stem}.k{kante}.png")
            verkleinertes = seite.get_pixmap(matrix=pymupdf.Matrix(kante / flaeche, kante / flaeche), alpha=False)
            _schreibe(ziel, verkleinertes.tobytes("png"))
            groesse = ziel.stat().st_size
            if max_bytes is None or groesse <= max_bytes:
                return ziel
            kante = max(1, int(kante * (max_bytes / groesse) ** 0.5 * 0.95))
    raise SeitenFehler(f"{bild.name} faellt auch verkleinert nicht unter {max_bytes} Bytes")
