"""Gemeinsame Bausteine der Tests.

Kein Test braucht Netz, Schluessel, ein Sprachmodell oder die Stimm-Software;
Muster-Quellen und Tabellen entstehen hier im Test, nie aus echten Buechern oder
Stimmen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

KOPF = """\
standard = "{standard}"
"""

STIMME = """
[stimmen.{name}]
beschreibung = "Teststimme"
vorlage = "vorlagen/{name}.wav"
exaggeration = 0.45
cfg_weight = 0.45
temperature = 0.75
tempo = 0.9
stand = "probe"
"""


@pytest.fixture(autouse=True)
def _keine_fremde_konfiguration(tmp_path_factory, monkeypatch):
    """Kein Test liest die Konfiguration des Menschen, der ihn laufen laesst.

    Sonst bewiese die Suite auf dessen Rechner etwas anderes als auf einem
    fremden, und beides saehe gruen aus. Die Bedingung wird HERGESTELLT: die
    Variable zeigt auf einen Pfad, der garantiert nicht existiert.
    """
    monkeypatch.setenv(
        "MKN_MP4_KONFIG", str(tmp_path_factory.mktemp("ohne-konfig") / "gibtsnicht.toml")
    )


@pytest.fixture
def schreibe_tabelle(tmp_path):
    """Schreibt eine Stimmen-Tabelle; `standard=None` laesst die Zeile weg."""

    def _schreibe(*namen: str, standard: str | None = None, extra: str = "") -> Path:
        text = KOPF.format(standard=standard) if standard else ""
        text += "".join(STIMME.format(name=n) for n in namen) + extra
        pfad = tmp_path / "stimmen.toml"
        pfad.write_text(text, encoding="utf-8")
        return pfad

    return _schreibe
