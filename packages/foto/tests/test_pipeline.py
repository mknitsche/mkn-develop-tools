"""Die Verdrahtung. Jeder Einzelschritt hat eigene Tests — hier geht es um das,
was NUR beim Zusammenstecken schiefgehen kann.

Drei Dinge fallen genau hier durch und nirgends sonst:

1. **Die GPX-Zeit wird umgerechnet.** GPX traegt UTC, EXIF traegt lokale Zeit
   ohne Zone. Wer die Anker roh weiterreicht, bekommt im Sommer zwei Stunden
   Versatz — und damit fuer jedes Bild eine Koordinate, die plausibel aussieht
   und falsch ist.
2. **Widerlegte Anker fliegen VOR der Ortsbestimmung raus.** Danach ist es zu
   spaet: der Ausreisser hat den Radius dann schon aufgeblaeht.
3. **Was keinen belegten Ort hat, landet auf der Entscheidungsliste** — und
   NICHT im Baum mit einem geratenen Ort. Das ist KT-1s oberste Regel: im
   Zweifel nicht schreiben.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mkn_foto import inventar, pipeline
from mkn_foto.modell import Anker


def _gpx(pfad: Path, punkte: list[tuple[str, float, float]]) -> Path:
    zeilen = [
        '<?xml version="1.0"?>',
        '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">',
        "<trk><trkseg>",
    ]
    for zeit, lat, lon in punkte:
        zeilen.append(f'<trkpt lat="{lat}" lon="{lon}"><time>{zeit}</time></trkpt>')
    zeilen += ["</trkseg></trk>", "</gpx>"]
    pfad.write_text("\n".join(zeilen), encoding="utf-8")
    return pfad


def test_gpx_anker_kommen_in_kamerazeit_an(tmp_path):
    """Der teuerste Fehler der ganzen Kette, und er sieht nach nichts aus."""
    datei = _gpx(tmp_path / "spur.gpx", [("2026-08-27T08:31:22Z", 47.5, 11.4)])

    anker = pipeline.anker_sammeln(gpx_datei=datei)

    assert len(anker) == 1
    # 08:31 UTC ist im August 10:31 in Berlin. Zonenlos, wie das EXIF.
    assert anker[0].zeit == datetime(2026, 8, 27, 10, 31, 22)
    assert anker[0].zeit.tzinfo is None, "die Kamerazeit traegt keine Zone"


def test_widerlegte_anker_sind_vor_der_ortsbestimmung_weg(tmp_path):
    """Ein Ausreisser zwischen zwei nahen Nachbarn blaeht sonst den Radius auf
    und macht aus einem belegten Ort einen blossen Vorschlag."""
    datei = _gpx(
        tmp_path / "spur.gpx",
        [
            ("2026-08-27T08:00:00Z", 47.5000, 11.4000),
            ("2026-08-27T08:05:00Z", 47.5100, 11.4100),  # ~1,4 km daneben
            ("2026-08-27T08:10:00Z", 47.5001, 11.4001),
        ],
    )

    roh = pipeline.anker_sammeln(gpx_datei=datei, bereinigen=False)
    sauber = pipeline.anker_sammeln(gpx_datei=datei)

    assert len(roh) == 3
    assert len(sauber) == 2, f"der Ausreisser steht noch drin: {sauber}"
    assert all(a.lat < 47.505 for a in sauber)


def test_anker_aus_beiden_quellen_werden_chronologisch_gemischt(tmp_path):
    """Handybilder und Spur sind zwei Quellen fuer dieselbe Frage. Wer sie
    hintereinanderhaengt statt zu mischen, macht die Nachbarschaftspruefung
    der Ortsbestimmung wertlos."""
    datei = _gpx(
        tmp_path / "spur.gpx",
        [("2026-08-27T08:00:00Z", 47.500, 11.400), ("2026-08-27T08:20:00Z", 47.501, 11.401)],
    )
    handy = [Anker(zeit=datetime(2026, 8, 27, 10, 10, 0), lat=47.5005, lon=11.4005, name=None)]

    anker = pipeline.anker_sammeln(gpx_datei=datei, weitere=handy)

    zeiten = [a.zeit for a in anker]
    assert zeiten == sorted(zeiten), f"nicht chronologisch: {zeiten}"
    assert len(anker) == 3


def test_ein_spot_mit_beleg_wird_verortet_der_andere_vorgelegt(tmp_path, monkeypatch):
    """Die Zusicherung, die `fahre` SELBST prueft — und die den drei Tests oben
    fehlte.

    Genau hier sass der Fehler: `fuer_spot` gibt die HERKUNFT in `quelle`
    zurueck (gpx | schild | anker) und den Zweifel als `vorschlag`. Die erste
    Fassung verglich gegen das Wort "belegt", das es nie gab — damit waere JEDER
    Spot offen gewesen: nichts verortet, alles vorgelegt, und der Lauf haette das
    fehlerfrei gemeldet.

    exiftool wird ersetzt, nicht gefahren — die Konvention des Hauses
    (`test_inventar.py`): geprueft wird die Verdrahtung, nicht der Wrapper.
    """
    quelle = tmp_path / "kamera"
    quelle.mkdir()
    felder = []
    for name, zeit in (("A0001", "2026:08:27 10:31:22"), ("A0002", "2026:08:27 11:31:22")):
        (quelle / f"{name}.JPG").write_bytes(b"bild")
        felder.append({"EXIF:DateTimeOriginal": zeit, "EXIF:Model": "X-E5"})

    monkeypatch.setattr(inventar.exif, "lies", lambda pfade: felder[: len(pfade)])

    # Der erste Spot hat Anker in seiner Naehe, der zweite keine.
    anker = [
        Anker(zeit=datetime(2026, 8, 27, 10, 30, 0), lat=47.5000, lon=11.4000, name="Ort A"),
        Anker(zeit=datetime(2026, 8, 27, 10, 33, 0), lat=47.5001, lon=11.4001, name=None),
    ]

    lauf = pipeline.fahre(quelle, tmp_path / "ziel", anker=anker, schreiben_aktiv=False)

    assert len(lauf.spots) == 2, f"erwartet zwei Sessions, bekommen {len(lauf.spots)}"
    assert len(lauf.orte) == 1, (
        f"erwartet genau einen verorteten Spot, bekommen {len(lauf.orte)} — "
        "bei 0 vergleicht die Verortung gegen einen Enum-Wert, den es nicht gibt"
    )
    assert len(lauf.offen) == 1, f"erwartet einen offenen Spot: {lauf.offen}"
    assert lauf.belegt == 1


def test_zwei_sessions_am_selben_ort_werden_ein_spot(tmp_path, monkeypatch):
    """Der Scheibum-Fall, und er ist der haeufigste der ganzen Reise.

    KT-1 hat ihn selbst beschrieben: *"Parkplatz .. dann handy ... dann laufen
    ... dann teil 1 ... dann teil 2 ... dann zurueck zum Parkplatz"*. Zwischen
    Teil 1 und Teil 2 liegt eine Pause, die groesser ist als die Sessionschwelle
    — und trotzdem ist es EIN Spot. Die Zeit allein kann das nicht sehen, die
    Anker sehen es.

    Ohne diese Zusicherung war der Aufruf von `fasse_gleichen_ort_zusammen` in
    der Pipeline unbewiesen: die Mutation, die ihn ersatzlos entfernt, ueberlebte
    den Test darueber, weil dessen zwei Sessions an verschiedenen Orten lagen.
    """
    quelle = tmp_path / "kamera"
    quelle.mkdir()
    felder = []
    # Zwei Sessions, 20 Minuten Pause -- ueber der Sessionschwelle von 15.
    for name, zeit in (
        ("B0001", "2026:08:25 15:35:00"),
        ("B0002", "2026:08:25 15:36:00"),
        ("B0003", "2026:08:25 16:37:00"),
        ("B0004", "2026:08:25 16:38:00"),
    ):
        (quelle / f"{name}.JPG").write_bytes(b"bild")
        felder.append({"EXIF:DateTimeOriginal": zeit, "EXIF:Model": "X-E5"})

    monkeypatch.setattr(inventar.exif, "lies", lambda pfade: felder[: len(pfade)])

    # Anker um BEIDE Sessions herum, alle am selben Ort (wenige Meter).
    anker = [
        Anker(zeit=datetime(2026, 8, 25, 15, 34, 0), lat=47.5000, lon=11.4000, name="Scheibum"),
        Anker(zeit=datetime(2026, 8, 25, 15, 37, 0), lat=47.5001, lon=11.4001, name=None),
        Anker(zeit=datetime(2026, 8, 25, 16, 36, 0), lat=47.5001, lon=11.4000, name=None),
        Anker(zeit=datetime(2026, 8, 25, 16, 39, 0), lat=47.5000, lon=11.4001, name=None),
    ]

    lauf = pipeline.fahre(quelle, tmp_path / "ziel", anker=anker, schreiben_aktiv=False)

    assert len(lauf.spots) == 1, (
        f"zwei Sessions am selben Ort blieben getrennt ({len(lauf.spots)} Spots) — "
        "die Pause gehoert zum Ort, und KT-1 muesste denselben Ort zweimal beschriften"
    )
    assert len(lauf.spots[0].aufnahmen) == 4
    assert len(lauf.orte) == 1, "der zusammengefasste Spot ist nicht verortet"


def test_zonenbehaftete_anker_werden_auf_kamerazeit_gebracht(tmp_path):
    """Die Mediathek liefert UTC MIT Zone (Core-Data-Epoche), GPX nach der
    Umrechnung ohne. Ungeprueft gemischt bricht schon das Sortieren.

    Firsthand beim ersten echten Lauf ueber 283 Handybilder:
    `TypeError: can't compare offset-naive and offset-aware datetimes`.
    Der Test darueber hatte einen handgebauten NAIVEN Anker benutzt und konnte
    den Fall deshalb nicht sehen — ein Beweis muss seinen Gegenstand enthalten
    (LP-34).
    """
    datei = _gpx(tmp_path / "spur.gpx", [("2026-08-27T08:00:00Z", 47.500, 11.400)])
    # So, wie die Mediathek sie liefert: UTC mit Zone.
    aus_mediathek = [
        Anker(
            zeit=datetime(2026, 8, 27, 8, 10, 0, tzinfo=UTC),
            lat=47.5005,
            lon=11.4005,
            name=None,
        )
    ]

    anker = pipeline.anker_sammeln(gpx_datei=datei, weitere=[])
    gemischt = pipeline.anker_sammeln(
        gpx_datei=datei, weitere=[pipeline._in_kamerazeit_anker(a) for a in aus_mediathek]
    )

    assert len(anker) == 1
    assert len(gemischt) == 2
    assert all(a.zeit.tzinfo is None for a in gemischt), (
        f"nicht alle Anker sind zonenlos: {[a.zeit for a in gemischt]}"
    )
    # 08:10 UTC ist im August 10:10 in Berlin.
    assert gemischt[1].zeit == datetime(2026, 8, 27, 10, 10, 0)


def test_eine_menschliche_antwort_gilt_als_belegt(tmp_path, monkeypatch):
    """KT-1s Antwort ist keine Schaetzung, sondern eine Aussage.

    Die Abdeckungspruefung in `ort.fuer_spot` misst, wie gut die Anker eine
    Session einrahmen — bei EINEM Anker aus einer Notiz reicht das nie, und der
    Spot bliebe `vorschlag`. Firsthand: vier Spots trugen nach dem Einlesen der
    Notizen den richtigen Namen ("Lenggries", "Vomp", "Kochel am See") und
    standen trotzdem wieder auf der Entscheidungsliste. KT-1 haette dieselbe
    Frage ein zweites Mal beantworten muessen.

    Die Geometrie wird dafuer NICHT angefasst: die menschliche Antwort ist eine
    eigene Ebene ueber ihr, keine Manipulation der Rechnung.
    """
    quelle = tmp_path / "kamera"
    quelle.mkdir()
    felder = []
    # Dicht genug fuer EINE Session -- 57 Minuten Abstand waeren zwei Spots
    # gewesen, und der Test haette seinen eigenen Aufbau geprueft statt die Sache.
    for name, zeit in (("C0001", "2026:08:24 06:19:00"), ("C0002", "2026:08:24 06:25:00")):
        (quelle / f"{name}.JPG").write_bytes(b"bild")
        felder.append({"EXIF:DateTimeOriginal": zeit, "EXIF:Model": "X-E5"})
    monkeypatch.setattr(inventar.exif, "lies", lambda pfade: felder[: len(pfade)])

    notiz_ordner = tmp_path / "offen" / "2026-08-24_0619-0716"
    notiz_ordner.mkdir(parents=True)
    (notiz_ordner / "ort.md").write_text(
        "# x\n\n## Ort\n\n## Gehoert zusammen mit\n\nLenggries im findpinguines\n",
        encoding="utf-8",
    )

    footprint = [Anker(zeit=datetime(2026, 8, 24, 7, 23), lat=47.68, lon=11.57, name="Lenggries")]
    anker = pipeline.anker_sammeln(
        weitere=footprint, notiz_ordner=tmp_path / "offen", bereinigen=False
    )

    lauf = pipeline.fahre(
        quelle,
        tmp_path / "ziel",
        anker=anker,
        notiz_ordner=tmp_path / "offen",
        schreiben_aktiv=False,
    )

    assert len(lauf.orte) == 1, (
        "die beantwortete Session gilt nicht als verortet — KT-1 muesste dieselbe "
        f"Frage noch einmal beantworten. offen: {lauf.offen}"
    )
    assert lauf.orte[id(lauf.spots[0])].name == "Lenggries"
    assert not lauf.offen
