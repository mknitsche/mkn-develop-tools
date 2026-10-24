# ruff: noqa: RUF001  (Gedankenstriche sind hier die Testdaten: der Halbgeviertstrich ist der Gegenstand)
"""Abkuerzungen, Aussprache-Woerterbuch und Schreibweisen, die man anders spricht."""

from __future__ import annotations

import pytest

from mkn_audio.hoertext.abkuerzungen import (
    ersetze_abkuerzungen,
    ersetze_woerter,
    lade_tabellen,
    saeubere,
)
from mkn_audio.typen import Mp4Fehler


@pytest.mark.parametrize(
    ("quelle", "erwartet"),
    [
        ("z. B. Äpfel", "zum Beispiel Äpfel"),
        ("z.B. Äpfel", "zum Beispiel Äpfel"),
        ("Z. B. Äpfel", "Zum Beispiel Äpfel"),
        ("Äpfel bzw. Birnen", "Äpfel beziehungsweise Birnen"),
        ("Dr. Müller kam", "Doktor Müller kam"),
        ("Prof. Dr. Müller", "Professor Doktor Müller"),
        ("ca. 20 Leute", "circa 20 Leute"),
        ("d. h. gar nicht", "das heißt gar nicht"),
        ("2,4 Mrd. Euro", "2,4 Milliarden Euro"),
        ("Die USA und die EU", "Die USA und die EU"),
        ("§ 3", "Paragraf 3"),
        ("§§ 3 bis 5", "Paragrafen 3 bis 5"),
        ("um 3000 v. Chr. lebten", "um 3000 vor Christus lebten"),
        ("(seit etwa 2000 v. Chr.)", "(seit etwa 2000 vor Christus)"),
        ("im Jahr 79 n. Chr. brach", "im Jahr 79 nach Christus brach"),
    ],
)
def test_abkuerzungen_werden_ausgeschrieben(quelle, erwartet):
    assert ersetze_abkuerzungen(quelle) == erwartet


def test_abkuerzung_verlangt_wortgrenze_davor():
    # "bzw." im Wort "Abzw." oder "Dr." in "Ladr." darf nichts treffen.
    assert ersetze_abkuerzungen("Ladr. und Abzw.") == "Ladr. und Abzw."


def test_satzende_abkuerzung_behaelt_den_punkt_nur_am_satzende():
    # "usw." ist ein Satzende, wenn ein neuer Satz folgt; mitten im Satz nicht.
    assert (
        ersetze_abkuerzungen("Äpfel, Birnen usw. Dann ging er.")
        == "Äpfel, Birnen und so weiter. Dann ging er."
    )
    assert ersetze_abkuerzungen("Äpfel usw. und mehr") == "Äpfel und so weiter und mehr"
    assert ersetze_abkuerzungen("Äpfel, Birnen usw.") == "Äpfel, Birnen und so weiter."


def test_aussprache_ist_wortgenau():
    woerter = {"Nietzsche": "Nitsche", "GmbH": "Gemmbeha"}
    assert ersetze_woerter("Nietzsche und die GmbH", woerter) == "Nitsche und die Gemmbeha"
    # Teil eines laengeren Wortes: unberuehrt.
    assert ersetze_woerter("Nietzsches Werk", woerter) == "Nietzsches Werk"


def test_aussprache_laengster_schluessel_gewinnt_und_ist_gross_klein_genau():
    woerter = {"New York": "Nju Jork", "New": "Nju"}
    assert ersetze_woerter("New York und New Delhi", woerter) == "Nju Jork und Nju Delhi"
    assert ersetze_woerter("new york", woerter) == "new york"


def test_aussprache_leer_aendert_nichts():
    assert ersetze_woerter("Nietzsche", {}) == "Nietzsche"
    assert ersetze_woerter("Nietzsche", None) == "Nietzsche"


def test_url_wird_auf_die_domain_gekuerzt_und_sprechbar():
    assert (
        saeubere("Siehe https://www.beispiel.de/pfad/seite?x=1 dort.")
        == "Siehe beispiel Punkt de dort."
    )
    # Satzzeichen hinter der Adresse gehoeren zum Satz, nicht zur Adresse.
    assert saeubere("Siehe www.beispiel.de.") == "Siehe beispiel Punkt de."
    assert saeubere("(http://a.example.org/x)") == "(a Punkt example Punkt org)"


def test_fussnotenzeichen_fallen_weg():
    assert saeubere("Das Haus¹ stand dort.²³") == "Das Haus stand dort."
    assert saeubere("Das Haus[12] stand dort.") == "Das Haus stand dort."


def test_paarige_gedankenstriche_werden_kommas():
    assert saeubere("Er – der Chef – kam.") == "Er, der Chef, kam."
    assert saeubere("Er kam – wie es hieß –.") == "Er kam, wie es hieß."
    assert saeubere("Er kam — der Chef — spät.") == "Er kam, der Chef, spät."


def test_einzelner_gedankenstrich_und_zahlenbereich_bleiben():
    assert saeubere("Er kam – spät.") == "Er kam – spät."
    assert saeubere("von 5 – 10 und 20 – 30") == "von 5 – 10 und 20 – 30"


def test_silbentrennung_am_zeilenende_wird_geheilt():
    assert saeubere("Zei-\nlen und\nUmbruch") == "Zeilen und Umbruch"


def test_leerraum_wird_vereinheitlicht():
    assert saeubere("  a \N{NO-BREAK SPACE} \N{NARROW NO-BREAK SPACE}b\t c  ") == "a b c"


def test_tabelle_laedt_und_hat_alle_drei_teile():
    tabellen = lade_tabellen()
    assert tabellen.abkuerzungen["z. B."] == "zum Beispiel"
    assert "usw." in tabellen.satzende
    assert tabellen.einheiten["%"] == "Prozent"


def test_tabelle_mit_fremdem_abschnitt_bricht_laut(tmp_path):
    pfad = tmp_path / "x.toml"
    pfad.write_text('[abkuerzungen]\n"a." = "b"\n[satzende]\n[einheiten]\n[sonst]\n', "utf-8")
    with pytest.raises(Mp4Fehler, match="sonst"):
        lade_tabellen(pfad)


def test_tabelle_mit_nicht_text_wert_bricht_laut(tmp_path):
    pfad = tmp_path / "x.toml"
    pfad.write_text('[abkuerzungen]\n"a." = 3\n[satzende]\n[einheiten]\n', "utf-8")
    with pytest.raises(Mp4Fehler, match="a\\."):
        lade_tabellen(pfad)


def test_abkuerzung_am_absatzende_behaelt_den_satzpunkt():
    assert ersetze_abkuerzungen("Es dauerte 7 Std.") == "Es dauerte 7 Stunden."
    assert ersetze_abkuerzungen("Es dauerte 7 Std. und mehr") == "Es dauerte 7 Stunden und mehr"


def test_ua_ist_urauffuehrung():
    assert ersetze_abkuerzungen("Sinfonie Nr. 1 (UA)") == "Sinfonie Nummer 1 (Uraufführung)"
    # Ohne Punkt im Original gibt es keinen Satzpunkt zu retten.
    assert ersetze_abkuerzungen("Sinfonie (UA)") == "Sinfonie (Uraufführung)"
    assert ersetze_abkuerzungen("Sinfonie UA") == "Sinfonie Uraufführung"


@pytest.mark.parametrize(
    ("quelle", "erwartet"),
    [
        ("SYMPHONISCHES KONZERT", "Symphonisches Konzert"),
        ("ÖSTERREICHISCHE STÖRUNG", "Österreichische Störung"),
        ("SYMPHONIE-ORCHESTER", "Symphonie-Orchester"),
        # Unter vier Buchstaben und mit Ziffern: unberuehrt.
        ("DIE USA UND EU", "DIE USA UND EU"),
        ("Der MP3-Player ABC123", "Der MP3-Player ABC123"),
        # Gemischte Schreibung ist schon ein Wort.
        ("GmbH und iPhone", "GmbH und iPhone"),
    ],
)
def test_grossbuchstaben_woerter_werden_lesbar(quelle, erwartet):
    assert ersetze_abkuerzungen(quelle) == erwartet


def test_grossbuchstaben_abkuerzung_aus_der_tabelle_bleibt_abkuerzung():
    # "MIND." ist "mind." mit grossem Anfangsbuchstaben der Tabelle, kein Wort in Versalien.
    assert ersetze_abkuerzungen("MIND. zehn") == "Mindestens zehn"


def test_und_zeichen_und_senkrechter_strich_werden_gesprochen():
    assert saeubere("3. & 4. Konzert") == "3. und 4. Konzert"
    assert saeubere("Müller & Söhne") == "Müller und Söhne"
    # Der Strich ist eine Pause: ein Komma, am Rand nichts.
    assert saeubere("SA 17. OKT | 19:30 UHR") == "SA 17. OKT, 19:30 UHR"
    assert saeubere("| a | b |") == "a, b"
    # Endet das Stueck schon mit Satzzeichen, kommt kein zweites dazu.
    assert saeubere("Ende. | Neu") == "Ende. Neu"
    # Ein "&" mitten im Wort ("AT&T") ist kein Bindewort.
    assert saeubere("AT&T") == "AT&T"


@pytest.mark.parametrize(
    ("ein", "aus"),
    [
        ("SYMPHONISCHES KONZERT", "Symphonisches Konzert"),
        ("HTTP", "HTTP"),
        ("ISBN", "ISBN"),
        ("XVIII", "XVIII"),
        ("NATO", "Nato"),
    ],
)
def test_versalien_nur_sprechbare_woerter_umschreiben(ein, aus):
    from mkn_audio.hoertext.abkuerzungen import _versalien_lesbar

    assert _versalien_lesbar(ein, set()) == aus


def test_auslassungszeichen_fallen_weg():
    assert saeubere("Er schreibt „(…) sind überall“ und […] mehr.") == (
        "Er schreibt „sind überall“ und mehr."
    )
