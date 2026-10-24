"""Zahlen, Daten, Uhrzeiten und Einheiten so ausschreiben, wie man sie spricht.

**Warum Regeln und kein Sprachmodell.** Eine Zahl falsch zu sprechen ist der Fehler,
den ein Hoerer am sichersten merkt und am wenigsten verzeiht ("neunzehnhundertneunzig"
gegen "eintausendneunhundertneunzig"). Ein Modell darf Zahlen deshalb nie anfassen
(`pruefen.py` verlangt, dass jede hier ausgeschriebene Zahl unveraendert bleibt); sie
entstehen ausschliesslich in diesem Modul, nachvollziehbar und mit Tests.

**Was bewusst vereinfacht ist.** Datumsangaben stehen im Dativ ("am zwoelften
Oktober"): im Satz ohne Praeposition ("Der 12. Oktober war ...") waere es "zwoelfte",
aber der Dativ ist der haeufige Fall, und ein Satzbau-Parser waere fuer diese
Unterscheidung unverhaeltnismaessig. Die eine Ausnahme ist die Programmzeile
("SA 17. OKT 26 | 19:30 UHR"): dort steht das Datum fuer sich, ohne Praeposition, und
wird im Nominativ gelesen ("siebzehnter Oktober"), solange kein "am" davorsteht -- ein
Wochentags- oder Monatskuerzel in Versalien ist das Merkmal, dass es eine solche Zeile
ist. Bei zwei Ordnungszahlen vor einem Hauptwort ("3. und 4. Konzert") ist das
Geschlecht des Hauptworts nicht bekannt; die Endung seines ersten Worts entscheidet
(siehe `_paar_endung`), sonst gilt das Neutrum. Was keine Regel trifft (Zahl an Buchstaben wie
"3a" oder "5G", fuehrende Null, ueber 15 Stellen), bleibt als Ziffer stehen; `hoertext()`
meldet es dann im Bericht, statt es zu raten.
"""

from __future__ import annotations

import re
from functools import cache

from num2words import num2words

from mkn_audio.hoertext.abkuerzungen import lade_tabellen

_MONATE = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)
# Woerter, vor denen "12." eine Ordnungszahl ist und kein Satzende ("im 20. Jahrhundert").
_ORDNUNGS_FOLGEWOERTER = (
    "Jahrhundert",
    "Jahrtausend",
    "Platz",
    "Klasse",
    "Geburtstag",
    "Stock",
    "Auflage",
    "Mal",
)
_ZIFFER = {
    "0": "null",
    "1": "eins",
    "2": "zwei",
    "3": "drei",
    "4": "vier",
    "5": "fünf",
    "6": "sechs",
    "7": "sieben",
    "8": "acht",
    "9": "neun",
}
# Hinter "1" lautet es "ein" (Euro, Uhr, Jahr ...) bzw. "eine" (Million, Stunde ...).
_EIN_FOLGEWOERTER = frozenset({"Uhr", "Jahr", "Tag", "Mal", "Tausend", "Hundert"})
_EINE_FOLGEWOERTER = frozenset({"Stunde", "Minute", "Sekunde", "Woche"})
_WAEHRUNGSWOERTER = frozenset({"Euro", "Cent", "Dollar", "Prozent"})
_MAX_STELLEN = 15

_LEERRAUM = "[ \N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE}]"
_STRICH = "\N{EN DASH}"
_MINUSZEICHEN = "\N{MINUS SIGN}"
_NUMMER = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?"
_VOR = r"(?<![\w.,])"  # nicht mitten in einer anderen Zahl oder einem Wort beginnen
_NEUER_SATZ = re.compile(r"\s*$|\s+[A-ZÄÖÜ]")


def _kuerze(wort: str) -> str:
    """ "einhundert" -> "hundert", "eintausend" -> "tausend" am Wortanfang.

    num2words schreibt die Eins vor Hundert/Tausend mit; gesprochen wird sie nur,
    wenn sie betont ist. Mitten im Wort ("zweihunderteintausend") bleibt sie.
    """
    return re.sub(r"\bein(?=hundert|tausend)", "", wort)


def _kardinal(n: int) -> str:
    return _kuerze(num2words(n, lang="de"))


def _ordinal(n: int, endung: str) -> str:
    """Ordnungszahl mit der gewuenschten Endung: 12 + "er" -> "zwoelfter".

    num2words liefert die Grundform auf "-e" ("erste", "dritte", "zwoelfte", "hundertste");
    die Endung ersetzt dieses "e". Hinge man sie nur an, kaeme "ersteer" heraus.
    """
    grund = _kuerze(num2words(n, lang="de", to="ordinal"))
    return grund[:-1] + endung


def _ordinal_dativ(n: int) -> str:
    """ "zwoelf" -> "zwoelften" (die Form hinter am/im/zum/der)."""
    return _ordinal(n, "en")


def _jahr(n: int) -> str:
    """1100-1999 wird als Jahr gelesen ("neunzehnhundert..."), sonst als Zahl."""
    if 1100 <= n <= 1999:
        return num2words(n, lang="de", to="year")
    return _kardinal(n)


def _ganzzahl(ziffern: str) -> int | None:
    """Wert, oder None, wo die Regel nicht greift (fuehrende Null, zu lang)."""
    if len(ziffern) > _MAX_STELLEN or (len(ziffern) > 1 and ziffern.startswith("0")):
        return None
    return int(ziffern)


@cache
def _einheitswoerter() -> frozenset[str]:
    """Erstes Wort jeder Einheit ("Grad" aus "Grad Celsius") plus Waehrungswoerter."""
    erste = {wort.split()[0] for wort in lade_tabellen().einheiten.values()}
    return frozenset(erste | _WAEHRUNGSWOERTER)


def _eins(folgewort: str) -> str:
    if folgewort.startswith(("Million", "Milliarde", "Billion")) or (
        folgewort in _EINE_FOLGEWOERTER
    ):
        return "eine"
    if folgewort in _EIN_FOLGEWOERTER or folgewort in _einheitswoerter():
        return "ein"
    return "eins"


def _zahl_zu_worten(roh: str, folgewort: str) -> str | None:
    """Eine geschriebene Zahl ("1.234,5") als Worte; None, wo keine Regel greift."""
    ganz, komma, nachkomma = roh.partition(",")
    tausender = "." in ganz
    ziffern = ganz.replace(".", "")
    n = _ganzzahl(ziffern)
    if n is None:
        return None
    if komma:
        # Nach dem Komma wird ziffernweise gelesen: "0,05" -> "null Komma null fuenf".
        return f"{_kardinal(n)} Komma " + " ".join(_ZIFFER[z] for z in nachkomma)
    ist_jahr = (
        not tausender
        and len(ziffern) == 4
        and 1100 <= n <= 1999
        and folgewort not in _einheitswoerter()
    )
    if ist_jahr:
        return _jahr(n)
    if n == 1:
        return _eins(folgewort)
    return _kardinal(n)


def _folgewort(rest: str) -> str:
    treffer = re.match(r"\s*(\w+)", rest)
    return treffer.group(1) if treffer else ""


# --- Daten -----------------------------------------------------------------------------

_ISO_DATUM = re.compile(r"(?<![\w.-])(\d{4})-(\d{2})-(\d{2})(?![\w-])")
_PUNKT_DATUM = re.compile(
    rf"{_VOR}(?<!Version )(?<!Abschnitt )(\d{{1,2}})\.(\d{{1,2}})\."
    rf"(?:(\d{{4}}|\d{{2}})(?!\d)(?!\.\d))?(?!\w)"
)
_MONATS_ORDINAL = re.compile(rf"{_VOR}(\d{{1,2}})\. ({'|'.join(_MONATE)})(?!\w)")
# Bis vier Stellen, damit auch "zum 1000. Mal" eine Ordnungszahl wird.
_ORDNUNGSWORT = re.compile(rf"{_VOR}(\d{{1,4}})\. ({'|'.join(_ORDNUNGS_FOLGEWOERTER)})(?!\w)")


def _datum(tag: int, monat: int, jahr: int | None, endung: str = "en") -> str | None:
    if not (1 <= monat <= 12 and 1 <= tag <= 31):
        return None
    teile = [_ordinal(tag, endung), _MONATE[monat - 1]]
    if jahr is not None:
        teile.append(_jahr(jahr))
    return " ".join(teile)


def _iso_datum(m: re.Match[str]) -> str:
    return _datum(int(m[3]), int(m[2]), int(m[1])) or m[0]


def _punkt_datum(m: re.Match[str]) -> str:
    jahr = int(m[3]) if m[3] else None
    if m[3] and len(m[3]) == 2 and m[3].startswith("0"):  # "1.2.05": "null fuenf"
        text = _datum(int(m[1]), int(m[2]), None)
        return m[0] if text is None else f"{text} null {_kardinal(int(m[3]))}"
    text = _datum(int(m[1]), int(m[2]), jahr)
    if text is None:
        return m[0]
    # Ohne Jahr ist der letzte Punkt auch Satzzeichen, wenn ein neuer Satz folgt.
    if jahr is None and _NEUER_SATZ.match(m.string, m.end()):
        text += "."
    return text


def _monats_ordinal(m: re.Match[str]) -> str:
    tag = int(m[1])
    return f"{_ordinal_dativ(tag)} {m[2]}" if 1 <= tag <= 31 else m[0]


def _ordnungswort(m: re.Match[str]) -> str:
    return f"{_ordinal_dativ(int(m[1]))} {m[2]}" if int(m[1]) > 0 else m[0]


# --- Ordnungszahl hinter Artikel, Ziffern im Wort, Herrschernamen ----------------------

# Woerter, mit denen nach "der 3." eher ein neuer Satz beginnt als ein Hauptwort folgt.
_SATZANFAENGE = (
    "Dann", "Danach", "Da", "Dort", "Hier", "Nun", "Jetzt", "Auch", "Aber", "Doch", "Und",
    "Oder", "Denn", "So", "Er", "Sie", "Es", "Ich", "Wir", "Ihr", "Man", "Der", "Die", "Das",
    "Ein", "Eine", "Dies", "Diese", "Dieser", "Wenn", "Als", "Wie", "Was", "Wer", "Später",
    "Am", "Im", "Zum", "Vom", "Beim", "In", "An", "Auf", "Mit", "Nach", "Vor", "Bei", "Für",
    "Bis", "Seit", "Dabei", "Daher", "Deshalb", "Also", "Zudem", "Außerdem", "Schon", "Erst",
    "Noch", "Nur", "Heute", "Damals", "Darauf", "Dazu",
)  # fmt: skip
# "Im 8. Haus", "das 3. Kapitel": hinter Artikel oder Verschmelzung und vor einem Hauptwort ist
# die Zahl mit Punkt eine Ordnungszahl, kein Satzende ("Im acht." / "Haus." entstand sonst).
_ARTIKEL_ORDINAL = re.compile(
    r"(?<!\w)(im|am|zum|vom|beim|ins|dem|den|des|der|die|das)\s+(\d{1,4})\.\s+"
    rf"(?=[A-ZÄÖÜ])(?!(?:{'|'.join(_SATZANFAENGE)})(?!\w))",
    re.IGNORECASE,
)


def _artikel_ordinal(m: re.Match[str]) -> str:
    endung = "e" if m[1].lower() in ("der", "die", "das", "ins") else "en"
    return f"{m[1]} {_ordinal(int(m[2]), endung)} " if int(m[2]) > 0 else m[0]


# "1970er Jahre" -> "neunzehnhundertsiebziger"; danach Ziffern am Wort abtrennen, damit die
# Zahlenregel sie liest: "CO2" -> "CO 2", "5G" -> "5 G" ("2er" bleibt: Zahlwort plus "er").
_JAHRZEHNT = re.compile(r"(?<!\w)(1[0-9]|20)(\d)0(ern?s?)(?!\w)")
# "m2", "km3": Flaeche und Raum, bevor die Ziffer abgetrennt wird ("Meter zwei" sonst).
_FLAECHE = re.compile(r"(?<!\w)([kcdm]?)m([23])(?!\w)")
_LAENGE = {"": "meter", "k": "kilometer", "c": "zentimeter", "d": "dezimeter", "m": "millimeter"}
# "3fache", "30jährige": Zahl und angehaengte Endung sind ein Wort.
_ZAHL_ENDUNG = re.compile(
    r"(?<!\w)(\d{1,4})((?:fach|jährig|mal|malig|tägig|wöchig|monatig|stündig|minütig|köpfig"
    r"|seitig|teilig|stellig|prozentig|stöckig|sprachig|farbig|zimmer|eck|zeiler)[a-zäöüß]*)(?!\w)"
)
# "1.FC": Ordnungszahl vor einem Kuerzel bekommt ihr Leerzeichen, die Regeln danach lesen sie.
_ORDNUNG_VOR_KUERZEL = re.compile(r"(?<![\w.])(\d{1,2})\.(?=[A-ZÄÖÜ]{2,4}(?!\w))")
_ZIFFER_HINTER_BUCHSTABE = re.compile(r"(?<=[^\W\d_])(\d+)")
_ZIFFER_VOR_BUCHSTABE = re.compile(r"(?<!\w)(\d+)(?=[^\W\d_])(?!er(?!\w))")


# Folgen, die keine Zahl im ueblichen Sinn sind: Bibelstelle "9,16,12" (zwei Kommas sind kein
# Dezimalbruch), Version "2.1.3" (Gruppen nach dem ersten Punkt hoechstens zweistellig, sonst
# Tausenderpunkte oder IP-Adresse), Vorwahl "0911" (fuehrende Null wird Ziffer fuer Ziffer gelesen).
_KOMMA_FOLGE = re.compile(r"(?<![\w,])\d+(?:,\d+){2,}(?![\w,])")
_PUNKT_FOLGE = re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,2}){2,}(?![\w.]|\.\d)")
_FUEHRENDE_NULL = re.compile(r"(?<![\w.,])0\d+(?![\w.,]\d)")
_ZIFFERN = ("null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun")


def _ziffernweise(m: re.Match[str]) -> str:
    if len(m[0]) == 2:  # "08 bis 17 Uhr": Stunde oder Tag, keine Kennung
        return _kardinal(int(m[0]))
    return " ".join(_ZIFFERN[int(z)] for z in m[0])


# Telefon und Fax: alle Gruppen Ziffer fuer Ziffer ("0911 123456" ist keine Zahl).
_TELEFON = re.compile(r"(?<!\w)(Telefon|Fax|Mobil|Handy)(:?\s+)(\+?\d[\d /-]*\d)")


def _telefon(m: re.Match[str]) -> str:
    ziffern = " ".join(_ZIFFERN[int(z)] for z in m[3] if z.isdigit())
    return f"{m[1]}{m[2]}{'plus ' if m[3].startswith('+') else ''}{ziffern}"


def _jahrzehnt(m: re.Match[str]) -> str:
    return _jahr(int(f"{m[1]}{m[2]}0")) + m[3]


def trenne_ziffern(text: str) -> str:
    """Ziffern, die an Buchstaben kleben, lesbar machen -- VOR den Abkuerzungen ("5Mrd.").

    "1970er" -> "neunzehnhundertsiebziger", "m2" -> "Quadratmeter", "3fache" -> "dreifache",
    dann abtrennen: "CO2" -> "CO 2", "5G" -> "5 G", "1.FC" -> "1. FC"; die Zahlenregeln lesen
    die Ziffer danach. "2er" bleibt (Zahlwort plus Endung). Idempotent: `deterministisch` ruft
    sie vor den Abkuerzungen, `ausschreiben` (eigenstaendige Schnittstelle) noch einmal.
    """
    text = _JAHRZEHNT.sub(_jahrzehnt, text)
    text = _FLAECHE.sub(lambda m: ("Quadrat" if m[2] == "2" else "Kubik") + _LAENGE[m[1]], text)
    text = _ZAHL_ENDUNG.sub(lambda m: ("ein" if m[1] == "1" else _kardinal(int(m[1]))) + m[2], text)
    text = _ORDNUNG_VOR_KUERZEL.sub(r"\1. ", text)
    text = _ZIFFER_HINTER_BUCHSTABE.sub(r" \1", text)
    return _ZIFFER_VOR_BUCHSTABE.sub(r"\1 ", text)


# "Papst Pius IX." -> "Pius der Neunte"; nach Praeposition oder "dem" der Dativ ("von Papst
# Pius dem Neunten"), nach "des" der Genitiv. Eine einzelne Ziffer (I, V, X) kann eine
# Initiale sein und bleibt; hinter Kapitel, Teil, Band ... ist es eine Zaehlung, kein Name.
_HERRSCHER = re.compile(r"(?<!\w)([A-ZÄÖÜ][a-zäöü]+) ([IVX]{2,5})\.(?=\s|$)")
# Nur hinter einem Titelwort ist es sicher ein Herrschername ("Typ II.", "Rocky II." nicht),
# und das Titelwort gibt das Geschlecht ("Königin Elisabeth die Zweite").
_TITEL_M = {"Papst", "König", "Kaiser", "Zar", "Fürst", "Herzog", "Graf", "Prinz", "Kurfürst"}
_TITEL_W = {"Königin", "Kaiserin", "Zarin", "Fürstin", "Herzogin", "Gräfin", "Prinzessin"}
_ZAEHLWOERTER = {"Kapitel", "Teil", "Band", "Abschnitt", "Akt", "Buch", "Tafel", "Anhang", "Heft"}
_DATIV_DAVOR = {
    "von",
    "vom",
    "mit",
    "bei",
    "beim",
    "nach",
    "zu",
    "zum",
    "seit",
    "aus",
    "unter",
    "dem",
}
_ROEMISCH = {"I": 1, "V": 5, "X": 10}


def _roemisch(zeichen: str, *, ab: int = 2) -> int | None:
    """Wert einer roemischen Zahl, wenn er zwischen `ab` und 39 liegt (sonst `None`)."""
    wert = 0
    for i, z in enumerate(zeichen):
        n = _ROEMISCH[z]
        wert += -n if i + 1 < len(zeichen) and _ROEMISCH[zeichen[i + 1]] > n else n
    return wert if ab <= wert <= 39 else None


# "Kapitel XII", "Röm IX,16": hinter einem Zaehlwort oder vor einer Versangabe ist die roemische
# Zahl eine Grundzahl; sie wird arabisch, die Zahlenregel liest sie danach.
_ZAEHLUNG_ROEMISCH = re.compile(rf"(?<!\w)({'|'.join(sorted(_ZAEHLWOERTER))}) ([IVX]{{1,6}})(?!\w)")
_ROEMISCH_VERS = re.compile(r"(?<!\w)([IVX]{1,6}),(\d+(?:,\d+)*)(?![\w,])")


def _arabisch(zeichen: str) -> str:
    wert = _roemisch(zeichen, ab=1)
    return zeichen if wert is None else str(wert)


def _herrscher(m: re.Match[str]) -> str:
    n = _roemisch(m[2])
    # Nur die eigene Wortgruppe: ein Titelwort oder eine Praeposition im Satz davor zaehlt nicht.
    davor = re.split(r"[.!?:;,()]", m.string[max(0, m.start() - 60) : m.start()])[-1].split()
    davor = [*davor[-3:], m[1]]
    stellen = [i for i, w in enumerate(davor) if w in _TITEL_M or w in _TITEL_W]
    if n is None or m[1] in _ZAEHLWOERTER or not stellen:
        return m[0]
    weiblich = davor[stellen[0]] in _TITEL_W
    vor_titel = davor[stellen[0] - 1].lower() if stellen[0] else ""
    if vor_titel in _DATIV_DAVOR or (weiblich and vor_titel in ("des", "der")):
        artikel, endung = ("der" if weiblich else "dem"), "en"
    elif vor_titel == "des":
        artikel, endung = "des", "en"
    else:
        artikel, endung = ("die" if weiblich else "der"), "e"
    ordnung = _ordinal(n, endung)
    rest = m.string[m.end() :]
    punkt = "." if re.match(r"\s*$|\s+[A-ZÄÖÜ„»\"]", rest) else ""
    return f"{m[1]} {artikel} {ordnung[0].upper()}{ordnung[1:]}{punkt}"


# --- Programmzeilen: "SA 17. OKT 26" -------------------------------------------------

_WOCHENTAGE = {
    "MO": "Montag",
    "DI": "Dienstag",
    "MI": "Mittwoch",
    "DO": "Donnerstag",
    "FR": "Freitag",
    "SA": "Samstag",
    "SO": "Sonntag",
}
_MONATS_KUERZEL = {
    "JAN": 1,
    "FEB": 2,
    "MÄR": 3,
    "MRZ": 3,
    "APR": 4,
    "MAI": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "SEPT": 9,
    "OKT": 10,
    "NOV": 11,
    "DEZ": 12,
}
_WOCHENTAG = "|".join(_WOCHENTAGE)
_MONATSNAMEN = "|".join(sorted([*_MONATS_KUERZEL, *_MONATE], key=len, reverse=True))
# Das Kuerzel steht in Versalien, sonst waere "so 5 Euro" ein Wochentag.
_PROGRAMM_DATUM = re.compile(
    rf"(?:(?<!\w)(?P<wt>{_WOCHENTAG}){_LEERRAUM}+)?{_VOR}(?P<tag>\d{{1,2}})\.{_LEERRAUM}?"
    rf"(?P<monat>{_MONATSNAMEN})(?!\w)"
)
_WOCHENTAG_DATUM = re.compile(
    rf"(?<!\w)(?P<wt>{_WOCHENTAG}){_LEERRAUM}+(?P<tag>\d{{1,2}})\.(?P<monat>\d{{1,2}})\."
    rf"(?:(?P<jahr>\d{{4}})(?!\d))?(?!\w)"
)
_AM_DAVOR = re.compile(r"(?<!\w)[Aa]m\s+$")
_UHR_VERSALIEN = re.compile(rf"(?<=\d)({_LEERRAUM}?)UHR(?!\w)")


def _programm_endung(m: re.Match[str]) -> str:
    """Nominativ ("er"), es sei denn ein "am" steht davor: dann der Dativ ("en")."""
    return "en" if _AM_DAVOR.search(m.string[: m.start()]) else "er"


def _programm_datum(m: re.Match[str]) -> str:
    monat = m["monat"]
    # Ohne Wochentag und ohne Kuerzel ("17. Oktober") gilt die allgemeine Regel.
    if not (m["wt"] or monat.isupper()):
        return m[0]
    nummer = _MONATS_KUERZEL.get(monat) or _MONATE.index(monat) + 1
    datum = _datum(int(m["tag"]), nummer, None, _programm_endung(m))
    if datum is None:
        return m[0]
    return f"{_WOCHENTAGE[m['wt']]}, {datum}" if m["wt"] else datum


def _wochentag_datum(m: re.Match[str]) -> str:
    jahr = int(m["jahr"]) if m["jahr"] else None
    datum = _datum(int(m["tag"]), int(m["monat"]), jahr, _programm_endung(m))
    if datum is None:
        return m[0]
    if jahr is None and _NEUER_SATZ.match(m.string, m.end()):
        datum += "."
    return f"{_WOCHENTAGE[m['wt']]}, {datum}"


# --- zwei Ordnungszahlen vor einem Hauptwort: "3. und 4. Konzert" -----------------------

_ORDNUNGS_PAAR = re.compile(rf"{_VOR}(\d{{1,2}})\. (&|und|bis) (\d{{1,2}})\. ([A-ZÄÖÜ][\w-]*)")
_DATIV_WOERTER = frozenset({*_MONATE, *_ORDNUNGS_FOLGEWOERTER})


def _paar_endung(wort: str) -> str:
    """Endung der Ordnungszahlen nach dem ersten Wort hinter ihnen.

    Das Geschlecht steht nicht im Text. Ein Adjektiv davor verraet es ("Symphonisches
    Konzert" -> Neutrum, "Symphonischer Abend" -> Maennlich); ein Hauptwort auf "-e"
    ("Sinfonie") ist fast immer weiblich. Alles andere gilt als Neutrum ("Konzert").
    """
    if wort.endswith("er"):
        return "er"
    if wort.endswith("es"):
        return "es"
    return "e" if wort.endswith("e") else "es"


def _ordnungs_paar(m: re.Match[str]) -> str:
    erste, zweite = int(m[1]), int(m[3])
    if not (erste and zweite):
        return m[0]
    und = "und" if m[2] == "&" else m[2]
    wort = m[4]
    # Vor Monat und bekannten Folgewoertern der Dativ, wie bei der einzelnen Ordnungszahl.
    endung = "en" if wort in _DATIV_WOERTER else _paar_endung(wort)
    return f"{_ordinal(erste, endung)} {und} {_ordinal(zweite, endung)} {wort}"


# --- Uhrzeiten, Betraege, Bereiche -----------------------------------------------------

_UHRZEIT = re.compile(rf"(?<![\w.,:])(\d{{1,2}})[:.](\d{{2}}){_LEERRAUM}?Uhr(?!\w)")
_EURO_CENT = re.compile(
    rf"{_VOR}(?P<ganz>\d{{1,3}}(?:\.\d{{3}})+|\d+),(?:(?P<cent>\d{{2}})|[-{_STRICH}]{{1,2}})"
    rf"{_LEERRAUM}?(?:€|EUR|Euro)(?!\w)"
)
_WAEHRUNG_DAVOR = re.compile(rf"([€$]){_LEERRAUM}?(\d+(?:\.\d{{3}})*(?:,\d+)?)")
_BEREICH = re.compile(
    rf"{_VOR}(\d+(?:[.,]\d+)*){_LEERRAUM}?{_STRICH}{_LEERRAUM}?(\d+(?:[.,]\d+)*)(?!\w)"
)
_JAHRES_BEREICH = re.compile(r"(?<![\w.,-])(1[1-9]\d\d|20\d\d)-(1[1-9]\d\d|20\d\d)(?![\w-])")
# "Bio." ist nur hinter einer Zahl Billionen ("2 Bio. Euro"); allein ist es "Bio" ("Bio. Dann").
# Es steht nicht in der Abkuerzungstabelle, die den Zusammenhang nicht kennt.
_BILLIONEN = re.compile(rf"{_VOR}((?:{_NUMMER})){_LEERRAUM}+Bio\.(?!\w)")
# Nach einer Abkuerzung wie "Mio." steht die Mehrzahl hinter der Eins: "1 Millionen".
_EINS_MEHRZAHL = re.compile(r"(?<![\w.,])1(\s+)(Million|Milliarde|Billion)(?:en|n)?(?!\w)")
# "3.5": ein Punkt zwischen kleinen Zahlen, der weder Datum noch Tausendertrenner ist
# (Version, Gliederungsnummer) -- gelesen wird er als "Punkt".
_ZAHL_PUNKT_ZAHL = re.compile(r"(?<![\w.,])(\d{1,3})\.(\d{1,2})(?!\w|[.,]\d)")
_MINUS = re.compile(rf"(?<![\w)])[-{_MINUSZEICHEN}](?=\d)")


def _billionen(m: re.Match[str]) -> str:
    # Nur am Absatzende schliesst der Punkt den Satz; "2 Bio. Euro" fuehrt weiter.
    ende = "." if re.match(r"\s*$", m.string[m.end() :]) else ""
    return f"{m[1]} Billionen{ende}"


def _uhrzeit(m: re.Match[str]) -> str:
    stunde, minute = int(m[1]), int(m[2])
    if stunde > 24 or minute > 59:
        return m[0]
    text = f"{'ein' if stunde == 1 else _kardinal(stunde)} Uhr"
    return f"{text} {_kardinal(minute)}" if minute else text


def _zahl_punkt_zahl(m: re.Match[str]) -> str:
    vorn, hinten = _zahl_zu_worten(m[1], ""), _zahl_zu_worten(m[2], "")
    return f"{vorn} Punkt {hinten}" if vorn and hinten else m[0]


def _euro_cent(m: re.Match[str]) -> str:
    euro = _ganzzahl(m["ganz"].replace(".", ""))
    if euro is None:
        return m[0]
    text = f"{'ein' if euro == 1 else _kardinal(euro)} Euro"
    if m["cent"] and int(m["cent"]):
        text += f" {_kardinal(int(m['cent']))}"
    return text


# --- die einzelne Zahl ---------------------------------------------------------------


@cache
def _zahl_muster() -> tuple[re.Pattern[str], dict[str, str]]:
    einheiten = dict(lade_tabellen().einheiten)
    alternativen = "|".join(re.escape(e) for e in sorted(einheiten, key=len, reverse=True))
    # "1 g-Moll" ist eine Tonart und kein Gramm: hinter der Einheit darf kein "-Dur"/"-Moll"
    # stehen, sonst gilt sie nicht als Einheit.
    muster = re.compile(
        rf"{_VOR}(?P<zahl>{_NUMMER})"
        rf"(?:{_LEERRAUM}?(?P<einheit>{alternativen})(?!-(?:Dur|Moll)(?!\w)))?(?!\w|[.,]\d)"
    )
    return muster, einheiten


def _zahl(m: re.Match[str]) -> str:
    _, einheiten = _zahl_muster()
    einheit = m["einheit"]
    gesprochen = einheiten[einheit] if einheit else None
    folgewort = gesprochen.split()[0] if gesprochen else _folgewort(m.string[m.end() :])
    worte = _zahl_zu_worten(m["zahl"], folgewort)
    if worte is None:
        return m[0]
    return f"{worte} {gesprochen}" if gesprochen else worte


def ausschreiben(text: str) -> str:
    """Schreibt Zahlen, Daten, Uhrzeiten, Betraege, Bereiche und Einheiten aus.

    Die Reihenfolge ist Teil der Regel: Programmzeilen und Ordnungszahl-Paare vor den
    allgemeinen Daten (sonst wuerde "SA 17. OKT" Dativ); Daten und Uhrzeiten vor den
    Zahlen, weil ihre Punkte und Doppelpunkte sonst als Dezimal- oder Tausenderzeichen
    verstanden wuerden;
    Bereiche vor der einzelnen Zahl, weil sonst jede Seite des Strichs fuer sich gelesen
    wuerde.
    """
    text = _TELEFON.sub(_telefon, text)
    text = _UHR_VERSALIEN.sub(r"\1Uhr", text)
    text = _PROGRAMM_DATUM.sub(_programm_datum, text)
    text = _WOCHENTAG_DATUM.sub(_wochentag_datum, text)
    text = _ORDNUNGS_PAAR.sub(_ordnungs_paar, text)
    text = _ISO_DATUM.sub(_iso_datum, text)
    text = _PUNKT_DATUM.sub(_punkt_datum, text)
    text = _MONATS_ORDINAL.sub(_monats_ordinal, text)
    text = _ORDNUNGSWORT.sub(_ordnungswort, text)
    text = _ARTIKEL_ORDINAL.sub(_artikel_ordinal, text)
    text = _HERRSCHER.sub(_herrscher, text)
    text = _ZAEHLUNG_ROEMISCH.sub(lambda m: f"{m[1]} {_arabisch(m[2])}", text)
    text = _ROEMISCH_VERS.sub(lambda m: ", ".join([_arabisch(m[1]), *m[2].split(",")]), text)
    text = trenne_ziffern(text)
    text = _UHRZEIT.sub(_uhrzeit, text)
    text = _KOMMA_FOLGE.sub(lambda m: ", ".join(m[0].split(",")), text)
    text = _PUNKT_FOLGE.sub(lambda m: " Punkt ".join(m[0].split(".")), text)
    text = _FUEHRENDE_NULL.sub(_ziffernweise, text)
    text = _EURO_CENT.sub(_euro_cent, text)
    text = _WAEHRUNG_DAVOR.sub(r"\2 \1", text)
    text = _BEREICH.sub(r"\1 bis \2", text)
    text = _JAHRES_BEREICH.sub(r"\1 bis \2", text)
    text = _MINUS.sub("minus ", text)
    text = _BILLIONEN.sub(_billionen, text)
    text = _EINS_MEHRZAHL.sub(r"1\1\2", text)
    text = _ZAHL_PUNKT_ZAHL.sub(_zahl_punkt_zahl, text)
    muster, einheiten = _zahl_muster()
    text = muster.sub(_zahl, text)
    # Uebrig gebliebene Zeichen ("2,4 Milliarden €": die Zahl steht nicht direkt davor).
    return re.sub(r"([€$%])", lambda m: einheiten[m[1]], text)
