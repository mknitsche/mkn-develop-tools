"""Datenschutz-Hinweis vor dem Versand an Google (Spec 9).

Die Erkennung ist deterministisch und eine Untergrenze: Kontaktdaten und Kennziffern zaehlen
immer, Briefform nur mit Personen-Anrede UND Grussformel, Lebensdaten nur ausserhalb von
Buechern und nur in kurzen Dokumenten. Alle Werte sind erfunden; PII-foermige entstehen zur
Laufzeit aus Teilen (`pii_bausteine`), weil der PII-Riegel auch erfundene sperrt (HC-3).
`mkn_audio.vertraulich` entsteht mit Plan C3; der Import steht darum in den Tests.
"""

from __future__ import annotations

import pytest

from mkn_audio.typen import Dokument, Kapitel
from pii_bausteine import (
    geburtsdatum_numerisch,
    historische_person,
    iban,
    steuernummer,
    telefon,
    telefon_national,
)

GRUSS = "Mit freundlichen Grüßen"


def dok(*absaetze: str) -> Dokument:
    return Dokument(
        titel="Testdokument", autor=None, sprache="de", kapitel=(Kapitel("Eins", absaetze),)
    )


def pruefe(*absaetze: str, dokumentart: str | None = None, seiten: int | None = 1):
    from mkn_audio.vertraulich import pruefe_vertraulich

    return pruefe_vertraulich(dok(*absaetze), dokumentart=dokumentart, seiten=seiten)


def klassen(hinweise) -> dict[str, int]:
    return {h.klasse: h.anzahl for h in hinweise}


def test_email_telefon_iban_erkannt():
    """Kontaktdaten zaehlen immer -- auch im Sachbuch. Das Beispiel ist maskiert."""
    hinweise = pruefe(
        f"Schreiben Sie an erika@beispiel.example oder rufen Sie {telefon()} an.",
        f"Tagsueber erreichen Sie das Buero unter {telefon_national()}.",
        f"Die Bankverbindung lautet {iban()}.",
        dokumentart="Sachbuch",
        seiten=120,
    )

    assert klassen(hinweise) == {"Kontaktdaten": 4}
    (hinweis,) = hinweise
    for roh in ("erika@beispiel.example", telefon(), telefon_national(), iban()):
        assert roh not in hinweis.beispiel
    assert hinweis.beispiel.strip()

    assert pruefe("Im Garten bluehen die Rosen.", "Die Amsel singt.") == ()


def test_kennziffern_mit_vorwort():
    """Eine Kennziffer braucht ihr Vorwort; dieselbe Zahl allein ist keine."""
    assert (
        klassen(pruefe(f"Ihre Steuernummer {steuernummer()} bitte angeben.")).get("Kennziffern")
        == 1
    )
    assert "Kennziffern" not in klassen(pruefe(f"Die Zahl {steuernummer()} steht allein."))


def test_briefform_nur_personenanrede_mit_gruss():
    """Briefform heisst: eine Person wird angesprochen UND es wird gegruesst."""
    brief = pruefe(
        "Sehr geehrter Herr Mustermann,",
        "vielen Dank für Ihre Nachricht vom Montag.",
        GRUSS,
    )
    sammelanrede = pruefe("Liebe Freunde,", "vielen Dank für die schöne Feier.", GRUSS)
    ohne_gruss = pruefe("Sehr geehrter Herr Mustermann,", "vielen Dank für Ihre Nachricht.")

    assert klassen(brief).get("Briefform") == 1
    assert "Briefform" not in klassen(sammelanrede)
    assert "Briefform" not in klassen(ohne_gruss)


def test_buch_mit_sammelanrede_und_lebensdatum_ohne_hinweis():
    """Review Focus 4: ein Buch mit Sammelanrede, Grussformel und dem biografischen
    Geburtsdatum einer (erfundenen) historischen Person loest nichts aus -- keine Rueckfrage."""
    hinweise = pruefe(
        "Liebe Leserinnen und Leser,",
        "dieses Buch erzählt vom Garten und seinen Bewohnern durch die Jahrhunderte.",
        f"Schon {historische_person()} pflanzte hier die ersten Rosen.",
        "Herzliche Grüße",
        dokumentart="Sachbuch",
        seiten=120,
    )

    assert hinweise == ()


def test_kurzer_brief_mit_geburtsdatum_hinweis():
    """Ohne Dokumentart und kurz: ein Geburtsdatum ist ein Hinweis."""
    hinweise = pruefe(
        f"Herr Mustermann, geboren am {geburtsdatum_numerisch()}, wohnt seit Jahren hier.",
        dokumentart=None,
        seiten=2,
    )

    assert klassen(hinweise).get("Lebensdaten") == 1
    assert all(geburtsdatum_numerisch() not in h.beispiel for h in hinweise)


@pytest.mark.parametrize("praefix", ["Geboren am", "Geb.", "GEBOREN AM", "geb.", "Geburtsdatum:"])
def test_lebensdatum_praefix_unabhaengig_von_gross_und_kleinschreibung(praefix):
    """Am Satzanfang (Lebenslauf) steht der Praefix gross -- er ist trotzdem ein Hinweis."""
    datum = geburtsdatum_numerisch()
    hinweise = pruefe(f"{praefix} {datum} in der Beispielstadt.", dokumentart=None, seiten=2)

    assert klassen(hinweise).get("Lebensdaten") == 1
    assert all(datum not in h.beispiel for h in hinweise)


@pytest.mark.parametrize(
    ("dokumentart", "hinweis"),
    [
        ("Brief", True),
        ("ein Arztbrief", True),
        ("eine Rechnung", True),
        ("ein Befund", True),
        ("Sachbuch", False),
        ("ein Artikel", False),
    ],
)
def test_dokumentart_brief_ist_hinweis(dokumentart, hinweis):
    """Die Dokumentart der Regie (mit unbestimmtem Artikel) im Wortstamm-Abgleich."""
    hinweise = pruefe("Im Garten bluehen die Rosen.", dokumentart=dokumentart, seiten=3)

    assert ("Dokumentart" in klassen(hinweise)) is hinweis


def test_regie_aus_nutzt_laengenschwellen():
    """Bei `--regie aus` ist die Dokumentart leer: dann entscheiden Seiten und Woerter allein."""
    from mkn_audio.vertraulich import MAX_SEITEN_LEBENSDATEN, MAX_WOERTER_LEBENSDATEN

    satz = f"Schon {historische_person()} pflanzte hier die ersten Rosen."
    fuell = "Der Garten ruht im Winter. " * 2_200  # rund 11.000 Woerter

    assert (MAX_SEITEN_LEBENSDATEN, MAX_WOERTER_LEBENSDATEN) == (20, 10_000)
    assert "Lebensdaten" in klassen(pruefe(satz, dokumentart=None, seiten=2))
    assert "Lebensdaten" in klassen(pruefe(satz, dokumentart=None, seiten=None))
    # viele Woerter, wenige Seiten: allein der Seitenzweig der Schwelle loest aus
    assert "Lebensdaten" in klassen(pruefe(satz, fuell, dokumentart=None, seiten=2))
    assert "Lebensdaten" not in klassen(pruefe(satz, fuell, dokumentart=None, seiten=None))
    assert "Lebensdaten" not in klassen(pruefe(satz, fuell, dokumentart=None, seiten=120))
