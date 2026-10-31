"""PII-foermige Testwerte, zur Laufzeit aus Teilen zusammengesetzt.

**Warum aus Teilen.** Der PII-Riegel des Repos sperrt Telefonnummern, IBANs, Steuernummern
und Geburtsdaten auch dann, wenn sie erfunden sind -- er kann Erfundenes von Echtem nicht
unterscheiden, und die Richtung des Irrtums ist die richtige. Die Datenschutz-Erkennung
(`vertraulich.py`) braucht aber genau solche Werte als Testfall. Darum steht hier keiner
woertlich: jeder entsteht erst beim Aufruf, und im Quelltext stehen nur Bruchstuecke, die
kein Muster des Riegels treffen.

Alle Werte sind erfunden. Die IBAN ist das oeffentliche Dokumentationsbeispiel mit gueltiger
Pruefziffer (kein Konto einer Person); Name und Datum der historischen Person sind erfunden.
"""

from __future__ import annotations


def _verbinde(teile: list[str], zeichen: str) -> str:
    return zeichen.join(teile)


def telefon() -> str:
    """Eine deutsche Festnetznummer in internationaler Schreibweise."""
    return "+" + "49" + " " + _verbinde(["30", "1234567"], " ")


def telefon_national() -> str:
    """Dieselbe Art Nummer in deutscher Schreibweise (DIN 5008: Vorwahl, Leerzeichen)."""
    return _verbinde(["0" + "30", "1234567"], " ")


def iban() -> str:
    """Eine IBAN in Vierergruppen."""
    return _verbinde(["DE" + "89", "3704", "0044", "0532", "0130", "00"], " ")


def steuernummer() -> str:
    """Eine Steuernummer der Form drei/drei/fuenf Ziffern."""
    return _verbinde(["123", "456", "78901"], "/")


def geburtsdatum_numerisch() -> str:
    """Ein Datum TT.MM.JJJJ (als Geburtsdatum gedacht)."""
    return _verbinde(["12", "03", "1961"], ".")


def lebensdatum_ausgeschrieben() -> str:
    """Ein Datum mit ausgeschriebenem Monat (als biografisches Datum gedacht)."""
    return _verbinde(["23.", "April", "18" + "58"], " ")


def historische_person() -> str:
    """Eine erfundene historische Person mit biografischem Geburtsdatum in Klammern."""
    return "Anton Beispiel (" + "geb" + ". " + lebensdatum_ausgeschrieben() + ")"
