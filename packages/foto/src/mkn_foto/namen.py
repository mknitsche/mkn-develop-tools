"""Die Dateinotation des angereicherten Baums.

Baut den Zielnamen, das stabile Suchmuster und die Existenzpruefung.
Anwender sind `schreiben` und die Pipeline.

Notation:

    <datum>_<zeit>_<kamera>_<typ><serie>-<pos>v<gesamt>_<originalname>.<ext>
    2026-08-26_201519_D850_pan01-01v15_D85_2560.NEF
    2026-08-27_191100_XE5_std_DSCF3620.RAF

Der Originalname bleibt am Ende stehen, damit eine umbenannte Datei zu ihrem
Kamera-Original zurueckfindet.
"""

from __future__ import annotations

from pathlib import Path

from mkn_foto.modell import Aufnahme

TYPEN = frozenset({"std", "hdr", "pan", "foc", "iso", "wb"})

_MAX_ZAEHLER = 99


class NotationUeberlauf(RuntimeError):
    """Ein Zaehler passt nicht mehr in zwei Stellen."""


def _kopf(a: Aufnahme) -> str:
    return f"{a.zeitpunkt:%Y-%m-%d_%H%M%S}_{a.kamera}"


def archiv_name(
    a: Aufnahme,
    endung: str,
    *,
    typ: str = "std",
    serie: int | None = None,
    pos: int | None = None,
    gesamt: int | None = None,
) -> str:
    """Baut den Zielnamen einer Aufnahme.

    Bei `typ="std"` entfaellt der Serienteil; sonst sind `serie`, `pos` und
    `gesamt` Pflicht und muessen zweistellig darstellbar sein.
    """
    if typ not in TYPEN:
        raise ValueError(f"Unbekannter Typ {typ!r}. Erlaubt: {sorted(TYPEN)}")

    if typ == "std":
        return f"{_kopf(a)}_{typ}_{a.stamm}{endung}"

    if serie is None or pos is None or gesamt is None:
        raise ValueError(f"Typ {typ!r} braucht serie, pos und gesamt")

    for beschriftung, wert in (("serie", serie), ("pos", pos), ("gesamt", gesamt)):
        if wert > _MAX_ZAEHLER:
            raise NotationUeberlauf(
                f"{beschriftung}={wert} passt nicht in zwei Stellen "
                f"(max {_MAX_ZAEHLER}) — die Notation waere unlesbar."
            )

    abschnitt = f"{typ}{serie:02d}-{pos:02d}v{gesamt:02d}"
    return f"{_kopf(a)}_{abschnitt}_{a.stamm}{endung}"


def stabiles_muster(a: Aufnahme, endung: str) -> str:
    """Glob-Muster, das eine Aufnahme unabhaengig von ihrem Typ findet.

    Der Typ-Abschnitt bleibt offen: genau dort steht eine Korrektur von Hand,
    und danach darf nicht gesucht werden — sonst legt ein zweiter Lauf die
    korrigierte Aufnahme noch einmal an.
    """
    return f"{_kopf(a)}_*_{a.stamm}{endung}"


def ist_schon_da(ziel_tag: Path, a: Aufnahme) -> bool:
    """True, sobald irgendeine Datei dieser Aufnahme im Zielordner liegt.

    Ein noch nicht angelegter Zielordner ist kein Sonderfall: `glob` liefert
    dort eine leere Folge. Ein eigener `exists()`-Riegel davor saehe nach
    Sorgfalt aus und pruefte nichts — die Mutation hat ihn ueberlebt.
    """
    return any(
        next(ziel_tag.glob(stabiles_muster(a, endung)), None) is not None for endung in a.dateien
    )


def vorhandene_kopien(ziel_tag: Path, a: Aufnahme) -> dict[str, Path]:
    """Die Zielpfade einer Aufnahme, die bereits im Zielordner liegt.

    Gegenstueck zu `ist_schon_da`: jene Funktion beantwortet OB, diese WO. Die
    Trennung ist nicht kosmetisch -- wer nur das Ob kennt, kann eine vorhandene
    Datei zaehlen, aber nicht anreichern.

    Gesucht wird mit demselben offenen Muster: der Typ-Abschnitt bleibt frei,
    weil genau dort eine Korrektur von Hand steht.
    """
    gefunden: dict[str, Path] = {}
    for endung in a.dateien:
        treffer = next(ziel_tag.glob(stabiles_muster(a, endung)), None)
        if treffer is not None:
            gefunden[endung] = treffer
    return gefunden
