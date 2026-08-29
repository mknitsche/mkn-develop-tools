"""Liest Ortsanker aus einem Album der Apple-Fotos-Mediathek.

Handybilder sind die ZWEITE, unabhaengige Meinung zum Ort. Ihr Wert liegt
nicht in der Menge, sondern darin, dass sie einer anderen Quelle
WIDERSPRECHEN koennen. Gemessen: ein Spurpunkt 3383 m abseits, zwischen zwei
Handybildern, die 3 m auseinanderliegen — widerlegt. Keine Regel ueber
Geschwindigkeit haette ihn gefangen, denn 3,4 km in dreieinhalb Minuten sind
mit dem Auto moeglich.

Gelesen wird NUR, und nur aus einer Kopie-sicheren Verbindung
(`immutable=1`): die Mediathek gehoert der Fotos-App, dieses Modul fasst sie
nicht an.

**Plattform:** die Mediathek gibt es so nur unter macOS. Auf anderen Systemen
faellt diese Quelle aus — das Werkzeug bleibt benutzbar, es hat dann eine
Quelle weniger. Der Ausfall ist laut (`MediathekFehlt`), nicht still.
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
from pathlib import Path

from mkn_foto.modell import Anker

# Core Data zaehlt Sekunden seit dem 1.1.2001, in UTC. Die Deutung ist nicht
# geraten: als UTC gelesen liegen die Anker im Median 24 m neben dem naechsten
# Spurpunkt derselben Reise, als lokale Zeit gelesen 17 km daneben.
_APPLE_EPOCHE = dt.datetime(2001, 1, 1, tzinfo=dt.UTC)

# Apples Platzhalter fuer „kein Ort bekannt". Als Koordinate genommen ergaebe
# er Anker mitten im Pazifik.
_GUELTIGE_BREITE = (-90.0, 90.0)


class MediathekFehlt(RuntimeError):
    """Die angegebene Mediathek existiert nicht oder ist nicht lesbar."""


class AlbumFehlt(RuntimeError):
    """Das gesuchte Album gibt es in dieser Mediathek nicht."""


def lies_album(bibliothek: Path, album: str) -> list[Anker]:
    """Alle Bilder eines Albums mit gueltiger Koordinate, chronologisch.

    `album` wird ohne Ruecksicht auf Gross- und Kleinschreibung gesucht.
    """
    datenbank = Path(bibliothek) / "database" / "Photos.sqlite"
    if not datenbank.is_file():
        raise MediathekFehlt(
            f"Keine Fotos-Mediathek unter {bibliothek}. Erwartet wird der Ordner "
            "'... .photoslibrary'; unter macOS liegt er ueblicherweise in ~/Pictures."
        )

    con = sqlite3.connect(f"file:{datenbank}?immutable=1", uri=True)
    try:
        album_pk = _album_pk(con, album)
        spalte_album, tabelle = _verknuepfung(con)
        zeilen = con.execute(
            f"SELECT a.ZDATECREATED, a.ZLATITUDE, a.ZLONGITUDE "
            f"FROM {tabelle} j JOIN ZASSET a ON a.Z_PK = j.Z_3ASSETS "
            f"WHERE j.{spalte_album} = ? AND a.ZLATITUDE BETWEEN ? AND ? "
            f"ORDER BY a.ZDATECREATED",
            (album_pk, *_GUELTIGE_BREITE),
        ).fetchall()
    finally:
        con.close()

    return [
        Anker(zeit=_APPLE_EPOCHE + dt.timedelta(seconds=ts), lat=lat, lon=lon, name=None)
        for ts, lat, lon in zeilen
    ]


def _album_pk(con: sqlite3.Connection, album: str) -> int:
    treffer = con.execute(
        "SELECT Z_PK FROM ZGENERICALBUM WHERE LOWER(ZTITLE) = LOWER(?)", (album,)
    ).fetchone()
    if treffer is None:
        raise AlbumFehlt(
            f"Kein Album mit dem Namen {album!r} in dieser Mediathek. "
            "Der Name muss dem in der Fotos-App entsprechen."
        )
    return int(treffer[0])


def _verknuepfung(con: sqlite3.Connection) -> tuple[str, str]:
    """Findet die Album-Asset-Tabelle, statt ihren Namen zu raten.

    Ihre Nummer haengt von der Photos-Version ab — auf dem Rechner, an dem
    dieses Modul entstand, heisst sie `Z_33ASSETS`. Fest verdrahtet braeche das
    Modul beim naechsten Systemupdate, und zwar mit der irrefuehrenden Meldung
    „Album nicht gefunden" statt mit der Wahrheit.
    """
    for (name,) in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Z\\_%ASSETS' ESCAPE '\\'"
    ):
        spalten = [r[1] for r in con.execute(f"PRAGMA table_info({name})")]
        album_spalte = next((s for s in spalten if re.fullmatch(r"Z_\d+ALBUMS", s)), None)
        if album_spalte and "Z_3ASSETS" in spalten:
            return album_spalte, name
    raise MediathekFehlt(
        "In dieser Mediathek ist keine Album-Zuordnungstabelle zu finden. "
        "Das Schema der Fotos-App weicht ab — bitte melden."
    )
