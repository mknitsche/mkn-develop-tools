"""Das Urteil des Modells — und die Regel, die es zaehmt.

Spec § 10a, Regel A (KT-1-Entscheid 2026-08-29): **nur was das Modell `sicher`
nennt, wird geschrieben.** Die Herleitung steht in § 4 Stufe 3 und ist gemessen:
Sonnet lag bei 15/20 und war einmal falsch UND selbstsicher, Opus bei 17/20 mit
14/14 Praezision auf seiner eigenen Sicherheitsangabe. Ein Modell, dessen
Selbsteinschaetzung traegt, darf man ihr glauben — aber nur ihr.

Alles `unsicher` geht ins Protokoll, nicht in die Datei. Das ist dieselbe Regel
wie beim Ort: im Zweifel nicht schreiben, sondern vorlegen.

Alle Tests laufen offline mit aufgezeichneten Antworten.
"""

from __future__ import annotations

import json

import pytest
from mkn_foto import bildurteil


#: Eine echte Antwortform, wie das Modell sie liefert.
def _antwort(nutzlast: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(nutzlast)}]}


SICHER = _antwort(
    {
        "sicher": True,
        "motive": ["Sonnenuntergang", "Bergkette", "Wolken"],
        "beschreibung": "Sonnenuntergang ueber einer Bergkette mit Wolkenband.",
        "belichtung": "gut",
    }
)

UNSICHER = _antwort(
    {
        "sicher": False,
        "motive": ["vielleicht Wald"],
        "beschreibung": "Sehr dunkel, schwer zu erkennen.",
        "belichtung": "unklar",
    }
)


def test_ein_sicheres_urteil_liefert_motive_und_beschreibung():
    u = bildurteil.aus_antwort(SICHER)

    assert u.sicher is True
    assert u.motive == ("Sonnenuntergang", "Bergkette", "Wolken")
    assert u.beschreibung.startswith("Sonnenuntergang ueber")


def test_ein_unsicheres_urteil_gibt_nichts_zum_schreiben_her():
    """Regel A. Der Text bleibt fuer das Protokoll erhalten — geschrieben wird er
    nicht."""
    u = bildurteil.aus_antwort(UNSICHER)

    assert u.sicher is False
    assert u.zum_schreiben() == {}, (
        f"ein unsicheres Urteil liefert Schreibdaten: {u.zum_schreiben()}"
    )
    assert u.motive, "der Inhalt muss fuer das Protokoll erhalten bleiben"


def test_ein_sicheres_urteil_liefert_sehr_wohl_schreibdaten():
    """Untergrenze: sonst waere ein `zum_schreiben`, das immer leer ist, genauso
    gruen — und nichts kaeme je in eine Datei."""
    u = bildurteil.aus_antwort(SICHER)

    d = u.zum_schreiben()
    assert d.get("motive"), f"nichts zu schreiben trotz sicher: {d}"
    assert d.get("beschreibung")


def test_eine_kaputte_antwort_wirft_nicht_sondern_gilt_als_unsicher():
    """Ein einzelnes Bild darf den Lauf ueber 1.293 Aufnahmen nicht abreissen.
    Aber es darf auch nichts schreiben."""
    u = bildurteil.aus_antwort({"content": [{"type": "text", "text": "kein json"}]})

    assert u.sicher is False
    assert u.zum_schreiben() == {}
    assert u.fehler, "der Grund muss erhalten bleiben, sonst sucht man im Blinden"


def test_eine_leere_antwort_gilt_als_unsicher():
    assert bildurteil.aus_antwort({}).sicher is False


def test_der_prompt_verlangt_die_sicherheitsangabe():
    """Ohne sie kann Regel A nicht greifen — und das Modell antwortet dann in
    einer Form, die der Parser nicht kennt."""
    p = bildurteil.prompt()

    # Auf den FELDNAMEN in Anfuehrungszeichen pruefen, nicht auf das Wort:
    # "sicher" steht im Prompt mehrfach im Fliesstext ("sicher bist", "unsichere
    # Angabe"), und die erste Testfassung blieb deshalb gruen, als die
    # Feldzeile ersetzt wurde. Ein Beweis muss seinen Gegenstand enthalten.
    assert '"sicher"' in p, f"das Feld sicher wird nicht verlangt:\n{p}"
    assert "json" in p.lower()
    for feld in ("motive", "beschreibung", "belichtung"):
        assert f'"{feld}"' in p, f"das Feld {feld} fehlt im Prompt"
    # Und die Regel dahinter muss dastehen, sonst raet das Modell mit.
    assert "zweifel" in p.lower(), (
        "der Prompt sagt nicht, was im Zweifel gilt — dann setzt das Modell "
        "sicher=true aus Hoeflichkeit"
    )


def test_die_belichtungsangabe_kommt_durch():
    """KT-1 am 2026-08-30: "bilder die offensichtlich falsch belichtet sind ...
    oder ein llm sagt, das bild ist gruselig, dann gehoert es auch
    gekennzeichnet"."""
    schlecht = _antwort(
        {
            "sicher": True,
            "motive": ["Wald"],
            "beschreibung": "Stark unterbelichtet, kaum Zeichnung.",
            "belichtung": "unterbelichtet",
        }
    )

    u = bildurteil.aus_antwort(schlecht)

    assert u.belichtung == "unterbelichtet"
    assert u.zum_schreiben().get("belichtung") == "unterbelichtet"


@pytest.mark.parametrize("wert", ["gut", "unterbelichtet", "ueberbelichtet", "unklar"])
def test_alle_belichtungswerte_werden_angenommen(wert):
    u = bildurteil.aus_antwort(
        _antwort(
            {
                "sicher": True,
                "motive": ["x"],
                "beschreibung": "y",
                "belichtung": wert,
            }
        )
    )
    assert u.belichtung == wert


def test_ein_fremder_belichtungswert_wird_zu_unklar():
    """Untergrenze zur Werteliste: der Test darueber prueft nur GUELTIGE Werte
    und bliebe gruen, wenn die Pruefung ganz entfiele.

    Ein Modell, das "katastrophal" oder "ok" antwortet, darf diesen Wert nicht in
    ein Stichwort schreiben — das Vokabular waere dann offen, und Filtern nach
    Fehlbelichtung fiele auseinander.
    """
    u = bildurteil.aus_antwort(
        _antwort(
            {
                "sicher": True,
                "motive": ["x"],
                "beschreibung": "y",
                "belichtung": "katastrophal",
            }
        )
    )

    assert u.belichtung == "unklar", f"ein fremder Wert kam durch: {u.belichtung!r}"


def test_geminis_antwortform_wird_gelesen() -> None:
    """Der Anbieter, der die Schnittstelle ehrlich prueft.

    **Firsthand, 2026-08-30.** Der Gemini-Lauf gegen die echte API meldete
    `sicher=False` und KEINE Motive -- das Modell hatte in Wahrheit vier
    genannt und das Bild korrekt als unterbelichtet beschrieben. Gelesen wurde
    nichts davon: `_text` kannte `content`, `choices` und `message`, aber nicht
    Googles `candidates`.

    Das sieht nach einer ehrlichen "unsicher"-Antwort aus und ist in Wahrheit
    Blindheit. Genau das meinte KT-1 mit dem zweiten Anbieter: was nur bei EINEM
    laeuft, hat die Schnittstelle nicht verstanden, sondern eine Eigenheit.
    """
    antwort = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": '{"sicher": true, "motive": ["Wald"], "belichtung": "gut"}'}
                    ],
                    "role": "model",
                }
            }
        ],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
    }

    urteil = bildurteil.aus_antwort(antwort)

    assert urteil.sicher is True
    assert urteil.motive == ("Wald",)


def test_ein_denkblock_verdeckt_die_antwort_nicht() -> None:
    """Opus 5 liefert `thinking` UND `text`. Wer blind den ersten Block nimmt,
    liest die Signatur des Denkens statt der Antwort -- und haelt eine
    einwandfreie Auskunft fuer unlesbar."""
    antwort = {
        "content": [
            {"type": "thinking", "thinking": "", "signature": "CAIS..."},
            {"type": "text", "text": '{"sicher": true, "motive": ["Berg"]}'},
        ]
    }

    assert bildurteil.aus_antwort(antwort).motive == ("Berg",)
