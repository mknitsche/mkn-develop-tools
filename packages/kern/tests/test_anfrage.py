"""Der Sender — und warum er einen injizierbaren Transport hat.

**Kein Test dieses Repos braucht Netz oder einen Schluessel.** Ein Test, der
gegen einen echten Anbieter laeuft, kostet Geld, ist von fremder Verfuegbarkeit
abhaengig und beweist am Ende die Verfuegbarkeit statt den Code. Der Transport
ist deshalb ein Parameter; die Tests reichen aufgezeichnete Antworten hinein.

**Was hier laut sein muss:** eine Zeitueberschreitung, ein Fehlerstatus und eine
Antwort, die kein JSON ist. Alle drei enden sonst als stiller Teilerfolg — und
ein stiller Teilerfolg in einer Kette ueber 1.293 Aufnahmen ist teurer als ein
Abbruch, weil er erst am Ergebnis auffaellt.
"""

from __future__ import annotations

import json

import pytest

from mkn_kern import anfrage


def test_die_antwort_kommt_als_geparstes_json_zurueck():
    def transport(url, koerper, kopf, zeitgrenze):
        return 200, json.dumps({"content": [{"text": "Sonnenuntergang"}]}).encode()

    ergebnis = anfrage.sende("https://beispiel.invalid/v1", {"model": "x"}, {}, transport=transport)

    assert ergebnis == {"content": [{"text": "Sonnenuntergang"}]}


def test_ein_fehlerstatus_bricht_laut_ab():
    """Nicht `None` zurueckgeben: ein Aufrufer, der das nicht prueft, schreibt
    dann eine leere Antwort in die Datei."""

    def transport(url, koerper, kopf, zeitgrenze):
        return 429, b'{"error":{"message":"rate limit"}}'

    with pytest.raises(anfrage.AnfrageFehler) as fehler:
        anfrage.sende("https://beispiel.invalid/v1", {}, {}, transport=transport)

    assert "429" in str(fehler.value)
    assert "rate limit" in str(fehler.value), (
        f"die Meldung des Anbieters fehlt — dann sucht man im Blinden: {fehler.value}"
    )


def test_eine_zeitueberschreitung_bricht_laut_ab():
    """Ohne Zeitgrenze haengt ein Lauf ueber 1.293 Aufnahmen an einem einzigen
    Bild fuer immer."""

    def transport(url, koerper, kopf, zeitgrenze):
        raise TimeoutError("zu langsam")

    with pytest.raises(anfrage.AnfrageFehler) as fehler:
        anfrage.sende("https://beispiel.invalid/v1", {}, {}, transport=transport)

    assert "zeit" in str(fehler.value).lower()


def test_eine_antwort_die_kein_json_ist_bricht_laut_ab():
    """Ein HTML-Fehlerseiten-Body mit Status 200 kommt in der Praxis vor
    (Zwischen-Server, Anmeldeseite). Wer ihn stillschweigend verwirft, sieht
    einen leeren Lauf und keinen Grund."""

    def transport(url, koerper, kopf, zeitgrenze):
        return 200, b"<html>Bitte anmelden</html>"

    with pytest.raises(anfrage.AnfrageFehler) as fehler:
        anfrage.sende("https://beispiel.invalid/v1", {}, {}, transport=transport)

    assert "json" in str(fehler.value).lower()


def test_die_zeitgrenze_wird_an_den_transport_durchgereicht():
    """Untergrenze: ohne diese Zusicherung koennte die Grenze gesetzt und nie
    verwendet werden — der Test darueber bliebe trotzdem gruen, weil er die
    Ausnahme selbst wirft."""
    gesehen = {}

    def transport(url, koerper, kopf, zeitgrenze):
        gesehen["zeit"] = zeitgrenze
        return 200, b"{}"

    anfrage.sende("https://beispiel.invalid/v1", {}, {}, zeitgrenze=42.0, transport=transport)

    assert gesehen["zeit"] == 42.0


def test_der_koerper_geht_als_json_hinaus():
    """Untergrenze zur ersten Zusicherung: sie prueft nur den Rueckweg."""
    gesehen = {}

    def transport(url, koerper, kopf, zeitgrenze):
        gesehen["koerper"] = koerper
        gesehen["kopf"] = kopf
        return 200, b"{}"

    anfrage.sende(
        "https://beispiel.invalid/v1",
        {"model": "opus", "messages": []},
        {"x-api-key": "geheim"},
        transport=transport,
    )

    assert json.loads(gesehen["koerper"]) == {"model": "opus", "messages": []}
    assert gesehen["kopf"]["x-api-key"] == "geheim"
    assert gesehen["kopf"]["content-type"] == "application/json"
