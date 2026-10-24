"""Abkuerzungen, Aussprache-Woerterbuch und Schreibweisen, die man anders spricht.

**Warum Regeln vor dem Sprachmodell.** Eine Abkuerzung wie "z. B." hat genau eine
Aussprache. Ein Modell, das sie "mal eben" ausschreibt, kann sie auch verfaelschen, und
dann haette die Pruefung (`pruefen.py`) nichts, woran sie das merkt. Die Regeln dieses
Moduls sind dagegen vorhersagbar, und was sie schreiben, ist die Bezugsgroesse, an der
das Modell spaeter gemessen wird.

Die Tabellen stehen in `abkuerzungen_de.toml` (von Hand pflegbar); ein Tippfehler dort
bricht laut ab, statt eine Abkuerzung still nicht zu treffen.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from itertools import pairwise
from pathlib import Path
from types import MappingProxyType

from mkn_audio._toml import lies, pruefe_schluessel
from mkn_audio._toml import text as pruefe_text

_ABSCHNITTE = {"abkuerzungen", "satzende", "einheiten"}


@dataclass(frozen=True, eq=False)
class Tabellen:
    """Die drei Tabellen der TOML-Datei, unveraenderlich.

    `eq=False`: Vergleich und Hash laufen ueber die Identitaet, damit das fertig
    uebersetzte Suchmuster je Tabellensatz gemerkt werden kann (siehe `_muster`).
    """

    abkuerzungen: Mapping[str, str]
    satzende: Mapping[str, str]
    einheiten: Mapping[str, str]


def lade_tabellen(pfad: Path | None = None) -> Tabellen:
    """Liest die Tabellen; ohne `pfad` die mitgelieferte Datei (einmal, dann gemerkt)."""
    if pfad is None:
        return _standardtabellen()
    return _lies_tabellen(pfad)


@cache
def _standardtabellen() -> Tabellen:
    datei = resources.files("mkn_audio.hoertext") / "abkuerzungen_de.toml"
    with resources.as_file(datei) as pfad:
        return _lies_tabellen(pfad)


def _lies_tabellen(pfad: Path) -> Tabellen:
    daten = lies(pfad, "Abkuerzungs-Tabelle")
    wo = f"Abkuerzungs-Tabelle {pfad}"
    pruefe_schluessel(daten, pflicht=_ABSCHNITTE, erlaubt=_ABSCHNITTE, wo=wo)
    for abschnitt in sorted(_ABSCHNITTE):
        for schluessel, wert in daten[abschnitt].items():
            pruefe_text(wert, schluessel, f"{wo} [{abschnitt}]")
    return Tabellen(
        abkuerzungen=MappingProxyType(dict(daten["abkuerzungen"])),
        satzende=MappingProxyType(dict(daten["satzende"])),
        einheiten=MappingProxyType(dict(daten["einheiten"])),
    )


def _rand(zeichen: str, *, vorn: bool) -> str:
    """Wortgrenze nur dort, wo das Randzeichen ein Wortzeichen ist.

    "Dr." darf nicht in "Ladr." greifen, aber "§" hat links und rechts keine Grenze.
    """
    if not (zeichen.isalnum() or zeichen == "_"):
        return ""
    return r"(?<!\w)" if vorn else r"(?!\w)"


def ersetze_woerter(text: str, woerterbuch: Mapping[str, str] | None) -> str:
    """Aussprache-Woerterbuch: ganze Woerter (oder Wortfolgen), Gross/Klein genau.

    Laengere Schluessel gewinnen ("New York" vor "New"). Wortgenau heisst: "Nietzsche"
    trifft nicht "Nietzsches" -- ein Name in einer Beugung muss eigens eingetragen
    werden, sonst wuerde die Ersetzung auch Teile fremder Woerter treffen.
    """
    if not woerterbuch:
        return text
    schluessel = sorted(woerterbuch, key=len, reverse=True)
    muster = "|".join(
        _rand(s[0], vorn=True) + re.escape(s) + _rand(s[-1], vorn=False) for s in schluessel
    )
    return re.sub(muster, lambda m: woerterbuch[m.group(0)], text)


def _schluessel_muster(schluessel: str) -> str:
    """Suchmuster einer Abkuerzung: Leerraum ist beliebig, der erste Buchstabe beides."""
    teile = [re.escape(t) for t in schluessel.split()]
    muster = r"\s*".join(teile)
    erster = schluessel[0]
    if erster.isalpha():
        klein, gross = erster.lower(), erster.upper()
        muster = f"[{klein}{gross}]" + muster[len(re.escape(erster)) :]
    return _rand(erster, vorn=True) + muster + _rand(schluessel[-1], vorn=False)


# Nach einer Satzende-Abkuerzung beginnt ein neuer Satz, wenn der Absatz endet oder ein
# Grossbuchstabe (eventuell nach Anfuehrungszeichen) folgt.
_ABSATZENDE = re.compile(r"\s*$")
_NEUER_SATZ = re.compile(r"""\s*$|\s+["„“»«'(]?[A-ZÄÖÜ]""")


@cache
def _muster(tabellen: Tabellen) -> tuple[re.Pattern[str], tuple[str, ...]]:
    """Ein Suchmuster fuer alle Abkuerzungen, laengste zuerst ("u. a. m." vor "u. a.")."""
    reihenfolge = tuple(sorted({*tabellen.abkuerzungen, *tabellen.satzende}, key=len, reverse=True))
    muster = re.compile(
        "|".join(f"(?P<k{i}>{_schluessel_muster(s)})" for i, s in enumerate(reihenfolge))
    )
    return muster, reihenfolge


# Ein ganzes Wort in Versalien ab vier Buchstaben ("SYMPHONISCHES"): eine Stimme buchstabiert
# es oder betont es falsch. Drei Buchstaben und weniger bleiben (USA, EU, SA ...), weil das
# meist Kuerzel sind, deren Lesart die Zahlenregeln oder die Stimme kennen; Ziffern im Wort
# ("MP3") nehmen es aus der Regel.
_VERSALWORT = re.compile(r"(?<!\w)[A-ZÄÖÜ]{4,}(?!\w)")


def _versalien_lesbar(text: str, bekannt: set[str]) -> str:
    """ "SYMPHONISCHES KONZERT" -> "Symphonisches Konzert"; Tabelleneintraege bleiben."""
    return _VERSALWORT.sub(
        lambda m: m[0] if m[0] in bekannt or not _umschreiben(m[0], bekannt) else m[0].capitalize(),
        text,
    )


# Ein Kuerzel, das buchstabiert wird (HTTP, ISBN, XVIII), hat meist hoechstens einen Vokal auf
# vier Buchstaben; ein Wort wie "KONZERT" hat mehr. Nur das sprechbare Wort wird umgeschrieben,
# sonst liest die Stimme "Http" als Kunstwort.
def _umschreiben(wort: str, bekannt: set[str]) -> bool:
    if f"{wort.lower()}." in {b.lower() for b in bekannt}:  # "MIND." trifft "mind." der Tabelle
        return True
    if re.fullmatch(r"[IVXLCDM]+", wort):  # roemische Zahl
        return False
    vokale = sum(1 for z in wort if z in "AEIOUÄÖÜY")
    return vokale >= 2 and vokale * 4 >= len(wort)


def wortformen(texte: Iterable[str]) -> dict[str, str]:
    """Die normal geschriebenen Woerter eines Dokuments: klein -> haeufigste Schreibweise.

    Grundlage fuer `ersetze_abkuerzungen(formen=...)`: ein Wort in Versalien, das hier steht,
    ist kein Kuerzel ("UND", "GOTT", "EVA"); ein echtes Kuerzel (WHO, CERN) steht nie klein.
    Gezaehlt wird nur mitten im Satz -- am Satzanfang ist jedes Wort gross ("Die Liebe" gegen
    "ich liebe"); ein Wort, das nur am Satzanfang steht, zaehlt als Notbehelf trotzdem.
    """
    zaehler: dict[str, dict[str, int]] = {}
    notbehelf: dict[str, str] = {}
    for text in texte:
        for m in re.finditer(r"[^\W\d_]+", text):
            wort = m[0]
            if wort.isupper():
                continue
            davor = text[: m.start()].rstrip(' \t\u201e\u00bb"(')
            if not davor or davor[-1] in ".!?:":
                notbehelf.setdefault(wort.lower(), wort)
                continue
            formen = zaehler.setdefault(wort.lower(), {})
            formen[wort] = formen.get(wort, 0) + 1
    ergebnis = dict(notbehelf)
    for klein, formen in zaehler.items():
        ergebnis[klein] = max(formen, key=lambda f: (formen[f], f.islower()))
    return ergebnis


# Kurze Funktionswoerter, die als Betonung in Versalien stehen ("auf DIE gemeinsame", "das ICH
# und das DU") und praktisch nie ein Kuerzel sind. MAN, ALS und IT fehlen bewusst: sie sind
# auch Kuerzel (Firma, Krankheit, Informationstechnik).
_FUNKTIONSWOERTER = frozenset(
    {"DER", "DIE", "DAS", "DEN", "DEM", "DES", "UND", "ICH", "DU", "ER", "SIE", "ES", "WIR",
     "MIT", "IST", "BIN", "AUF", "AUS", "VON", "ZUM", "ZUR", "UR", "NUR", "WAS", "WER"}
)  # fmt: skip
_PROGRAMM_KUERZEL = frozenset(
    {"MO", "DI", "MI", "DO", "FR", "SA", "SO", "JAN", "FEB", "MÄR", "MRZ", "APR", "MAI", "JUN",
     "JUL", "AUG", "SEP", "SEPT", "OKT", "NOV", "DEZ"}
)  # fmt: skip
_VERSAL_KURZ = re.compile(r"(?<!\w)[A-ZÄÖÜ]{2,}(?!\w)")


def _versalien_aus_dokument(text: str, formen: Mapping[str, str]) -> str:
    """Versalwort -> Schreibweise des Dokuments; bis drei Buchstaben nur im Versal-Umfeld.

    Echte Kuerzel stehen auch als gewoehnliches Wort im Text ("Die MAN baut", "Er hat ALS",
    "IT-Abteilung"); ein kurzes Versalwort wird darum nur ein Wort, wenn ein Nachbarwort auch
    in Versalien steht ("DER GLAUBE", "Adam UND EVA").
    """
    woerter = list(re.finditer(r"[^\W\d_]+", text))
    versal = {w.start() for w in woerter if len(w[0]) >= 2 and w[0].isupper()}
    nachbar_versal: set[int] = set()
    for vorne, hinten in pairwise(woerter):
        # Nachbarn nur ueber reinen Leerraum ("DER GLAUBE"), nie ueber "3." oder ein Satzende.
        if (
            vorne.start() in versal
            and hinten.start() in versal
            and text[vorne.end() : hinten.start()].isspace()
        ):
            nachbar_versal.update((vorne.start(), hinten.start()))

    def ersatz(m: re.Match[str]) -> str:
        form = formen.get(m[0].lower())
        if form is None or re.fullmatch(r"[IVXLCDM]+", m[0]):
            return m[0]
        if m[0] in _PROGRAMM_KUERZEL:  # "SO 3. MÄR": Wochentag und Monat liest die Zahlenregel
            return m[0]
        if len(m[0]) <= 3 and m.start() not in nachbar_versal and m[0] not in _FUNKTIONSWOERTER:
            return m[0]
        davor = text[: m.start()].rstrip(' \t\u201e\u00bb"(')
        if not davor or davor[-1] in ".!?:":
            form = form[0].upper() + form[1:]
        return form

    return _VERSAL_KURZ.sub(ersatz, text)


def ersetze_abkuerzungen(
    text: str, tabellen: Tabellen | None = None, *, formen: Mapping[str, str] | None = None
) -> str:
    """Schreibt Abkuerzungen aus; am Satzende bleibt der Punkt, wo er den Satz schliesst.

    Zuerst werden Woerter in Versalien lesbar gemacht, damit "MIND." als "Mind." die
    Abkuerzung trifft. Was selbst in einer Tabelle steht, bleibt dabei unberuehrt.
    """
    tabellen = tabellen or lade_tabellen()
    muster, reihenfolge = _muster(tabellen)
    alle = {**tabellen.abkuerzungen, **tabellen.satzende}
    if formen:
        text = _versalien_aus_dokument(text, formen)
    text = _versalien_lesbar(text, {*alle, *tabellen.einheiten})

    def ersatz(treffer: re.Match[str]) -> str:
        schluessel = reihenfolge[int(treffer.lastgroup[1:])]  # type: ignore[index]
        wort = alle[schluessel]
        if treffer.group(0)[0].isupper() and schluessel[0].islower():
            wort = wort[0].upper() + wort[1:]
        # Am Absatzende schliesst der Punkt jede Abkuerzung den Satz ("... sieben Std.").
        # Eine Abkuerzung ohne Punkt ("UA") hat keinen, den es zu retten gaebe.
        if schluessel.endswith(".") and (
            _ABSATZENDE.match(treffer.string, treffer.end())
            or (
                schluessel in tabellen.satzende and _NEUER_SATZ.match(treffer.string, treffer.end())
            )
        ):
            wort += "."
        return wort

    return muster.sub(ersatz, text)


_ADRESSE = re.compile(r"(?:https?://|www\.)[^\s<>\"]+")
_ADRESSE_ENDE = ".,;:!?)]}»\"”'"
_HOCHZAHL = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+")
_STRICHE = "\N{EN DASH}\N{EM DASH}"
_SONDERLEERRAUM = "\N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE}"
_FUSSNOTE = re.compile(r"\[\d{1,3}\]")
# "&" als Wort ("3. & 4. Konzert"), nicht mitten in einem Namen ("AT&T").
_UND_ZEICHEN = re.compile(r"(?<=\s)&(?=\s)")
_PAUSEN_ENDE = ".,;:!?"
# Gedankenstrich-Paar um einen Einschub. Vor dem oeffnenden Strich darf keine Ziffer
# stehen ("5 bis 10" ist ein Bereich, kein Einschub), im Einschub kein Satzende.
_EINSCHUB = re.compile(
    rf"(?<!\d)\s[{_STRICHE}]\s([^.!?{_STRICHE}]+?)\s?[{_STRICHE}](\s|(?=[.,;:!?)]|$))"
)


def _adresse_sprechbar(treffer: re.Match[str]) -> str:
    adresse = treffer.group(0)
    rest = ""
    while adresse and adresse[-1] in _ADRESSE_ENDE:
        rest = adresse[-1] + rest
        adresse = adresse[:-1]
    adresse = re.sub(r"^(?:https?://)?(?:www\.)?", "", adresse)
    domain = re.split(r"[/?#:]", adresse, maxsplit=1)[0]
    return domain.replace(".", " Punkt ") + rest


def _pausen(text: str) -> str:
    """Der senkrechte Strich ("SA 17. OKT | 19:30 UHR") ist eine Pause: ein Komma.

    Am Rand und doppelt wird er nicht zum Komma, und endet das Stueck davor schon mit
    einem Satzzeichen, kommt kein zweites dazu.
    """
    ergebnis = ""
    for teil in (t.strip() for t in text.split("|")):
        if not teil:
            continue
        if ergebnis:
            ergebnis += (" " if ergebnis.endswith(tuple(_PAUSEN_ENDE)) else ", ") + teil
        else:
            ergebnis = teil
    return ergebnis


def _einschub(treffer: re.Match[str]) -> str:
    einschub = treffer.group(1).strip()
    return f", {einschub}, " if treffer.group(2) else f", {einschub}"


_AUSLASSUNG = re.compile(r"[(\[](?:…|\.{3})[)\]]\s*")


def saeubere(text: str) -> str:
    """Schreibweisen, die der Hoerer nicht mitlesen kann, so umformen, dass sie klingen.

    Heilt Silbentrennung am Zeilenende, kuerzt Webadressen auf die Domain ("beispiel
    Punkt de" -- mit Punkt, weil "beispiel.de" von der Stimme unvorhersehbar gelesen
    wird und die Satzteilung an Punkten ansetzt), entfernt Fussnotenzeichen und macht
    aus einem Gedankenstrich-Paar um einen Einschub Kommas; "&" wird "und", der senkrechte
    Strich eine Pause.
    """
    text = re.sub(r"(?<=[a-zäöüß])-[ \t]*\n[ \t]*(?=[a-zäöüß])", "", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = _ADRESSE.sub(_adresse_sprechbar, text)
    text = _pausen(_UND_ZEICHEN.sub("und", text))
    text = _HOCHZAHL.sub("", text)
    text = _FUSSNOTE.sub("", text)
    text = _EINSCHUB.sub(_einschub, text)
    # Auslassungszeichen eines Zitats ("„(…) sind", "[...]"): nicht hoerbar, sonst ein
    # eigenes Stueck "(…)", an dem die Stimme scheitert.
    text = _AUSLASSUNG.sub("", text)
    text = re.sub(rf"[ \t{_SONDERLEERRAUM}]+", " ", text).strip()
    return re.sub(r" +(?=[.,;:!?])", "", text)
