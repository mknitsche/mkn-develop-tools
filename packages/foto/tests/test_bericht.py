"""Protokoll und Rueckweg — die zwei Dinge, die KT-1 am 2026-08-30 verlangt hat.

> *"so dass klar ist, was durch ist (also nach capONE koennte) und was offen ist,
> mit einer eindeutigen protokolldatei und einer sinnvolen moeglichkeit die
> entscheidungen einzutragen und dir mitzugeben"*

Drei Anforderungen, und die dritte ist die, an der die erste Fassung gescheitert
ist: *"irgendwie weiss ich ueberhaupt nicht was ich machen soll"*. Zwoelf Ordner
mit je einer `ort.md` sind kein Formular, sondern eine Schnitzeljagd.

**Die Bilder muessen verteilt liegen, die Eingabe gehoert an EINE Stelle.** Eine
einzige Datei, in der alle offenen Faelle untereinander stehen, jeder mit einem
Feld zum Hineinschreiben. Sie ist zugleich der Rueckweg: dasselbe Modul liest
sie wieder ein.
"""

from __future__ import annotations

from datetime import datetime

from mkn_foto import bericht, notizen
from mkn_foto.modell import Aufnahme, Ort, Spot

ORT = Ort(lat=47.68, lon=11.57, radius_m=250, name="Lenggries", quelle="schild")


def _spot(tag: int, von: tuple[int, int], bis: tuple[int, int], anzahl: int) -> Spot:
    """Baut eine Session mit `anzahl` Aufnahmen zwischen zwei Uhrzeiten.

    Die Zwischenzeiten werden ueber `timedelta` verteilt, nicht durch Addition
    auf das Minutenfeld: die erste Fassung tat das und lief bei 141 Aufnahmen ab
    Minute 7 in "minute must be in 0..59".
    """
    start = datetime(2026, 8, tag, *von)
    ende = datetime(2026, 8, tag, *bis)
    schritt = (ende - start) / max(anzahl - 1, 1)
    aufnahmen = tuple(
        Aufnahme(
            # Die LETZTE exakt auf `ende`: die Division rundet, und 30 Minuten
            # durch 26 mal 26 ergibt 08:08:59 statt 08:09 -- der Ordnername
            # hiesse dann -0808 und der Test pruefte seine eigene Rundung.
            zeitpunkt=ende if i == anzahl - 1 else start + schritt * i,
            kamera="XE5",
            stamm=f"X{i:04d}",
            dateien={},
            exif={},
        )
        for i in range(anzahl)
    )
    return Spot(aufnahmen=aufnahmen)


def test_protokoll_trennt_durch_von_offen(tmp_path):
    """Die Kernfrage: was kann nach Capture One, was nicht."""
    fertig = _spot(26, (6, 7), (6, 57), 141)
    offen = _spot(24, (7, 39), (8, 9), 27)

    pfad = bericht.protokoll(
        tmp_path, verortet=[(fertig, ORT)], beantwortet=[], offen=[(offen, None)]
    )

    text = pfad.read_text(encoding="utf-8")

    # Nicht "kommt vor", sondern "steht im richtigen Abschnitt". Die erste
    # Fassung prueste nur die Anwesenheit der Zahlen -- und blieb gruen, als die
    # Mutation die Trennung ganz entfernte. Genau die Trennung ist aber KT-1s
    # Anforderung: "so dass klar ist, was durch ist und was offen ist".
    durch = text.index("## Durch")
    offen_ab = text.index("## Offen")
    assert durch < offen_ab, "die Abschnitte stehen in der falschen Reihenfolge"

    abschnitt_durch = text[durch:offen_ab]
    abschnitt_offen = text[offen_ab:]

    assert "2026-08-26" in abschnitt_durch and "141" in abschnitt_durch, (
        f"die fertige Session steht nicht im Durch-Abschnitt:\n{abschnitt_durch}"
    )
    assert "Lenggries" in abschnitt_durch
    assert "2026-08-24" in abschnitt_offen and "27" in abschnitt_offen, (
        f"die offene Session steht nicht im Offen-Abschnitt:\n{abschnitt_offen}"
    )
    assert "2026-08-24" not in abschnitt_durch, (
        "eine offene Session steht im Durch-Abschnitt — sie ginge faelschlich nach Capture One"
    )
    assert "Capture One" in abschnitt_durch, "der Durch-Abschnitt sagt nicht, wofuer er da ist"


def test_protokoll_nennt_die_gesamtzahlen(tmp_path):
    """Ohne Summen muss KT-1 selbst zaehlen, um zu wissen, wo er steht."""
    pfad = bericht.protokoll(
        tmp_path,
        verortet=[(_spot(26, (6, 7), (6, 57), 141), ORT)],
        beantwortet=[(_spot(24, (23, 4), (23, 4), 1), "Loeschen - war im Hotel")],
        offen=[(_spot(24, (7, 39), (8, 9), 27), None)],
    )

    text = pfad.read_text(encoding="utf-8")
    assert "169" in text, f"die Gesamtzahl der Aufnahmen fehlt:\n{text}"


def test_entscheidungsdatei_hat_je_offenem_fall_ein_feld(tmp_path):
    """EINE Datei, nicht zwoelf Ordner. Das war KT-1s eigentliche Klage."""
    a = _spot(24, (7, 39), (8, 9), 27)
    b = _spot(25, (19, 14), (19, 58), 57)

    pfad = bericht.entscheidungsdatei(tmp_path, [(a, None), (b, ORT)])

    text = pfad.read_text(encoding="utf-8")
    assert text.count(bericht.FELD) == 2, (
        f"erwartet zwei Eingabefelder, gefunden {text.count(bericht.FELD)}:\n{text}"
    )
    assert "2026-08-24_0739-0809" in text and "2026-08-25_1914-1958" in text
    # Der Vorschlag ist eine Frage, die sich mit Ja beantworten laesst.
    assert "Lenggries" in text


def test_der_rueckweg_liest_die_eingetragenen_antworten(tmp_path):
    """Ohne diese Haelfte waere die Datei eine Sackgasse: KT-1 traegt ein, und
    niemand liest es je."""
    pfad = bericht.entscheidungsdatei(
        tmp_path,
        [(_spot(24, (7, 39), (8, 9), 27), None), (_spot(25, (19, 14), (19, 58), 57), None)],
    )
    text = pfad.read_text(encoding="utf-8")
    # So, wie ein Mensch es tut: hinter das Feld schreiben.
    text = text.replace(f"{bericht.FELD}\n", f"{bericht.FELD} Vomp, gleich hinter der Bruecke\n", 1)
    pfad.write_text(text, encoding="utf-8")

    gelesen = bericht.lies_entscheidungen(pfad)

    assert len(gelesen) == 1, f"erwartet genau eine beantwortete Zeile: {gelesen}"
    assert gelesen[0].text == "Vomp, gleich hinter der Bruecke"
    assert gelesen[0].von == datetime(2026, 8, 24, 7, 39)
    assert gelesen[0].bis == datetime(2026, 8, 24, 8, 9)


def test_leere_felder_zaehlen_nicht_als_antwort(tmp_path):
    """Untergrenze: ohne diesen Fall bestuende der Leser auch dann, wenn er jedes
    Feld als beantwortet meldete — und eine unbearbeitete Datei saehe aus wie
    zwoelf Antworten."""
    pfad = bericht.entscheidungsdatei(tmp_path, [(_spot(24, (7, 39), (8, 9), 27), None)])

    assert bericht.lies_entscheidungen(pfad) == []


def test_die_antworten_passen_ins_notizen_format(tmp_path):
    """Der Rueckweg muss in die bestehende Pipeline passen, sonst braeuchte es
    einen zweiten Weg fuer dieselbe Sache."""
    pfad = bericht.entscheidungsdatei(tmp_path, [(_spot(24, (6, 19), (7, 16), 43), None)])
    text = pfad.read_text(encoding="utf-8").replace(
        f"{bericht.FELD}\n", f"{bericht.FELD} Lenggries im findpinguines\n", 1
    )
    pfad.write_text(text, encoding="utf-8")

    gelesen = bericht.lies_entscheidungen(pfad)

    assert isinstance(gelesen[0], notizen.Notiz), "kein Notiz-Objekt — die Pipeline kann es nicht"
    anker = [
        type(gelesen[0])  # nur um den Import zu nutzen
    ]
    assert anker
