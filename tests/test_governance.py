"""The repository is public. These are the guarantees that must not quietly vanish.

Deleting a LICENSE or a trademark reservation is a one-line change that no
reviewer notices and that nobody feels. Its consequence — work released into
the world under terms nobody chose — is not reversible once someone has taken
a copy. So it is guarded here rather than remembered.

Each assertion below is on the *effect* (does the file grant/reserve the thing),
not on exact wording, so that rewording the prose does not break the test while
removing the substance does.
"""

from __future__ import annotations

import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent


def _lies(name: str) -> str:
    pfad = WURZEL / name
    assert pfad.is_file(), f"{name} fehlt — das ist der Befund, nicht ein fehlender Test."
    return pfad.read_text(encoding="utf-8")


def test_lizenz_ist_agpl3_und_vollstaendig():
    """AGPL-3.0, und zwar der ganze Text — nicht nur eine Ueberschrift.

    Die Laengenpruefung ist die Untergrenze (Regel 4 in CONTRIBUTING): eine Datei,
    die nur `AGPL-3.0` enthaelt, wuerde jede Mustersuche bestehen und trotzdem
    keine Lizenz sein.
    """
    text = _lies("LICENSE")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in text
    assert "Version 3, 19 November 2007" in text
    # Die tragenden Abschnitte, ohne die die Lizenz ihre Wirkung verliert:
    assert "13. Remote Network Interaction" in text, "der Netzwerk-Paragraf fehlt"
    assert len(text.splitlines()) > 600, "Lizenztext ist verkuerzt"


def test_notice_behaelt_namen_und_marken_zurueck():
    """Die Lizenz deckt die Software, nicht die Identitaet dahinter."""
    text = _lies("NOTICE")
    assert "Copyright" in text and "Matthias Nitsche" in text
    assert re.search(r"[Nn]o trademark rights are granted", text), (
        "die Marken-Rueckbehaltung ist weg — dann laesst sich der Name mit-uebernehmen"
    )


def test_beitraege_kommen_unter_dco_herein():
    """Ohne Herkunftsnachweis ist bei einem spaeteren Streit nicht belegbar,
    unter welchen Bedingungen fremder Code hereinkam."""
    text = _lies("CONTRIBUTING.md")
    assert "Developer Certificate of Origin" in text
    assert "Signed-off-by" in text


def test_sicherheitsmeldungen_haben_einen_nichtoeffentlichen_weg():
    text = _lies("SECURITY.md")
    assert re.search(r"do not open a public issue", text, re.IGNORECASE)
    assert "vulnerability" in text.lower()


def test_verhaltensregeln_vorhanden():
    assert "Contributor Covenant" in _lies("CODE_OF_CONDUCT.md")


def test_readme_nennt_lizenz_und_grenze_des_repos():
    """Wer hier landet, muss ohne Klick wissen, was er darf und was hierher gehoert."""
    text = _lies("README.md")
    assert "Affero" in text, "die Lizenz steht nicht im README"
    assert "LICENSE" in text and "NOTICE" in text
