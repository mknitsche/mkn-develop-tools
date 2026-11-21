"""The guard `scripts/check-private-markers.sh` keeps private paths and internal
identifiers out of this public repository.

Two things must hold: the current tree is clean, and each family of marker is
caught in a throwaway repository (with the file named in the output). The sample
strings are assembled from fragments so this file does not trip the guard itself.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SKRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check-private-markers.sh"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git nicht verfuegbar")


def _lauf(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(repo / "scripts" / "check-private-markers.sh")],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    (tmp_path / "scripts").mkdir()
    shutil.copy(SKRIPT, tmp_path / "scripts" / SKRIPT.name)
    return tmp_path


def test_der_aktuelle_baum_ist_sauber():
    antwort = subprocess.run(
        ["bash", str(SKRIPT)], cwd=SKRIPT.parent, capture_output=True, text=True, check=False
    )
    assert antwort.returncode == 0, antwort.stdout + antwort.stderr


FAELLE = {
    "benutzerpfad-mac": "pfad = '/Use" + "rs/jemand/Bilder'",
    "benutzerpfad-linux": "pfad = '/ho" + "me/jemand/arbeit'",
    "benutzerpfad-root": "pfad = '/ro" + "ot/arbeit'",
    "laufwerk": "pfad = '/Vol" + "umes/Mein Laufwerk/Fotos'",
    "kontakt-id": "# das hat K" + "T-1 so gewollt",
    "sitzung": "# gefunden in ma" + "cb-S314",
    "instanz": "# Warnung von cl" + "d1",
    "ticket": "# siehe TO" + "DO-664",
    "regel": "# Untergrenze (L" + "P-36)",
}


@pytest.mark.parametrize("inhalt", FAELLE.values(), ids=FAELLE.keys())
def test_jede_musterfamilie_wird_gefunden(repo: Path, inhalt: str):
    (repo / "modul.py").write_text(inhalt + "\n", encoding="utf-8")
    _git(repo, "add", "modul.py")

    antwort = _lauf(repo)

    assert antwort.returncode == 1, antwort.stdout + antwort.stderr
    assert "modul.py:1" in antwort.stdout


@pytest.mark.parametrize(
    "inhalt",
    [
        "ziel = '/Vol" + "umes/YourDisk/enriched'",
        "ziel = '/Vol" + "umes/SSD/angereichert'",
        "for v in /Vol" + "umes/*; do :; done",
        "ls -1 /Vol" + "umes/ | sort",
        "x = 'Das Wort macbook und HC-x und ein Hinweis'",
    ],
)
def test_platzhalter_und_harmloses_bleiben_erlaubt(repo: Path, inhalt: str):
    (repo / "modul.py").write_text(inhalt + "\n", encoding="utf-8")
    _git(repo, "add", "modul.py")

    antwort = _lauf(repo)

    assert antwort.returncode == 0, antwort.stdout + antwort.stderr


def test_changelog_wird_nicht_geprueft(repo: Path):
    (repo / "CHANGELOG.md").write_text(FAELLE["kontakt-id"] + "\n", encoding="utf-8")
    _git(repo, "add", "CHANGELOG.md")

    assert _lauf(repo).returncode == 0
