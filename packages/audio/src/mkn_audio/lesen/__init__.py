"""Stufe 1: eine Quelle lesen und als `Dokument` ablegen.

**Warum die Endung entscheidet.** Die Stufe muss vor dem Oeffnen wissen, welcher Leser
zustaendig ist; jeder Leser prueft dann den Inhalt selbst (Zip-Kopf, PDF-Kopf,
Bild-Kopf) und bricht laut ab, wenn die Datei nicht ist, was die Endung sagt.

**Ein leeres Ergebnis ist ein Fehler** (`KeinText`), nie ein leeres Dokument: ein
Hoerstueck ohne Inhalt sieht nach Erfolg aus.

**Die Sprache bestimmt `lies`, nicht der Leser.** PDF, Text und Bild kennen sie nicht;
sie setzen nur eine Vorgabe. Wuerde sie so bleiben, lieferte ein englisches PDF mit
deutschen Regeln und deutscher Stimme ein verfaelschtes Hoerstueck, ohne dass etwas
auffaellt. Darum erkennt `lies` sie am Text (`sprache.erkenne`); bei einem EPUB gilt die
Angabe der Quelle, und ein deutlich anderer Text steht als Warnung im Dokument. Bleibt sie
unklar, gilt Deutsch -- und das steht ebenfalls als Warnung im Dokument.

**Versalien-Ueberschriften schreibt `lies` am Ende in Satzschreibung** (`wende_satzschreibung`):
erst jetzt sind Sprache und Fliesstext des ganzen Dokuments bekannt, aus denen die Schreibweisen
kommen. Kapiteltitel und Absaetze der Art `ueberschrift` ohne Kleinbuchstaben werden so gesetzt;
gemischt geschriebene Titel bleiben.

**Private und unsichtbare Zeichen raeumt `lies` fuer alle Leser aus** (Unicode-Kategorien
`Co` und `Cf`): Symbolschriften setzen sie als Bildzeichen vor Rubriken und Titel, Textverarbeitung
als Richtungs- und Formatmarken. Vorgelesen wird nichts davon, aber jeder Vergleich ("ist das
der Titel?") und jede Zaehlung stolpert darueber. Der Weiche Trennstrich ist ebenfalls `Cf`; die
Silbentrennung heilen die Leser VOR dieser Stufe (`verbinde_zeilen`), sie bleibt also, was sie war.
"""

from __future__ import annotations

import re
import unicodedata
import zipfile
from dataclasses import replace
from pathlib import Path

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as DefusedET

from mkn_audio.lesen.bild import lies_bild
from mkn_audio.lesen.epub import lies_epub
from mkn_audio.lesen.pdf import lies_pdf
from mkn_audio.lesen.text import KeinText, lies_text, wende_satzschreibung
from mkn_audio.sprache import erkenne
from mkn_audio.typen import Dokument, Kapitel, Mp4Fehler, Textmodell

__all__ = ["KeinText", "ist_bildquelle", "lies"]

_BILD_ENDUNGEN = frozenset({".jpg", ".jpeg", ".png", ".heic"})
_TEXT_ENDUNGEN = frozenset({".txt", ".md"})
_ENDUNGEN = sorted({".epub", ".pdf", *_TEXT_ENDUNGEN, *_BILD_ENDUNGEN})

_VORGABE_SPRACHE = "de"
_ERKENNUNGS_ZEICHEN = 200_000
"""Mehr Text als das braucht die Erkennung nicht; ein dickes Buch wird nicht ganz gezaehlt."""


def ist_bildquelle(quelle: Path) -> bool:
    """Ist die Quelle eine Bilddatei (Endung)? Dann gehoert das Bild selbst zum Verstehen."""
    return Path(quelle).suffix.lower() in _BILD_ENDUNGEN


def _opf_sprache(quelle: Path) -> str | None:
    """Die Sprachangabe (`dc:language`) im OPF eines EPUB, zweibuchstabig, sonst `None`.

    Der EPUB-Leser setzt bei fehlender Angabe selbst Deutsch ein; von dort aus laesst sich
    nicht mehr unterscheiden, ob die Quelle Deutsch sagt oder gar nichts. Darum wird die
    Angabe hier noch einmal gelesen. Ist das Archiv nicht lesbar, hat der Leser schon laut
    abgebrochen; was hier schiefgeht, heisst nur: keine Angabe.
    """
    try:
        with zipfile.ZipFile(quelle) as zf:
            container = DefusedET.fromstring(zf.read("META-INF/container.xml"))
            wurzel = container.find(".//{*}rootfile")
            if wurzel is None or not wurzel.get("full-path"):
                return None
            opf = DefusedET.fromstring(zf.read(wurzel.get("full-path")))
    except (zipfile.BadZipFile, KeyError, DefusedXmlException, ValueError, OSError):
        return None
    for element in opf.iterfind(".//{*}metadata/{*}language"):
        code = (element.text or "").strip().split("-")[0].lower()
        if code:
            return code
    return None


def _setze_sprache(dok: Dokument, angabe: str | None) -> Dokument:
    """Setzt `Dokument.sprache` aus Angabe der Quelle und Text; Zweifel werden Warnung."""
    text = "\n".join(a for k in dok.kapitel for a in k.absaetze)[:_ERKENNUNGS_ZEICHEN]
    erkannt = erkenne(text)
    warnungen = list(dok.warnungen)
    if angabe:
        sprache = angabe
        if erkannt and erkannt != angabe:
            warnungen.append(
                f"Sprachangabe der Quelle »{angabe}« widerspricht dem Text "
                f"(erkannt: »{erkannt}«); die Angabe gilt"
            )
    elif erkannt:
        sprache = erkannt
    else:
        sprache = _VORGABE_SPRACHE
        warnungen.append("Sprache nicht sicher erkannt, als Deutsch gelesen")
    return replace(dok, sprache=sprache, warnungen=tuple(warnungen))


_UNSICHTBAR = frozenset({"Co", "Cf"})
_LEERRAUM = re.compile(r"\s+")


def _ohne_unsichtbares(text: str) -> str:
    """Der Text ohne Zeichen der Kategorien `Co`/`Cf`; Leerraum nur dort neu geordnet.

    Ein Zeichen zwischen zwei Leerzeichen hinterliesse sonst ein doppeltes.
    """
    if not any(unicodedata.category(z) in _UNSICHTBAR for z in text):
        return text
    rein = "".join(z for z in text if unicodedata.category(z) not in _UNSICHTBAR)
    return _LEERRAUM.sub(" ", rein).strip()


def _entferne_unsichtbares(dok: Dokument) -> Dokument:
    """Raeumt Titel, Autor, Kapiteltitel und Absaetze auf; was dabei leer wird, faellt weg."""
    kapitel = []
    for k in dok.kapitel:
        arten = k.arten or ("wortlaut",) * len(k.absaetze)
        behalten = [
            (a, art)
            for a, art in (
                (_ohne_unsichtbares(x), art) for x, art in zip(k.absaetze, arten, strict=True)
            )
            if a
        ]
        if behalten:
            kapitel.append(
                Kapitel(
                    _ohne_unsichtbares(k.titel),
                    tuple(a for a, _art in behalten),
                    tuple(art for _a, art in behalten) if k.arten else (),
                )
            )
    return replace(
        dok,
        titel=_ohne_unsichtbares(dok.titel),
        autor=None if dok.autor is None else _ohne_unsichtbares(dok.autor) or None,
        kapitel=tuple(kapitel),
    )


def lies(
    quelle: Path,
    *,
    textmodell: Textmodell | None,
    ocr_sprache: str = "deu",
    bild_seiten_max: int = 20,
) -> Dokument:
    """Liest `quelle` (Endung entscheidet) und liefert das `Dokument`.

    `textmodell` liest Bilder und Bildseiten; ohne es (oder ueber `bild_seiten_max`
    Seiten) liest die lokale Texterkennung in `ocr_sprache`.
    """
    quelle = Path(quelle)
    if not quelle.is_file():
        raise Mp4Fehler(f"Quelle nicht gefunden: {quelle.name}")
    endung = quelle.suffix.lower()
    angabe = None
    if endung == ".epub":
        dok, angabe = lies_epub(quelle), _opf_sprache(quelle)
    elif endung == ".pdf":
        dok = lies_pdf(
            quelle, textmodell=textmodell, ocr_sprache=ocr_sprache, bild_seiten_max=bild_seiten_max
        )
    elif endung in _TEXT_ENDUNGEN:
        dok = lies_text(quelle)
    elif endung in _BILD_ENDUNGEN:
        dok = lies_bild(quelle, textmodell=textmodell, ocr_sprache=ocr_sprache)
    else:
        raise Mp4Fehler(f"nicht unterstuetzte Endung '{endung}' (moeglich: {', '.join(_ENDUNGEN)})")
    # Satzschreibung zuletzt: sie braucht die Sprache und die Absaetze ohne unsichtbare Zeichen.
    return wende_satzschreibung(_setze_sprache(_entferne_unsichtbares(dok), angabe))
