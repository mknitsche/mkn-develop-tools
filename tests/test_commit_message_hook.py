"""Der Commit-Message-Pruefer wird gegen sein VERHALTEN geprueft, nicht gegen seinen Text.

Ein Hook, der nichts abweist, sieht im Alltag genauso aus wie einer, der wirkt —
man merkt den Unterschied erst, wenn die Historie schon unbrauchbar ist. Darum
laeuft hier fuer jeden Fall das echte Skript mit einer echten Datei.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SKRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check-commit-message.sh"


def pruefe(text: str, tmp_path: Path) -> int:
    datei = tmp_path / "COMMIT_EDITMSG"
    datei.write_text(text, encoding="utf-8")
    return subprocess.run([str(SKRIPT), str(datei)], capture_output=True, text=True).returncode


ANGENOMMEN = [
    "feat: add the thing",
    "fix(kern): stop swallowing the error",
    "docs(foto): explain the sidecar rule",
    "refactor!: drop the old entry point",
    "chore(ci): pin the runner",
    "Merge branch 'main' into feature",
    'Revert "feat: add the thing"',
]

ABGEWIESEN = [
    "add the thing",  # kein Typ
    "feat add the thing",  # kein Doppelpunkt
    "feat:",  # keine Zusammenfassung
    "Feat: add the thing",  # Grossschreibung ist kein gueltiger Typ
    "wip: quick fix",  # kein bekannter Typ
]


@pytest.mark.parametrize("betreff", ANGENOMMEN)
def test_gueltige_betreffs_kommen_durch(betreff, tmp_path):
    assert pruefe(betreff + "\n", tmp_path) == 0, f"faelschlich abgewiesen: {betreff!r}"


@pytest.mark.parametrize("betreff", ABGEWIESEN)
def test_ungueltige_betreffs_werden_abgewiesen(betreff, tmp_path):
    assert pruefe(betreff + "\n", tmp_path) != 0, f"durchgelassen, obwohl ungueltig: {betreff!r}"


def test_kommentarzeilen_von_git_verdecken_den_betreff_nicht(tmp_path):
    """git haengt an die Vorlage Kommentarzeilen an. Wer die erste Zeile der DATEI
    liest statt die erste echte Zeile, prueft am Ende einen git-Kommentar."""
    nachricht = "# bitte Nachricht eingeben\n\nfeat: add the thing\n"
    assert pruefe(nachricht, tmp_path) == 0


def test_leerzeilen_vor_dem_betreff_verdecken_ihn_nicht(tmp_path):
    assert pruefe("\n\nfix(kern): repair it\n", tmp_path) == 0


def test_ungueltiger_betreff_unter_kommentaren_wird_trotzdem_gefunden(tmp_path):
    """Die Untergrenze zum Test darueber: das Ausblenden der Kommentare darf nicht
    dazu fuehren, dass am Ende gar nichts mehr geprueft wird."""
    assert pruefe("# hinweis von git\n\nkaputter betreff\n", tmp_path) != 0


def test_leere_nachricht_hat_einen_eigenen_ausgang(tmp_path):
    """Exit 2 statt 1 — sonst ist "leer" von "fehlerhaft" nicht zu unterscheiden,
    und die Leer-Pruefung im Skript waere ungeprueft (die Mutation, die sie
    entfernt, blieb zuerst gruen)."""
    assert pruefe("", tmp_path) == 2
    assert pruefe("# nur ein git-Kommentar\n", tmp_path) == 2
    # Untergrenze: ein fehlerhafter, aber nicht leerer Betreff nutzt den anderen Ausgang.
    assert pruefe("kaputt\n", tmp_path) == 1
