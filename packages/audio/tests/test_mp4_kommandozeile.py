"""Die Kommandozeile: Bedienung, Exit-Codes, Ausgabenamen, Anbindung des Sprachmodells.

Wie beim Lauf braucht kein Test Chatterbox oder ein Netz: der Arbeiter wird durch den
Schein-Arbeiter ersetzt, das Sprachmodell durch einen gefaelschten Transport.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

import pytest

import mkn_audio.kommandozeile as kz
from mkn_audio.arbeiter_client import Arbeiter
from mkn_audio.typen import Mp4Fehler
from muster_quellen import muster_pdf_leer

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
    assert kz.haupt(["--help"]) == 0
    aus = capsys.readouterr().out
    for stichwort in ("--stimme", "--ziel", "--auswahl", "--format", "vorlage", "stimmen"):
        assert stichwort in aus


def test_ohne_argumente_ist_ein_bedienfehler(capsys):
    assert kz.haupt([]) == 2
    assert "vorlage" in capsys.readouterr().err


def test_ungueltiges_format_exit_2(quelle, capsys):
    assert kz.haupt([str(quelle), "--format", "flac"]) == 2
    assert "flac" in capsys.readouterr().err


def test_fehlende_quelle_exit_2(tmp_path, capsys):
    assert kz.haupt([str(tmp_path / "gibtsnicht.epub")]) == 2
    assert "gibtsnicht.epub" in capsys.readouterr().err


def test_unbekannte_stimme_exit_2_und_nennt_die_verfuegbaren(quelle, konfig, capsys):
    assert kz.haupt([str(quelle), "--stimme", "gibtsnicht"]) == 2
    fehler = capsys.readouterr().err
    assert "gibtsnicht" in fehler
    assert "stimme-a" in fehler
    assert "stimme-b" in fehler


def test_konfiguration_fehlt_exit_1(quelle, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MKN_MP4_KONFIG", str(tmp_path / "gibtsnicht.toml"))
    assert kz.haupt([str(quelle)]) == 1
    assert "gibtsnicht.toml" in capsys.readouterr().err


def test_quelle_ohne_text_exit_1(tmp_path, konfig, schein_arbeiter, capsys):
    leer = muster_pdf_leer(tmp_path / "leer.pdf")
    ziel = tmp_path / "aus"
    assert kz.haupt([str(leer), "--ziel", str(ziel)]) == 1
    assert "Fehler:" in capsys.readouterr().err
    assert not ziel.exists() or not list(ziel.iterdir())


# -- Lauf ----------------------------------------------------------------------------------


def test_lauf_mit_schein_arbeiter_exit_0(quelle, konfig, schein_arbeiter, tmp_path, capsys):
    ziel = tmp_path / "aus"
    assert kz.haupt([str(quelle), "--ziel", str(ziel), "--stimme", "stimme-b"]) == 0
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


def test_ziel_vorgabe_ist_der_ordner_der_quelle(quelle, konfig, schein_arbeiter):
    assert kz.haupt([str(quelle)]) == 0
    assert len(list(quelle.parent.glob("*.m4b"))) == 1


def test_mp3_je_kapitel(quelle, konfig, schein_arbeiter, tmp_path):
    ziel = tmp_path / "aus"
    assert kz.haupt([str(quelle), "--ziel", str(ziel), "--format", "mp3"]) == 0
    assert list(ziel.glob("*.mp3"))
    assert not list(ziel.glob("*.m4b"))


def test_auswahl_ausserhalb_exit_1(quelle, konfig, schein_arbeiter, tmp_path, capsys):
    assert kz.haupt([str(quelle), "--ziel", str(tmp_path / "aus"), "--auswahl", "9"]) == 1
    assert "9" in capsys.readouterr().err


def test_ausgabename_nfc(tmp_path, konfig, schein_arbeiter):
    nfd = unicodedata.normalize("NFD", "Äpfel für Übermorgen")
    roh = tmp_path / f"{nfd}.txt"
    roh.write_text("Die Äpfel sind reif. Wir ernten sie morgen früh.\n", encoding="utf-8")
    ziel = tmp_path / "aus"
    assert kz.haupt([str(roh), "--ziel", str(ziel)]) == 0
    namen = [p.name for p in ziel.iterdir()]
    assert namen
    assert all(unicodedata.is_normalized("NFC", n) for n in namen)
    assert any("Äpfel für Übermorgen" in n for n in namen)


def test_ohne_sprachmodell_wird_es_gesagt(quelle, konfig, schein_arbeiter, capsys):
    assert kz.haupt([str(quelle)]) == 0
    assert "MKN_LLM_ANBIETER" in capsys.readouterr().err


# -- Vorlage und Stimmen -----------------------------------------------------------------


def test_vorlage_befehl(tmp_path, konfig, schein_arbeiter, capsys):
    aufnahme = tmp_path / "aufnahme.m4a"
    aufnahme.write_bytes(b"x")
    ziel = tmp_path / "vorlage.wav"
    assert kz.haupt(["vorlage", str(aufnahme), "--ziel", str(ziel), "--dauer", "2"]) == 0
    assert ziel.exists()
    ausgabe = capsys.readouterr()
    assert ausgabe.out.strip() == str(ziel)
    assert "Streuung" in ausgabe.err


def test_vorlage_braucht_ein_ziel(tmp_path, capsys):
    assert kz.haupt(["vorlage", str(tmp_path / "a.m4a")]) == 2


def test_stimmen_zeigt_die_tabelle(konfig, capsys):
    assert kz.haupt(["stimmen"]) == 0
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
    assert kz.haupt([str(quelle)]) == 0
    assert kz.haupt([str(quelle), "--regie", "aus"]) == 0
    assert kz.haupt([str(quelle), "--regie", "buch"]) == 0
    assert gesehen == [None, "aus", "buch"]  # ohne Schalter entscheidet die Quelle

    assert kz.haupt([str(quelle), "--regie", "halb"]) == 2
    assert "--regie" in capsys.readouterr().err
    assert kz.haupt(["--help"]) == 0
    assert "--regie" in capsys.readouterr().out
