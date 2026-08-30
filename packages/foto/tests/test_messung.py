"""Was ein Lauf ueber 969 Aufrufe hinterlassen muss, damit man ihn auswerten kann.

KT-1 vor dem Start, 2026-08-30: *"hast du eine umfangreiche, stabile
observibility ... nicht dass wir durchlaufen und uns dann messwerte token pro
aktion, pro bild usw fehlen?"*

Die ehrliche Antwort war nein: es gab einen Zaehler und eine Fehlerliste. Nach
dem Lauf haette man gewusst, DASS es 969 Aufrufe waren — nicht, wo die Kosten
herkamen, welches Bild teuer war, wie lange etwas dauerte.

Dabei liefert die API die Zahlen frei Haus: jede Antwort traegt `usage` mit
Eingabe- und Ausgabe-Tokens. Sie wegzuwerfen und hinterher zu schaetzen waere
die teuerste Art, an Daten zu kommen, die man schon hatte.

**Eine Messung, die im Fehlerfall fehlt, ist keine.** Gerade der abgebrochene
Aufruf ist der interessante — er hat Zeit gekostet und vielleicht Tokens.
"""

from __future__ import annotations

from mkn_foto import messung


def test_tokens_kommen_aus_der_antwort():
    """Nicht schaetzen, was dasteht."""
    m = messung.Messwert.aus_antwort(
        "bild.jpg", {"usage": {"input_tokens": 2184, "output_tokens": 187}}, dauer_s=3.2
    )

    assert m.tokens_ein == 2184
    assert m.tokens_aus == 187
    assert m.dauer_s == 3.2


def test_die_openai_form_wird_auch_gelesen():
    """Gemini und Moonshot nennen es anders. Wer nur eine Form kennt, misst bei
    zwei von drei Anbietern nichts — und meldet dabei null Tokens statt
    'nicht gemessen'."""
    m = messung.Messwert.aus_antwort(
        "b.jpg", {"usageMetadata": {"promptTokenCount": 900, "candidatesTokenCount": 120}}
    )

    assert m.tokens_ein == 900
    assert m.tokens_aus == 120


def test_eine_antwort_ohne_usage_meldet_nicht_gemessen():
    """Untergrenze: 0 Tokens und 'nicht gemessen' sind zwei verschiedene
    Aussagen. Wer sie zusammenwirft, rechnet eine Summe aus, die zu klein ist,
    und merkt es nicht."""
    m = messung.Messwert.aus_antwort("b.jpg", {"content": []})

    assert m.tokens_ein is None
    assert not m.gemessen


def test_die_kosten_werden_aus_den_tokens_gerechnet():
    m = messung.Messwert("b.jpg", tokens_ein=1_000_000, tokens_aus=0, dauer_s=1.0)

    assert m.kosten_eur(preis_ein=4.63, preis_aus=23.15) == 4.63


def test_ein_lauf_summiert_und_nennt_die_ausreisser():
    """Der Mittelwert allein sagt nichts: bei 969 Aufrufen ist die Frage, WELCHE
    teuer waren — sonst sucht man beim naechsten Mal wieder im Ganzen."""
    p = messung.Protokoll()
    p.nimm(messung.Messwert("klein.jpg", tokens_ein=2000, tokens_aus=150, dauer_s=2.0))
    p.nimm(messung.Messwert("gross.jpg", tokens_ein=40000, tokens_aus=200, dauer_s=9.0))
    p.nimm(messung.Messwert("mittel.jpg", tokens_ein=2200, tokens_aus=160, dauer_s=2.5))

    assert p.tokens_ein == 44200
    assert p.aufrufe == 3
    teuerste = p.teuerste(1)
    assert teuerste[0].name == "gross.jpg", f"der Ausreisser fehlt: {teuerste}"


def test_ein_gescheiterter_aufruf_wird_mitgezaehlt():
    """Gerade der abgebrochene Aufruf ist der interessante: er hat Zeit gekostet
    und vielleicht Tokens. Wer nur die gelungenen misst, sieht einen Lauf, der
    schneller und billiger war, als er wirklich war."""
    p = messung.Protokoll()
    p.nimm(messung.Messwert("gut.jpg", tokens_ein=2000, tokens_aus=100, dauer_s=2.0))
    p.nimm(messung.Messwert("kaputt.jpg", dauer_s=120.0, fehler="Zeitueberschreitung"))

    assert p.aufrufe == 2
    assert p.gescheitert == 1
    assert p.dauer_s == 122.0, f"die Zeit des Fehlschlags fehlt: {p.dauer_s}"


def test_der_vergleich_gegen_die_schaetzung_steht_im_protokoll():
    """Der eigentliche Zweck dieses Laufs (KT-1s Billing-Test): stimmte die
    Vorhersage? Ohne den Vergleich im Protokoll muss man ihn von Hand
    nachrechnen — und dann tut es niemand."""
    p = messung.Protokoll(geschaetzt_eur=16.25)
    p.nimm(messung.Messwert("a.jpg", tokens_ein=1_000_000, tokens_aus=0, dauer_s=1.0))

    bericht = p.zusammenfassung(preis_ein=4.63, preis_aus=23.15)

    assert "16,25" in bericht or "16.25" in bericht, f"die Schaetzung fehlt:\n{bericht}"
    assert "4,63" in bericht or "4.63" in bericht, f"der Istwert fehlt:\n{bericht}"


def test_die_zusammenfassung_trennt_serien_von_einzelbildern():
    """Sie kosten verschieden viel, und der Unterschied ist der Grund fuer den
    Kontaktbogen. Ohne die Trennung laesst sich nicht pruefen, ob er sich
    gelohnt hat."""
    p = messung.Protokoll()
    p.nimm(messung.Messwert("s.jpg", tokens_ein=4371, tokens_aus=200, dauer_s=5.0, art="serie"))
    p.nimm(messung.Messwert("e.jpg", tokens_ein=2184, tokens_aus=150, dauer_s=3.0, art="einzel"))

    bericht = p.zusammenfassung(preis_ein=4.63, preis_aus=23.15)

    assert "serie" in bericht.lower()
    assert "einzel" in bericht.lower()
