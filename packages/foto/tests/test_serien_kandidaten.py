"""Zusicherungen zur Kandidaten-Heuristik (Stufe 2).

Stufe 2 raet — und sie soll grosszuegig raten, weil ueber ihre Treffer erst
der Blick auf das Bild entscheidet. Der teure Fehler ist deshalb NICHT der
falsche Verdacht, sondern der uebersehene Fall: was Stufe 2 nicht vorschlaegt,
sieht nie jemand an.

Die Grenzwerte stammen aus gemessenen Reihen, nicht aus einer Schaetzung.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from mkn_foto import serien
from mkn_foto.modell import Aufnahme, Serie

_START = datetime(2026, 8, 26, 20, 15, 19)


def _bild(
    nr: int,
    *,
    brennweite: float = 34.0,
    blende: float = 8.0,
    zeit_s: float = 1 / 300,
    abstand: float = 2,
    kamera: str = "D850",
) -> Aufnahme:
    return Aufnahme(
        zeitpunkt=_START + timedelta(seconds=nr * abstand),
        kamera=kamera,
        stamm=f"D85_{2560 + nr}",
        dateien={},
        exif={
            "EXIF:Model": "NIKON D850",
            "EXIF:FocalLength": brennweite,
            "EXIF:FNumber": blende,
            "EXIF:ExposureTime": zeit_s,
        },
    )


def test_driftende_belichtungszeit_zerreisst_den_kandidaten_nicht():
    """Bei Zeitautomatik misst die Kamera jedes Bild neu. Ein Kriterium
    „alles konstant" verpasst genau die Panoramen — firsthand gemessen an
    einer Reihe mit f/8 und 34 mm konstant, waehrend die Zeit von 1/300 auf
    1/240 wanderte."""
    zeiten = [1 / 300, 1 / 280, 1 / 260, 1 / 250, 1 / 240]
    aufnahmen = [_bild(nr, zeit_s=z) for nr, z in enumerate(zeiten)]

    (kandidat,) = serien.kandidaten(aufnahmen, schon_erkannt=[])

    assert len(kandidat.aufnahmen) == 5


def test_wechselnde_brennweite_beendet_den_kandidaten():
    """Wer zoomt, schwenkt kein Panorama."""
    aufnahmen = [_bild(0), _bild(1), _bild(2), _bild(3), _bild(4, brennweite=70.0)]

    (kandidat,) = serien.kandidaten(aufnahmen, schon_erkannt=[])

    assert len(kandidat.aufnahmen) == 4


def test_wechselnde_blende_beendet_den_kandidaten():
    """Untergrenze zur Brennweite: ohne diesen Fall wuerde ein Merkmalspaar,
    das nur die Brennweite prueft, unbemerkt durchgehen."""
    aufnahmen = [_bild(0), _bild(1), _bild(2), _bild(3), _bild(4, blende=11.0)]

    (kandidat,) = serien.kandidaten(aufnahmen, schon_erkannt=[])

    assert len(kandidat.aufnahmen) == 4


def test_eine_lange_pause_beendet_den_kandidaten():
    """Zwei Motive nacheinander mit derselben Einstellung sind kein Schwenk.

    Die Zusicherung ist unveraendert, die ZAHL nicht: das Fenster haelt seit dem
    Umbau zum Vorfilter 60 s statt 10 s zusammen. Die bisherige Pause (54 s)
    trennte deshalb nicht mehr -- der Test war rot, ohne dass etwas kaputt war.
    Die Begruendung der 60 s steht an `_FENSTER_MAX_LUECKE_S`: die Fensterweite
    ist die einzige irreversible Stelle der Kette.
    """
    aufnahmen = [_bild(nr) for nr in range(4)] + [_bild(nr, abstand=2) for nr in range(60, 64)]

    ergebnis = serien.kandidaten(aufnahmen, schon_erkannt=[])

    assert [len(k.aufnahmen) for k in ergebnis] == [4, 4]


def test_ein_kamerawechsel_beendet_den_kandidaten():
    """Zwei Kameras koennen dieselbe Sekunde belegen — ohne diese Grenze
    liefe eine Fuji-Aufnahme mitten in eine Nikon-Reihe."""
    aufnahmen = [_bild(nr) for nr in range(4)] + [_bild(nr, kamera="XE5") for nr in range(4, 8)]

    ergebnis = serien.kandidaten(aufnahmen, schon_erkannt=[])

    assert [len(k.aufnahmen) for k in ergebnis] == [4, 4]


def test_drei_bilder_bilden_ein_fenster():
    """**Diese Zusicherung ist bewusst umgedreht — sie war der Fehler.**

    Sie hiess frueher „drei Bilder sind noch kein Kandidat: darunter ist es keine
    Reihe, sondern eine Wiederholung". Das klingt vernuenftig und ist falsch:
    KT-1s Panorama von der Sebalduskirche besteht aus DREI Aufnahmen, von denen
    zwei den Schwenk tragen. Es entstand als Gruppe voellig korrekt und fiel
    einzig an dieser Zahl durch — ueber 1.234 Kursbilder wurde null Panorama
    erkannt.

    Der Unterschied Reihe/Wiederholung ist real, aber er ist keine Frage der
    LAENGE: die Deckungsmessung trennt beides an der Verschiebung, und sie kostet
    nichts. Ein Fenster ist noch keine Aussage.
    """
    fenster = serien.kandidaten([_bild(0), _bild(1), _bild(2)], schon_erkannt=[])

    assert len(fenster) == 1, "drei zusammengehoerige Aufnahmen bilden kein Fenster"
    assert len(fenster[0].aufnahmen) == 3


def test_ein_einzelbild_bildet_kein_fenster():
    """Die Untergrenze, die von der Mindestlaenge uebrig bleibt.

    Ohne sie koennte die Schwelle auf 1 fallen und jedes Einzelbild waere ein
    Fenster — die Messung liefe dann ueber den ganzen Bestand statt ueber
    Nachbarn, und der Vorfilter filterte nichts mehr.
    """
    assert serien.kandidaten([_bild(0)], schon_erkannt=[]) == []


def test_was_die_kamera_schon_bezeugt_hat_wird_nicht_nochmal_geraten():
    """Sonst traegt dieselbe Aufnahme zwei Serienzuordnungen — und der
    Dateiname kann nur eine tragen."""
    aufnahmen = [_bild(nr) for nr in range(5)]
    bekannt = Serie(typ="hdr", nummer=1, aufnahmen=tuple(aufnahmen), quelle="kamera", sicher=True)

    assert serien.kandidaten(aufnahmen, schon_erkannt=[bekannt]) == []


def test_eine_bereits_belegte_aufnahme_verbindet_nicht_ueber_sich_hinweg():
    """Untergrenze zur Zeile darueber: die belegte Aufnahme darf nicht
    einfach uebersprungen werden, sonst waechst ein Kandidat quer durch eine
    bezeugte Serie hindurch zusammen."""
    aufnahmen = [_bild(nr) for nr in range(9)]
    bekannt = Serie(typ="hdr", nummer=1, aufnahmen=(aufnahmen[4],), quelle="kamera", sicher=True)

    ergebnis = serien.kandidaten(aufnahmen, schon_erkannt=[bekannt])

    assert [len(k.aufnahmen) for k in ergebnis] == [4, 4]


def test_kandidaten_sind_ausdruecklich_unsicher():
    """`sicher=False` ist das Signal an Stufe 3, das Bild anzusehen — und an
    den Bericht, den Punkt auf die Nacharbeits-Liste zu setzen."""
    (kandidat,) = serien.kandidaten([_bild(nr) for nr in range(5)], schon_erkannt=[])

    assert kandidat.sicher is False
    assert kandidat.quelle == "heuristik"
    assert kandidat.typ == "pan"


def test_gleiche_zeitstempel_bringen_die_gruppierung_nicht_durcheinander():
    """Die Kamera schreibt nur Sekunden — bei einem schnellen Schwenk teilen
    sich mehrere Bilder eine. Haengt die Reihenfolge dann an der Eingabe,
    schwankt auch das Ergebnis."""
    aufnahmen = [_bild(nr, abstand=0) for nr in range(6)]
    verdreht = [aufnahmen[3], aufnahmen[5], aufnahmen[0], aufnahmen[4], aufnahmen[1], aufnahmen[2]]

    (kandidat,) = serien.kandidaten(verdreht, schon_erkannt=[])

    assert [a.stamm for a in kandidat.aufnahmen] == [a.stamm for a in aufnahmen]


def _fenster_bild(
    stamm: str,
    uhrzeit: str,
    *,
    brennweite: float = 18.0,
    blende: float = 4.0,
    ausrichtung: int = 1,
) -> Aufnahme:
    """Eine Aufnahme mit fester Uhrzeit -- fuer die Fenster-Zusicherungen.

    Der Helfer daneben (`_bild`) zaehlt Abstaende ab einem Start hoch; hier
    braucht es die gemessenen Uhrzeiten aus dem echten Bestand, damit die
    Luecken (442 s / 5 s / 7 s / 187 s) im Test dieselben sind wie auf der
    Platte.
    """
    stunde, minute, sekunde = (int(x) for x in uhrzeit.split(":"))
    return Aufnahme(
        zeitpunkt=datetime(2026, 8, 30, stunde, minute, sekunde),
        kamera="XE5",
        stamm=stamm,
        dateien={},
        exif={
            "EXIF:Model": "X-E5",
            "EXIF:FocalLength": brennweite,
            "EXIF:FNumber": blende,
            "EXIF:Orientation": ausrichtung,
        },
    )


def test_ein_dreier_fenster_entsteht() -> None:
    """**KT-1s Panorama fiel einzig an der Mindestlaenge durch.**

    Firsthand am Bestand gemessen (`DSCF3894`-`3896`, Sebalduskirche): Brennweite
    und Blende konstant, Luecken 5 s und 7 s, davor und dahinter trennen 442 s
    bzw. 187 s. Die Gruppe ENTSTAND korrekt -- und wurde von
    `_KANDIDAT_MIN_LAENGE = 4` verworfen.

    Die Mindestlaenge als ENTSCHEIDER faellt damit weg: Stufe 2 ist nur noch der
    Vorfilter, der Zeitfenster schneidet. Was durchkommt, misst die
    Deckungsstufe kostenlos, und erst was danach ans Modell geht, kostet etwas.
    KT-1 woertlich: *"ggf. sind 2 bilder bereits der anfang des panoramas"*.
    """
    aufnahmen = [
        _fenster_bild("DSCF3893", "15:46:47", brennweite=18, blende=5.0),
        _fenster_bild("DSCF3894", "15:54:09", brennweite=18, blende=3.2),
        _fenster_bild("DSCF3895", "15:54:14", brennweite=18, blende=3.2),
        _fenster_bild("DSCF3896", "15:54:21", brennweite=18, blende=3.2),
    ]

    fenster = serien.kandidaten(aufnahmen, [])

    dreier = [f for f in fenster if len(f.aufnahmen) == 3]
    assert dreier, f"kein Dreier-Fenster entstanden: {[len(f.aufnahmen) for f in fenster]}"
    assert [a.stamm for a in dreier[0].aufnahmen] == ["DSCF3894", "DSCF3895", "DSCF3896"]


def test_ein_formatwechsel_schneidet_das_fenster() -> None:
    """Ein Wechsel zwischen Quer- und Hochformat ist eine neue Bildabsicht.

    Und er hat eine zweite, technische Folge: gemischte Achsen machen jede
    Richtungsaussage der Messung wertlos, weil sich Schwenk-Richtung und
    Rasterlage nicht mehr vergleichen lassen.

    Firsthand in der Fotorunde: das Merkmal schneidet zwei Fenster korrekt --
    `[3881 | 3882, 3883]` und `[3891, 3892 | 3893]`, jeweils Quer neben Hoch.
    """
    aufnahmen = [
        _fenster_bild("A", "10:00:00", brennweite=18, blende=4.0, ausrichtung=1),
        _fenster_bild("B", "10:00:05", brennweite=18, blende=4.0, ausrichtung=6),
        _fenster_bild("C", "10:00:10", brennweite=18, blende=4.0, ausrichtung=6),
    ]

    fenster = serien.kandidaten(aufnahmen, [])

    assert len(fenster) == 1, f"erwartet ein Fenster, war {len(fenster)}"
    assert [a.stamm for a in fenster[0].aufnahmen] == ["B", "C"], (
        "der Formatwechsel hat das Fenster nicht geschnitten"
    )


def test_eine_luecke_von_einer_minute_haelt_das_fenster_zusammen() -> None:
    """**Die Fensterweite ist die einzige irreversible Stelle der Kette.**

    Ein zu enges Fenster zerreisst eine Reihe, BEVOR irgendjemand misst -- und
    der Fehler ist danach unsichtbar, weil die Bilder nie zusammen betrachtet
    wurden. Ein zu weites kostet Messsekunden und schlimmstenfalls Cent-Betraege
    am Modell.

    Beide belegten Panoramen liegen zwar unter 10 s Binnenabstand (Prueffall
    5/7 s, Poster-Raster 15 Bilder in 25 s). Aber ein Stativ-Umbau zwischen zwei
    Zeilen eines Rasters ist real, und genau dort ist der Schaden nicht mehr
    gutzumachen. Deshalb 60 s statt 10 -- eine Abwaegung, kein Messwert.
    """
    aufnahmen = [
        _fenster_bild("A", "10:00:00", brennweite=18, blende=4.0),
        _fenster_bild("B", "10:00:45", brennweite=18, blende=4.0),
    ]

    fenster = serien.kandidaten(aufnahmen, [])

    assert len(fenster) == 1, "45 s Luecke hat das Fenster zerrissen"


def test_eine_luecke_von_zwei_minuten_trennt_weiterhin() -> None:
    """Die Untergrenze zur vorigen Zusicherung.

    Ohne sie koennte die Luecke beliebig gross werden und der Test darueber
    bliebe gruen -- ein Fenster ueber den ganzen Tag laesst die Messung an jedem
    Nachbarpaar laufen und traegt die Kosten, die das Design beziffert hat.
    """
    aufnahmen = [
        _fenster_bild("A", "10:00:00", brennweite=18, blende=4.0),
        _fenster_bild("B", "10:02:00", brennweite=18, blende=4.0),
    ]

    assert serien.kandidaten(aufnahmen, []) == [], "120 s Luecke trennt nicht mehr"
