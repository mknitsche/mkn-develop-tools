"""Was ein Paket importiert, muss es auch fordern.

FIRSTHAND macb-S316: `mkn-foto` deklarierte `Pillow` als einzige Abhaengigkeit und
importierte `mkn_kern` auf Modulebene. Im Repo faellt das nie auf — `pythonpath` in
der pytest-Konfiguration blendet BEIDE Paketquellen ein, also war die Suite gruen.
In einer frischen Umgebung brach schon `--help` mit
`ModuleNotFoundError: No module named 'mkn_kern'`.

Genau die Klasse „Tests gruen, Werkzeug kaputt" (LP-18): der Testlauf bewies die
Entwicklungsumgebung, nicht das ausgelieferte Paket. Gefunden wurde es nicht von
einem Test, sondern durch echtes Installieren in eine leere Umgebung.

Dieser Riegel prueft die Geschwister-Abhaengigkeiten (`mkn_*`), nicht alle:
fremde Bibliotheken haben viele legitime Wege in ein Paket (optional, nur im Test,
bedingt importiert). Die Geschwister sind der Fall, der hier real schiefging und
der mit jedem weiteren Paket im Monorepo wahrscheinlicher wird.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PAKETE = sorted(p for p in (REPO / "packages").iterdir() if (p / "pyproject.toml").is_file())


def _geforderte_geschwister(paket: Path) -> set[str]:
    """Die `mkn-*`-Namen aus `[project].dependencies`, als Modulnamen."""
    daten = tomllib.loads((paket / "pyproject.toml").read_text(encoding="utf-8"))
    geforderte = set()
    for eintrag in daten.get("project", {}).get("dependencies", []):
        # "mkn-kern>=0.2" -> "mkn_kern"
        name = eintrag.split(">")[0].split("<")[0].split("=")[0].split("[")[0].strip()
        if name.startswith("mkn"):
            geforderte.add(name.replace("-", "_"))
    return geforderte


def _importierte_geschwister(paket: Path) -> dict[str, str]:
    """Alle auf MODULEBENE importierten `mkn_*`-Pakete -> erste Fundstelle.

    Nur Modulebene: ein Import in einer Funktion ist erst beim Aufruf faellig und
    darf bewusst optional sein. Ein Import am Dateikopf bricht dagegen schon beim
    Laden — das ist der Fall, der `--help` zerlegt hat.
    """
    gefunden: dict[str, str] = {}
    eigener = paket.name
    for datei in sorted((paket / "src").rglob("*.py")):
        baum = ast.parse(datei.read_text(encoding="utf-8"), filename=str(datei))
        for knoten in baum.body:  # body, nicht walk: nur die oberste Ebene
            namen: list[str] = []
            if isinstance(knoten, ast.Import):
                namen = [a.name for a in knoten.names]
            elif isinstance(knoten, ast.ImportFrom) and knoten.module and knoten.level == 0:
                namen = [knoten.module]
            for voll in namen:
                wurzel = voll.split(".")[0]
                if not wurzel.startswith("mkn_") or wurzel.endswith(eigener):
                    continue
                gefunden.setdefault(wurzel, f"{datei.relative_to(REPO)}:{knoten.lineno}")
    return gefunden


@pytest.mark.parametrize("paket", PAKETE, ids=lambda p: p.name)
def test_jedes_geschwisterpaket_das_importiert_wird_ist_auch_gefordert(paket: Path):
    importiert = _importierte_geschwister(paket)
    gefordert = _geforderte_geschwister(paket)

    fehlend = {name: wo for name, wo in importiert.items() if name not in gefordert}
    assert not fehlend, (
        f"{paket.name} importiert auf Modulebene "
        + ", ".join(f"{n} ({wo})" for n, wo in sorted(fehlend.items()))
        + f" — aber {paket.name}/pyproject.toml fordert es nicht. In einer frischen "
        "Installation bricht das Paket beim Import."
    )


def test_der_riegel_sieht_ueberhaupt_etwas():
    """Untergrenze (LP-36): ueber einer leeren Menge ist der Ausschluss trivial wahr.

    Findet die Sammelfunktion keinen einzigen Geschwister-Import mehr — weil sich
    die Ordnerstruktur geaendert hat oder das AST-Muster nicht mehr passt —, waere
    der Test oben still gruen und pruefte nichts.
    """
    assert PAKETE, "Keine Pakete gefunden — der Riegel liefe ueber der leeren Menge."
    gesamt = {n: wo for p in PAKETE for n, wo in _importierte_geschwister(p).items()}
    assert gesamt, (
        "Kein einziger mkn_*-Import auf Modulebene gefunden. Entweder gibt es "
        "wirklich keinen mehr, oder die Sammelfunktion trifft nicht mehr — im "
        "zweiten Fall prueft der Riegel darueber nichts."
    )
