"""Zusicherungen zur Modell-Auswahl.

Die Auswahl hat vier Ausfallmodi, die alle still sind und deshalb teuer:

- Ein **fest verdrahtetes Modell** macht die Auswahl zur Attrappe. Der Anwender
  glaubt zu waehlen und bekommt, was der Autor wollte.
- Ein **fehlender Schluessel** darf nicht wie "keine Antwort" aussehen.
- Ein **unbekannter Anbieter** darf nicht auf einen bekannten zurueckfallen.
- **Bilder duerfen nicht still verschwinden**: eine Bildanalyse ohne Bild
  liefert eine fluessige, vollstaendig erfundene Antwort.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mkn_kern import modelle

# --- Auswahl ---------------------------------------------------------------


def test_anbieter_und_modell_kommen_aus_der_konfiguration():
    w = modelle.waehle(anbieter="anthropic", modell="claude-sonnet-5")
    assert w.anbieter == "anthropic"
    assert w.modell == "claude-sonnet-5"


def test_kimi_ist_gleichrangig_waehlbar():
    """Der zweite Anbieter ist kein Sonderfall, sondern dieselbe Auswahl."""
    w = modelle.waehle(anbieter="moonshot", modell="kimi-k3")
    assert w.anbieter == "moonshot"
    assert w.modell == "kimi-k3"


def test_unbekannter_anbieter_bricht_ab_statt_zurueckzufallen():
    with pytest.raises(modelle.UnbekannterAnbieter, match="openai"):
        modelle.waehle(anbieter="openai", modell="gpt-5")


def test_ohne_modell_kein_lauf():
    """Kein stiller Vorgabewert: wer nicht waehlt, bekommt eine Frage, keine
    Rechnung. Ein eingebautes Vorgabemodell waere genau die Verdrahtung, die
    diese Auswahl verhindern soll."""
    with pytest.raises(modelle.KeinModellGewaehlt):
        modelle.waehle(anbieter="anthropic", modell=None)


def test_umgebung_liefert_die_wahl_wenn_kein_argument_kommt(monkeypatch):
    monkeypatch.setenv("MKN_LLM_ANBIETER", "moonshot")
    monkeypatch.setenv("MKN_LLM_MODELL", "kimi-k3")
    w = modelle.waehle()
    assert (w.anbieter, w.modell) == ("moonshot", "kimi-k3")


def test_argument_schlaegt_umgebung(monkeypatch):
    monkeypatch.setenv("MKN_LLM_ANBIETER", "moonshot")
    monkeypatch.setenv("MKN_LLM_MODELL", "kimi-k3")
    w = modelle.waehle(anbieter="anthropic", modell="claude-opus-5")
    assert w.anbieter == "anthropic"


# --- Schluessel ------------------------------------------------------------


def test_fehlender_schluessel_bricht_laut_ab(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    w = modelle.waehle(anbieter="anthropic", modell="claude-sonnet-5")
    with pytest.raises(modelle.KeinSchluessel, match="ANTHROPIC_API_KEY"):
        w.schluessel()


def test_schluessel_kommt_aus_der_umgebung(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-nur-fuer-den-test")
    w = modelle.waehle(anbieter="anthropic", modell="claude-sonnet-5")
    assert w.schluessel() == "sk-test-nur-fuer-den-test"


def test_jeder_anbieter_hat_seine_eigene_schluesselvariable(monkeypatch):
    """Untergrenze: ohne diesen Fall wuerde ein Wrapper, der ueberall dieselbe
    Variable liest, unbemerkt den Anthropic-Schluessel an Moonshot senden."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic")
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    w = modelle.waehle(anbieter="moonshot", modell="kimi-k3")
    with pytest.raises(modelle.KeinSchluessel, match="MOONSHOT_API_KEY"):
        w.schluessel()


# --- Anfrage-Aufbau --------------------------------------------------------


def test_bilder_landen_wirklich_in_der_anfrage(tmp_path: Path):
    """Der teuerste stille Fehler: das Bild faellt weg, das Modell antwortet
    trotzdem fluessig - und alles daran ist erfunden."""
    bild = tmp_path / "b.jpg"
    bild.write_bytes(_MINI_JPEG)
    w = modelle.waehle(anbieter="anthropic", modell="claude-sonnet-5")

    anfrage = w.baue_anfrage("Was ist zu sehen?", bilder=[bild])

    teile = anfrage["messages"][0]["content"]
    assert sum(1 for t in teile if t.get("type") == "image") == 1
    assert any(t.get("type") == "text" for t in teile)


def test_zwei_bilder_kommen_beide_an(tmp_path: Path):
    """Untergrenze zum Test darueber: 'mindestens eins' waere auch erfuellt,
    wenn alle weiteren verloren gehen - und genau das braucht der Kontaktbogen."""
    bilder = []
    for name in ("a.jpg", "b.jpg"):
        p = tmp_path / name
        p.write_bytes(_MINI_JPEG)
        bilder.append(p)
    w = modelle.waehle(anbieter="anthropic", modell="claude-sonnet-5")

    teile = w.baue_anfrage("x", bilder=bilder)["messages"][0]["content"]

    assert sum(1 for t in teile if t.get("type") == "image") == 2


def test_lokales_modell_ist_gleichrangig_waehlbar():
    """Wer ein Modell auf dem eigenen Rechner hat, soll es nehmen duerfen -
    ohne Schluessel und ohne dass Daten das Geraet verlassen."""
    w = modelle.waehle(anbieter="ollama", modell="gemma4:26b")
    assert w.anbieter == "ollama"


def test_lokales_modell_verlangt_keinen_schluessel(monkeypatch):
    """Untergrenze zur Schluessel-Pruefung: ein lokaler Lauf darf nicht an
    einer fehlenden Umgebungsvariable scheitern, die es dort gar nicht gibt."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    w = modelle.waehle(anbieter="ollama", modell="gemma4:26b")
    assert w.schluessel() is None


def test_ollama_baut_seine_eigene_bildform(tmp_path: Path):
    """Drei Anbieter, drei Bildformen. Ollama haengt die Bilder als Liste an
    die Nachricht, nicht als Inhaltsteil - wer die falsche Form baut, bekommt
    eine Antwort ohne Bild."""
    bild = tmp_path / "b.jpg"
    bild.write_bytes(_MINI_JPEG)
    w = modelle.waehle(anbieter="ollama", modell="gemma4:26b")

    nachricht = w.baue_anfrage("x", bilder=[bild])["messages"][0]

    assert len(nachricht["images"]) == 1
    assert isinstance(nachricht["content"], str)


def test_moonshot_baut_die_andere_bildform(tmp_path: Path):
    """Anthropic und OpenAI-kompatible Anbieter erwarten verschiedene Formen.
    Wer eine davon fuer beide baut, bekommt vom anderen einen 400er - oder,
    schlimmer, eine Antwort ohne Bild."""
    bild = tmp_path / "b.jpg"
    bild.write_bytes(_MINI_JPEG)
    w = modelle.waehle(anbieter="moonshot", modell="kimi-k3")

    teile = w.baue_anfrage("x", bilder=[bild])["messages"][0]["content"]

    assert sum(1 for t in teile if t.get("type") == "image_url") == 1


def test_ohne_bilder_bleibt_die_anfrage_reiner_text():
    w = modelle.waehle(anbieter="anthropic", modell="claude-sonnet-5")
    teile = w.baue_anfrage("nur Text")["messages"][0]["content"]
    assert all(t["type"] == "text" for t in teile)


_MINI_JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9")
