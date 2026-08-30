"""Protokoll und Rueckweg: was ist durch, was ist offen, und wie kommt die
Antwort zurueck.

KT-1 am 2026-08-30, nachdem er den ersten Lauf verworfen hatte:

    "so dass klar ist, was durch ist (also nach capONE koennte) und was offen
    ist, mit einer eindeutigen protokolldatei und einer sinnvolen moeglichkeit
    die entscheidungen einzutragen und dir mitzugeben"

Drei Anforderungen. Die dritte ist die, an der die erste Fassung scheiterte:
*"irgendwie weiss ich ueberhaupt nicht was ich machen soll"*. Zwoelf Ordner mit
je einer `ort.md` sind kein Formular, sondern eine Schnitzeljagd.

**Die Bilder muessen verteilt liegen — die Eingabe gehoert an EINE Stelle.** Eine
einzige Datei, in der alle offenen Faelle untereinander stehen, jeder mit einem
Feld zum Hineinschreiben. Sie ist zugleich der Rueckweg: `lies_entscheidungen`
liest sie wieder ein und liefert dieselben `Notiz`-Objekte, die die Pipeline
ohnehin verarbeitet — kein zweiter Weg fuer dieselbe Sache.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from mkn_foto.modell import Ort, Spot
from mkn_foto.notizen import Notiz

PROTOKOLL = "_protokoll.md"
ENTSCHEIDUNGEN = "_offene-orte.md"

FELD = "**Antwort:**"
"""Der Marker, hinter den geschrieben wird. Bewusst EIN Wort in Fettschrift und
am Zeilenanfang: er muss beim Ueberfliegen ins Auge springen und beim Einlesen
eindeutig sein.

Die Anleitung in der Datei nennt ihn NICHT beim Namen -- `lies_entscheidungen`
sucht Zeilen, die damit BEGINNEN, und ein Beispiel im Fliesstext waere eine
zusaetzliche, leere Antwort. Wer ein Muster dokumentiert, schreibt es hin und
faellt selbst durch (LP-35). Diese Begruendung gehoert hierher und nicht in die
Datei, die KT-1 liest -- dort ist sie Werkzeug-Innensicht, die nur verwirrt."""

_ORDNER = "%Y-%m-%d_%H%M"


def _name(spot: Spot) -> str:
    return f"{spot.von:{_ORDNER}}-{spot.bis:%H%M}"


def protokoll(
    ziel: Path,
    *,
    verortet: Sequence[tuple[Spot, Ort]],
    beantwortet: Sequence[tuple[Spot, str]],
    offen: Sequence[tuple[Spot, Ort | None]],
) -> Path:
    """Schreibt, was durch ist und was nicht — mit Zahlen, nicht mit Zusicherungen."""
    ziel = Path(ziel)
    ziel.mkdir(parents=True, exist_ok=True)

    n_verortet = sum(len(s.aufnahmen) for s, _ in verortet)
    n_beantwortet = sum(len(s.aufnahmen) for s, _ in beantwortet)
    n_offen = sum(len(s.aufnahmen) for s, _ in offen)
    gesamt = n_verortet + n_beantwortet + n_offen

    zeilen = [
        "# Foto-Anreicherung — Protokoll",
        "",
        f"Lauf vom {datetime.now():%Y-%m-%d %H:%M}. "
        f"**{gesamt} Aufnahmen** in {len(verortet) + len(beantwortet) + len(offen)} Sessions.",
        "",
        "| | Sessions | Aufnahmen | |",
        "|---|---:|---:|---|",
        f"| **Durch** — Ort steht in der Datei | {len(verortet)} | {n_verortet} | "
        "kann nach Capture One |",
        f"| **Beantwortet, ohne Ort** | {len(beantwortet)} | {n_beantwortet} | "
        "deine Antwort liegt vor, sie nennt keinen Ort |",
        f"| **Offen** | {len(offen)} | {n_offen} | warten auf dich in `{ENTSCHEIDUNGEN}` |",
        "",
        "---",
        "",
        "## Durch — diese Ordner koennen nach Capture One",
        "",
        "Zu jeder RAW liegt ein XMP-Sidecar daneben, jedes JPEG traegt die Daten",
        "eingebettet. Ort, Radius, Serie und Technik stehen drin.",
        "",
    ]

    for s, o in sorted(verortet, key=lambda x: x[0].von):
        benennung = f" — **{o.name}**" if o.name else ""
        zeilen.append(
            f"- `{_name(s)}` · {len(s.aufnahmen)} Aufnahmen{benennung} "
            f"· {o.lat:.5f}, {o.lon:.5f} ±{o.radius_m} m"
        )

    if beantwortet:
        zeilen += [
            "",
            "## Beantwortet, aber ohne Ortsangabe",
            "",
            "Diese Sessions hast du schon beurteilt — sie kommen NICHT wieder auf die",
            "Frageliste. Ein Ort steht nicht drin, weil deine Antwort keinen nennt.",
            "",
        ]
        for s, text in sorted(beantwortet, key=lambda x: x[0].von):
            zeilen.append(f'- `{_name(s)}` · {len(s.aufnahmen)} Aufnahmen — „{text[:90]}"')

    if offen:
        zeilen += [
            "",
            "## Offen — hier fehlt der Ort",
            "",
            f"Eintragen in **`{ENTSCHEIDUNGEN}`**, eine Datei fuer alle Faelle.",
            "",
        ]
        for s, o in sorted(offen, key=lambda x: x[0].von):
            hinweis = f" · Vorschlag: {o.name or f'{o.lat:.4f}, {o.lon:.4f}'}" if o else ""
            zeilen.append(f"- `{_name(s)}` · {len(s.aufnahmen)} Aufnahmen{hinweis}")

    zeilen.append("")
    pfad = ziel / PROTOKOLL
    pfad.write_text("\n".join(zeilen), encoding="utf-8")
    return pfad


def entscheidungsdatei(ziel: Path, offen: Sequence[tuple[Spot, Ort | None]]) -> Path:
    """EINE Datei mit einem Feld je offenem Fall.

    Nicht zwoelf Ordner mit je einer Notiz: das war die Form, bei der KT-1 nicht
    mehr wusste, was er tun soll.
    """
    ziel = Path(ziel)
    ziel.mkdir(parents=True, exist_ok=True)

    zeilen = [
        "# Offene Orte",
        "",
        f"{len(offen)} Sessions warten auf dich. Unter jeder Ueberschrift steht eine",
        "fett gedruckte Zeile, die mit einem Doppelpunkt endet — dahinter schreibst",
        "du, was du weisst. Ein Ortsname reicht, ganze Saetze sind auch gut. Was du",
        "nicht weisst, laesst du leer; leere Zeilen stehen beim naechsten Mal einfach",
        "wieder hier.",
        "",
        "Die Bilder zum Ansehen liegen je Fall im gleichnamigen Ordner daneben.",
        "",
        "---",
        "",
    ]

    for s, o in sorted(offen, key=lambda x: x[0].von):
        name = _name(s)
        zeilen += [
            f"## {s.von:%Y-%m-%d} · {s.von:%H:%M}-{s.bis:%H:%M} · {len(s.aufnahmen)} Aufnahmen",
            "",
            f"Bilder: `{name}/`",
        ]
        if o is not None:
            benennung = o.name or f"{o.lat:.5f}, {o.lon:.5f}"
            zeilen.append(
                f"Vermutung des Werkzeugs: **{benennung}** (±{o.radius_m} m) — "
                "nicht belegt genug zum Schreiben. Stimmt das?"
            )
        else:
            zeilen.append("Kein Anhaltspunkt — weder Spur noch Handybild in der Naehe.")
        zeilen += ["", FELD, "", ""]

    pfad = ziel / ENTSCHEIDUNGEN
    pfad.write_text("\n".join(zeilen), encoding="utf-8")
    return pfad


def lies_entscheidungen(pfad: Path) -> list[Notiz]:
    """Liest die ausgefuellten Felder zurueck.

    Ergebnis sind `Notiz`-Objekte — dieselben, die `notizen.lies` aus den
    Einzeldateien liefert. Die Pipeline muss deshalb nichts Zusaetzliches
    koennen; es gibt zwei Eingabeformen, aber nur einen Weg dahinter.
    """
    text = Path(pfad).read_text(encoding="utf-8")
    gefunden: list[Notiz] = []
    aktueller: tuple[datetime, datetime, str] | None = None

    for zeile in text.splitlines():
        if zeile.startswith("## "):
            aktueller = _kopf_lesen(zeile)
        elif zeile.startswith(FELD) and aktueller is not None:
            antwort = zeile[len(FELD) :].strip()
            if antwort:
                von, bis, name = aktueller
                gefunden.append(Notiz(von=von, bis=bis, text=antwort, ordner=name))
    return gefunden


def _kopf_lesen(zeile: str) -> tuple[datetime, datetime, str] | None:
    """`## 2026-08-24 · 07:39-08:09 · 27 Aufnahmen` -> Zeitfenster und Ordnername.

    Getrennt wird mit einem gewoehnlichen Bindestrich, nicht mit einem
    Gedankenstrich: die Ueberschrift wird von Hand bearbeitet und danach wieder
    EINGELESEN, und zwei Zeichen, die gleich aussehen, sind dort eine Falle.
    """
    teile = [t.strip() for t in zeile[3:].split("·")]
    if len(teile) < 2 or "-" not in teile[1]:
        return None
    try:
        tag = datetime.strptime(teile[0], "%Y-%m-%d")
        von_t, bis_t = teile[1].split("-")
        von = datetime.combine(tag.date(), datetime.strptime(von_t.strip(), "%H:%M").time())
        bis = datetime.combine(tag.date(), datetime.strptime(bis_t.strip(), "%H:%M").time())
    except ValueError:
        return None
    return von, bis, f"{von:{_ORDNER}}-{bis:%H%M}"
