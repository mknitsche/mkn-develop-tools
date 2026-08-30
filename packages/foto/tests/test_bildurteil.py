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


# ---------------------------------------------------------------------------
# Serienurteil (Design 2026-08-30 Stufe 3 § 4) -- die ZWEITE Frage: ist eine
# Kandidaten-Gruppe ein Panorama, eine Wiederholung oder gar keine Serie. Der
# Aufruf ERSETZT den Motiv-Aufruf der Gruppe, statt zu ihm hinzuzukommen (§ 7)
# -- deshalb traegt das Urteil dieselben Motiv-Felder wie `Urteil`.
#
# Regel A gilt unveraendert (nur `sicher` schreibt) -- mit einem Sonderfall:
# `serie == "keine"` vererbt NICHT, auch wenn das Modell sicher ist (die
# Mitglieder gehoeren nicht zusammen, ein Sammel-Motiv waere je Bild falsch).
# ---------------------------------------------------------------------------


def _antwort_roh(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


SERIE_PANORAMA = _antwort(
    {
        "serie": "panorama",
        "bilder": [1, 2, 3],
        "sicher": True,
        "motive": ["Kirche", "Turm"],
        "beschreibung": "Schwenk ueber die Kirche.",
        "belichtung": "gut",
    }
)


def test_ein_sicheres_serienurteil_liefert_serie_und_bilder():
    u = bildurteil.serie_aus_antwort(SERIE_PANORAMA)

    assert u.sicher is True
    assert u.serie == "panorama"
    assert u.bilder == (1, 2, 3)
    assert u.motive == ("Kirche", "Turm")


def test_serie_regel_a_unsicher_liefert_nichts_zum_schreiben():
    u = bildurteil.serie_aus_antwort(
        _antwort({"serie": "panorama", "bilder": [1, 2], "sicher": False, "motive": ["x"]})
    )

    assert u.zum_schreiben() == {}, f"unsicher schreibt trotzdem: {u.zum_schreiben()}"


def test_serie_keine_vererbt_auch_sicher_nichts():
    """Der Sonderfall aus Design § 4: die Mitglieder gehoeren nicht zusammen --
    ein Sammel-Motiv ueber eine Gehsequenz waere je Bild falsch."""
    u = bildurteil.serie_aus_antwort(
        _antwort(
            {
                "serie": "keine",
                "bilder": [1, 2, 3],
                "sicher": True,
                "motive": ["Wald", "Weg"],
                "beschreibung": "Spaziergang.",
            }
        )
    )

    assert u.sicher is True, "das Urteil selbst ist sicher -- nur die Vererbung entfaellt"
    assert u.zum_schreiben() == {}, f"'keine' vererbt trotzdem: {u.zum_schreiben()}"


def test_serie_wiederholung_sicher_vererbt_die_motive():
    u = bildurteil.serie_aus_antwort(
        _antwort(
            {
                "serie": "wiederholung",
                "bilder": [1, 2],
                "sicher": True,
                "motive": ["Portal"],
                "beschreibung": "Zwei Anlaeufe desselben Portals.",
                "belichtung": "gut",
            }
        )
    )

    d = u.zum_schreiben()
    assert d.get("motive") == ("Portal",)
    assert d.get("beschreibung")


def test_teilmengen_urteil_traegt_nur_die_genannten_nummern():
    """`bilder` = [2..5] von 6 -- Bild 1 und 6 fallen (an anderer Stelle, in
    `schreiben.py`) auf `std` zurueck. Hier wird nur geprueft, dass das URTEIL
    selbst die Teilmenge exakt traegt."""
    u = bildurteil.serie_aus_antwort(
        _antwort({"serie": "panorama", "bilder": [2, 3, 4, 5], "sicher": True, "motive": ["x"]})
    )

    assert u.bilder == (2, 3, 4, 5)
    assert 1 not in u.bilder
    assert 6 not in u.bilder


def test_serie_bilder_ignoriert_nicht_ganzzahlige_werte():
    """`bool` ist in Python ein `int` (`isinstance(True, int)` ist wahr) --
    ohne Schutz rutscht `true`/`false` unbemerkt als 1/0 durch."""
    u = bildurteil.serie_aus_antwort(
        _antwort({"serie": "panorama", "bilder": [1, True, "2", 3.5, 4], "sicher": True})
    )

    assert u.bilder == (1, 4), f"fremde Werte wurden nicht ausgefiltert: {u.bilder}"


def test_eine_kaputte_serienantwort_wirft_nicht_sondern_gilt_als_unsicher():
    u = bildurteil.serie_aus_antwort(_antwort_roh("kein json"))

    assert u.sicher is False
    assert u.zum_schreiben() == {}
    assert u.fehler, "der Grund muss erhalten bleiben"


def test_eine_leere_serienantwort_gilt_als_unsicher():
    """Auf `.fehler` pruefen, nicht nur auf `.sicher`: eine leere Antwort ergibt
    `d.get("serie") == ""`, und der SPAETERE Vokabular-Test wuerde `sicher`
    ebenfalls auf `False` ziehen -- ohne den fehler-Text bliebe der fruehe
    Kurzschluss fuer die leere Antwort ungeprueft (LP-40: eine Mutation, die
    nichts aendert, ist selbst ein Befund)."""
    u = bildurteil.serie_aus_antwort({})

    assert u.sicher is False
    assert "leer" in u.fehler.lower(), f"der Grund nennt nicht die leere Antwort: {u.fehler!r}"


def test_ein_serienurteil_ohne_json_objekt_gilt_als_unsicher():
    """Fremdformatig: eine JSON-Liste statt eines Objekts."""
    u = bildurteil.serie_aus_antwort(_antwort_roh("[1, 2, 3]"))

    assert u.sicher is False
    assert "Objekt" in u.fehler, f"der Grund nennt die Form nicht: {u.fehler!r}"


def test_ein_unbekannter_serie_wert_gilt_als_unsicher():
    """Fremdformatig: `serie` ausserhalb des Vokabulars. Regel A darf einem
    Wert nicht glauben, den sie nicht kennt -- auch wenn `sicher: true`
    danebensteht."""
    u = bildurteil.serie_aus_antwort(
        _antwort({"serie": "collage", "bilder": [1, 2], "sicher": True, "motive": ["x"]})
    )

    assert u.sicher is False, "ein unbekannter serie-Wert darf nicht als sicher gelten"
    assert u.zum_schreiben() == {}
    assert u.fehler


def test_der_serien_prompt_verlangt_serie_bilder_und_sicherheitsangabe():
    p = bildurteil.serien_prompt()

    for feld in ("serie", "bilder", "sicher", "motive", "beschreibung", "belichtung"):
        assert f'"{feld}"' in p, f"das Feld {feld} fehlt im Serien-Prompt:\n{p}"
    for wert in bildurteil.SERIE_WERTE:
        assert wert in p, f"der Wert {wert} fehlt im Serien-Prompt"
    assert "zweifel" in p.lower(), "der Prompt sagt nicht, was im Zweifel gilt"
    assert "json" in p.lower()


def test_der_serien_prompt_stellt_zwei_fragen_statt_einer():
    """Der Aufruf ERSETZT den Motiv-Aufruf der Gruppe, statt zu ihm
    hinzuzukommen -- daran haengt die Kostenrechnung des Designs (§ 7)."""
    p = bildurteil.serien_prompt()

    assert p != bildurteil.prompt()
    assert "kontaktbogen" in p.lower() or "nummeriert" in p.lower(), (
        "der Prompt sagt dem Modell nicht, dass es einen Kontaktbogen sieht"
    )


def test_serie_geminis_antwortform_wird_gelesen():
    """`_text` wird wiederverwendet, nicht nachgebaut -- die Gemini-Form fehlte
    dort einmal genau an dieser Stelle und sah wie eine ehrliche
    'unsicher'-Antwort aus."""
    antwort = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": (
                                '{"serie": "panorama", "bilder": [1, 2], '
                                '"sicher": true, "motive": ["Berg"]}'
                            )
                        }
                    ]
                }
            }
        ]
    }

    u = bildurteil.serie_aus_antwort(antwort)

    assert u.sicher is True
    assert u.serie == "panorama"
    assert u.bilder == (1, 2)
