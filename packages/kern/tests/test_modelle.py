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


# --- Gemini (KT-1, 2026-08-30) ---------------------------------------------
#
# KT-1: "da ich ja mehrere api keys in den credential habe, kannst du sogar fuer
# die sw testen, ob es mit anthropic bzw. mit gemini funktioniert (kimi hatten
# wir ja ausgeschlossen / und ok, gemini noch gar nicht probiert)".
#
# Fuer ein veroeffentlichtes Werkzeug ist das die ehrlichere Probe: was nur bei
# EINEM Anbieter laeuft, hat die Schnittstelle nicht verstanden, sondern eine
# Eigenheit.


def test_gemini_ist_gleichrangig_waehlbar():
    w = modelle.waehle(anbieter="gemini", modell="gemini-3-pro")
    assert w.anbieter == "gemini"
    assert w.modell == "gemini-3-pro"


def test_gemini_hat_eine_eigene_schluesselvariable(monkeypatch):
    """Je Anbieter eine eigene Variable — sonst landet der Schluessel des einen
    beim anderen, und das faellt erst am Abrechnungsbeleg auf."""
    monkeypatch.setenv("GEMINI_API_KEY", "g-geheim")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-geheim")

    assert modelle.waehle(anbieter="gemini", modell="x").schluessel() == "g-geheim"
    assert modelle.waehle(anbieter="anthropic", modell="y").schluessel() == "a-geheim"


def test_gemini_bekommt_das_bild_in_seiner_eigenen_form(tmp_path):
    """Gemini erwartet weder Anthropics `source` noch OpenAIs `image_url`,
    sondern `inline_data` mit `mime_type`. Wer die Form verwechselt, bekommt
    eine Antwort — nur eben ohne Bild, und die ist fluessig und erfunden."""
    bild = tmp_path / "b.jpg"
    bild.write_bytes(b"\xff\xd8\xff\xe0BILD\xff\xd9")

    koerper = modelle.waehle(anbieter="gemini", modell="x").baue_anfrage(
        "Was ist zu sehen?", bilder=[bild]
    )

    teile = koerper["contents"][0]["parts"]
    bildteile = [t for t in teile if "inline_data" in t]
    assert bildteile, f"kein Bild in Gemini-Form: {[list(t) for t in teile]}"
    assert bildteile[0]["inline_data"]["mime_type"] == "image/jpeg"
    assert bildteile[0]["inline_data"]["data"], "das Bild ist leer"


def test_gemini_traegt_den_text_mit(tmp_path):
    """Untergrenze zur Zusicherung darueber: ein Bild ohne Frage ist so wertlos
    wie eine Frage ohne Bild."""
    koerper = modelle.waehle(anbieter="gemini", modell="x").baue_anfrage("Die Frage.")

    texte = [t["text"] for t in koerper["contents"][0]["parts"] if "text" in t]
    assert "Die Frage." in texte


# --- Wo der Schluessel liegt (KT-1s Loesungsgedanke, 2026-08-30) ------------
#
# Sein Konzept, woertlich: *"es braucht eh eine beschreibung der sw ... meine
# idee ist, dass in diesem how-to dann auch drinsteht, dass der anwender an einem
# platz (ueber einen weg) der sw bekannt gibt, wo der api-schluessel fuer die
# LLM-Nutzung liegt ... natuerlich wird der nicht in der sw persistiert ...
# natuerlich ist der pfad und die definierte stelle nicht fix"*.
#
# Der Kern: **die Software kennt den ORT, nicht den Schluessel.** Der Anwender
# sagt einmal, wo seiner liegt; gelesen wird zur Laufzeit, gespeichert nichts.


def test_der_schluessel_kann_aus_einer_datei_kommen(tmp_path, monkeypatch):
    """Der Weg fuer alle, die ihre Schluessel nicht in der Umgebung halten."""
    ablage = tmp_path / "meine-schluessel.json"
    ablage.write_text('{"api_key": "aus-der-datei"}', encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("MKN_LLM_SCHLUESSEL_DATEI", str(ablage))

    assert modelle.waehle(anbieter="anthropic", modell="x").schluessel() == "aus-der-datei"


def test_die_umgebung_hat_vorrang_vor_der_datei(tmp_path, monkeypatch):
    """Wer die Variable setzt, meint sie — sonst waere ein schneller Wechsel
    („einmal anders laufen lassen") nicht moeglich, ohne eine Datei anzufassen."""
    ablage = tmp_path / "s.json"
    ablage.write_text('{"api_key": "aus-der-datei"}', encoding="utf-8")
    monkeypatch.setenv("MKN_LLM_SCHLUESSEL_DATEI", str(ablage))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "aus-der-umgebung")

    assert modelle.waehle(anbieter="anthropic", modell="x").schluessel() == "aus-der-umgebung"


def test_die_datei_darf_je_anbieter_einen_eigenen_schluessel_tragen(tmp_path, monkeypatch):
    """Eine Datei fuer alle Anbieter — sonst braucht der Anwender je Anbieter
    eine eigene, und der Sinn der einen definierten Stelle ist dahin."""
    ablage = tmp_path / "s.json"
    ablage.write_text('{"anthropic": "a-schluessel", "gemini": "g-schluessel"}', encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("MKN_LLM_SCHLUESSEL_DATEI", str(ablage))

    assert modelle.waehle(anbieter="anthropic", modell="x").schluessel() == "a-schluessel"
    assert modelle.waehle(anbieter="gemini", modell="x").schluessel() == "g-schluessel"


def test_eine_fehlende_datei_sagt_wo_sie_gesucht_wurde(tmp_path, monkeypatch):
    """Ein "Schluessel fehlt" ohne den gesuchten Ort schickt den Anwender auf
    die Suche nach etwas, das er selbst konfiguriert hat."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("MKN_LLM_SCHLUESSEL_DATEI", str(tmp_path / "gibt-es-nicht.json"))

    with pytest.raises(modelle.KeinSchluessel) as fehler:
        modelle.waehle(anbieter="anthropic", modell="x").schluessel()

    assert "gibt-es-nicht.json" in str(fehler.value), (
        f"der gesuchte Ort fehlt in der Meldung: {fehler.value}"
    )


def test_ohne_jede_quelle_wird_die_umgebungsvariable_genannt(monkeypatch):
    """Untergrenze: wer gar nichts konfiguriert hat, braucht den einfachsten
    Weg genannt — nicht den, den er nicht kennt."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MKN_LLM_SCHLUESSEL_DATEI", raising=False)

    with pytest.raises(modelle.KeinSchluessel) as fehler:
        modelle.waehle(anbieter="anthropic", modell="x").schluessel()

    assert "ANTHROPIC_API_KEY" in str(fehler.value)


def test_der_schluessel_wird_nirgends_gespeichert(tmp_path, monkeypatch):
    """KT-1s 1.5, und es ist die wichtigste der Zusicherungen: die Software
    liest den Schluessel, sie behaelt ihn nicht.

    Geprueft an der Wahl selbst — sie ist eingefroren und traegt nur Anbieter
    und Modell. Ein Feld mehr waere ein Ort, an dem ein Schluessel liegen bleibt.
    """
    ablage = tmp_path / "s.json"
    ablage.write_text('{"api_key": "geheim-123"}', encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("MKN_LLM_SCHLUESSEL_DATEI", str(ablage))

    w = modelle.waehle(anbieter="anthropic", modell="x")
    w.schluessel()

    assert "geheim-123" not in repr(w), f"der Schluessel steckt in der Wahl: {w!r}"
    assert "geheim-123" not in str(vars(w)), "der Schluessel wurde als Feld abgelegt"


def test_der_ort_darf_auch_vom_aufrufer_kommen(tmp_path, monkeypatch) -> None:
    """Nicht jeder Anwender setzt Umgebungsvariablen.

    Bis 2026-08-30 war `MKN_LLM_SCHLUESSEL_DATEI` der einzige Weg, den Ort zu
    nennen. Damit haette die Konfigurationsdatei ein Feld `schluessel_datei`
    getragen, das NICHTS tut -- ein Feld, das Deckung behauptet und keine hat.
    Der Aufrufer darf den Ort deshalb direkt uebergeben; die Umgebung behaelt
    Vorrang, denn wer sie setzt, meint sie.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv(modelle.SCHLUESSEL_DATEI_VARIABLE, raising=False)
    datei = tmp_path / "keys.json"
    datei.write_text('{"anthropic": "sk-aus-der-konfig"}', encoding="utf-8")

    wahl = modelle.waehle("anthropic", "irgendeins")

    assert wahl.schluessel(ablage=datei) == "sk-aus-der-konfig"


def test_die_umgebung_schlaegt_den_uebergebenen_ort(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-aus-der-umgebung")
    datei = tmp_path / "keys.json"
    datei.write_text('{"anthropic": "sk-aus-der-konfig"}', encoding="utf-8")

    assert modelle.waehle("anthropic", "x").schluessel(ablage=datei) == "sk-aus-der-umgebung"
