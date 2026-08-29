"""Der Commit-Message-Hook hat einen Ausfallmodus, den man im Alltag nicht sieht:
er laesst alles durch und sieht dabei aus wie ein Hook, der wirkt. Gemerkt wird es
erst an einer Historie, die niemand mehr auswerten kann.

Vier Faelle, vier echte Ausfallmodi. Mehr braucht es nicht.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

SKRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check-commit-message.sh"


def pruefe(text: str, tmp_path: Path) -> int:
    datei = tmp_path / "COMMIT_EDITMSG"
    datei.write_text(text, encoding="utf-8")
    return subprocess.run([str(SKRIPT), str(datei)], capture_output=True, text=True).returncode


def test_gueltiger_betreff_kommt_durch(tmp_path):
    assert pruefe("fix(kern): stop swallowing the error\n", tmp_path) == 0


def test_ungueltiger_betreff_wird_abgewiesen(tmp_path):
    """Der Ausfallmodus, um den es geht: ein Hook, der nichts abweist."""
    assert pruefe("quick fix\n", tmp_path) != 0


def test_git_kommentare_verdecken_den_betreff_nicht(tmp_path):
    """git haengt an die Vorlage Kommentarzeilen an. Wer die erste Zeile der DATEI
    liest statt die erste inhaltliche, prueft am Ende einen git-Kommentar — und
    das faellt nie auf, weil der Kommentar zufaellig immer gleich aussieht."""
    assert pruefe("# bitte Nachricht eingeben\n\nfeat: add the thing\n", tmp_path) == 0
    # Untergrenze: das Ausblenden darf nicht dazu fuehren, dass gar nichts geprueft wird.
    assert pruefe("# bitte Nachricht eingeben\n\nkaputter betreff\n", tmp_path) != 0


def test_merge_commits_von_git_werden_nicht_abgewiesen(tmp_path):
    """Sonst blockiert der Hook Commits, die der Beitragende gar nicht formuliert hat."""
    assert pruefe("Merge branch 'main' into feature\n", tmp_path) == 0
