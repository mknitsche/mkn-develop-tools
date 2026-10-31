"""Die Kommandozeile: Bedienung, Exit-Codes, Ausgabenamen, Anbindung des Sprachmodells.

Wie beim Lauf braucht kein Test Chatterbox oder ein Netz: der Arbeiter wird durch den
Schein-Arbeiter ersetzt, das Sprachmodell durch einen gefaelschten Transport.
"""

from __future__ import annotations

import io
import json
import re
import sys
import tomllib
import unicodedata
from pathlib import Path
from typing import ClassVar

import pytest

import mkn_audio.kommandozeile as kz
from mkn_audio.arbeiter_client import Arbeiter
from mkn_audio.typen import Mp4Fehler
from muster_quellen import muster_pdf_leer
from schein_google import ScheinGoogle, Uhr, schreibe_tabelle_schema2

SCHEIN = Path(__file__).with_name("schein_arbeiter.py")
TEXT = "# Kleines Buch\n\nDie Sonne geht heute früh auf. Ein leiser Wind weht über den See.\n"


@pytest.fixture
def schein_arbeiter(monkeypatch):
    """Ersetzt den echten Arbeiter durch den Schein-Arbeiter (gleiches Protokoll)."""
    monkeypatch.setattr(
        kz,
        "Arbeiter",
        lambda python, *, whisper_modell="small": Arbeiter(Path(sys.executable), skript=SCHEIN),
    )


@pytest.fixture
def konfig(tmp_path, schreibe_tabelle, monkeypatch):
    """Konfiguration auf Wegwerf-Orten; ohne Sprachmodell-Umgebung."""
    tabelle = schreibe_tabelle("stimme-a", "stimme-b", standard="stimme-a")
    (tmp_path / "vorlagen").mkdir()
    for n in ("stimme-a", "stimme-b"):
        (tmp_path / "vorlagen" / f"{n}.wav").write_bytes(n.encode())
    pfad = tmp_path / "konfig.toml"
    pfad.write_text(
        f'stimmen_tabelle = "{tabelle}"\n'
        f'arbeiter_python = "{sys.executable}"\n'
        f'arbeitsort = "{tmp_path / "arbeit"}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("MKN_MP4_KONFIG", str(pfad))
    for name in ("MKN_LLM_ANBIETER", "MKN_LLM_MODELL"):
        monkeypatch.delenv(name, raising=False)
    return pfad


@pytest.fixture
def quelle(tmp_path):
    ordner = tmp_path / "eingang"
    ordner.mkdir()
    pfad = ordner / "buch.md"
    pfad.write_text(TEXT, encoding="utf-8")
    return pfad


# -- Bedienung --------------------------------------------------------------------------


def test_hilfe(capsys):
    assert kz.haupt(["--help"], weg="local") == 0
    aus = capsys.readouterr().out
    for stichwort in ("--stimme", "--ziel", "--auswahl", "--format", "vorlage", "stimmen"):
        assert stichwort in aus


def test_ohne_argumente_ist_ein_bedienfehler(capsys):
    assert kz.haupt([], weg="local") == 2
    assert "vorlage" in capsys.readouterr().err


def test_ungueltiges_format_exit_2(quelle, capsys):
    assert kz.haupt([str(quelle), "--format", "flac"], weg="local") == 2
    assert "flac" in capsys.readouterr().err


def test_fehlende_quelle_exit_2(tmp_path, capsys):
    assert kz.haupt([str(tmp_path / "gibtsnicht.epub")], weg="local") == 2
    assert "gibtsnicht.epub" in capsys.readouterr().err


def test_unbekannte_stimme_exit_2_und_nennt_die_verfuegbaren(quelle, konfig, capsys):
    assert kz.haupt([str(quelle), "--stimme", "gibtsnicht"], weg="local") == 2
    fehler = capsys.readouterr().err
    assert "gibtsnicht" in fehler
    assert "stimme-a" in fehler
    assert "stimme-b" in fehler


def test_konfiguration_fehlt_exit_1(quelle, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MKN_MP4_KONFIG", str(tmp_path / "gibtsnicht.toml"))
    assert kz.haupt([str(quelle)], weg="local") == 1
    assert "gibtsnicht.toml" in capsys.readouterr().err


def test_quelle_ohne_text_exit_1(tmp_path, konfig, schein_arbeiter, capsys):
    leer = muster_pdf_leer(tmp_path / "leer.pdf")
    ziel = tmp_path / "aus"
    assert kz.haupt([str(leer), "--ziel", str(ziel)], weg="local") == 1
    assert "Fehler:" in capsys.readouterr().err
    assert not ziel.exists() or not list(ziel.iterdir())


# -- Lauf ----------------------------------------------------------------------------------


def test_lauf_mit_schein_arbeiter_exit_0(quelle, konfig, schein_arbeiter, tmp_path, capsys):
    ziel = tmp_path / "aus"
    assert kz.haupt([str(quelle), "--ziel", str(ziel), "--stimme", "stimme-b"], weg="local") == 0
    ergebnis = capsys.readouterr()
    m4b = list(ziel.glob("*.m4b"))
    bericht = list(ziel.glob("* Bericht_v01.md"))
    assert len(m4b) == 1
    assert len(bericht) == 1
    # stdout traegt nur die Ergebnisse (eine Datei je Zeile), Fortschritt geht nach stderr
    zeilen = ergebnis.out.strip().splitlines()
    assert str(m4b[0]) in zeilen
    assert str(bericht[0]) in zeilen
    assert "Sprechen" in ergebnis.err
    assert "stimme-b_v01" in bericht[0].read_text(encoding="utf-8")


def test_vorab_lesen_der_sprachwahl_meldet_fortschritt(
    quelle, konfig, schein_arbeiter, tmp_path, capsys
):
    """Ohne `--stimme` liest die Kommandozeile die Quelle vorab (Sprachwahl): das ist die
    Stelle, an der ein Bildmodell lange arbeitet -- "Lesen" erscheint, bevor gesprochen wird."""
    ziel = tmp_path / "aus"
    assert kz.haupt([str(quelle), "--ziel", str(ziel)], weg="local") == 0

    zeilen = capsys.readouterr().err.splitlines()
    assert "Lesen" in zeilen  # das echte Lesen; der Lauf danach nimmt den Zwischenstand
    assert zeilen.index("Lesen") < zeilen.index("Lesen (vorhanden)")
    assert zeilen.index("Lesen") < next(i for i, z in enumerate(zeilen) if z.startswith("Sprechen"))


def test_ziel_vorgabe_ist_der_ordner_der_quelle(quelle, konfig, schein_arbeiter):
    assert kz.haupt([str(quelle)], weg="local") == 0
    assert len(list(quelle.parent.glob("*.m4b"))) == 1


def test_mp3_je_kapitel(quelle, konfig, schein_arbeiter, tmp_path):
    ziel = tmp_path / "aus"
    assert kz.haupt([str(quelle), "--ziel", str(ziel), "--format", "mp3"], weg="local") == 0
    assert list(ziel.glob("*.mp3"))
    assert not list(ziel.glob("*.m4b"))


def test_auswahl_ausserhalb_exit_1(quelle, konfig, schein_arbeiter, tmp_path, capsys):
    assert (
        kz.haupt([str(quelle), "--ziel", str(tmp_path / "aus"), "--auswahl", "9"], weg="local") == 1
    )
    assert "9" in capsys.readouterr().err


def test_ausgabename_nfc(tmp_path, konfig, schein_arbeiter):
    nfd = unicodedata.normalize("NFD", "Äpfel für Übermorgen")
    roh = tmp_path / f"{nfd}.txt"
    roh.write_text("Die Äpfel sind reif. Wir ernten sie morgen früh.\n", encoding="utf-8")
    ziel = tmp_path / "aus"
    assert kz.haupt([str(roh), "--ziel", str(ziel)], weg="local") == 0
    namen = [p.name for p in ziel.iterdir()]
    assert namen
    assert all(unicodedata.is_normalized("NFC", n) for n in namen)
    assert any("Äpfel für Übermorgen" in n for n in namen)


def test_ohne_sprachmodell_wird_es_gesagt(quelle, konfig, schein_arbeiter, capsys):
    assert kz.haupt([str(quelle)], weg="local") == 0
    assert "MKN_LLM_ANBIETER" in capsys.readouterr().err


# -- Vorlage und Stimmen -----------------------------------------------------------------


def test_vorlage_befehl(tmp_path, konfig, schein_arbeiter, capsys):
    aufnahme = tmp_path / "aufnahme.m4a"
    aufnahme.write_bytes(b"x")
    ziel = tmp_path / "vorlage.wav"
    assert (
        kz.haupt(["vorlage", str(aufnahme), "--ziel", str(ziel), "--dauer", "2"], weg="local") == 0
    )
    assert ziel.exists()
    ausgabe = capsys.readouterr()
    assert ausgabe.out.strip() == str(ziel)
    assert "Streuung" in ausgabe.err


def test_vorlage_braucht_ein_ziel(tmp_path, capsys):
    assert kz.haupt(["vorlage", str(tmp_path / "a.m4a")], weg="local") == 2


def test_stimmen_zeigt_die_tabelle(konfig, capsys):
    assert kz.haupt(["stimmen"], weg="local") == 0
    zeilen = capsys.readouterr().out.splitlines()
    a = next(z for z in zeilen if "stimme-a" in z)
    b = next(z for z in zeilen if "stimme-b" in z)
    assert "*" in a  # die Standard-Stimme ist gekennzeichnet
    assert "*" not in b
    assert "Teststimme" in a


# -- Sprachmodell ---------------------------------------------------------------------------


def _transport(antwort: dict, mitschrift: list):
    def senden(url, koerper, kopf, zeitgrenze):
        mitschrift.append((url, json.loads(koerper), kopf))
        return 200, json.dumps(antwort).encode()

    return senden


def test_ohne_anbieter_kein_textmodell(monkeypatch):
    monkeypatch.delenv("MKN_LLM_ANBIETER", raising=False)
    assert kz.baue_textmodell() is None


def test_anbieter_ohne_modell_bricht(monkeypatch):
    monkeypatch.setenv("MKN_LLM_ANBIETER", "anthropic")
    monkeypatch.delenv("MKN_LLM_MODELL", raising=False)
    with pytest.raises(Mp4Fehler, match="Modell"):
        kz.baue_textmodell()


def test_anbieter_ohne_schluessel_bricht_vor_dem_lauf(monkeypatch):
    monkeypatch.setenv("MKN_LLM_ANBIETER", "anthropic")
    monkeypatch.setenv("MKN_LLM_MODELL", "irgendeins")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MKN_LLM_SCHLUESSEL_DATEI", raising=False)
    with pytest.raises(Mp4Fehler, match="Schluessel"):
        kz.baue_textmodell()


def test_textmodell_schickt_prompt_und_bilder_und_liest_die_antwort(monkeypatch):
    monkeypatch.setenv("MKN_LLM_ANBIETER", "anthropic")
    monkeypatch.setenv("MKN_LLM_MODELL", "irgendeins")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "geheim-fuer-den-test")
    gesehen: list = []
    modell = kz.baue_textmodell(
        transport=_transport(
            {"content": [{"type": "text", "text": "Hallo "}, {"type": "text", "text": "Welt"}]},
            gesehen,
        )
    )
    assert modell is not None

    text = modell("Lies das.", (("image/png", b"\x89PNG-bytes"),))

    assert text == "Hallo Welt"
    ((url, koerper, kopf),) = gesehen
    assert url.startswith("https://")
    inhalt = koerper["messages"][0]["content"]
    assert inhalt[0] == {"type": "text", "text": "Lies das."}
    assert (
        inhalt[1]["source"]["media_type"] == "image/png"
    )  # der Typ kommt aus dem mime, nicht geraten
    assert kopf["x-api-key"] == "geheim-fuer-den-test"
    assert koerper["max_tokens"] >= 4096  # eine Seite Text darf nicht abgeschnitten werden


def test_unbekannter_bildtyp_bricht(monkeypatch):
    monkeypatch.setenv("MKN_LLM_ANBIETER", "ollama")
    monkeypatch.setenv("MKN_LLM_MODELL", "irgendeins")
    modell = kz.baue_textmodell(transport=_transport({"message": {"content": "x"}}, []))
    with pytest.raises(Mp4Fehler, match="image/x-unbekannt"):
        modell("Lies das.", (("image/x-unbekannt", b"x"),))


@pytest.mark.parametrize(
    ("antwort", "erwartet"),
    [
        ({"content": [{"type": "text", "text": "a"}], "stop_reason": "end_turn"}, "a"),
        ({"candidates": [{"content": {"parts": [{"text": "b"}]}}]}, "b"),
        ({"choices": [{"message": {"content": "c"}}]}, "c"),
        ({"message": {"content": "d"}}, "d"),
    ],
)
def test_antworttext_aller_formen(antwort, erwartet):
    assert kz.antwort_text(antwort) == erwartet


@pytest.mark.parametrize(
    "antwort",
    [
        {"content": [{"type": "text", "text": "halb"}], "stop_reason": "max_tokens"},
        {"candidates": [{"content": {"parts": [{"text": "halb"}]}, "finishReason": "MAX_TOKENS"}]},
        {"choices": [{"message": {"content": "halb"}, "finish_reason": "length"}]},
        {"message": {"content": "halb"}, "done_reason": "length"},
    ],
)
def test_abgeschnittene_antwort_bricht(antwort):
    with pytest.raises(Mp4Fehler, match="abgeschnitten"):
        kz.antwort_text(antwort)


def test_antwort_ohne_text_bricht():
    with pytest.raises(Mp4Fehler, match="Text"):
        kz.antwort_text({"unbekannt": 1})


def test_anfragefehler_wird_ein_paketfehler(monkeypatch):
    monkeypatch.setenv("MKN_LLM_ANBIETER", "ollama")
    monkeypatch.setenv("MKN_LLM_MODELL", "irgendeins")

    def kaputt(url, koerper, kopf, zeitgrenze):
        return 500, b'{"error": "nein"}'

    modell = kz.baue_textmodell(transport=kaputt)
    with pytest.raises(Mp4Fehler, match="500"):
        modell("Lies das.", ())


# -- Regie-Schalter --------------------------------------------------------------------------


def test_kommandozeile_regie_schalter(quelle, konfig, schein_arbeiter, monkeypatch, capsys):
    gesehen: list = []
    echt = kz.konvertiere

    def merke(*args, **kw):
        gesehen.append(kw["regie_modus"])
        return echt(*args, **kw)

    monkeypatch.setattr(kz, "konvertiere", merke)
    assert kz.haupt([str(quelle)], weg="local") == 0
    assert kz.haupt([str(quelle), "--regie", "aus"], weg="local") == 0
    assert kz.haupt([str(quelle), "--regie", "buch"], weg="local") == 0
    assert gesehen == [None, "aus", "buch"]  # ohne Schalter entscheidet die Quelle

    assert kz.haupt([str(quelle), "--regie", "halb"], weg="local") == 2
    assert "--regie" in capsys.readouterr().err
    assert kz.haupt(["--help"], weg="local") == 0
    assert "--regie" in capsys.readouterr().out


# -- Zwei Befehle: mkn-mp4-local und mkn-mp4-gemini (Plan C4) --------------------------------
# `haupt(argv, weg=...)` ist der eine Kern; der Gemini-Weg spricht am Schein-Transport. Dafuer
# ersetzt `schein_google` das Symbol `kz.SprecherGemini` durch eine Fabrik, die den Transport,
# die Uhr und den Schlaf einspeist (alle anderen Argumente reicht sie durch).


KONTAKT = "Antworten bitte an erika@beispiel.example bis Ende der Woche."
PREISE = (
    "preis_usd_je_1m_text_token = 1.0\n"
    "preis_usd_je_1m_audio_token = 20.0\n"
    "preisstand = 2026-10-30\n"
)


@pytest.fixture
def konfig_gemini(tmp_path, monkeypatch):
    """Tabelle Schema 2 (local + gemini, Preise gesetzt), Konfiguration OHNE `arbeiter_python`."""
    tabelle = schreibe_tabelle_schema2(tmp_path, wege_gemini_extra=PREISE)
    pfad = tmp_path / "konfig-gemini.toml"
    pfad.write_text(
        f'stimmen_tabelle = "{tabelle}"\narbeitsort = "{tmp_path / "arbeit"}"\n', encoding="utf-8"
    )
    monkeypatch.setenv("MKN_MP4_KONFIG", str(pfad))
    for name in ("MKN_LLM_ANBIETER", "MKN_LLM_MODELL", "MKN_LLM_SCHLUESSEL_DATEI"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "nur-ein-test")
    return pfad


@pytest.fixture
def schein_google(monkeypatch):
    from mkn_audio.gemini import SprecherGemini

    schein = ScheinGoogle()
    uhr = Uhr()

    def fabrik(**kw):
        return SprecherGemini(**{"transport": schein, "uhr": uhr, "schlaf": uhr.schlaf, **kw})

    monkeypatch.setattr(kz, "SprecherGemini", fabrik)
    return schein


def _quelle(tmp_path: Path, *absaetze: str) -> Path:
    pfad = tmp_path / "eingang" / "garten.md"
    pfad.parent.mkdir(exist_ok=True)
    pfad.write_text("# Gartenjahr\n\n" + "\n\n".join(absaetze) + "\n", encoding="utf-8")
    return pfad


SATZ = "Der Gärtner gießt am Morgen die Rosen."


def test_mkn_mp4_entfaellt():
    """`mkn-mp4` entfaellt ohne Alias (E6); zwei Einstiege in einen Kern."""
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    befehle = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["scripts"]

    assert befehle == {
        "mkn-mp4-local": "mkn_audio.kommandozeile:haupt_local",
        "mkn-mp4-gemini": "mkn_audio.kommandozeile:haupt_gemini",
    }
    assert callable(kz.haupt_local) and callable(kz.haupt_gemini)


def test_gemini_hilfe_nennt_cloud_ok_und_modell(capsys):
    assert kz.haupt(["--help"], weg="gemini") == 0
    aus = capsys.readouterr().out
    for stichwort in (
        "mkn-mp4-gemini",
        "--cloud-ok",
        "--modell",
        "--ansage",
        "--stimme",
        "stimmen",
    ):
        assert stichwort in aus, stichwort
    assert "vorlage" not in aus
    assert not re.search(r"mkn-mp4(?![-\w])", aus)  # kein alter Befehlsname


def test_local_hilfe_ohne_cloud_ok(capsys):
    assert kz.haupt(["--help"], weg="local") == 0
    aus = capsys.readouterr().out
    for stichwort in ("mkn-mp4-local", "--ansage", "--stimme", "vorlage", "stimmen"):
        assert stichwort in aus, stichwort
    assert "--cloud-ok" not in aus and "--modell" not in aus
    assert not re.search(r"mkn-mp4(?![-\w])", aus)


def test_stimme_fremden_wegs_exit_2(tmp_path, konfig_gemini, capsys):
    quelle = _quelle(tmp_path, SATZ)

    assert kz.haupt([str(quelle), "--stimme", "deutsch-gemini-charon"], weg="local") == 2
    assert "deutsch-gemini-charon" in capsys.readouterr().err
    assert kz.haupt([str(quelle), "--stimme", "beispiel"], weg="gemini") == 2
    assert "beispiel" in capsys.readouterr().err


class _Merker(Arbeiter):
    """Schein-Arbeiter, der je gesprochenem Text den Dateinamen der Vorlage festhaelt."""

    vorlagen: ClassVar[dict[str, str]] = {}

    def sprich(self, text, *, ziel, **kw):
        _Merker.vorlagen[text] = Path(kw["vorlage"]).name
        return super().sprich(text, ziel=ziel, **kw)


def test_ansage_ueberschreibt_rolle(quelle, konfig, monkeypatch, tmp_path):
    """`--ansage` waehlt die Stimme der Rolle Ansage (Titel); `--stimme` den Fliesstext."""
    _Merker.vorlagen = {}
    monkeypatch.setattr(
        kz,
        "Arbeiter",
        lambda python, *, whisper_modell="small": _Merker(Path(sys.executable), skript=SCHEIN),
    )

    code = kz.haupt(
        [
            str(quelle),
            "--ziel",
            str(tmp_path / "aus"),
            "--stimme",
            "stimme-a",
            "--ansage",
            "stimme-b",
        ],
        weg="local",
    )

    assert code == 0
    assert _Merker.vorlagen["Kleines Buch"] == "stimme-b.wav"
    uebrige = {v for t, v in _Merker.vorlagen.items() if t != "Kleines Buch"}
    assert uebrige == {"stimme-a.wav"}


def test_rueckfrage_ohne_tty_exit_3(tmp_path, konfig_gemini, schein_google, monkeypatch, capsys):
    """Hinweise, kein TTY, kein `--cloud-ok`: Exit 3 VOR der ersten Anfrage."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    ziel = tmp_path / "aus"

    assert kz.haupt([str(_quelle(tmp_path, SATZ, KONTAKT)), "--ziel", str(ziel)], weg="gemini") == 3
    assert schein_google.ruempfe == []  # Transport-Zaehler 0
    assert "Kontaktdaten" in capsys.readouterr().err
    assert not ziel.exists() or not list(ziel.glob("*.m4b"))


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.mark.parametrize(("antwort", "code"), [("n\n", 3), ("j\n", 0)])
def test_rueckfrage_mit_tty_antwort_entscheidet(
    tmp_path, konfig_gemini, schein_google, monkeypatch, capsys, antwort, code
):
    """Mit TTY fragt der Befehl "[j/N]" auf stderr; nur "j" sendet (Spec 9)."""
    monkeypatch.setattr(sys, "stdin", _Tty(antwort))
    quelle = _quelle(tmp_path, SATZ, KONTAKT)

    assert kz.haupt([str(quelle), "--ziel", str(tmp_path / "aus")], weg="gemini") == code
    assert "[j/N]" in capsys.readouterr().err
    assert bool(schein_google.ruempfe) is (code == 0)


def test_cloud_ok_spricht(tmp_path, konfig_gemini, schein_google, capsys):
    ziel = tmp_path / "aus"
    quelle = _quelle(tmp_path, SATZ, KONTAKT)

    assert kz.haupt([str(quelle), "--ziel", str(ziel), "--cloud-ok"], weg="gemini") == 0
    (m4b,) = ziel.glob("*.m4b")
    assert str(m4b) in capsys.readouterr().out
    assert schein_google.ruempfe


def test_vorlage_nur_local(tmp_path, konfig_gemini, capsys):
    aufnahme = tmp_path / "aufnahme.m4a"
    aufnahme.write_bytes(b"x")

    assert (
        kz.haupt(["vorlage", str(aufnahme), "--ziel", str(tmp_path / "v.wav")], weg="gemini") == 2
    )
    assert not (tmp_path / "v.wav").exists()


def test_gemini_ohne_schluessel_bricht_vor_der_arbeit(
    tmp_path, konfig_gemini, schein_google, monkeypatch, capsys
):
    """Ohne Schluessel Exit 1 mit dem Namen der Variablen -- bevor gelesen wird."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("MKN_LLM_SCHLUESSEL_DATEI", raising=False)

    assert kz.haupt([str(_quelle(tmp_path, SATZ)), "--cloud-ok"], weg="gemini") == 1
    assert "GEMINI_API_KEY" in capsys.readouterr().err
    assert schein_google.ruempfe == []
    assert not (tmp_path / "arbeit").exists()  # nichts gelesen, kein Zwischenstand


class _Mitschrift:
    """Ersatz fuer stderr: jede geschriebene Zeile kommt mit Marke in eine gemeinsame Folge."""

    def __init__(self, folge: list[tuple[str, str]]) -> None:
        self.folge = folge

    def write(self, text: str) -> int:
        if text.strip():
            self.folge.append(("stderr", text))
        return len(text)

    def flush(self) -> None:
        pass


def test_schaetzung_auf_stderr_vor_dem_sprechen(
    tmp_path, konfig_gemini, schein_google, monkeypatch
):
    """Die Kostenschaetzung (USD) steht auf stderr, BEVOR die erste Anfrage hinausgeht."""
    folge: list[tuple[str, str]] = []

    def regel(n, rumpf):
        folge.append(("anfrage", str(n)))

    schein_google.regel = regel
    monkeypatch.setattr(sys, "stderr", _Mitschrift(folge))

    assert (
        kz.haupt([str(_quelle(tmp_path, SATZ)), "--ziel", str(tmp_path / "aus")], weg="gemini") == 0
    )

    erste_anfrage = next(i for i, (art, _) in enumerate(folge) if art == "anfrage")
    schaetzung = [i for i, (art, text) in enumerate(folge) if art == "stderr" and "USD" in text]
    assert schaetzung, folge
    assert schaetzung[0] < erste_anfrage


def test_schema1_hinweis_auf_stderr(quelle, konfig, schein_arbeiter, tmp_path, capsys):
    """Eine Tabelle im alten Format laeuft; der Hinweis steht genau einmal auf stderr."""
    assert kz.haupt([str(quelle), "--ziel", str(tmp_path / "aus")], weg="local") == 0
    assert capsys.readouterr().err.count("Schema 1") == 1


def test_modell_ueberschreibung_rechnet_nicht_mit_den_preisen_der_tabelle(
    tmp_path, konfig_gemini, schein_google, capsys
):
    """`--modell` mit fremdem Modell: die Tabellenpreise gehoeren dem Tabellen-Modell (Spec 8.7).

    Schutzgut falsche Information: Schaetzung UND Bericht nennen keine USD-Zahl, sondern
    "Preise nicht konfiguriert"."""
    ziel = tmp_path / "aus"

    code = kz.haupt(
        [
            str(_quelle(tmp_path, SATZ)),
            "--ziel",
            str(ziel),
            "--cloud-ok",
            "--modell",
            "anderes-tts",
        ],
        weg="gemini",
    )

    assert code == 0
    fehlerausgabe = capsys.readouterr().err
    assert "Preise nicht konfiguriert" in fehlerausgabe
    assert "USD für" not in fehlerausgabe  # keine Zahl in der Schaetzung
    assert schein_google.modelle == {"anderes-tts"}
    bericht = next(ziel.glob("*.md")).read_text(encoding="utf-8")
    assert "Preise nicht konfiguriert" in bericht
    assert "Preisstand" not in bericht


def test_modell_gleich_der_tabelle_behaelt_die_preise(
    tmp_path, konfig_gemini, schein_google, capsys
):
    from mkn_audio.stimmen import lade_tabelle

    tabelle = lade_tabelle(Path(tomllib.loads(konfig_gemini.read_text())["stimmen_tabelle"]))
    ziel = tmp_path / "aus"

    code = kz.haupt(
        [
            str(_quelle(tmp_path, SATZ)),
            "--ziel",
            str(ziel),
            "--cloud-ok",
            "--modell",
            tabelle.wege["gemini"].modell,
        ],
        weg="gemini",
    )

    assert code == 0
    assert "USD für" in capsys.readouterr().err


def test_local_ohne_arbeiter_python_exit_1_nennt_das_feld(tmp_path, konfig_gemini, capsys):
    """Der Weg local braucht den Arbeiter (Chatterbox); ohne `arbeiter_python` bricht er laut ab."""
    ziel = tmp_path / "aus"

    code = kz.haupt([str(_quelle(tmp_path, SATZ)), "--ziel", str(ziel)], weg="local")

    assert code == 1
    assert "arbeiter_python" in capsys.readouterr().err
    assert not ziel.exists()


def test_vorlage_ohne_arbeiter_python_exit_1_nennt_das_feld(tmp_path, konfig_gemini, capsys):
    aufnahme = tmp_path / "aufnahme.m4a"
    aufnahme.write_bytes(b"x")
    ziel = tmp_path / "v.wav"

    code = kz.haupt(["vorlage", str(aufnahme), "--ziel", str(ziel)], weg="local")

    assert code == 1
    assert "arbeiter_python" in capsys.readouterr().err
    assert not ziel.exists()


# -- Sprachwahl nach Dokumentsprache (Spec 7.1) -------------------------------------------------

ENGLISCH = (
    "The gardener walks along the old wall in the early morning and waits for the sun to rise "
    "over the hills. There is a quiet wind in the trees, and the birds begin to sing as the "
    "light comes into the garden. It is a good day for the roses, and the water in the pond "
    "is clear and cold."
)
FRANZOESISCH = (
    "Le jardinier marche le long du vieux mur dans la matinée et attend que le soleil se lève "
    "sur les collines. Il y a un vent doux dans les arbres, et les oiseaux commencent à chanter "
    "pendant que la lumière entre dans le jardin. C'est un bon jour pour les roses, et l'eau "
    "du bassin est claire et froide."
)
ENGLISCHE_ZEILEN = """
[standard.gemini.en]
text = "englisch-gemini-puck"
ansage = "englisch-gemini-zephyr"

[stimmen.englisch-gemini-puck]
weg = "gemini"
stimme = "Puck"
beschreibung = "Teststimme Text englisch"
sprache = "en"
stand = "probe"

[stimmen.englisch-gemini-zephyr]
weg = "gemini"
stimme = "Zephyr"
beschreibung = "Teststimme Ansage englisch"
sprache = "en"
stand = "probe"
"""


@pytest.fixture
def konfig_gemini_englisch(konfig_gemini):
    """Die Tabelle der Kommandozeilen-Tests, dazu die Standard-Stimmen `[standard.gemini.en]`."""
    tabelle = Path(tomllib.loads(konfig_gemini.read_text())["stimmen_tabelle"])
    tabelle.write_text(tabelle.read_text(encoding="utf-8") + ENGLISCHE_ZEILEN, encoding="utf-8")
    return konfig_gemini


def _stimmen_im_lauf(schein_google) -> set[str]:
    return {r["generation_config"]["speech_config"][0]["voice"] for r in schein_google.ruempfe}


def test_englisches_dokument_waehlt_die_englischen_standardstimmen(
    tmp_path, konfig_gemini_englisch, schein_google, capsys
):
    """Ohne `--stimme`/`--ansage` gilt `[standard.<weg>.<dokumentsprache>]` (Spec 7.1)."""
    code = kz.haupt(
        [str(_quelle(tmp_path, ENGLISCH)), "--ziel", str(tmp_path / "aus"), "--cloud-ok"],
        weg="gemini",
    )

    assert code == 0
    assert _stimmen_im_lauf(schein_google) == {"Puck", "Zephyr"}  # Text und Ansage (Titel)
    assert "Keine Standard-Stimme" not in capsys.readouterr().err


def test_dokumentsprache_ohne_standard_faellt_auf_de_mit_warnung(
    tmp_path, konfig_gemini_englisch, schein_google, capsys
):
    code = kz.haupt(
        [str(_quelle(tmp_path, FRANZOESISCH)), "--ziel", str(tmp_path / "aus"), "--cloud-ok"],
        weg="gemini",
    )

    assert code == 0
    assert _stimmen_im_lauf(schein_google) == {"Charon", "Kore"}
    assert "Keine Standard-Stimme fuer Sprache 'fr'" in capsys.readouterr().err


def test_stimme_hat_vorrang_vor_der_dokumentsprache(
    tmp_path, konfig_gemini_englisch, schein_google
):
    code = kz.haupt(
        [
            str(_quelle(tmp_path, ENGLISCH)),
            "--ziel",
            str(tmp_path / "aus"),
            "--cloud-ok",
            "--stimme",
            "deutsch-gemini-charon",
            "--ansage",
            "deutsch-gemini-kore",
        ],
        weg="gemini",
    )

    assert code == 0
    assert _stimmen_im_lauf(schein_google) == {"Charon", "Kore"}


def test_bildquelle_ohne_stimme_wird_vom_bildmodell_nur_einmal_gelesen(
    tmp_path, konfig_gemini, schein_google, monkeypatch
):
    """Critic R B3: die Sprachwahl liest die Quelle vorab, `konvertiere` danach noch einmal --
    ein Bildmodell bezahlt man nicht doppelt. Beide Wege teilen den Zwischenstand `lesetext`;
    ein Neustart derselben Quelle liest gar nicht mehr.
    Mutation (rot): die Kommandozeile liest wieder mit `lies(...)` statt ueber den Zwischenstand.
    """
    from mkn_audio.hoertext.glaetten import PROMPT as PROMPT_GLAETTEN
    from muster_quellen import muster_png

    gelesen: list[int] = []

    def bildmodell(prompt, bilder):
        if prompt.startswith(PROMPT_GLAETTEN):
            return prompt.removeprefix(PROMPT_GLAETTEN)
        gelesen.append(len(bilder))
        return "Ein erfundener Satz auf dem Bild.\n\nNoch ein erfundener Satz dazu."

    monkeypatch.setattr(kz, "baue_textmodell", lambda: bildmodell)
    bild = muster_png(tmp_path / "Seite aus dem alten Gartenbuch.png")
    argumente = [str(bild), "--ziel", str(tmp_path / "aus"), "--cloud-ok", "--regie", "aus"]

    assert kz.haupt(argumente, weg="gemini") == 0
    assert gelesen == [1]  # ein Bild, einmal gelesen

    assert kz.haupt(argumente, weg="gemini") == 0
    assert gelesen == [1]  # Neustart: aus dem Zwischenstand, kein Bildmodell mehr
