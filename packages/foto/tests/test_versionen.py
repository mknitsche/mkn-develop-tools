"""Eine Version, zwei Orte — das darf nicht auseinanderlaufen.

Jedes Paket traegt seine Nummer in `pyproject.toml` UND in `__init__.py`. Das
ist kein Versehen: die eine liest der Paketbau, die andere liest der Code, der
sie in jede geschriebene Bilddatei schreibt (`xmp:CreatorTool`). Driften sie,
behauptet eine Datei einen Stand, den es nie gab -- und die Provenienz, derent-
wegen das Feld ueberhaupt existiert, ist wertlos.

`release-please` pflegt beide. Dieser Riegel prueft, dass es dabei bleibt.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import mkn_foto

import mkn_kern

WURZEL = Path(__file__).resolve().parents[3]


def _aus_pyproject(paket: str) -> str:
    daten = tomllib.loads((WURZEL / "packages" / paket / "pyproject.toml").read_text("utf-8"))
    return daten["project"]["version"]


def test_die_beiden_nummern_stimmen_ueberein() -> None:
    assert mkn_foto.__version__ == _aus_pyproject("foto")
    assert mkn_kern.__version__ == _aus_pyproject("kern")


def test_release_please_findet_beide_stellen() -> None:
    """Ohne die Markierung aktualisiert release-please nur `pyproject.toml` --
    und `__init__.py` bleibt auf dem alten Stand stehen. Das ist genau die
    Drift, gegen die der Test darueber schuetzt: er waere dann rot, und niemand
    wuesste warum."""
    for paket, modul in (("foto", "mkn_foto"), ("kern", "mkn_kern")):
        text = (WURZEL / "packages" / paket / "src" / modul / "__init__.py").read_text("utf-8")
        assert "x-release-please-version" in text, paket


def test_die_nummer_ist_eine_nummer() -> None:
    """Semver, nicht Prosa — sonst kann keine Automatik sie erhoehen."""
    for version in (mkn_foto.__version__, mkn_kern.__version__):
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), version
