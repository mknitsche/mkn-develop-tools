"""Schreibt die gewonnenen Angaben in die Dateien — der Schritt, der dem Baum
seinen Namen gibt.

**Warum dieses Modul entstanden ist.** Am 2026-08-30 lief die Pipeline ueber
1.293 Aufnahmen und legte 2.520 Dateien in einem Ordner namens "03 Bilder
angereichert" ab. Darin: 1.227 RAW-Dateien und 139 XMP-Sidecars — genau die 139,
die schon vorher existierten. Kein einziger neuer. Die gesamte Ortsarbeit lag im
Arbeitsspeicher und war mit dem Prozessende verloren. KT-1 hat es sofort gesehen:
*"bei den dateien auf 1tb fehlen systemisch die xmps"*.

Eine Zahl wie "91 % verortet" ist wahr ueber die Rechnung und wertlos ueber das
Ergebnis, solange sie in keiner Datei steht.

**Wohin geschrieben wird, entscheidet das Format** (Spec § 10):

    NEF, RAF     XMP-Sidecar daneben — das Original bleibt bitgleich
    JPEG, HEIC   eingebettet — fuer diese Formate gibt es keine Sidecar-Konvention

**Nie beides fuer dieselbe Datei.** Zwei Traeger derselben Aussage sind zwei
Zustaende ueber eine Sache. Ein RAW+JPEG-Paar bekommt deshalb einen Sidecar
(zur RAW) UND eine Einbettung (ins JPEG) — das sind zwei Dateien, nicht zwei
Traeger fuer eine.

**Ohne belegten Ort wird kein Ort geschrieben.** Serie und Technik gehen
trotzdem hinein; sie stehen fest, auch wenn der Ort offen ist.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from mkn_foto.modell import Aufnahme, Ort, Serie
from mkn_foto.urheber import Urheber

SIDECAR = ".xmp"

ZWEI_SCHREIBER = """\
**In dieselben Dateien schreiben ZWEI Stellen: `anreichern.schreibe` und
`motivlauf._merke`. Jede Regel ueber den Dateiinhalt muss BEIDE erreichen.**

Dreimal in einer Nacht ist genau das misslungen, jedes Mal in derselben Form --
eine Regel an einer Stelle eingebaut, die zweite stehengelassen:

1. die Traeger-Regel (Sidecar gegen eingebettet): in `schreibe` richtig, in
   `_merke` nicht -- 71 ueberzaehlige Dateien;
2. die Marken-Pruefung (Anfang statt Teilstring): im eingebetteten Zweig
   repariert, im Sidecar-Zweig nicht -- 1.227 Aufnahmen haetten nie ein Urteil
   bekommen;
3. der Dedupe (`ohne_wiederholung`): in `_argumente` eingebaut, in `_merke`
   nicht -- und dort heilt der Schaden nicht, weil die Wiederaufnahme ein Urteil
   ohne Motive liefert.

Deshalb sind `setze` und `ohne_wiederholung` oeffentlich: sie sind gemeinsames
Gut beider Schreiber, kein Innenleben dieses Moduls. Wer eine neue Regel ueber
Datei-Inhalte einbaut, sucht zuerst die zweite Stelle."""

WERKZEUG = "mkn-foto"
"""Was in `xmp:CreatorTool` steht — zusammen mit der Version.

**Warum das kein Schmuck ist.** KT-1 am 2026-08-30: *"nicht das alte staende
der sw die duemmer waren als die aktuellen versionen die gesamte arbeit negativ
beeinflussen"*. Eine Versionsnummer im Repository beantwortet das nicht -- sie
sagt, was HEUTE gilt, nicht, welcher Stand die Datei vor drei Wochen angefasst
hat.

Ohne diese Angabe ist ein Baum aus mehreren Laeufen nicht auseinanderzuhalten.
Genau daran scheiterte es an diesem Tag: es war nicht erkennbar, welche Datei
von welchem Stand stammte, und die einzige sichere Antwort war, alles zu
loeschen und neu zu rechnen. Ein Feld haette das erspart.

`xmp:CreatorTool` ist das dafuer vorgesehene Feld, kein Eigenbau."""

FARBE = "Blue"
"""Die einzige Farbe, die das Werkzeug vergibt. Sie heisst "gehoert zu einer
Serie". Rot, Gelb und Gruen sind KT-1s Bewertungsachse (Spec § 6)."""

URGENCY = 3
"""Dieselbe Farbe in der aelteren Notation, die Capture One tatsaechlich liest.
An KT-1s Capture One 16.8.5 abgelesen: 3 ist blau (1 rot, 2 gruen, 7 gelb)."""

FARBE_UNKLAR = "Purple"
URGENCY_UNKLAR = 5
"""Violett — in der Spec die einzige bewusst unbelegte Farbe, seit dem
2026-08-30 die Kennzeichnung von Unklarheit (KT-1: *"immer wenn etwas unklar
oder fehlerhaft identifiziert ist, bekommt es ein stichwort und diese farbe —
ein stichwort kann ich zwar filtern, aber die farbe zeigt es gleich"*).

**Violett schlaegt Blau.** Ein Bild traegt nur EINE Farbe; eine unklare Aufnahme
in einer Serie kann nicht beides sein. KT-1 hat den Konflikt selbst gefunden und
die Rangfolge gesetzt. Sie ist auch sachlich richtig: die Serienzugehoerigkeit
steht DREIFACH in der Datei (Ordner, Dateiname, Stichwort) — dort ist die Farbe
nur Sichthilfe. Die Unklarheit steht sonst nirgends sichtbar."""

MOTIV = "Motiv"
"""Der Zweig fuer das, was IM Bild ist. Freies Vokabular (Spec Paragraf 6) --
der Praefix sortiert, er schraenkt nicht ein."""

PRUEFEN = "Pruefen"
"""Das Filterwort. Immer WORTGLEICH, sonst findet eine Suche nur einen Teil —
und die Liste ist unvollstaendig, ohne dass man es sieht. Der Grund haengt
hierarchisch darunter: `Pruefen|Ort`, `Pruefen|Belichtung`."""

EINGEBETTET = frozenset({".JPG", ".JPEG", ".HEIC"})
"""Formate mit eigener Metadaten-Konvention. Alles andere bekommt einen Sidecar."""


def traeger(pfad: Path) -> tuple[Path, bool]:
    """Wohin die Angaben zu dieser Datei gehoeren: `(Ziel, eingebettet)`.

    **Eine Stelle je Format -- und diese Funktion ist die eine Stelle je Regel.**
    Sie lebte vorher nur als `if`-Zweig im Schreiber, und `motivlauf._merke`
    hatte seine eigene Fassung: eine, die die Regel gar nicht kannte und ihre
    Marke blind neben JEDES Bild legte. Bei 65 JPEG ohne RAW im Bestand entstand
    so ein Sidecar neben einer Datei, in die unmittelbar danach eingebettet
    wurde -- dieselbe Aussage an zwei Stellen, was Spec Paragraf 10 ausdruecklich
    verbietet, plus 71 ueberzaehlige Dateien in KT-1s Ordner.

    Zwei Aufrufer mit derselben Frage und verschiedenen Antworten. Deshalb steht
    die Antwort jetzt hier und nicht dort.
    """
    if pfad.suffix.upper() in EINGEBETTET:
        return pfad, True
    return pfad.with_suffix(SIDECAR), False


def setze(feld: str, wert: str) -> list[str]:
    """Ein Listenwert, der genau EINMAL dasteht -- auch beim zweiten Lauf.

    `-=` und `+=` zusammen: exiftool wendet die Loeschung vor der Neuanlage an,
    das Ergebnis traegt den Wert genau einmal, und ein `-=` raeumt dabei ALLE
    vorhandenen Vorkommen ab -- der Aufruf heilt einen bestehenden Doppelbestand
    also mit. Fremde Werte im selben Feld bleiben unberuehrt; dort steht KT-1s
    Handarbeit aus Capture One, und die darf kein Lauf loeschen.

    **Die Argument-REIHENFOLGE ist dabei ohne Wirkung**, und das ist eine
    Korrektur: eine fruehere Fassung dieses Docstrings behauptete, exiftool
    arbeite die Argumente der Reihe nach ab -- mit Firsthand-Siegel. Ein Critic
    hat die Gegenprobe gefahren, die ich nicht gefahren hatte: die Mutation
    "Reihenfolge vertauscht" ueberlebte die Suite, weil beide Reihenfolgen
    Zeichen fuer Zeichen dasselbe liefern (mit Vorbestand, ohne, im zweiten
    Lauf). Das Verhalten stimmte, die Erklaerung nicht. Eine begruendete
    Vermutung mit Messsiegel ist schlimmer als eine offene Frage, weil niemand
    sie mehr nachprueft.

    Nicht abgedeckt: die Loeschung ist gross-/kleinschreibungsempfindlich. Ein
    vorhandenes `motiv|wald` und ein neues `Motiv|Wald` stehen danach
    nebeneinander.

    Ohne das entstand die Verdopplung, die KT-1s Direktive verletzte (*"alle
    inhalte muessen bei jpeg und raw gleich sein"*): `motivlauf._merke` legt die
    Motiv-Marke waehrend des Laufs an, hier wurde dieselbe danach ein zweites
    Mal angehaengt. Gemessen am Lauf ueber die 42 Nuernberger Aufnahmen: 29 von
    42 Sidecars (69 %) trugen ihre Stichworte doppelt, die JPEGs einfach.

    **Der Wert braucht keine Saeuberung, und das ist gemessen, nicht vermutet.**
    Ein Cross-Modell-Review meldete, `*`, `?` und `${...}` wuerden im `-=`-Wert
    als Platzhalter bzw. Tag-Referenz gelesen und loeschten dann mehr als sich
    selbst -- also fremde Stichworte. Nachgeprueft trifft das nicht zu:
    exiftool nimmt alle drei woertlich, auch ein fuehrendes `-`; Platzhalter
    gelten dort fuer Tag-NAMEN, nicht fuer Werte. Der daraufhin gebaute
    Schutzzweig war spekulativ und ist wieder entfernt (HC-7). Die Eigenschaft
    haengt aber an einer Fremdabhaengigkeit und wird deshalb von einem
    Charakterisierungstest festgehalten, damit eine kuenftige exiftool-Version
    sie nicht still aendert.
    """
    return [f"-{feld}-={wert}", f"-{feld}+={wert}"]


_ROH = frozenset({".NEF", ".RAF"})


class ExiftoolFehlt(RuntimeError):
    """Ohne exiftool kann nichts geschrieben werden — laut, nicht stillschweigend."""


@dataclass
class Ergebnis:
    """Was geschrieben wurde. Zahlen, keine Behauptungen."""

    sidecars: int = 0
    eingebettet: int = 0
    fehler: list[str] = field(default_factory=list)


def schreibe(
    eintraege: Sequence[tuple[Aufnahme, Ort | None]],
    *,
    serien: Iterable[Serie] = (),
    beschreibungen: dict[int, str] | None = None,
    unklar: dict[int, str] | None = None,
    motive: dict[int, tuple[str, ...]] | None = None,
    urheber_angaben: Urheber | None = None,
    farbe_serie: str = FARBE,
    farbe_unklar: str = FARBE_UNKLAR,
) -> Ergebnis:
    """Schreibt Ort, Serie, Technik und Beschreibung an jede Aufnahme.

    `eintraege` paart jede Aufnahme mit ihrem Ort — `None`, wenn er offen ist.
    `beschreibungen` bildet die Aufnahme-Identitaet auf einen Satz ab; gefuellt
    wird sie ab V2 vom Modell, der Pfad steht schon hier.
    """
    beschreibungen = beschreibungen or {}
    unklar = unklar or {}
    motive = motive or {}
    stichworte_je_aufnahme = _stichworte(eintraege, serien)
    # Was das Modell gesehen hat, kommt als eigener Zweig dazu -- freies
    # Vokabular, wie die Spec es verlangt (Paragraf 6: 'Motiv nimmt, was im
    # Bild ist; der Zweig ist ein Praefix zum Sortieren, keine Schranke').
    for kennung, worte in motive.items():
        stichworte_je_aufnahme.setdefault(kennung, []).extend(f"{MOTIV}|{w}" for w in worte)
    in_serie = {id(a) for s in serien for a in s.aufnahmen}
    ergebnis = Ergebnis()

    for aufnahme, ort in eintraege:
        stichworte = stichworte_je_aufnahme.get(id(aufnahme), [])
        for pfad in aufnahme.dateien.values():
            ziel, ist_eingebettet = traeger(pfad)
            argumente = _argumente(
                ort,
                stichworte,
                beschreibung=beschreibungen.get(id(aufnahme)),
                serienbild=id(aufnahme) in in_serie,
                # NICHT noch einmal selbst entscheiden: `traeger` oben hat die
                # Frage bereits beantwortet. Eine zweite Fassung derselben Regel
                # im selben Block ist genau der Fehler, den dieser Commit
                # behebt -- nur eine Zeile weiter unten.
                eingebettet=ist_eingebettet,
                unklar_grund=unklar.get(id(aufnahme)),
                urheber_angaben=urheber_angaben,
                jahr=aufnahme.zeitpunkt.year if aufnahme.zeitpunkt else None,
                farbe_serie=farbe_serie,
                farbe_unklar=farbe_unklar,
            )
            if not argumente:
                continue
            if ist_eingebettet:
                extra = ["-overwrite_original"]
                zaehler = "eingebettet"
            else:
                # `-overwrite_original`: sonst legt exiftool neben JEDEN
                # vorhandenen Sidecar eine `.xmp_original`. Nach einem Lauf ueber
                # 1.234 Aufnahmen lagen 1.228 solcher Kopien in KT-1s
                # Bilderordner -- klein (2,5 MB), aber genau das, was er
                # verboten hatte, und wer den Ordner oeffnet, sieht doppelt so
                # viele Dateien wie Bilder.
                #
                # Die Sicherung ist hier auch sachlich ueberfluessig: der
                # Zielbaum IST bereits die Kopie, die Originale werden nie
                # angefasst.
                extra = ["-overwrite_original"]
                zaehler = "sidecars"
                # Ein vorhandener Sidecar wird ERGAENZT, nie ersetzt: dort steht
                # oft die Handarbeit aus Capture One.
                if not ziel.exists():
                    extra = ["-o", str(ziel)]
                    ziel = None

            if _ruf_exiftool(argumente + extra, ziel):
                setattr(ergebnis, zaehler, getattr(ergebnis, zaehler) + 1)
            else:
                ergebnis.fehler.append(str(pfad))

    return ergebnis


def _argumente(
    ort: Ort | None,
    stichworte: Sequence[str],
    *,
    beschreibung: str | None = None,
    serienbild: bool = False,
    eingebettet: bool = False,
    unklar_grund: str | None = None,
    urheber_angaben: Urheber | None = None,
    jahr: int | None = None,
    farbe_serie: str = FARBE,
    farbe_unklar: str = FARBE_UNKLAR,
) -> list[str]:
    """Baut die exiftool-Argumente nach der Traeger-Tabelle der Spec § 6.

    Ohne Ort keine Koordinate — im Zweifel schreibt das Werkzeug nichts, statt
    etwas Ungefaehres zu behaupten.
    """
    from mkn_foto import __version__

    # An JEDER Datei, unabhaengig davon, was sonst bekannt ist: die Frage
    # "welcher Stand hat das geschrieben" muss immer beantwortbar sein.
    args: list[str] = [f"-XMP-xmp:CreatorTool={WERKZEUG} {__version__}"]

    if urheber_angaben is not None:
        # Der Urheber steht an JEDER Datei, unabhaengig davon, ob Ort, Serie
        # oder Motiv bekannt sind. Er haengt nicht am Erkenntnisstand.
        args += urheber_angaben.argumente(jahr=jahr, eingebettet=eingebettet)

    if ort is not None:
        args += [
            f"-GPSLatitude={abs(ort.lat)}",
            f"-GPSLatitudeRef={'N' if ort.lat >= 0 else 'S'}",
            f"-GPSLongitude={abs(ort.lon)}",
            f"-GPSLongitudeRef={'E' if ort.lon >= 0 else 'W'}",
            # Ohne Fehlerangabe behauptet eine Koordinate eine Genauigkeit, die
            # sie nicht hat.
            f"-GPSHPositioningError={ort.radius_m}",
        ]
        if ort.name:
            # Der SPOT gehoert nach iptcCore:Location (Capture-One-Anzeige
            # gemessen, Spec § 13.10) und LocationShownSublocation. Meine erste
            # Fassung schrieb ihn nach `photoshop:City` -- das ist nach der
            # Traeger-Tabelle das Feld fuer das GEBIET, nicht fuer den Spot.
            args += [
                f"-XMP-iptcCore:Location={ort.name}",
                f"-XMP-iptcExt:LocationShownSublocation={ort.name}",
            ]
            if eingebettet:
                # IIM traegt nur ein eingebettetes Format. Im XMP-Sidecar meldet
                # exiftool "Nothing to write" -- firsthand geprueft 2026-08-30.
                args.append(f"-IPTC:Sub-location={ort.name}")

    if unklar_grund:
        # Violett schlaegt Blau: ein Bild traegt nur eine Farbe, und die
        # Unklarheit ist die Information, die sonst nirgends sichtbar steht.
        args += [f"-XMP:Label={farbe_unklar}", f"-XMP-photoshop:Urgency={URGENCY_UNKLAR}"]
        if eingebettet:
            args.append(f"-IPTC:Urgency={URGENCY_UNKLAR}")
        # Das Filterwort und der Grund darunter -- beide, weil das eine filtert
        # und das andere erklaert.
        args += (
            setze("XMP-dc:Subject", PRUEFEN)
            + setze("XMP-lr:HierarchicalSubject", PRUEFEN)
            + setze("XMP-dc:Subject", unklar_grund)
            + setze("XMP-lr:HierarchicalSubject", f"{PRUEFEN}|{unklar_grund}")
        )
    elif serienbild:
        # ZWEIMAL, und das ist keine Vorsicht: Capture One liest `xmp:Label`
        # nicht, sondern die aeltere Notation `photoshop:Urgency`. Dort ist 3
        # die blaue -- an KT-1s Capture One 16.8.5 abgelesen. Wer nur `Label`
        # setzt, zeigt in Lightroom Farben und in Capture One nichts.
        #
        # Blau gehoert dem Werkzeug und heisst "gehoert zu einer Serie". Rot,
        # Gelb und Gruen sind KT-1s Bewertungsachse und werden nie angefasst.
        args += [f"-XMP:Label={farbe_serie}", f"-XMP-photoshop:Urgency={URGENCY}"]
        if eingebettet:
            args.append(f"-IPTC:Urgency={URGENCY}")

    if beschreibung:
        args.append(f"-XMP-dc:Description={beschreibung}")

    for wort in stichworte:
        args += setze("XMP-dc:Subject", wort.split("|")[-1])
        args += setze("XMP-lr:HierarchicalSubject", wort)

    return ohne_wiederholung(args)


def ohne_wiederholung(args: list[str]) -> list[str]:
    """Dasselbe Argument zweimal ist einmal zu viel.

    **`_setze` macht ein Stichwort idempotent gegenueber einem VORBESTAND, nicht
    innerhalb eines Aufrufs.** Steht dasselbe Feld-Wert-Paar zweimal in
    derselben exiftool-Zeile, entstehen zwei Kopien -- und der Schaden heilt
    nicht von selbst, ein zweiter Lauf laesst sie stehen.

    Erreichbar auf zwei Wegen, beide gemessen: ein Vision-Modell nennt ein Motiv
    doppelt (die Kette dedupliziert an keiner Station), oder zwei verschiedene
    Zweige liefern dasselbe BLATT fuer `dc:Subject` -- `Technik|Einzelbild` und
    ein Motiv `Einzelbild` ergeben beide `Einzelbild`, ganz ohne doppelte
    Eingabe.

    Damit haette ausgerechnet der Fix, der KT-1s doppelte Stichworte beheben
    soll, sie auf einem anderen Weg weiter erzeugt. Gefunden vom Critic.

    Die Reihenfolge bleibt erhalten (`dict.fromkeys`), damit Argumentlisten
    stabil und Diffs reproduzierbar sind -- **nicht, weil sie bei exiftool etwas
    bewirkte.** Genau das behauptete die erste Fassung dieses Absatzes, woertlich
    dieselbe Aussage, die `setze` zwanzig Zeilen darueber gerade korrigiert
    hatte. Der Critic hat sie mit einer Mutation erledigt: `sorted(set(args))`
    zerstoert die Reihenfolge vollstaendig, und die Suite bleibt gruen.

    Die widerlegte Begruendung war beim Umschreiben eine Funktion weiter
    gewandert. Das ist der Grund, warum sie hier ausdruecklich steht statt
    stillschweigend ersetzt zu werden.
    """
    return list(dict.fromkeys(args))


EINZELN = "Technik|Einzelbild"
"""Das Stichwort fuer eine Aufnahme, die zu keiner Serie gehoert.

Es sorgt dafuer, dass JEDE Aufnahme etwas zu schreiben hat und damit einen
Sidecar bekommt. Ohne es blieben genau die Bilder ohne Sidecar, die weder Ort
noch Serie haben -- nach dem Lauf vom 2026-08-30 waeren das rund 112 gewesen,
und KT-1 haette zu Recht wieder "systemisch fehlen die xmps" gesagt.

Die Angabe ist wahr, nicht bloss Fuellung: ein Bild, das zu keiner Reihe
gehoert, IST ein Einzelbild, und das ist eine Technik-Aussage wie "Panorama"."""


def _stichworte(
    eintraege: Sequence[tuple[Aufnahme, Ort | None]], serien: Iterable[Serie]
) -> dict[int, list[str]]:
    """Ordnet jeder Aufnahme ihre hierarchischen Stichworte zu."""
    zuordnung: dict[int, list[str]] = {}
    for s in serien:
        # Mit Datum: `2026-08-26-pan01`. Ohne es kollidiert `pan01` vom 26.08.
        # mit `pan01` vom 27.08., und der Stichwortbaum wirft beide zusammen.
        tag = s.aufnahmen[0].zeitpunkt.date() if s.aufnahmen else None
        marke = f"{tag}-{s.typ}{s.nummer:02d}" if tag else f"{s.typ}{s.nummer:02d}"
        for a in s.aufnahmen:
            zuordnung.setdefault(id(a), []).extend([f"Serie|{marke}", f"Technik|{s.typ}"])
    for aufnahme, _ in eintraege:
        zuordnung.setdefault(id(aufnahme), [EINZELN])
    return zuordnung


def _ruf_exiftool(argumente: list[str], ziel: Path | None) -> bool:
    befehl = ["exiftool", "-q", "-m", *argumente]
    if ziel is not None:
        befehl.append(str(ziel))
    try:
        fertig = subprocess.run(befehl, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise ExiftoolFehlt(
            "exiftool ist nicht installiert — ohne es kann nichts geschrieben werden."
        ) from exc
    return fertig.returncode == 0
