"""Gemeinsame Bausteine der Tests.

Kein Test braucht Netz oder einen Schluessel; Dokumente und Lesungen entstehen hier
im Test, nie aus echten Belegen.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest


@pytest.fixture(autouse=True)
def _keine_fremden_schluessel(monkeypatch, tmp_path_factory):
    """Kein Test liest Schluessel oder Leser-Wahl des Menschen, der ihn laufen laesst."""
    for name in (
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "MOONSHOT_API_KEY",
        "MKN_LLM_ANBIETER",
        "MKN_LLM_MODELL",
        "MKN_DOKUMENT_LESER_A",
        "MKN_DOKUMENT_LESER_B",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(
        "MKN_LLM_SCHLUESSEL_DATEI",
        str(tmp_path_factory.mktemp("ohne-schluessel") / "gibtsnicht.json"),
    )


def schreibe_pdf(pfad: Path, seiten: int = 1, text: str = "Messgroesse 6,25 kg") -> Path:
    dokument = pymupdf.open()
    for nr in range(seiten):
        seite = dokument.new_page(width=595, height=842)
        seite.insert_text((72, 100), f"{text} (Seite {nr + 1})", fontsize=12)
    dokument.save(pfad)
    dokument.close()
    return pfad


def angabe(wert: str, lage=(100, 100, 110, 140), bezeichnung: str = "Messgroesse", **mehr) -> dict:
    return {
        "abschnitt": "",
        "bezeichnung": bezeichnung,
        "zusatz": "",
        "art": "messwert",
        "wert": wert,
        "vergleich": "",
        "einheit": "",
        "bereich": "",
        "kennzeichen": "",
        "lage": list(lage),
        "unsicher": False,
    } | mehr


class ScheinLeser:
    """Leser ohne Modell: gibt je Aufruf die naechste vorbereitete Antwort und zaehlt die Aufrufe."""

    def __init__(self, kennung: str, antworten: list) -> None:
        self.kennung = kennung
        self.antworten = list(antworten)
        self.aufrufe: list[Path] = []

    def lies(self, auftrag: str, bild: Path) -> dict:
        self.aufrufe.append(bild)
        antwort = self.antworten[len(self.aufrufe) - 1]
        if isinstance(antwort, Exception):
            raise antwort
        return antwort
