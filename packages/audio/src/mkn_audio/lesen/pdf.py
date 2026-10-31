"""PDF lesen: Textebene in Lesereihenfolge, ohne Kopf- und Fusszeilen.

**Kopf- und Fusszeilen** sind Bloecke im oberen oder unteren Rand, deren Text (ohne
Ziffern) auf mindestens der Haelfte der Seiten wiederkehrt -- die Wiederkehr ist der
Beweis, dass es Seitenschmuck ist und kein Inhalt. Eine Zeile ganz oben auf einer
einzigen Seite bleibt deshalb stehen. Eine Seitenzahl allein im Rand faellt immer weg.

**Seiten ohne Textebene** (Scans) liest das Bildmodell, solange es hoechstens
`bild_seiten_max` sind, sonst tesseract: ein Scan-Buch soll nicht Hunderte Bilder an
ein Modell schicken. Eine Seite ganz ohne Text UND ohne Bild/Zeichnung ist leer und wird
uebersprungen.

**Absaetze ueber Blockgrenzen.** MuPDF beginnt ab einem gewissen Zeilenabstand einen neuen
Block, auch mitten im Satz (Seiten- und Spaltenende, grosszuegiger Zeilenabstand). Ein
Absatz wird deshalb an den vorigen gehaengt, wenn der Satz dort nicht zu Ende ist UND der
Text klein weitergeht ODER in derselben Spalte ohne Einzug, in gleicher Schrift. Die
Schrift (Groesse, fett) schuetzt Ueberschriften: eine Zeile ohne Satzzeichen, gefolgt von
Fliesstext ohne Einzug, ist eine Ueberschrift und kein halber Satz.

**Titel**: Metadaten, sonst die groesste Schrift auf der ersten Seite (ein- bis zweizeilig
und deutlich groesser als der Fliesstext), sonst der Dateiname -- ohne Zahlenanhang
("...-44179"), der sonst als "vierundvierzigtausend..." vorgelesen wuerde.

**Zweispaltige PDF ohne Lesezeichen**: ein Block oben auf der Seite, der beide Spalten ueber-
spannt, ist ein Kapiteltitel (`_seitentitel`); mehrere solche Bloecke einer Seite werden ein
Titel, die Seite beginnt ein Kapitel. Zweispaltig heisst: auf mehr als der Haelfte der Seiten
stehen Bloecke links UND rechts der Mitte.

**Ueberschriften** erkennt nur der Versalien-Lauf (`_segmente`): Zeilen ganz in Versalien am
Anfang eines Blocks, ohne Satzende dazwischen, sind EINE Ueberschrift (Art `ueberschrift`),
ueber Blockgrenzen derselben Spalte hinweg; ein Trennstrich am Zeilenende darin ist Silben-
trennung. Schriftgroesse und Fettdruck werden dafuer nicht ausgewertet -- es gibt keinen Beleg,
dass sie in Sachbuechern verlaesslich sind (`_setzt_fort` nutzt sie nur gegen halbe Saetze).

**Spalten** werden nach Position geordnet: Bloecke, die ueber die Seitenmitte reichen,
trennen Baender; in einem Band folgt die rechte Spalte der linken. Reicht das bei einem
Zeitungslayout nicht, ist das Bildmodell der bessere Leser -- das entscheidet
der Aufrufer, indem er die Seite als Bild liefert.
"""

from __future__ import annotations

import math
import re
from bisect import bisect_right
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import pymupdf

from mkn_audio.lesen import bild
from mkn_audio.lesen.text import (
    Befunde,
    Ueberschrift,
    baue_kapitel,
    normalisiere,
    pruefe_text_da,
    verbinde_zeilen,
)
from mkn_audio.sprache import hat_kleinbuchstaben
from mkn_audio.typen import Dokument, Mp4Fehler, Textmodell

RAND = 0.08
"""Anteil der Seitenhoehe oben und unten, in dem Kopf- und Fusszeilen gesucht werden."""

BILD_DPI = 150
"""Aufloesung der Seitenbilder fuer das Modell; tesseract bekommt `OCR_DPI`."""

OCR_DPI = 300

_SEITENZAHL = re.compile(
    r"^\W*(?:seite\s*)?(?:\d{1,4}|[ivxlc]{1,7})(?:\s*(?:/|von)\s*\d{1,4})?\W*$", re.IGNORECASE
)
_ZIFFERN = re.compile(r"\d+")
_SATZENDE = (".", "!", "?", "…", ":", '"', "»", "“", "”", ")")
_VERSAL_SATZENDE = (".", "!", "?", "…")
# Ein Zahlenanhang im Dateinamen ("...-44179", "..._2026-10"): eine Kennung, kein Titel. Erst ab
# vier Ziffern, damit "Kapitel-12" seine Zahl behaelt.
_ZAHLENANHANG = re.compile(r"(?:[-_\s]+\d{4,})+$")

EINZUG = 6.0
"""Ab so vielen Punkten Einzug der ersten Zeile beginnt ein neuer Absatz (ein halber Geviert)."""

SCHRIFT_TOLERANZ = 0.5
"""Zwei Bloecke gelten als gleich gross gesetzt, wenn ihre Schriften so nah beieinander liegen."""

TITEL_FAKTOR = 1.15
"""Ein Titel auf Seite 1 ist mindestens so viel groesser als der Fliesstext."""

TITEL_ZEILEN_MAX = 2
TITEL_ZEICHEN_MAX = 200

SEITENKOPF_ANTEIL = 0.25
"""Ein Block ueber beide Spalten ist ein Seitentitel, wenn er im oberen Viertel beginnt."""


@dataclass(frozen=True)
class _Block:
    seite: int  # ab 0
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    erste_x0: float  # linker Rand der ersten Zeile: der Einzug zeigt sich hier
    spalte: str  # "links", "rechts" oder "ganz" (reicht ueber die Mitte)
    groesse: float  # Schriftgroesse, die die meisten Zeichen hat
    fett: bool


@dataclass(frozen=True)
class _Absatz:
    """Ein Absatz auf dem Weg zum Kapitel; `block` ist der LETZTE Block, der in ihn einging.

    Bildmodell und Texterkennung kennen keine Geometrie (`block=None`): dort gilt nur die
    Kleinschreibung als Zeichen fuer eine Fortsetzung.
    """

    seite: int
    text: str
    block: _Block | None
    ueberschrift: bool = False


def _oeffne(pfad: Path) -> pymupdf.Document:
    try:
        doc = pymupdf.open(pfad)
    except (RuntimeError, ValueError, OSError) as fehler:
        raise Mp4Fehler(f"PDF nicht lesbar: {pfad.name} ({type(fehler).__name__})") from None
    if doc.needs_pass:
        doc.close()
        raise Mp4Fehler(f"PDF ist durch ein Passwort geschuetzt: {pfad.name}")
    return doc


def _bloecke(seite: pymupdf.Page, nr: int) -> list[_Block]:
    """Die Textbloecke einer Seite; zwei in eine Zeile verschmolzene Spalten werden getrennt.

    MuPDF fasst Zeilen auf gleicher Hoehe gern zu einem Block zusammen, auch wenn sie in
    verschiedenen Spalten stehen. Liegen in einem Block Zeilen links UND rechts der
    Mitte, wird er an diesen Stellen geteilt, sonst liefe die Lesereihenfolge quer ueber
    die Spalten.
    """
    breite = seite.rect.width
    mitte, spiel = breite / 2, breite * 0.05

    def spalte(zeile_bbox: tuple[float, ...]) -> str:
        if zeile_bbox[2] <= mitte + spiel:
            return "links"
        return "rechts" if zeile_bbox[0] >= mitte - spiel else "ganz"

    ergebnis: list[_Block] = []
    for block in seite.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        zeilen = [
            (zeile["bbox"], "".join(s["text"] for s in zeile["spans"]), _schriftmass(zeile))
            for zeile in block["lines"]
        ]
        zeilen = [(bbox, text, mass) for bbox, text, mass in zeilen if text.strip()]
        if not zeilen:
            continue
        arten = [spalte(bbox) for bbox, _t, _m in zeilen]
        gruppen: list[list[tuple[tuple[float, ...], str, Counter[tuple[float, bool]]]]] = [[]]
        for i, zeile in enumerate(zeilen):
            if i and "links" in arten and "rechts" in arten and arten[i] != arten[i - 1]:
                gruppen.append([])
            gruppen[-1].append(zeile)
        for gruppe in gruppen:
            x0, y0 = min(b[0] for b, _t, _m in gruppe), min(b[1] for b, _t, _m in gruppe)
            x1, y1 = max(b[2] for b, _t, _m in gruppe), max(b[3] for b, _t, _m in gruppe)
            mass = sum((m for _b, _t, m in gruppe), Counter())
            (groesse, fett), _n = mass.most_common(1)[0]
            ergebnis.append(
                _Block(
                    nr,
                    x0,
                    y0,
                    x1,
                    y1,
                    "\n".join(t for _b, t, _m in gruppe),
                    gruppe[0][0][0],
                    spalte((x0, y0, x1, y1)),
                    groesse,
                    fett,
                )
            )
    return ergebnis


def _schriftmass(zeile: dict) -> Counter[tuple[float, bool]]:
    """Zeichen je Schrift (Groesse auf halbe Punkte gerundet, fett) einer Zeile."""
    mass: Counter[tuple[float, bool]] = Counter()
    for span in zeile["spans"]:
        zeichen = len(span["text"].strip())
        if zeichen:
            fett = bool(span["flags"] & 16) or "bold" in span["font"].lower()
            mass[(round(span["size"] * 2) / 2, fett)] += zeichen
    return mass


def _schmuck(bloecke: list[_Block], hoehen: dict[int, float]) -> set[_Block]:
    """Die Bloecke, die Kopf-/Fusszeile oder Seitenzahl sind."""

    def im_rand(b: _Block) -> bool:
        mitte = (b.y0 + b.y1) / 2
        return mitte < RAND * hoehen[b.seite] or mitte > (1 - RAND) * hoehen[b.seite]

    def schluessel(b: _Block) -> str:
        return normalisiere(_ZIFFERN.sub("", b.text)).casefold()

    randbloecke = [b for b in bloecke if im_rand(b)]
    schwelle = max(2, math.ceil(len({b.seite for b in bloecke}) / 2))
    # Jeder Schluessel zaehlt je Seite einmal, sonst taeuscht eine doppelte Zeile Wiederkehr vor.
    wiederkehr = Counter(k for _s, k in {(b.seite, schluessel(b)) for b in randbloecke} if k)
    return {
        b
        for b in randbloecke
        if _SEITENZAHL.match(normalisiere(b.text)) or wiederkehr[schluessel(b)] >= schwelle
    }


def _ordne(bloecke: list[_Block], breite: float) -> list[_Block]:
    """Lesereihenfolge einer Seite: Baender von oben nach unten, links vor rechts."""
    mitte, spiel = breite / 2, breite * 0.05
    ergebnis: list[_Block] = []
    band: list[_Block] = []

    def leere_band() -> None:
        links = [b for b in band if b.x1 <= mitte + spiel]
        rechts = [b for b in band if b.x1 > mitte + spiel]
        if links and rechts:
            ergebnis.extend(sorted(links, key=lambda b: b.y0))
            ergebnis.extend(sorted(rechts, key=lambda b: b.y0))
        else:
            ergebnis.extend(sorted(band, key=lambda b: (b.y0, b.x0)))
        band.clear()

    for b in sorted(bloecke, key=lambda b: (b.y0, b.x0)):
        if b.x0 < mitte - spiel and b.x1 > mitte + spiel:  # ueberspannt beide Spalten
            leere_band()
            ergebnis.append(b)
        else:
            band.append(b)
    leere_band()
    return ergebnis


# Auf ein Komma oder ein solches Wort endet weder ein Satz noch eine Ueberschrift: der Satz geht
# weiter, auch ueber Spalte und Schrift hinweg ("... voruebergehen wie" | "Wolken.").
_OFFENES_ENDE = re.compile(
    r"(?:,|\b(?:wie|und|oder|aber|sondern|denn|dass|als|der|die|das|den|dem|des|ein|eine|einen"
    r"|einem|einer|mit|von|zu|zum|zur|in|im|an|am|auf|aus|bei|nach|vor|für|über|unter|durch"
    r"|gegen|ohne|um|ist|sind|war|wird|werden|hat|haben|nicht|sich|so|auch|noch))$"
)


def _setzt_fort(alt: _Absatz, neu: _Absatz) -> bool:
    """Geht der Satz aus `alt` in `neu` weiter?

    Kleinschreibung genuegt immer (auch ueber Spalten und fuer Bildseiten). Sonst muss
    es dieselbe Spalte, dieselbe Schrift und ein Anfang ohne Einzug sein: Einzug ist das
    Zeichen fuer einen neuen Absatz, eine andere Schrift das fuer eine Ueberschrift.
    """
    if alt.ueberschrift or neu.ueberschrift or alt.text.endswith(_SATZENDE):
        return False
    if neu.text[0].islower() or _OFFENES_ENDE.search(alt.text):
        return True
    a, b = alt.block, neu.block
    if a is None or b is None or a.spalte != b.spalte:
        return False
    gleiche_schrift = abs(a.groesse - b.groesse) <= SCHRIFT_TOLERANZ and a.fett == b.fett
    return gleiche_schrift and b.erste_x0 - min(a.x0, b.x0) < EINZUG


def _fuege_fortsetzungen(
    absaetze: list[_Absatz], kapitelseiten: Sequence[int] = ()
) -> list[_Absatz]:
    """Haengt einen Absatz an den vorigen, wenn der Satz dort noch nicht zu Ende ist.

    Ein Absatz, der am Block-, Seiten- oder Spaltenende abbricht, setzt sich im naechsten
    Block fort; ohne diese Naht gaebe es eine Pause mitten im Satz. Ueber den Beginn eines
    Kapitels (`kapitelseiten`, ab 0) hinweg wird nie gefuegt: der Satz gehoert dann zum
    Kapitel, in dem er beginnt, und der Rest ginge sonst dorthin mit.
    """
    ergebnis: list[_Absatz] = []
    for neu in absaetze:
        if ergebnis and _setzt_fort(ergebnis[-1], neu):
            alt = ergebnis[-1]
            if not any(alt.seite < start <= neu.seite for start in kapitelseiten):
                ergebnis[-1] = _Absatz(alt.seite, verbinde_zeilen([alt.text, neu.text]), neu.block)
                continue
        ergebnis.append(neu)
    return ergebnis


def _kapitelstarts(doc: pymupdf.Document, befunde: Befunde) -> list[tuple[int, str]]:
    """Seitenbeginn (ab 0) und Titel der obersten Lesezeichen-Ebene.

    Zwei Lesezeichen auf derselben Seite lassen sich nicht trennen (die Position im
    Text fehlt): der Text gehoert dem SPAETEREN, das fruehere hat keinen und wird
    gemeldet statt still verschluckt.
    """
    toc = [(ebene, titel, seite) for ebene, titel, seite in doc.get_toc(simple=True) if seite >= 1]
    if not toc:
        return []
    oberste = min(ebene for ebene, _t, _s in toc)
    starts: list[tuple[int, str]] = []
    for ebene, titel, seite in toc:
        if ebene != oberste:
            continue
        if starts and starts[-1][0] == seite - 1:
            befunde.warne(f"weggelassen: Ueberschrift ohne Text: {starts.pop()[1]}")
        starts.append((seite - 1, normalisiere(titel)))
    return sorted(starts)


def _ist_versalzeile(zeile: str) -> bool:
    """Eine Zeile ganz in Versalien: mindestens zwei Buchstaben, kein Kleinbuchstabe."""
    buchstaben = [z for z in zeile if z.isalpha()]
    return len(buchstaben) >= 2 and not hat_kleinbuchstaben("".join(buchstaben))


def _seitentitel(
    inhalt: list[_Block], hoehen: dict[int, float]
) -> tuple[list[tuple[int, str]], set[_Block]]:
    """Seitentitel eines zweispaltigen PDF: `[(Seite ab 0, Titel)]` und die Bloecke dahinter.

    Gesucht wird pro Seite der Block, der oben (`SEITENKOPF_ANTEIL`) beide Spalten ueberspannt;
    mehrere untereinander sind EIN Titel. Ist das PDF nicht zweispaltig (Bloecke links UND
    rechts auf mehr als der Haelfte der Seiten), gibt es keinen -- in einem einspaltigen Text
    ist ein breiter Block nur ein Absatz.
    """
    seiten = sorted({b.seite for b in inhalt})
    zweispaltig = sum(
        1 for s in seiten if {"links", "rechts"} <= {b.spalte for b in inhalt if b.seite == s}
    )
    if zweispaltig * 2 <= len(seiten):
        return [], set()
    starts: list[tuple[int, str]] = []
    bloecke: set[_Block] = set()
    for s in seiten:
        kopf = sorted(
            (
                b
                for b in inhalt
                if b.seite == s and b.spalte == "ganz" and b.y0 < SEITENKOPF_ANTEIL * hoehen[s]
            ),
            key=lambda b: b.y0,
        )
        if not kopf:
            continue
        zeilen = [z for b in kopf for z in b.text.splitlines()]
        titel = verbinde_zeilen(zeilen, versalien=all(_ist_versalzeile(z) for z in zeilen))
        starts.append((s, normalisiere(titel)))
        bloecke.update(kopf)
    return starts, bloecke


def _segmente(block: _Block) -> list[tuple[str, bool]]:
    """Zerlegt einen Block in `(Text, ist_ueberschrift)`: Versalien-Zeilen am Anfang, dann Text.

    Versalien-Zeilen am Blockanfang sind eine Ueberschrift; nach einer Zeile mit Satzende beginnt
    eine neue. Folgt kleingeschriebener Text, war die Versalien-Zeile ein Kuerzel am Satzanfang
    ("WHO" / "meldet ..."): dann ist alles Text. Versalien-Zeilen mitten im Block bleiben Text
    -- ein Kuerzel allein auf einer Zeile ist keine Ueberschrift.
    """
    zeilen = [z.strip() for z in block.text.splitlines() if z.strip()]
    n = 0
    while n < len(zeilen) and _ist_versalzeile(zeilen[n]):
        n += 1
    if n and n < len(zeilen) and zeilen[n][0].islower():
        n = 0
    if not n:
        return [(verbinde_zeilen(zeilen), False)]
    segmente: list[tuple[str, bool]] = []
    lauf: list[str] = []
    for zeile in zeilen[:n]:
        lauf.append(zeile)
        if zeile.endswith(_VERSAL_SATZENDE):
            segmente.append((verbinde_zeilen(lauf, versalien=True), True))
            lauf = []
    if lauf:
        segmente.append((verbinde_zeilen(lauf, versalien=True), True))
    if n < len(zeilen):
        segmente.append((verbinde_zeilen(zeilen[n:]), False))
    return segmente


def _seitenabsaetze(seite: int, geordnet: list[_Block]) -> list[_Absatz]:
    """Die Absaetze einer Seite in Lesereihenfolge; Versalien-Laeufe werden EINE Ueberschrift.

    Aufeinanderfolgende Ueberschriften derselben Spalte ohne Satzende dazwischen gehoeren zusammen
    (MuPDF beginnt bei grossem Zeilenabstand einen neuen Block, auch mitten in einer Ueberschrift).
    """
    absaetze: list[_Absatz] = []
    for block in geordnet:
        for text, ueberschrift in _segmente(block):
            alt = absaetze[-1] if absaetze else None
            if (
                ueberschrift
                and alt is not None
                and alt.ueberschrift
                and alt.block is not None
                and alt.block.spalte == block.spalte
                and not alt.text.endswith(_VERSAL_SATZENDE)
            ):
                absaetze[-1] = _Absatz(
                    seite, verbinde_zeilen([alt.text, text], versalien=True), block, True
                )
            else:
                absaetze.append(_Absatz(seite, text, block, ueberschrift))
    return absaetze


def _titel_aus_schrift(bloecke: list[_Block]) -> str | None:
    """Der Titel als groesste Schrift auf Seite 1; None, wo sie keiner ist.

    Es muss deutlich groesser sein als der Fliesstext (sonst waere in einem schlichten
    Dokument der erste Satz der Titel), hoechstens zwei Zeilen und kein ganzer Absatz.
    """
    if not bloecke:
        return None
    koerper = Counter[float]()
    for b in bloecke:
        koerper[b.groesse] += len(b.text)
    erste = [b for b in bloecke if b.seite == 0]
    if not erste:
        return None
    gross = max(b.groesse for b in erste)
    if gross < TITEL_FAKTOR * koerper.most_common(1)[0][0]:
        return None
    titel = sorted(
        (b for b in erste if gross - b.groesse <= SCHRIFT_TOLERANZ), key=lambda b: (b.y0, b.x0)
    )
    zeilen = [z for b in titel for z in b.text.splitlines()]
    text = normalisiere(verbinde_zeilen(zeilen))
    if len(zeilen) > TITEL_ZEILEN_MAX or len(text) > TITEL_ZEICHEN_MAX:
        return None
    return text if any(z.isalpha() for z in text) else None


def _titel_aus_dateiname(pfad: Path) -> str:
    """Dateiname ohne Zahlenanhang und mit Leerzeichen statt Bindestrichen."""

    def lesbar(name: str) -> str:
        return normalisiere(re.sub(r"[-_]+", " ", name))

    return lesbar(_ZAHLENANHANG.sub("", pfad.stem)) or lesbar(pfad.stem) or pfad.stem


def _seiten_ohne_text(
    seiten: list[pymupdf.Page], mit_text: set[int], befunde: Befunde
) -> list[int]:
    """Seiten ohne Textebene, auf denen etwas zu sehen ist; leere Seiten werden gemeldet."""
    ohne_text, leer = [], []
    for i, seite in enumerate(seiten):
        if i in mit_text:
            continue
        (ohne_text if seite.get_images() or seite.get_drawings() else leer).append(i)
    if leer:
        befunde.warne(f"leere Seiten uebersprungen: {bild.seitenliste([i + 1 for i in leer])}")
    return ohne_text


def _lies_bildseiten(
    seiten: list[pymupdf.Page],
    nummern: list[int],
    *,
    textmodell: Textmodell | None,
    ocr_sprache: str,
    bild_seiten_max: int,
    befunde: Befunde,
) -> dict[int, list[str]]:
    """Liest Seiten ohne Textebene: Bildmodell bis zur Grenze, sonst tesseract."""
    mit_modell = textmodell is not None and len(nummern) <= bild_seiten_max
    weg = "Bildmodell" if mit_modell else f"Texterkennung ({ocr_sprache})"
    befunde.warne(
        f"Seiten ohne Textebene per {weg} gelesen: {bild.seitenliste([i + 1 for i in nummern])}"
    )
    gelesen: dict[int, list[str]] = {}
    for i in nummern:
        if mit_modell:
            png = seiten[i].get_pixmap(dpi=BILD_DPI).tobytes("png")
            gelesen[i] = bild.lies_mit_modell(textmodell, png, "image/png")
        else:
            png = seiten[i].get_pixmap(dpi=OCR_DPI).tobytes("png")
            gelesen[i] = bild.lies_mit_ocr(png, ocr_sprache)
    stumm = [i + 1 for i in nummern if not any(a.strip() for a in gelesen[i])]
    if stumm:
        befunde.warne(f"ohne lesbaren Text gelesen: {bild.seitenliste(stumm)}")
    return gelesen


def lies_pdf(
    pfad: Path, *, textmodell: Textmodell | None, ocr_sprache: str, bild_seiten_max: int
) -> Dokument:
    """Liest ein PDF; Gliederung aus den Lesezeichen, sonst ein Kapitel."""
    befunde = Befunde()
    with _oeffne(pfad) as doc:
        seiten = list(doc)
        hoehen = {i: s.rect.height for i, s in enumerate(seiten)}
        alle = [b for i, s in enumerate(seiten) for b in _bloecke(s, i)]
        schmuck = _schmuck(alle, hoehen)
        if schmuck:
            befunde.warne(
                f"weggelassen: Kopf- und Fusszeilen, Seitenzahlen ({len(schmuck)} Bloecke)"
            )

        ohne_text = _seiten_ohne_text(seiten, {b.seite for b in alle}, befunde)
        gelesen = (
            _lies_bildseiten(
                seiten,
                ohne_text,
                textmodell=textmodell,
                ocr_sprache=ocr_sprache,
                bild_seiten_max=bild_seiten_max,
                befunde=befunde,
            )
            if ohne_text
            else {}
        )

        # Lesezeichen gliedern; fehlen sie, gliedern die Seitentitel eines zweispaltigen PDF.
        starts = _kapitelstarts(doc, befunde)
        titelbloecke: set[_Block] = set()
        if not starts:
            starts, titelbloecke = _seitentitel([b for b in alle if b not in schmuck], hoehen)

        absaetze: list[_Absatz] = []
        for i, seite in enumerate(seiten):
            if i in gelesen:
                absaetze.extend(_Absatz(i, a, None) for a in gelesen[i])
                continue
            inhalt = [
                b for b in alle if b.seite == i and b not in schmuck and b not in titelbloecke
            ]
            absaetze.extend(_seitenabsaetze(i, _ordne(inhalt, seite.rect.width)))
        # Erst bereinigen (Webadressen, Zierzeichen), dann Saetze ueber Bloecke verbinden.
        absaetze = [replace(a, text=t) for a in absaetze if (t := befunde.reinige(a.text))]
        absaetze = _fuege_fortsetzungen(absaetze, [s for s, _t in starts])

        meta = doc.metadata or {}
        titel = (
            normalisiere(meta.get("title") or "")
            or _titel_aus_schrift([b for b in alle if b not in schmuck])
            or _titel_aus_dateiname(pfad)
        )
        autor = normalisiere(meta.get("author") or "") or None

    rohe: list[tuple[str | None, list[str]]] = [(None, []), *[(t, []) for _s, t in starts]]
    seitenstarts = [s for s, _t in starts]
    for absatz in absaetze:
        text = Ueberschrift(absatz.text) if absatz.ueberschrift else absatz.text
        rohe[bisect_right(seitenstarts, absatz.seite)][1].append(text)
    kapitel = baue_kapitel(rohe, vorspann=titel, befunde=befunde)
    dok = Dokument(
        titel=titel, autor=autor, sprache="de", kapitel=kapitel, warnungen=befunde.alle()
    )
    return pruefe_text_da(dok, pfad, "PDF")
