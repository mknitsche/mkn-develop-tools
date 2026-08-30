"""Die Antworten des Menschen werden GELESEN, nicht abgetippt.

**Der Anlass, woertlich (KT-1, 2026-08-30):** *"dann wurden auch meine antworten
nicht intelligent interpretiert, sondern 1:1 uebernommen - da steht dann kein
ort - obwohl genannt war 'gehoert zu granau' oder 'zu vorordner' usw ... das ist
doch bloedsinn"* und *"ich hatte einfach in die datei unten reingeschrieben -
fertig ... mey, kann doch nicht so schwer sein!!!"*.

Er hat recht, und der Beleg ist eine Zahl: von seinen 20 Notizen erkannte die
Wortsuche (`footprint`, `findpinguin`) **neun**. Die elf verworfenen enthielten
"Schon Zugspitze ganz oben", "zu Hause", "also Stubaier G", "vorheriger Ordner"
und "ist schwarz - falsch belichtet" -- lauter verwertbare Aussagen, weggeworfen
wegen eines fehlenden Stichworts.

Eine Wortsuche kann "gehoert zu Grainau" nicht von "auf der Rueckfahrt VON
Grainau" unterscheiden. Ein Leser kann es. Deshalb liest hier ein Modell.

**Die Faelle unten sind KT-1s echte Notizen**, nicht ausgedachte. Ein Test aus
erfundenen Saetzen beweist ueber diese Aufgabe nichts.
"""

from __future__ import annotations

import json

from mkn_foto import notizurteil

# --- KT-1s echte Antworten, gekuerzt auf das Wesentliche --------------------

ORT_KLAR = "Tag 1 - erster spot - Montag, 24. August 2026 um 07:23 / Lenggries im findpinguines"
ORT_OHNE_STICHWORT = "Schon Zugspitze ganz oben ... erste Bilder"
BEZUG = "Gehört ebenfalls dazu - vorheriger Ordner"
VERMUTUNG = "Blick auf die Zugspitze / von Grainau unten Eibsee denke ich"
KEIN_ORT = "Das war ganz spontan ... irgendwo im nirgendwo ... da habe ich auch kein handy bild"
BELICHTUNG = "Ok - keine Ahnung - ist schwarz - falsch belichtet"
ZEIT = "Hier scheint mir die Uhrzeit nicht zu stimmen / ist eigentlich die letzte location am 24."


def _antwort(nutzlast: dict) -> object:
    """Ein Transport, der genau EINE Modellantwort liefert."""

    def transport(url, koerper, kopf, zeitgrenze=120.0):
        return {
            "content": [{"text": json.dumps(nutzlast)}],
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }

    return transport


def test_ein_ort_ohne_stichwort_wird_trotzdem_erkannt() -> None:
    """ "Schon Zugspitze ganz oben" -- die Wortsuche warf das weg."""
    urteil = notizurteil.aus_antwort(
        json.dumps({"ort": "Zugspitze", "art": "zuordnung", "sicher": True})
    )

    assert urteil.ort == "Zugspitze"
    assert urteil.sicher is True
    assert urteil.zum_schreiben()["ort"] == "Zugspitze"


def test_ein_bezug_auf_den_vorherigen_ordner_wird_verstanden() -> None:
    """ "Gehoert ebenfalls dazu - vorheriger Ordner" ist eine vollstaendige
    Auskunft: derselbe Ort wie die Session davor."""
    urteil = notizurteil.aus_antwort(
        json.dumps({"art": "bezug", "bezug": "vorheriger", "sicher": True})
    )

    assert urteil.art == "bezug"
    assert urteil.bezug == "vorheriger"


def test_eine_vermutung_wird_nicht_geschrieben_sondern_vorgelegt() -> None:
    """ "von Grainau unten Eibsee DENKE ICH" -- Regel A: nur Sicheres wird
    geschrieben. Das Gegenteil ist das Erfinden, das die oberste Regel verbietet."""
    urteil = notizurteil.aus_antwort(
        json.dumps({"ort": "Grainau", "art": "vermutung", "sicher": False})
    )

    assert urteil.zum_schreiben() == {}
    assert urteil.ort == "Grainau", "die Vermutung bleibt erhalten -- fuers Protokoll"


def test_kein_ort_bleibt_kein_ort() -> None:
    """ "irgendwo im nirgendwo" ist eine ehrliche Antwort ohne Ort. Sie darf
    keine Koordinate erfinden."""
    urteil = notizurteil.aus_antwort(json.dumps({"art": "kein_ort", "sicher": True}))

    assert urteil.ort == ""
    assert urteil.zum_schreiben().get("ort", "") == ""


def test_eine_belichtungsaussage_wird_uebernommen() -> None:
    """ "ist schwarz - falsch belichtet" ist genau die Kennzeichnung, die KT-1
    verlangt hat -- und die Wortsuche warf sie weg."""
    urteil = notizurteil.aus_antwort(
        json.dumps({"art": "kein_ort", "belichtung": "unterbelichtet", "sicher": True})
    )

    assert urteil.belichtung == "unterbelichtet"


def test_ein_kaputtes_urteil_reisst_nichts_ab() -> None:
    """Bei 20 Notizen ist eine unlesbare Antwort normal. Sie gilt als unsicher
    und traegt ihren Grund mit."""
    urteil = notizurteil.aus_antwort("kein json")

    assert urteil.sicher is False
    assert urteil.fehler


def test_der_prompt_nennt_die_regel_und_den_kontext() -> None:
    """Ohne die Nachbarsessions kann "vorheriger Ordner" nicht aufgeloest
    werden -- das Modell muss wissen, welche es sind."""
    text = notizurteil.prompt(
        ORT_KLAR, ordner="2026-08-24_0619-0716", nachbarn=("2026-08-23_1316-1316",)
    )

    assert "2026-08-23_1316-1316" in text
    assert ORT_KLAR in text
    assert "sicher" in text


def test_ein_denkblock_verdeckt_die_antwort_nicht() -> None:
    """**Der Fehler, der die ganze erste Fassung wertlos machte.**

    Opus 5 antwortet in ZWEI Bloecken: `thinking` (mit Signatur, ohne Text) und
    `text`. Die erste Fassung nahm blind `content[0]` -- also die Signatur des
    Denkens -- und hielt jede Antwort fuer unlesbar. Ergebnis: alle 20 Notizen
    galten als unsicher, obwohl das Modell "Lenggries" sauber als Zuordnung
    erkannt hatte.

    Das ist derselbe Fehler wie bei Geminis `candidates`: eine Antwortform, die
    nicht gelesen wird, sieht aus wie eine ehrliche "weiss nicht"-Antwort.
    """
    antwort = {
        "content": [
            {"type": "thinking", "thinking": "", "signature": "CAIS..."},
            {"type": "text", "text": '{"art": "zuordnung", "ort": "Lenggries", "sicher": true}'},
        ]
    }

    urteil = notizurteil.aus_antwort(antwort)

    assert urteil.ort == "Lenggries"
    assert urteil.sicher is True


def test_auch_geminis_form_wird_gelesen() -> None:
    antwort = {
        "candidates": [
            {"content": {"parts": [{"text": '{"art": "zuordnung", "ort": "X", "sicher": true}'}]}}
        ]
    }

    assert notizurteil.aus_antwort(antwort).ort == "X"


def test_der_prompt_verbietet_erfundene_adressen() -> None:
    """**Firsthand beobachtet, 2026-08-30.** Auf "zu Hause - Probebilder"
    antwortete das Modell mit einer vollstaendigen Strassenadresse samt
    Hausnummer und Postleitzahl. Sie stand in keiner Notiz -- das Modell hat
    sie erfunden.

    Geschrieben wurde sie nicht (Regel A: `sicher` war false), aber darauf darf
    man sich nicht verlassen: eine erfundene Privatadresse gehoert nicht einmal
    ins Protokoll. Der Prompt sagt es deshalb ausdruecklich.
    """
    text = notizurteil.prompt("zu Hause - Probebilder", ordner="x", nachbarn=())

    assert "ERFINDE NIEMALS eine Adresse" in text
    assert "zu Hause" in text


def test_ein_zuhause_ist_kein_kartenort() -> None:
    urteil = notizurteil.aus_antwort(json.dumps({"art": "verwerfen", "ort": "", "sicher": True}))

    assert urteil.zum_schreiben() == {}
