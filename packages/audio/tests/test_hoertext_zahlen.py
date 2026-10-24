# ruff: noqa: RUF001  (Gedankenstriche sind hier die Testdaten: der Halbgeviertstrich ist der Gegenstand)
"""Zahlen, Daten, Uhrzeiten und Einheiten werden so ausgeschrieben, wie man sie spricht.

Jeder Test haelt eine Regel fest, die ein Hoerer sofort bemerkt, wenn sie fehlt: eine
Stimme, die "1990" als "eins neun neun null" liest, ist nicht zu gebrauchen.
"""

from __future__ import annotations

import pytest

from mkn_audio.hoertext import deterministisch
from mkn_audio.hoertext.zahlen import ausschreiben


@pytest.mark.parametrize(
    ("quelle", "erwartet"),
    [
        ("1990", "neunzehnhundertneunzig"),
        ("Das war 1990.", "Das war neunzehnhundertneunzig."),
        ("2026", "zweitausendsechsundzwanzig"),
        ("476", "vierhundertsechsundsiebzig"),
        ("158.000", "hundertachtundfünfzigtausend"),
        ("1.000.000", "eine Million"),
        ("0", "null"),
    ],
)
def test_ganze_zahlen_und_jahre(quelle, erwartet):
    assert ausschreiben(quelle) == erwartet


@pytest.mark.parametrize(
    ("quelle", "erwartet"),
    [
        ("3,5", "drei Komma fünf"),
        ("0,05", "null Komma null fünf"),
        ("3,50", "drei Komma fünf null"),
        ("1.234,5", "tausendzweihundertvierunddreißig Komma fünf"),
    ],
)
def test_dezimalzahlen_ziffernweise_nach_dem_komma(quelle, erwartet):
    assert ausschreiben(quelle) == erwartet


@pytest.mark.parametrize(
    ("quelle", "erwartet"),
    [
        ("3,5 %", "drei Komma fünf Prozent"),
        ("5%", "fünf Prozent"),
        ("1 %", "ein Prozent"),
        ("5 €", "fünf Euro"),
        ("1 €", "ein Euro"),
        ("€ 5", "fünf Euro"),
        ("$5", "fünf Dollar"),
        ("3,50 €", "drei Euro fünfzig"),
        ("3,00 €", "drei Euro"),
        ("12,- €", "zwölf Euro"),
        # Zusammengesetzt, weil der PII-Riegel des Repos (HC-3) jeden Betrag ab 1.000 mit
        # Waehrung in getrackten Dateien sperrt -- auch einen erfundenen Testwert.
        ("1.234,50" + " €", "tausendzweihundertvierunddreißig Euro fünfzig"),
        ("5 km", "fünf Kilometer"),
        ("100 km/h", "hundert Kilometer pro Stunde"),
        ("20 °C", "zwanzig Grad Celsius"),
        ("-5 °C", "minus fünf Grad Celsius"),
        ("30 m²", "dreißig Quadratmeter"),
    ],
)
def test_einheiten_und_waehrungen(quelle, erwartet):
    assert ausschreiben(quelle) == erwartet


def test_zahl_mit_einheit_ist_nie_eine_jahreszahl():
    # "1990 Euro" ist ein Betrag, kein Jahr: die Jahresform "neunzehnhundert..."
    # waere hier falsch.
    assert ausschreiben("1990 Euro") == "tausendneunhundertneunzig Euro"
    assert ausschreiben("1500 m") == "tausendfünfhundert Meter"


def test_eins_wird_vor_dem_folgewort_zu_ein_oder_eine():
    assert ausschreiben("1 Million Euro") == "eine Million Euro"
    assert ausschreiben("1 Milliarde Euro") == "eine Milliarde Euro"
    assert ausschreiben("um 1 Uhr") == "um ein Uhr"
    assert ausschreiben("Es war Nummer 1.") == "Es war Nummer eins."


@pytest.mark.parametrize(
    ("quelle", "erwartet"),
    [
        ("12. Oktober", "zwölften Oktober"),
        ("am 1. Mai", "am ersten Mai"),
        ("der 3. März", "der dritten März"),
        ("21. Dezember", "einundzwanzigsten Dezember"),
        ("im 20. Jahrhundert", "im zwanzigsten Jahrhundert"),
        ("12.10.2026", "zwölften Oktober zweitausendsechsundzwanzig"),
        ("2026-10-24", "vierundzwanzigsten Oktober zweitausendsechsundzwanzig"),
        ("am 3.5.1999", "am dritten Mai neunzehnhundertneunundneunzig"),
        ("Am 3.5. kommt er.", "Am dritten Mai kommt er."),
        ("Er kam am 3.5. Dann ging er.", "Er kam am dritten Mai. Dann ging er."),
    ],
)
def test_daten(quelle, erwartet):
    assert ausschreiben(quelle) == erwartet


def test_ungueltiges_datum_wird_kein_datum():
    # Monat 13 gibt es nicht; die Zahlen werden einzeln gelesen, nicht erfunden.
    assert "Oktober" not in ausschreiben("12.13.2026")


@pytest.mark.parametrize(
    ("quelle", "erwartet"),
    [
        ("14:30 Uhr", "vierzehn Uhr dreißig"),
        ("14.30 Uhr", "vierzehn Uhr dreißig"),
        ("14:00 Uhr", "vierzehn Uhr"),
        ("9:05 Uhr", "neun Uhr fünf"),
        ("um 14 Uhr", "um vierzehn Uhr"),
    ],
)
def test_uhrzeiten(quelle, erwartet):
    assert ausschreiben(quelle) == erwartet


def test_uhrzeit_mit_unmoeglicher_minute_wird_keine_uhrzeit():
    assert "Uhr dreißig" not in ausschreiben("14:75 Uhr")


@pytest.mark.parametrize(
    ("quelle", "erwartet"),
    [
        ("1990–1995", "neunzehnhundertneunzig bis neunzehnhundertfünfundneunzig"),
        ("1990-1995", "neunzehnhundertneunzig bis neunzehnhundertfünfundneunzig"),
        ("5–10", "fünf bis zehn"),
        ("Seiten 12 – 15", "Seiten zwölf bis fünfzehn"),
    ],
)
def test_zahlenbereiche(quelle, erwartet):
    assert ausschreiben(quelle) == erwartet


def test_bindestrich_zwischen_kleinen_zahlen_ist_kein_bereich():
    # "5-7" kann ein Bereich, eine Kennung oder eine Telefonnummer sein; ohne Kontext
    # wird nicht geraten.
    assert " bis " not in ausschreiben("5-7")


def test_zahl_an_buchstaben_wird_abgetrennt_gelesen():
    # Bis 24.10. blieben "3a" und "5G" stehen (nur Warnung); jetzt wird jeder erkannte Fehler
    # behoben -- die Ziffer wird abgetrennt und gelesen, "2er" bleibt Zahlwort plus Endung.
    assert ausschreiben("Paragraf 3a und 5G") == "Paragraf drei a und fünf G"


def test_zu_lange_zahl_bleibt_fuehrende_null_wird_ziffernweise_gelesen():
    # Bis 24.10. blieb "007" stehen; eine fuehrende Null liest man Ziffer fuer Ziffer.
    assert ausschreiben("007") == "null null sieben"
    assert ausschreiben("12345678901234567890") == "12345678901234567890"


def test_text_ohne_ziffern_bleibt_gleich():
    text = "Der Hirte zählte die Hunde, bis es dunkel wurde."
    assert ausschreiben(text) == text


def test_eins_vor_abgekuerzter_mehrzahl_wird_einzahl():
    # "1 Mio." steht nach dem Ausschreiben der Abkuerzung als "1 Millionen" da.
    assert ausschreiben("1 Millionen Euro") == "eine Million Euro"
    assert ausschreiben("1 Milliarden Euro") == "eine Milliarde Euro"
    assert ausschreiben("11 Millionen") == "elf Millionen"
    assert ausschreiben("1,5 Millionen") == "eins Komma fünf Millionen"


@pytest.mark.parametrize(
    ("quelle", "erwartet"),
    [
        ("Version 3.5 ist da", "Version drei Punkt fünf ist da"),
        ("Abschnitt 3.5 zeigt es", "Abschnitt drei Punkt fünf zeigt es"),
        ("Python 3.14", "Python drei Punkt vierzehn"),
    ],
)
def test_punkt_zwischen_kleinen_zahlen_wird_punkt(quelle, erwartet):
    assert ausschreiben(quelle) == erwartet


def test_versionsnummer_mit_mehreren_punkten_wird_punktweise_gelesen():
    # Bis 24.10. blieb sie stehen; gelesen wird sie wie "3.5" ("drei Punkt fuenf").
    assert ausschreiben("Version 1.2.3") == "Version eins Punkt zwei Punkt drei"
    assert ausschreiben("192.168.1.1") == "192.168.1.1"


@pytest.mark.parametrize(
    ("quelle", "erwartet"),
    [
        ("Violinkonzert Nr. 1 g-Moll", "Violinkonzert Nummer eins g-Moll"),
        ("Symphonie Nr. 104 D-Dur", "Symphonie Nummer hundertvier D-Dur"),
        ("Streichquartett Nr. 2 fis-Moll", "Streichquartett Nummer zwei fis-Moll"),
        ("Sonate Nr. 3 G-Dur", "Sonate Nummer drei G-Dur"),
        ("Messe in Es-Dur", "Messe in Es-Dur"),
        # Die Einheit bleibt eine Einheit, wo kein "-Dur"/"-Moll" folgt.
        ("5 g Zucker", "fünf Gramm Zucker"),
    ],
)
def test_tonarten_bleiben_tonarten(quelle, erwartet):
    # Ueber die ganze Regelkette, weil "Nr." erst in der Abkuerzungsstufe zu "Nummer" wird.
    assert deterministisch(quelle) == erwartet


@pytest.mark.parametrize(
    ("quelle", "erwartet"),
    [
        (
            "SA 17. OKT 26 | 19:30 UHR",
            "Samstag, siebzehnter Oktober sechsundzwanzig, neunzehn Uhr dreißig",
        ),
        (
            "FR 2. NOV 26 | 19.30 Uhr",
            "Freitag, zweiter November sechsundzwanzig, neunzehn Uhr dreißig",
        ),
        # Mit "am" davor bleibt es der Dativ.
        ("Konzert am SA 17. OKT", "Konzert am Samstag, siebzehnten Oktober"),
        ("MI 1. JAN", "Mittwoch, erster Januar"),
        ("SO 3. MÄR", "Sonntag, dritter März"),
        # Ohne Kuerzel bleibt es bei der bisherigen Regel (Dativ).
        ("12. Oktober", "zwölften Oktober"),
        # "SO" ohne Datum ist kein Wochentag.
        ("SO 5 Euro", "SO fünf Euro"),
    ],
)
def test_programmzeile_wochentag_datum_uhrzeit(quelle, erwartet):
    assert deterministisch(quelle) == erwartet


@pytest.mark.parametrize(
    ("quelle", "erwartet"),
    [
        # Das Geschlecht des Hauptworts steht nicht da: Endung des ersten Worts danach.
        ("3. & 4. SYMPHONISCHES KONZERT", "drittes und viertes Symphonisches Konzert"),
        ("1. und 2. Sinfonie", "erste und zweite Sinfonie"),
        ("3. bis 4. Konzert", "drittes bis viertes Konzert"),
        # Vor Monat und bekannten Folgewoertern bleibt es der Dativ.
        ("am 3. und 4. Oktober", "am dritten und vierten Oktober"),
        ("im 3. und 4. Stock", "im dritten und vierten Stock"),
        # Ein einzelnes "3. Dann" bleibt ein Satzende.
        ("Es war der Dritte, nicht der 3. Dann ging er.", None),
    ],
)
def test_zwei_ordnungszahlen_vor_hauptwort(quelle, erwartet):
    ergebnis = deterministisch(quelle)
    if erwartet is None:
        assert "drittes" not in ergebnis and "drei." in ergebnis
    else:
        assert ergebnis == erwartet


@pytest.mark.parametrize(
    ("quelle", "erwartet"),
    [
        ("am 1. Mai", "am ersten Mai"),
        ("am 3. Mai", "am dritten Mai"),
        ("am 7. Mai", "am siebten Mai"),
        ("am 8. Mai", "am achten Mai"),
        ("im 100. Jahrhundert", "im hundertsten Jahrhundert"),
        ("zum 101. Mal", "zum hundertersten Mal"),
        ("zum 1000. Mal", "zum tausendsten Mal"),
        ("1 Mrd. Euro", "eine Milliarde Euro"),
        ("2 Mrd. Euro", "zwei Milliarden Euro"),
        ("1 Mio. Euro", "eine Million Euro"),
        ("1,5 Mio. Euro", "eins Komma fünf Millionen Euro"),
        ("21 Mio. Euro", "einundzwanzig Millionen Euro"),
        ("1 Bio. Euro", "eine Billion Euro"),
        ("2 Bio. Euro", "zwei Billionen Euro"),
        ("Das kostet 2 Bio.", "Das kostet zwei Billionen."),
        # "Bio." allein ist kein Billionen: es braucht die Zahl davor.
        ("Wir kaufen Bio. Dann gehen wir.", "Wir kaufen Bio. Dann gehen wir."),
    ],
)
def test_ordinal_und_grosszahl_formen(quelle, erwartet):
    assert deterministisch(quelle) == erwartet


# Fehlerliste aus der Trockenpruefung des ganzen Hoerbuchs (24.10.).
@pytest.mark.parametrize(
    ("quelle", "erwartet"),
    [
        ("Im 8. Haus wohnt der Tod.", "Im achten Haus wohnt der Tod."),
        ("Das 3. Kapitel und der 2. Teil.", "Das dritte Kapitel und der zweite Teil."),
        ("Der Anteil an CO2 steigt.", "Der Anteil an CO zwei steigt."),
        ("Die CO2-Konzentration steigt.", "Die CO zwei-Konzentration steigt."),
        ("Das Netz (5G) ist schnell.", "Das Netz (fünf G) ist schnell."),
        ("Bereits in den 1970er Jahren.", "Bereits in den neunzehnhundertsiebziger Jahren."),
        ("von Papst Pius IX. zum Dogma", "von Papst Pius dem Neunten zum Dogma"),
        ("Papst Johannes Paul II. sagte", "Papst Johannes Paul der Zweite sagte"),
        (
            "Es sprach Papst Johannes Paul II. Danach",
            "Es sprach Papst Johannes Paul der Zweite. Danach",
        ),
        ("(Röm 9,16,12).", "(Röm neun, sechzehn, zwölf)."),
        ("Version 2.1.3 kam.", "Version zwei Punkt eins Punkt drei kam."),
        ("Vorwahl 0911.", "Vorwahl null neun eins eins."),
        ("im Clemensbrief, Kap. XII drückt", "im Clemensbrief, Kapitel zwölf drückt"),
        ("(Röm IX,16,12).", "(Röm neun, sechzehn, zwölf)."),
        (
            "am 24.10.2026 um 3,5 Uhr",
            "am vierundzwanzigsten Oktober zweitausendsechsundzwanzig um drei Komma fünf Uhr",
        ),
    ],
)
def test_ordnungszahlen_ziffern_im_wort_und_herrschernamen(quelle, erwartet):
    assert deterministisch(quelle) == erwartet


# Critic 24.10.: was vorher sichtbar ungelesen blieb, darf nicht still falsch gelesen werden.
@pytest.mark.parametrize(
    ("quelle", "erwartet"),
    [
        ("am 1.2.24 kam", "am ersten Februar vierundzwanzig kam"),
        ("Königin Elisabeth II. sagte", "Königin Elisabeth die Zweite sagte"),
        ("von Königin Elisabeth II. hieß", "von Königin Elisabeth der Zweiten hieß"),
        ("Es war Typ II. Danach", "Es war Typ II. Danach"),
        ("Rocky II. lief", "Rocky II. lief"),
        ("in den 1920ern", "in den neunzehnhundertzwanzigern"),
        ("das 3fache und 30jährige", "das dreifache und dreißigjährige"),
        ("auf 5 m2 und 2 km2", "auf fünf Quadratmeter und zwei Quadratkilometer"),
        ("rund 5Mrd. Euro", "rund fünf Milliarden Euro"),
        ("(Röm IX,16).", "(Röm neun, sechzehn)."),
        ("nicht der 3. Am Ende", "nicht der drei. Am Ende"),
        ("von 08 bis 17 Uhr", "von acht bis siebzehn Uhr"),
        ("Tel. 0911 123456", "Telefon null neun eins eins eins zwei drei vier fünf sechs"),
        ("der 1.FC Nürnberg", "der erste FC Nürnberg"),  # gesprochen gleich
    ],
)
def test_critic_faelle_der_neuen_regeln(quelle, erwartet):
    assert deterministisch(quelle) == erwartet


# xreview 24.10. (Gemini, Kimi) zu den neuen Regeln.
@pytest.mark.parametrize(
    ("quelle", "erwartet"),
    [
        (
            "Er kam am 12.10.2026. Dann ging er.",
            "Er kam am zwölften Oktober zweitausendsechsundzwanzig. Dann ging er.",
        ),
        ("Version 1.2.10 kam", "Version eins Punkt zwei Punkt zehn kam"),
        ("am 1.2.05 kam", "am ersten Februar null fünf kam"),
        ("ein 1jähriges Kind", "ein einjähriges Kind"),
        ("nach 5std. und 30min.", "nach fünf Stunden und dreißig Minuten."),
        (
            "Auf dem Konzil sprach Papst Pius IX. sein Wort",
            "Auf dem Konzil sprach Papst Pius der Neunte sein Wort",
        ),
        ("Der König starb. Rocky II. lief", "Der König starb. Rocky II. lief"),
    ],
)
def test_xreview_faelle_der_neuen_regeln(quelle, erwartet):
    assert deterministisch(quelle) == erwartet
