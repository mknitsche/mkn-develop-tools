"""Zusicherungen zum Lesen der Fotos-Mediathek als Ortsquelle.

Die Handybilder sind die ZWEITE, unabhaengige Meinung. Ihr Wert liegt nicht
darin, mehr Punkte zu liefern, sondern darin, dass sie einer anderen Quelle
widersprechen koennen: ein Spurpunkt 3383 m abseits, zwischen zwei
Handybildern, die 3 m auseinanderliegen, ist widerlegt — und keine Regel ueber
Geschwindigkeit haette ihn gefangen.

Drei Dinge koennen hier still schiefgehen:

- Eine falsch gedeutete Zeit verschoebe JEDEN Anker um Stunden. Die Bilder
  saehen weiter plausibel aus und lagen alle am falschen Ort.
- Apples Platzhalter fuer „kein Ort" (-180/-180) als Koordinate zu nehmen
  ergaebe Anker mitten im Pazifik.
- Der Name der Verknuepfungstabelle traegt eine Nummer, die von der
  Photos-Version abhaengt. Fest verdrahtet bricht das Modul beim naechsten
  Systemupdate — und zwar mit „Album nicht gefunden", nicht mit der Wahrheit.

Die Tests fahren gegen eine ECHTE SQLite-Datei mit nachgebautem Schema, nicht
gegen einen Mock: geprueft wird das Lesen, und das kann man nur an einer Datei
pruefen.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest
from mkn_foto import mediathek


def _baue_bibliothek(tmp_path, *, eintraege, tabellennummer=33):
    """Legt eine Mediathek mit dem Kern des Photos-Schemas an."""
    ordner = tmp_path / "Test.photoslibrary" / "database"
    ordner.mkdir(parents=True)
    pfad = ordner.parent
    con = sqlite3.connect(ordner / "Photos.sqlite")
    con.execute("CREATE TABLE ZGENERICALBUM (Z_PK INTEGER PRIMARY KEY, ZTITLE TEXT)")
    con.execute(
        "CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, ZDATECREATED REAL, "
        "ZLATITUDE REAL, ZLONGITUDE REAL)"
    )
    con.execute(
        f"CREATE TABLE Z_{tabellennummer}ASSETS "
        f"(Z_{tabellennummer}ALBUMS INTEGER, Z_3ASSETS INTEGER)"
    )
    con.execute("INSERT INTO ZGENERICALBUM VALUES (7, 'Fotokurs Karwendel')")
    con.execute("INSERT INTO ZGENERICALBUM VALUES (8, 'Ganz anderes Album')")
    for pk, (zeit, lat, lon, album) in enumerate(eintraege, start=1):
        con.execute("INSERT INTO ZASSET VALUES (?,?,?,?)", (pk, zeit, lat, lon))
        con.execute(f"INSERT INTO Z_{tabellennummer}ASSETS VALUES (?,?)", (album, pk))
    con.commit()
    con.close()
    return pfad


# Apple zaehlt Sekunden seit 2001-01-01, in UTC. Der Stempel wird aus dem
# gewuenschten Zeitpunkt GERECHNET, nicht als Zahl hingeschrieben: die erste
# Fassung dieses Tests trug eine von Hand ausgerechnete Konstante und lag zwei
# Tage daneben — geprueft haette sie dann meine Kopfrechnung, nicht das Modul.
_SOLL = datetime(2026, 7, 25, 7, 46, 40, tzinfo=UTC)
_ZEIT = (_SOLL - datetime(2001, 1, 1, tzinfo=UTC)).total_seconds()


def test_ein_bild_wird_zu_einem_anker_mit_utc_zeit(tmp_path):
    """Die Zeitdeutung ist der teure Teil. Firsthand belegt: als UTC gedeutet
    liegen Handy-Anker und naechster Spurpunkt im Median 24 m auseinander, als
    lokale Zeit 17 km."""
    bib = _baue_bibliothek(tmp_path, eintraege=[(_ZEIT, 47.5, 11.3, 7)])

    (anker,) = mediathek.lies_album(bib, "Fotokurs Karwendel")

    assert anker.zeit == _SOLL
    assert (anker.lat, anker.lon) == (47.5, 11.3)
    assert anker.name is None


def test_bilder_ohne_ort_werden_uebergangen(tmp_path):
    """Apple traegt -180/-180 ein, wenn kein Ort bekannt ist — bei
    Bildschirmfotos etwa. Als Koordinate genommen ergaeben sie Anker mitten im
    Pazifik, und die haetten jeden Abgleich zerstoert."""
    bib = _baue_bibliothek(
        tmp_path, eintraege=[(_ZEIT, 47.5, 11.3, 7), (_ZEIT + 60, -180.0, -180.0, 7)]
    )

    anker = mediathek.lies_album(bib, "Fotokurs Karwendel")

    assert len(anker) == 1
    assert anker[0].lat == 47.5


def test_nur_das_gesuchte_album_wird_gelesen(tmp_path):
    """Die Mediathek enthaelt zehntausende Bilder. Ohne die Albumgrenze kaemen
    Anker aus voellig anderen Reisen dazu."""
    bib = _baue_bibliothek(tmp_path, eintraege=[(_ZEIT, 47.5, 11.3, 7), (_ZEIT, 40.0, 10.0, 8)])

    anker = mediathek.lies_album(bib, "Fotokurs Karwendel")

    assert [a.lat for a in anker] == [47.5]


def test_der_albumname_wird_ohne_ruecksicht_auf_gross_und_kleinschreibung_gesucht(tmp_path):
    """Der Anwender tippt den Namen — er soll ihn nicht buchstabengenau
    treffen muessen."""
    bib = _baue_bibliothek(tmp_path, eintraege=[(_ZEIT, 47.5, 11.3, 7)])

    assert len(mediathek.lies_album(bib, "fotokurs karwendel")) == 1


def test_anker_kommen_chronologisch_zurueck(tmp_path):
    """Der Abgleich prueft jeden Anker gegen seine zeitlichen Nachbarn — ohne
    Sortierung waeren das die falschen."""
    bib = _baue_bibliothek(
        tmp_path,
        eintraege=[
            (_ZEIT + 120, 47.7, 11.3, 7),
            (_ZEIT, 47.5, 11.3, 7),
            (_ZEIT + 60, 47.6, 11.3, 7),
        ],
    )

    anker = mediathek.lies_album(bib, "Fotokurs Karwendel")

    assert [a.lat for a in anker] == [47.5, 47.6, 47.7]


def test_die_verknuepfungstabelle_wird_gefunden_statt_geraten(tmp_path):
    """Ihr Name traegt eine Nummer, die von der Photos-Version abhaengt — auf
    diesem Rechner Z_33ASSETS. Fest verdrahtet braeche das Modul beim naechsten
    Systemupdate, und zwar mit der irrefuehrenden Meldung „Album nicht
    gefunden"."""
    bib = _baue_bibliothek(tmp_path, eintraege=[(_ZEIT, 47.5, 11.3, 7)], tabellennummer=41)

    assert len(mediathek.lies_album(bib, "Fotokurs Karwendel")) == 1


def test_ein_unbekanntes_album_bricht_laut_ab(tmp_path):
    """Sonst kaeme eine leere Anker-Liste zurueck und der Lauf saehe aus, als
    haette der Anwender einfach keine Handybilder — statt sich vertippt zu
    haben."""
    bib = _baue_bibliothek(tmp_path, eintraege=[(_ZEIT, 47.5, 11.3, 7)])

    with pytest.raises(mediathek.AlbumFehlt, match="Gibt es nicht"):
        mediathek.lies_album(bib, "Gibt es nicht")


def test_eine_fehlende_mediathek_bricht_laut_ab(tmp_path):
    with pytest.raises(mediathek.MediathekFehlt):
        mediathek.lies_album(tmp_path / "gibt-es-nicht.photoslibrary", "egal")
