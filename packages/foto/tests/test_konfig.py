"""Eine Stelle, an der der Anwender sagt, was er will.

KT-1: *"es muss eine art datei / feld uebergabe geben / der anwender muss halt
festlegen koennen, was er braucht und will / und er muss ja auch die apis
bekannt geben"*.

Vorher lagen die Angaben an drei Orten -- eine Umgebungsvariable fuer die
Schluessel, eine Datei fuer den Urheber, Pfade als Aufrufparameter. Drei Orte
fuer eine Sache sind drei Gelegenheiten, sie zu vergessen.
"""

from __future__ import annotations

import json
from pathlib import Path

from mkn_foto import konfig


def _schreibe(pfad: Path, daten: dict) -> Path:
    pfad.write_text(json.dumps(daten), encoding="utf-8")
    return pfad


def test_eine_datei_traegt_alles(tmp_path: Path) -> None:
    datei = _schreibe(
        tmp_path / "k.json",
        {
            "ziel": "/Volumes/SSD/angereichert",
            "schluessel_datei": "~/.geheim/keys.json",
            "modell": {"anbieter": "anthropic", "name": "claude-opus-5"},
            "urheber": {"name": "Erika Muster", "email": "e@m.de"},
        },
    )

    k = konfig.lade(datei)

    assert k.ziel == Path("/Volumes/SSD/angereichert")
    assert k.modell == ("anthropic", "claude-opus-5")
    assert k.urheber is not None
    assert k.urheber.name == "Erika Muster"


def test_die_tilde_wird_aufgeloest(tmp_path: Path) -> None:
    """`~/...` ist die Schreibweise, die jeder Anwender kennt. Wer sie nicht
    aufloest, bekommt einen Ordner namens `~` im Arbeitsverzeichnis -- und
    merkt es erst, wenn die Bilder dort liegen."""
    datei = _schreibe(tmp_path / "k.json", {"ziel": "~/Bilder/ziel"})

    k = konfig.lade(datei)

    assert k.ziel == Path.home() / "Bilder" / "ziel"
    assert "~" not in str(k.ziel)


def test_ohne_datei_bleibt_alles_leer_statt_zu_raten(tmp_path: Path) -> None:
    k = konfig.lade(tmp_path / "gibtsnicht.json")

    assert k.ziel is None
    assert k.modell is None
    assert k.urheber is None


def test_kaputte_datei_nennt_ihren_ort(tmp_path: Path) -> None:
    """Ein Tippfehler in der eigenen Konfiguration ist der haeufigste Fehler
    ueberhaupt. Er darf nicht als "keine Konfiguration" durchgehen -- sonst
    laeuft das Werkzeug scheinbar richtig und schreibt nichts."""
    datei = tmp_path / "k.json"
    datei.write_text("{kaputt", encoding="utf-8")

    try:
        konfig.lade(datei)
    except konfig.KonfigFehler as exc:
        assert str(datei) in str(exc)
    else:
        raise AssertionError("eine kaputte Datei muss laut sein, nicht leer")


def test_der_schluesselort_wird_als_pfad_geliefert(tmp_path: Path) -> None:
    datei = _schreibe(tmp_path / "k.json", {"schluessel_datei": "~/k.json"})

    assert konfig.lade(datei).schluessel_datei == Path.home() / "k.json"


def test_der_urheber_kommt_vollstaendig_aus_der_konfiguration(tmp_path: Path) -> None:
    """Alle sieben Felder, nicht nur der Name.

    Der Ladeweg lag bis 2026-08-30 in `urheber.py` als eigene Datei mit eigener
    Umgebungsvariable. Zwei Wege fuer eine Angabe sind einer zu viel: der
    Anwender muss zwei Stellen kennen, und wer nur eine pflegt, bekommt lautlos
    die Haelfte.
    """
    datei = _schreibe(
        tmp_path / "k.json",
        {
            "urheber": {
                "name": "Erika Muster",
                "stadt": "M",
                "land": "Germany",
                "email": "e@m.de",
                "website": "https://x.de",
                "rechte_url": "https://x.de/r",
                "nutzungsbedingungen": "Keine Nutzung ohne Erlaubnis.",
            }
        },
    )

    args = konfig.lade(datei).urheber.argumente(jahr=2019, eingebettet=False)

    assert "-XMP-iptcCore:CreatorWorkURL=https://x.de" in args
    assert "-XMP-xmpRights:WebStatement=https://x.de/r" in args
    assert "-XMP-xmpRights:UsageTerms=Keine Nutzung ohne Erlaubnis." in args
    assert "-XMP-iptcCore:CreatorCity=M" in args


def test_ein_urheber_ohne_namen_ist_keiner(tmp_path: Path) -> None:
    """Halb ausgefuellt ist nicht halb gueltig -- ohne Namen ergeben Stadt und
    Mailadresse keinen Urheber."""
    datei = _schreibe(tmp_path / "k.json", {"urheber": {"stadt": "M", "email": "e@m.de"}})

    assert konfig.lade(datei).urheber is None
