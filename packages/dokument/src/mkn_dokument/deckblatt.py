"""Deckblatt: ein vorhandenes PDF bekommt eine Seite vorn (Titel, Datum, Herkunft, Schlagworte, Verweise, Status) -
und verliert sie auf Wunsch wieder.

Drei Wege, alle ohne Modell und ohne weitere Abhaengigkeit als PyMuPDF:

- ``setzen``: die Quelle wird geoeffnet, die Kopfseite an Position 0 eingefuegt und das Ganze unter ``aus``
  gespeichert. Lesezeichen, Verweise, Formularfelder, Anhaenge und die Seiten der Quelle bleiben so erhalten (kein
  Neuaufbau aus kopierten Seiten). Die Kopfseite setzt ``pymupdf.Story`` auf A4 mit den eingebauten Schriften; eine
  eigene Gestaltung kommt ueber ``Stil`` (CSS, Schriftenordner) oder als ``kopfseite``-Funktion, die die eine Seite
  selbst liefert.
- ``abnehmen``: Seite 1 und die Kennung gehen wieder ab - nur, wenn die Kennung da ist und die Pruefsumme ihrer
  Kopfseite zum Text von Seite 1 passt. Es wird nie auf Verdacht eine Seite entfernt.
- ``lesen``: die Kennung als Zuordnung.

**Kennung:** eine eingebettete Datei ``mkn-deckblatt.json`` (Schema 1) mit den Angaben, Dateiname, SHA-256 und
Seitenzahl der Quelle, den vorherigen Infofeldern und dem SHA-256 der Wortfolge der Kopfseite.

**Schreiben:** das Ergebnis entsteht in einem Zwischenordner im Zielordner, wird dort vollstaendig geprueft
(Strukturabdruck: Seiten, Texte, Lesezeichen, Verweise, Anhaenge, Formularfelder, Kennung) und erst dann ohne
Ueberschreiben veroeffentlicht - als harter Verweis, der an einem vorhandenen Ziel scheitert; wo das Dateisystem
keine harten Verweise kann, durch exklusives Anlegen und Kopieren. Der Zwischenordner geht in jedem Fall weg.

Das Ergebnis von ``abnehmen`` ist inhaltsgleich mit dem, was hinter dem Deckblatt lag, aber nicht bytegleich mit der
Quelle. Eine zugesicherte PDF/A-Konformitaet der Quelle bleibt nicht erhalten. Ein signiertes PDF wird abgewiesen:
jede eingefuegte oder entfernte Seite entwertete die Signatur.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pymupdf

#: Name der eingebetteten Datei, die ein Deckblatt dieses Werkzeugs kennzeichnet.
KENNUNG = "mkn-deckblatt.json"
SCHEMA = 1
#: Groesste Kennung, die gelesen wird; eine groessere ist keine dieses Werkzeugs.
MAX_KENNUNG_BYTES = 2**20
#: Infofelder, die ``setzen`` beschreibt und ``abnehmen`` zuruecksetzt, solange sie unveraendert sind.
GESETZTE_INFOFELDER = ("title", "keywords")
#: Infofelder der Quelle, die die Kennung festhaelt.
VORHERIGE_INFOFELDER = ("title", "author", "subject", "keywords")

_DATUM = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_A4 = pymupdf.paper_rect("a4")
_RAND = 54

# Groessen relativ zur Grundgroesse der Story (12 pt), Farben mit Namen: ein eigenes CSS ueberschreibt alles.
_GRUNDSTIL = """
body { font-size: 0.85em; color: black; }
p.marke { font-size: 0.9em; color: dimgray; margin: 0 0 6pt 0; }
h1 { font-size: 2em; font-weight: bold; margin: 0 0 4pt 0; }
p.datum { font-size: 1.2em; margin: 0 0 14pt 0; }
h2 { font-size: 1em; font-weight: bold; color: dimgray; margin: 12pt 0 3pt 0; }
p.paar { margin: 0 0 2pt 0; }
span.name { color: dimgray; }
p.tags { margin: 0; }
"""


class DeckblattFehler(RuntimeError):
    """Setzen, Abnehmen oder Lesen bricht ab; der Text ist der Satz fuer den Menschen. Ein Ziel entsteht dann nicht."""


Paare = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Angaben:
    """Was auf dem Deckblatt steht. ``datum`` ist JJJJ, JJJJ-MM oder JJJJ-MM-TT; Paare sind (Beschriftung, Wert)."""

    titel: str
    datum: str
    quelle: str = ""
    tags: tuple[str, ...] = ()
    links: Paare = ()
    status: Paare = ()
    weitere: Paare = ()
    marke: str = ""


@dataclass(frozen=True)
class Stil:
    """Eigene Gestaltung des eingebauten Satzes: CSS-Text und ein Ordner mit Schriftdateien fuer ``@font-face``."""

    css: str = ""
    schriften: Path | None = None


#: Eine Funktion, die die Kopfseite selbst als PDF mit genau einer Seite nach ``ziel`` schreibt.
Kopfseite = Callable[[Angaben, Path], None]


# --- Pruefen -------------------------------------------------------------------------------------------------------


def _datum_pruefen(datum: str) -> None:
    """JJJJ, JJJJ-MM oder JJJJ-MM-TT mit echtem Monat und Tag."""
    m = _DATUM.match(datum)
    try:
        if not m:
            raise ValueError
        if m.group(3):
            dt.date.fromisoformat(datum)
        elif m.group(2) and not 1 <= int(m.group(2)) <= 12:
            raise ValueError
    except ValueError:
        raise DeckblattFehler(f"Datum ungueltig: {datum!r} (erwartet JJJJ, JJJJ-MM oder JJJJ-MM-TT)") from None


def _ziel_frei(aus: Path) -> None:
    if aus.exists() or aus.is_symlink():
        raise DeckblattFehler(f"{aus}: Ziel existiert schon - es wird nie ueberschrieben")
    if not aus.parent.is_dir():
        raise DeckblattFehler(f"{aus.parent}: Zielordner fehlt")


def _oeffnen(pdf: Path) -> pymupdf.Document:
    """Oeffnet ein lesbares, unverschluesseltes PDF mit mindestens einer Seite."""
    if not pdf.is_file():
        raise DeckblattFehler(f"{pdf}: Datei fehlt oder ist keine Datei")
    try:
        d = pymupdf.open(pdf)
    except (pymupdf.FileDataError, pymupdf.EmptyFileError, RuntimeError, ValueError) as exc:
        raise DeckblattFehler(f"{pdf}: kein lesbares PDF ({type(exc).__name__})") from None
    if not d.is_pdf:
        d.close()
        raise DeckblattFehler(f"{pdf}: kein lesbares PDF")
    if d.needs_pass or d.is_encrypted or (d.metadata or {}).get("encryption"):
        d.close()
        raise DeckblattFehler(f"{pdf}: verschluesselt - ein Deckblatt wird nur an unverschluesselte PDFs gesetzt")
    if d.page_count == 0:
        d.close()
        raise DeckblattFehler(f"{pdf}: PDF ohne Seite")
    return d


def _signiert(d: pymupdf.Document) -> bool:
    """Im Zweifel signiert: Signatur-Kennzeichen, ein Signaturfeld auf einer Seite oder ein Signatur-Bytebereich."""
    if d.get_sigflags() > 0:
        return True
    for seite in d:
        if any(f.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE for f in seite.widgets()):
            return True
    return any("/ByteRange" in d.xref_object(nr) for nr in range(1, d.xref_length()))


def _nicht_signiert(d: pymupdf.Document, pdf: Path) -> None:
    if _signiert(d):
        raise DeckblattFehler(
            f"{pdf}: traegt eine digitale Signatur - eine eingefuegte oder entfernte Seite entwertete sie"
        )


# --- Text, Pruefsumme, Kennung -------------------------------------------------------------------------------------


def _seitentext(seite: pymupdf.Page) -> str:
    """Wortfolge der Seite, mit einem Leerzeichen verbunden - unempfindlich gegen Zeilenumbruch und Leerraum."""
    return " ".join(w[4] for w in seite.get_text("words"))


def _pruefsumme(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ist_text(wert: Any) -> bool:
    return isinstance(wert, str)


def _gueltige_kennung(kennung: Any) -> bool:
    """Schema 1 mit allen Teilen, die ``abnehmen`` braucht."""
    if not isinstance(kennung, dict) or kennung.get("schema") != SCHEMA:
        return False
    quelle, kopf = kennung.get("quelle"), kennung.get("deckblatt")
    if not isinstance(quelle, dict) or not isinstance(kopf, dict) or not isinstance(kennung.get("angaben"), dict):
        return False
    seiten = quelle.get("seiten")
    if not isinstance(seiten, int) or isinstance(seiten, bool) or seiten < 1:
        return False
    if not _ist_text(kopf.get("text_sha256")) or not _SHA256.match(kopf["text_sha256"]):
        return False
    for feld in ("info_vorher", "info_gesetzt"):
        werte = kennung.get(feld)
        if not isinstance(werte, dict) or not all(_ist_text(k) and _ist_text(v) for k, v in werte.items()):
            return False
    return True


def _kennung(d: pymupdf.Document, pdf: Path) -> dict | None:
    """Die Kennung des Dokuments; ``None`` ohne. Eine unlesbare, fremde oder uebergrosse bricht ab."""
    if KENNUNG not in d.embfile_names():
        return None
    if d.embfile_info(KENNUNG).get("length", 0) > MAX_KENNUNG_BYTES:
        raise DeckblattFehler(f"{pdf}: die Kennung {KENNUNG} ist zu gross - keine Kennung dieses Werkzeugs")
    daten = d.embfile_get(KENNUNG)
    if len(daten) > MAX_KENNUNG_BYTES:
        raise DeckblattFehler(f"{pdf}: die Kennung {KENNUNG} ist zu gross - keine Kennung dieses Werkzeugs")
    try:
        kennung = json.loads(daten.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise DeckblattFehler(f"{pdf}: die Kennung {KENNUNG} ist kein lesbares JSON") from None
    if not _gueltige_kennung(kennung):
        raise DeckblattFehler(f"{pdf}: die Kennung {KENNUNG} hat ein unbekanntes Schema oder ist unvollstaendig")
    return kennung


def _passende_kennung(d: pymupdf.Document, pdf: Path) -> dict:
    """Kennung vorhanden und ihre Pruefsumme passt zum Text von Seite 1; sonst Abbruch."""
    kennung = _kennung(d, pdf)
    if kennung is None:
        raise DeckblattFehler(f"{pdf}: traegt kein Deckblatt dieses Werkzeugs")
    if _pruefsumme(_seitentext(d[0])) != kennung["deckblatt"]["text_sha256"]:
        raise DeckblattFehler(
            f"{pdf}: Seite 1 passt nicht zur Pruefsumme der Kennung - das Dokument wurde nach dem Setzen veraendert"
        )
    return kennung


def _als_json(werte: dict) -> dict:
    """So, wie die Kennung sich zuruecklesen wird (Tupel werden Listen) - Vergleich in der Selbstpruefung."""
    return json.loads(json.dumps(werte, ensure_ascii=False))


def _hinweis_seitenzahl(d: pymupdf.Document, kennung: dict, pdf: Path) -> None:
    erwartet = kennung["quelle"]["seiten"] + 1
    if d.page_count != erwartet:
        print(
            f"mkn-dokument: Hinweis: {pdf} hat {d.page_count} Seiten, beim Setzen waren es {erwartet} "
            "- das Dokument wurde danach bearbeitet",
            file=sys.stderr,
        )


# --- Strukturabdruck -----------------------------------------------------------------------------------------------


def _abdruck(d: pymupdf.Document, erste: int, *, mit_kennung: bool = False) -> dict:
    """Was von Seite ``erste`` an erhalten bleiben muss; Seitenzahlen auf ``erste`` bezogen, damit vorher und
    nachher vergleichbar sind. Die Kennung zaehlt nicht zu den Anhaengen, ausser ``mit_kennung``."""
    seiten = range(erste, d.page_count)

    def verweis(v: dict) -> tuple:
        ziel = v.get("page")
        ziel = ziel - erste if isinstance(ziel, int) and ziel >= 0 else None
        return (v.get("kind"), v.get("uri") or v.get("file") or v.get("name") or "", ziel)

    return {
        "seiten": len(seiten),
        "texte": [_seitentext(d[n]) for n in seiten],
        "lesezeichen": [[ebene, titel, seite - erste if seite > 0 else seite] for ebene, titel, seite in d.get_toc()],
        "verweise": [[verweis(v) for v in d[n].get_links()] for n in seiten],
        "anhaenge": {
            name: _pruefsumme_bytes(d.embfile_get(name)) for name in d.embfile_names() if mit_kennung or name != KENNUNG
        },
        "felder": [
            sorted((f.field_name or "", f.field_type, str(f.field_value)) for f in d[n].widgets()) for n in seiten
        ],
    }


def _pruefsumme_bytes(daten: bytes) -> str:
    return hashlib.sha256(daten).hexdigest()


def _vergleiche(vorher: dict, nachher: dict, wobei: str) -> None:
    """Bricht beim ersten Teil ab, der nicht gleich ist."""
    namen = {
        "seiten": "Seitenzahl",
        "texte": "Seitentexte",
        "lesezeichen": "Lesezeichen",
        "verweise": "Verweise",
        "anhaenge": "eingebettete Dateien",
        "felder": "Formularfelder",
    }
    for teil, name in namen.items():
        if vorher[teil] != nachher[teil]:
            raise DeckblattFehler(f"Selbstpruefung beim {wobei}: {name} weichen ab - kein Ziel geschrieben")


# --- Kopfseite -----------------------------------------------------------------------------------------------------


def _wert_html(wert: str) -> str:
    text = html.escape(wert)
    if wert.startswith(("http://", "https://")):
        return f'<a href="{html.escape(wert, quote=True)}">{text}</a>'
    return text


def _zeilen(paare: Paare) -> str:
    """Je Paar eine Zeile ``Beschriftung: Wert`` - Tabellen bricht der Satz von ``Story`` nicht verlaesslich um."""
    return "".join(
        f'<p class="paar"><span class="name">{html.escape(name)}:</span> {_wert_html(wert)}</p>' for name, wert in paare
    )


def _kopf_html(angaben: Angaben, herkunft: Paare) -> str:
    teile = []
    if angaben.marke:
        teile.append(f'<p class="marke">{html.escape(angaben.marke)}</p>')
    teile.append(f"<h1>{html.escape(angaben.titel)}</h1>")
    teile.append(f'<p class="datum">{html.escape(angaben.datum)}</p>')
    for ueberschrift, paare in (("Herkunft", herkunft), ("Angaben", angaben.weitere)):
        if paare:
            teile.append(f"<h2>{ueberschrift}</h2>{_zeilen(paare)}")
    if angaben.tags:
        teile.append(f'<h2>Schlagworte</h2><p class="tags">{html.escape(" · ".join(angaben.tags))}</p>')
    for ueberschrift, paare in (("Verweise", angaben.links), ("Status", angaben.status)):
        if paare:
            teile.append(f"<h2>{ueberschrift}</h2>{_zeilen(paare)}")
    return "<body>" + "".join(teile) + "</body>"


def _eingebaute_kopfseite(angaben: Angaben, ziel: Path, herkunft: Paare, stil: Stil) -> None:
    """Setzt die Kopfseite mit ``pymupdf.Story`` auf ein A4-Blatt; braeuchte sie mehr, bricht es ab."""
    archiv = None
    if stil.schriften is not None:
        if not stil.schriften.is_dir():
            raise DeckblattFehler(f"{stil.schriften}: Schriftenordner fehlt")
        archiv = pymupdf.Archive(str(stil.schriften))
    story = pymupdf.Story(_kopf_html(angaben, herkunft), user_css=_GRUNDSTIL + stil.css, archive=archiv)
    flaeche = pymupdf.Rect(_RAND, _RAND, _A4.width - _RAND, _A4.height - _RAND)
    with story.write_with_links(lambda nr, gefuellt: (_A4, flaeche, None)) as d:
        if d.page_count != 1:
            raise DeckblattFehler(
                f"Die Kopfseite braeuchte mehr als ein Blatt ({d.page_count}) - Angaben kuerzen "
                "(Schlagworte, Verweise, Status, weitere Angaben)"
            )
        d.save(ziel)


def _kopfseite_oeffnen(pfad: Path) -> pymupdf.Document:
    """Das Ergebnis der Kopfseite: ein PDF mit genau einer Seite, die Text traegt."""
    if not pfad.is_file() or pfad.stat().st_size == 0:
        raise DeckblattFehler("Die Kopfseite fehlt - die Funktion fuer die Kopfseite hat nichts geschrieben")
    try:
        kopf = pymupdf.open(pfad)
    except (pymupdf.FileDataError, pymupdf.EmptyFileError, RuntimeError, ValueError):
        raise DeckblattFehler("Die Kopfseite ist kein lesbares PDF") from None
    if not kopf.is_pdf or kopf.page_count != 1:
        anzahl = kopf.page_count
        kopf.close()
        raise DeckblattFehler(
            f"Die Kopfseite braeuchte mehr als ein Blatt oder ist leer ({anzahl} Seiten) - Angaben kuerzen"
        )
    if not _seitentext(kopf[0]):
        kopf.close()
        raise DeckblattFehler("Die Kopfseite traegt keinen Text - ein Deckblatt ohne Text liesse sich nicht erkennen")
    return kopf


# --- Schreiben -----------------------------------------------------------------------------------------------------


def _kennung_entfernen(d: pymupdf.Document) -> None:
    """Nimmt den Eintrag der Kennung aus der Namensliste der eingebetteten Dateien.

    Nicht ueber ``Document.embfile_del``: PyMuPDF 1.27 loescht dort fuer jeden Eintrag nach dem ersten das falsche
    Paar (Eintragsnummer statt Stelle in der Liste aus Name und Datei) - ein Anhang bekaeme den Inhalt der Kennung.
    Hier wird die Stelle geprueft, bevor geloescht wird; die Selbstpruefung vergleicht danach jeden Anhang.
    """
    mupdf = pymupdf.mupdf
    nr = d.embfile_names().index(KENNUNG)
    liste = mupdf.pdf_trailer(mupdf.pdf_specifics(d.this))
    for schluessel in ("Root", "Names", "EmbeddedFiles", "Names"):
        liste = mupdf.pdf_dict_gets(liste, schluessel)
    if (
        not mupdf.pdf_is_array(liste)
        or mupdf.pdf_array_len(liste) <= 2 * nr + 1
        or mupdf.pdf_to_text_string(mupdf.pdf_array_get(liste, 2 * nr)) != KENNUNG
    ):
        raise DeckblattFehler(f"Die Kennung {KENNUNG} steht nicht, wo erwartet - sie wird nicht auf Verdacht entfernt")
    mupdf.pdf_array_delete(liste, 2 * nr + 1)
    mupdf.pdf_array_delete(liste, 2 * nr)


def _speichern(d: pymupdf.Document, pfad: Path, *, garbage: int) -> None:
    """Das Ergebnis in den Zwischenordner; ein eigener Schritt, damit die Selbstpruefung testbar ist."""
    d.save(pfad, garbage=garbage)


def _veroeffentlichen(zwischen: Path, aus: Path) -> None:
    """Ohne Ueberschreiben: harter Verweis (scheitert an vorhandenem Ziel), sonst exklusiv anlegen und kopieren."""
    try:
        os.link(zwischen, aus)
        return
    except FileExistsError:
        raise DeckblattFehler(f"{aus}: Ziel existiert schon - es wird nie ueberschrieben") from None
    except OSError:
        pass  # Dateisystem ohne harte Verweise: exklusiv kopieren
    try:
        ziel = open(aus, "xb")  # noqa: SIM115 - im Fehlerfall wird die eigene, halbe Kopie entfernt
    except FileExistsError:
        raise DeckblattFehler(f"{aus}: Ziel existiert schon - es wird nie ueberschrieben") from None
    try:
        with ziel, open(zwischen, "rb") as quelle:
            shutil.copyfileobj(quelle, ziel)
            ziel.flush()
            os.fsync(ziel.fileno())
    except BaseException:
        aus.unlink(missing_ok=True)
        raise


def _aufraeumen(ordner: Path) -> None:
    """Zwischenordner entfernen; misslingt das, steht es auf stderr - das Ergebnis bleibt gueltig."""
    shutil.rmtree(ordner, ignore_errors=True)
    if ordner.exists():
        print(f"mkn-dokument: Hinweis: Zwischenordner {ordner} liess sich nicht entfernen", file=sys.stderr)


def _zwischenordner(aus: Path) -> Path:
    return Path(tempfile.mkdtemp(prefix=".deckblatt-", dir=aus.parent))


# --- die drei Wege -------------------------------------------------------------------------------------------------


def setzen(
    quelle: Path,
    aus: Path,
    angaben: Angaben,
    *,
    kopfseite: Kopfseite | None = None,
    stil: Stil | None = None,
) -> Path:
    """Setzt das Deckblatt vor die Quelle und schreibt das Ergebnis nach ``aus`` (nie ueberschrieben).

    ``kopfseite`` liefert die eine Seite selbst (statt des eingebauten Satzes); ``stil`` gestaltet den eingebauten
    Satz. Jede Schutzregel bricht mit ``DeckblattFehler`` ab; dann entsteht kein Ziel.
    """
    quelle, aus = Path(quelle), Path(aus)
    if not angaben.titel.strip():
        raise DeckblattFehler("Titel fehlt")
    _datum_pruefen(angaben.datum)
    _ziel_frei(aus)
    stil = stil or Stil()
    with _oeffnen(quelle) as q:
        _nicht_signiert(q, quelle)
        _anhaenge_flach(q, quelle)
        _ohne_kennung(q, quelle)
        vorher = _abdruck(q, 0)
        sha = _pruefsumme_bytes(quelle.read_bytes())
        info_vorher = {feld: (q.metadata or {}).get(feld) or "" for feld in VORHERIGE_INFOFELDER}
        herkunft = tuple(
            (name, wert)
            for name, wert in (
                ("Quelle", angaben.quelle),
                ("Datei", quelle.name),
                ("SHA-256", sha[:16] + "…"),
                ("Seiten", str(q.page_count)),
            )
            if wert
        )
        ordner = _zwischenordner(aus)
        try:
            kopf_pdf, zwischen = ordner / "kopfseite.pdf", ordner / aus.name
            if kopfseite is None:
                _eingebaute_kopfseite(angaben, kopf_pdf, herkunft, stil)
            else:
                kopfseite(angaben, kopf_pdf)
            with _kopfseite_oeffnen(kopf_pdf) as kopf:
                kopf_text = _seitentext(kopf[0])
                q.insert_pdf(kopf, start_at=0)
            info_gesetzt = {"title": angaben.titel, "keywords": ", ".join(angaben.tags)}
            kennung = _als_json(
                {
                    "schema": SCHEMA,
                    "angaben": asdict(angaben),
                    "quelle": {"datei": quelle.name, "sha256": sha, "seiten": vorher["seiten"]},
                    "deckblatt": {"text_sha256": _pruefsumme(kopf_text)},
                    "info_vorher": info_vorher,
                    "info_gesetzt": info_gesetzt,
                }
            )
            q.set_metadata((q.metadata or {}) | info_gesetzt)
            q.embfile_add(KENNUNG, json.dumps(kennung, ensure_ascii=False, indent=2).encode("utf-8"))
            _speichern(q, zwischen, garbage=0)
            _pruefe_gesetzt(zwischen, vorher, kennung)
            _veroeffentlichen(zwischen, aus)
        finally:
            _aufraeumen(ordner)
    return aus


def _art(q: pymupdf.Document, pfad: str) -> str:
    """Art des Werts unter ``pfad`` im Katalog; ein indirekter Verweis wird aufgeloest (``xref_get_key`` loest nur
    die Zwischenstufen des Pfads auf, nicht den Wert am Ende)."""
    art, wert = q.xref_get_key(q.pdf_catalog(), pfad)
    for _ in range(32):  # Verweiskette, nie endlos
        if art != "xref":
            return art
        objekt = q.xref_object(int(wert.split()[0])).strip()
        if objekt.startswith("["):
            return "array"
        if objekt.startswith("<<"):
            return "dict"
        if objekt == "null":
            return "null"
        art, wert = ("xref", objekt) if re.fullmatch(r"\d+ \d+ R", objekt) else ("anders", objekt)
    return "anders"


def _anhaenge_flach(q: pymupdf.Document, quelle: Path) -> None:
    """Das Anhang-Verzeichnis fehlt oder ist eine flache Liste.

    Ein ueber ``/Kids`` verzweigtes Verzeichnis zeigt PyMuPDF als leer; die Kennung kaeme als flache Liste daneben, und
    andere Leser saehen die Anhaenge der Quelle nicht mehr - die Selbstpruefung bemerkte das nicht.
    """
    if _art(q, "Names/EmbeddedFiles") == "null":
        return
    if _art(q, "Names/EmbeddedFiles/Kids") != "null" or _art(q, "Names/EmbeddedFiles/Names") != "array":
        raise DeckblattFehler(
            f"{quelle}: verzweigtes Anhang-Verzeichnis wird nicht unterstuetzt - die Anhaenge der Quelle gingen "
            "neben der Kennung verloren"
        )


def _ohne_kennung(q: pymupdf.Document, quelle: Path) -> None:
    """Kein zweites Deckblatt und keine fremde Datei unter dem Namen der Kennung, die beim Setzen verloren ginge."""
    if KENNUNG not in q.embfile_names():
        return
    try:
        _passende_kennung(q, quelle)
    except DeckblattFehler:
        raise DeckblattFehler(
            f"{quelle}: eine Datei {KENNUNG} ist schon eingebettet, beschreibt aber kein gueltiges Deckblatt"
        ) from None
    raise DeckblattFehler(f"{quelle}: traegt schon ein Deckblatt dieses Werkzeugs - kein zweites")


def _pruefe_gesetzt(zwischen: Path, vorher: dict, kennung: dict) -> None:
    """Genau eine Seite mehr, dahinter die Quelle unveraendert, Kennung liest sich zurueck und passt zu Seite 1."""
    with pymupdf.open(zwischen) as z:
        if z.page_count != vorher["seiten"] + 1:
            raise DeckblattFehler(
                f"Selbstpruefung beim Setzen: {z.page_count} Seiten statt 1 + {vorher['seiten']} "
                "- kein Ziel geschrieben"
            )
        _vergleiche(vorher, _abdruck(z, 1), "Setzen")
        try:
            gelesen = _passende_kennung(z, zwischen)
        except DeckblattFehler as exc:
            raise DeckblattFehler(f"Selbstpruefung beim Setzen: {exc} - kein Ziel geschrieben") from None
        if gelesen != kennung:
            raise DeckblattFehler("Selbstpruefung beim Setzen: die Kennung liest sich anders zurueck")


def abnehmen(quelle: Path, aus: Path) -> Path:
    """Schreibt das Dokument ohne sein Deckblatt nach ``aus`` (nie ueberschrieben).

    Nur, wenn die Kennung da ist, ihre Pruefsumme zum Text von Seite 1 passt und mindestens eine Seite dahinter
    liegt. Ein Infofeld geht nur dann auf den vorherigen Wert zurueck, wenn es noch den Wert traegt, den ``setzen``
    geschrieben hat. Das Ergebnis ist inhaltsgleich, nicht bytegleich mit der urspruenglichen Quelle.
    """
    quelle, aus = Path(quelle), Path(aus)
    _ziel_frei(aus)
    with _oeffnen(quelle) as d:
        _nicht_signiert(d, quelle)
        kennung = _passende_kennung(d, quelle)
        if d.page_count < 2:
            raise DeckblattFehler(f"{quelle}: traegt nur das Deckblatt, keine Seite dahinter - nichts abzunehmen")
        _hinweis_seitenzahl(d, kennung, quelle)
        vorher = _abdruck(d, 1)
        d.delete_page(0)
        _kennung_entfernen(d)
        info = d.metadata or {}
        zurueck = {
            feld: kennung["info_vorher"].get(feld, "")
            for feld, wert in kennung["info_gesetzt"].items()
            if feld in GESETZTE_INFOFELDER and info.get(feld, "") == wert
        }
        d.set_metadata(info | zurueck)
        ordner = _zwischenordner(aus)
        try:
            zwischen = ordner / aus.name
            # garbage=1: das entfernte Deckblatt und die Kennung bleiben nicht als verwaiste Objekte in der Datei
            _speichern(d, zwischen, garbage=1)
            with pymupdf.open(zwischen) as z:
                _vergleiche(vorher, _abdruck(z, 0, mit_kennung=True), "Abnehmen")
            _veroeffentlichen(zwischen, aus)
        finally:
            _aufraeumen(ordner)
    return aus


def lesen(pdf: Path) -> dict:
    """Die Kennung des Deckblatts; Abbruch ohne Kennung oder wenn Seite 1 nicht zur Pruefsumme passt."""
    pdf = Path(pdf)
    with _oeffnen(pdf) as d:
        kennung = _passende_kennung(d, pdf)
        _hinweis_seitenzahl(d, kennung, pdf)
    return kennung
