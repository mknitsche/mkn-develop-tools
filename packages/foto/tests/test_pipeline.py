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

from mkn_foto import anreichern, inventar, konfig, pipeline
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


def test_beantwortete_sessions_kommen_nicht_erneut_auf_die_liste(tmp_path, monkeypatch):
    """KT-1 am 2026-08-30: "es gibt einen ordner foto-neu - da sind aber die drin,
    die ich schon beantwortet habe".

    Er hatte recht: 11 von 12 vorgelegten Ordnern waren beantwortet. Mein
    Denkfehler war die Gleichsetzung von OFFEN mit NICHT VERORTET. "Loeschen -
    war im Hotel" und "ist schwarz - falsch belichtet" sind vollstaendige
    Antworten — sie liefern nur keine Koordinate. Wer sie erneut vorlegt, gibt
    dem Menschen seine eigene Arbeit zurueck.

    Vorgelegt wird deshalb nur, was WEDER verortet NOCH beantwortet ist.
    """
    quelle = tmp_path / "kamera"
    quelle.mkdir()
    felder = []
    # Zwei Sessions ohne jeden Anker, eine Stunde auseinander.
    for name, zeit in (("D0001", "2026:08:24 23:04:00"), ("D0002", "2026:08:25 11:49:00")):
        (quelle / f"{name}.JPG").write_bytes(b"bild")
        felder.append({"EXIF:DateTimeOriginal": zeit, "EXIF:Model": "X-E5"})
    monkeypatch.setattr(inventar.exif, "lies", lambda pfade: felder[: len(pfade)])

    # Nur fuer die ERSTE liegt eine Antwort vor -- eine ohne Ortsangabe.
    notiz = tmp_path / "offen" / "2026-08-24_2304-2304"
    notiz.mkdir(parents=True)
    (notiz / "ort.md").write_text(
        "# x\n\n## Ort\n\n## Gehoert zusammen mit\n\nLoeschen - war im Hotel\n",
        encoding="utf-8",
    )

    lauf = pipeline.fahre(
        quelle, tmp_path / "ziel", notiz_ordner=tmp_path / "offen", schreiben_aktiv=False
    )

    offene_ordner = [f"{s.von:%Y-%m-%d_%H%M}-{s.bis:%H%M}" for s, _ in lauf.offen]
    assert "2026-08-24_2304-2304" not in offene_ordner, (
        "eine beantwortete Session wird erneut vorgelegt — KT-1 bekaeme seine "
        f"eigene Arbeit zurueck. Vorgelegt: {offene_ordner}"
    )
    assert offene_ordner == ["2026-08-25_1149-1149"], f"unerwartete Liste: {offene_ordner}"
    assert len(lauf.beantwortet) == 1, "die Antwort ohne Ort ist nirgends festgehalten"


def test_die_serie_kommt_im_sidecar_der_kopie_an(tmp_path, monkeypatch):
    """Die Verdrahtungs-Zusicherung, und sie ist heikel.

    `anreichern` ordnet Stichworte ueber die OBJEKT-IDENTITAET zu. Die Pipeline
    baut fuer die Kopien neue Aufnahme-Objekte — wenn sie das zweimal tut, einmal
    fuer die Orte und einmal fuer die Serien, sind es VERSCHIEDENE Objekte, und
    die Zuordnung greift ins Leere. Alles bliebe gruen: Sidecars entstehen, Orte
    stehen drin, nur die Serienangabe fehlt lautlos.
    """
    import shutil

    if shutil.which("exiftool") is None:
        import pytest as _p

        _p.skip("exiftool nicht verfuegbar")

    quelle = tmp_path / "kamera"
    quelle.mkdir()
    felder = []
    for nr, (name, zeit) in enumerate(
        (("E0001", "2026:08:24 06:19:00"), ("E0002", "2026:08:24 06:19:02")), start=1
    ):
        (quelle / f"{name}.RAF").write_bytes(b"roh")
        felder.append(
            {
                "EXIF:DateTimeOriginal": zeit,
                "EXIF:Model": "X-E5",
                # Die Zahl 1, nicht "On" -- die Kamera schreibt einen Schalter, und
                # die Erkennung vergleicht gegen den Zahlwert.
                "MakerNotes:AutoBracketing": 1,
                "MakerNotes:SequenceNumber": nr,
            }
        )
    monkeypatch.setattr(inventar.exif, "lies", lambda pfade: felder[: len(pfade)])

    lauf = pipeline.fahre(quelle, tmp_path / "ziel", schreiben_aktiv=True)

    assert lauf.angereichert is not None, "die Anreicherung lief gar nicht"
    assert lauf.angereichert.sidecars == 2, (
        f"erwartet zwei Sidecars, bekommen {lauf.angereichert.sidecars}"
    )

    assert lauf.serien, "die Belichtungsreihe wurde gar nicht erkannt"
    marke = f"{lauf.serien[0].typ}{lauf.serien[0].nummer:02d}"

    sidecar = next((tmp_path / "ziel" / "2026-08-24").glob("*.xmp"))
    inhalt = sidecar.read_text(encoding="utf-8")
    # Auf die SERIENMARKE pruefen, nicht auf "Technik": letzteres steht durch das
    # Einzelbild-Stichwort ohnehin in jedem Sidecar, und der Test waere auch dann
    # gruen geblieben, wenn die Serie lautlos verlorengeht. Erste Fassung genau so.
    assert marke in inhalt, (
        f"die Serienmarke {marke} fehlt im Sidecar — die Stichwort-Zuordnung "
        f"ueber die Objekt-Identitaet greift ins Leere.\n{inhalt[:400]}"
    )
    assert "Einzelbild" not in inhalt, (
        "die Aufnahme gilt als Einzelbild, obwohl sie zu einer Serie gehoert"
    )


def test_heuristik_kandidaten_bekommen_keinen_serien_namen(tmp_path, monkeypatch):
    """Regel A, und der teuerste Einzeldefekt des bisherigen Stands.

    `serien.kandidaten` liefert Vermutungen (`sicher=False`, `quelle="heuristik"`).
    Die Pipeline reichte sie ungefiltert an `schreiben.kopiere` — Dateien hiessen
    `pan01…`, obwohl kein Blick aufs Bild stattgefunden hatte. Die Spec misst fuer
    genau diese Kandidaten **ein Drittel** Trefferquote (§ 4): zwei von drei so
    benannten Dateien tragen einen falschen Namen, und der Name ist das, wonach
    KT-1 spaeter sucht.

    Bis Stufe 3 urteilt, heissen sie `std`. Sie sind damit nicht verloren — sie
    stehen als Kandidat im Protokoll.
    """
    quelle = tmp_path / "kamera"
    quelle.mkdir()
    felder = []
    # Gleiche Brennweite und Blende, dicht hintereinander -- die Heuristik haelt
    # das fuer ein Panorama. Kein AutoBracketing: Stufe 1 sagt also nichts.
    # VIER Bilder, nicht drei: `_KANDIDAT_MIN_LAENGE` ist 4, und mit dreien
    # entstand gar kein Kandidat -- der Test war gruen, ohne seinen Gegenstand
    # zu enthalten (LP-34).
    for i, sek in enumerate((0, 3, 6, 9)):
        (quelle / f"F{i:04d}.RAF").write_bytes(b"roh")
        felder.append(
            {
                "EXIF:DateTimeOriginal": f"2026:08:24 06:19:{sek:02d}",
                "EXIF:Model": "X-E5",
                "EXIF:FocalLength": "16.0 mm",
                "EXIF:FNumber": 8.0,
            }
        )
    monkeypatch.setattr(inventar.exif, "lies", lambda pfade: felder[: len(pfade)])

    pipeline.fahre(quelle, tmp_path / "ziel", schreiben_aktiv=True)

    namen = sorted(p.name for p in (tmp_path / "ziel" / "2026-08-24").glob("*.RAF"))
    assert namen, "nichts geschrieben"
    unbelegt = [n for n in namen if "_pan" in n or "_hdr" in n or "_foc" in n]
    assert not unbelegt, (
        "Heuristik-Kandidaten tragen einen Serien-Namen, ohne dass jemand das Bild "
        f"gesehen hat — die Spec misst dafuer 1/3 Trefferquote: {unbelegt}"
    )
    assert all("_std_" in n for n in namen), f"unerwartete Namen: {namen}"


def test_kamerasichere_serien_werden_weiterhin_benannt(tmp_path, monkeypatch):
    """Untergrenze zur Regel darueber: was die KAMERA belegt, bleibt benannt.

    Ohne diesen Fall waere ein Filter, der jede Serie verwirft, genauso gruen —
    und die kamerasicheren Belichtungsreihen (77 im Bestand) verloeren ihren
    Namen, obwohl sie unfehlbar erkannt sind.
    """
    quelle = tmp_path / "kamera"
    quelle.mkdir()
    felder = []
    for nr, sek in enumerate((0, 1, 2), start=1):
        (quelle / f"G{nr:04d}.RAF").write_bytes(b"roh")
        felder.append(
            {
                "EXIF:DateTimeOriginal": f"2026:08:24 06:19:{sek:02d}",
                "EXIF:Model": "X-E5",
                "MakerNotes:AutoBracketing": 1,
                "MakerNotes:SequenceNumber": nr,
            }
        )
    monkeypatch.setattr(inventar.exif, "lies", lambda pfade: felder[: len(pfade)])

    pipeline.fahre(quelle, tmp_path / "ziel", schreiben_aktiv=True)

    namen = sorted(p.name for p in (tmp_path / "ziel" / "2026-08-24").glob("*.RAF"))
    assert all("_hdr" in n for n in namen), (
        f"die kamerabelegte Belichtungsreihe verlor ihren Namen: {namen}"
    )


def test_bilder_einer_session_bekommen_verschiedene_koordinaten(tmp_path, monkeypatch):
    """Der Kern von KT-1s Geotagging-Klage — und es war ein fehlender Aufruf.

    `geotag.fuer_aufnahme` existierte samt Tests, aber die Pipeline rief es nie.
    Alle Bilder einer Session trugen die Sammelkoordinate ihres Spots: 141 Bilder
    auf demselben Punkt. KT-1: *"sinnvolle gpx (gps) informationen, die man auf
    einer karte sieht"* — auf einer Karte ist das ein Punkt, keine Route.
    """
    quelle = tmp_path / "kamera"
    quelle.mkdir()
    felder = []
    for i, minute in enumerate((0, 4, 8)):
        (quelle / f"H{i:04d}.RAF").write_bytes(b"roh")
        felder.append(
            {
                "EXIF:DateTimeOriginal": f"2026:08:26 06:{minute:02d}:00",
                "EXIF:Model": "X-E5",
            }
        )
    monkeypatch.setattr(inventar.exif, "lies", lambda pfade: felder[: len(pfade)])

    # Dichte Spur, wie am 26.08. real vorhanden (Median 63 s).
    anker = [
        Anker(
            zeit=datetime(2026, 8, 26, 6, m),
            lat=47.5000 + m * 0.001,
            lon=11.4000 + m * 0.001,
            name=None,
        )
        for m in range(0, 10)
    ]

    lauf = pipeline.fahre(quelle, tmp_path / "ziel", anker=anker, schreiben_aktiv=False)

    orte = [pipeline.ort_fuer_bild(a, lauf) for a in lauf.aufnahmen]
    assert all(o is not None for o in orte), f"nicht jedes Bild verortet: {orte}"
    breiten = [round(o.lat, 6) for o in orte]
    assert len(set(breiten)) == 3, (
        f"alle Bilder derselben Session auf demselben Punkt: {breiten} — "
        "geotag wird nicht aufgerufen"
    )
    assert breiten == sorted(breiten), "die Positionen laufen nicht mit der Zeit"


def test_ohne_spur_bleibt_der_session_ort_der_rueckfall(tmp_path, monkeypatch):
    """Untergrenze: an den zwei Tagen ohne Spur (25.08. hat NULL Punkte) darf das
    Bild nicht ortlos werden, nur weil die Interpolation nichts hergibt.

    Ohne diese Zusicherung waere ein Geotagger, der den Session-Ort ersatzlos
    verwirft, genauso gruen — und die Verortung fiele von 91 % auf die Abdeckung
    der Spur zurueck.
    """
    quelle = tmp_path / "kamera"
    quelle.mkdir()
    felder = []
    for i, minute in enumerate((0, 2)):
        (quelle / f"J{i:04d}.RAF").write_bytes(b"roh")
        felder.append(
            {
                "EXIF:DateTimeOriginal": f"2026:08:25 12:{minute:02d}:00",
                "EXIF:Model": "X-E5",
            }
        )
    monkeypatch.setattr(inventar.exif, "lies", lambda pfade: felder[: len(pfade)])

    # Anker NUR VOR der Session. geotag extrapoliert nicht (die Position waere
    # unbekannt, nicht "wie der letzte Punkt"), der Session-Ort greift ueber sein
    # eigenes Randfenster noch.
    #
    # Die erste Fassung setzte einen Anker davor und einen danach -- damit
    # interpolierte geotag sauber, der Rueckfall wurde nie erreicht, und die
    # Mutation "Rueckfall entfernt" ueberlebte den Test.
    anker = [
        Anker(zeit=datetime(2026, 8, 25, 11, 58), lat=47.65, lon=11.37, name="Kochel am See"),
        Anker(zeit=datetime(2026, 8, 25, 11, 59), lat=47.6501, lon=11.3701, name=None),
    ]

    lauf = pipeline.fahre(quelle, tmp_path / "ziel", anker=anker, schreiben_aktiv=False)

    orte = [pipeline.ort_fuer_bild(a, lauf) for a in lauf.aufnahmen]
    assert all(o is not None for o in orte), (
        "ohne Interpolation ist das Bild ortlos — der Session-Ort muss der "
        f"Rueckfall bleiben: {orte}"
    )


def test_eine_beantwortete_einzelaufnahme_kommt_nicht_wieder(tmp_path, monkeypatch):
    """Der Fehler, der KT-1s Kritik nach dem V1-Lauf reproduzierte.

    Ein Ordnername traegt MINUTEN (`2026-08-22_1841-1841`), ein Spot SEKUNDEN
    (18:41:23). Bei einer Einzelaufnahme sind von und bis identisch — und dann
    ueberlappen die beiden Fenster nicht: 18:41:23 liegt hinter 18:41:00.

    Firsthand: fuenf Sessions, die KT-1 beantwortet hatte ("Loeschen - war im
    Hotel", "ist schwarz - falsch belichtet"), standen nach dem Lauf wieder auf
    der Frageliste. Genau das, was er zwei Stunden zuvor beanstandet hatte.
    """
    quelle = tmp_path / "kamera"
    quelle.mkdir()
    (quelle / "Z0001.RAF").write_bytes(b"roh")
    monkeypatch.setattr(
        inventar.exif,
        "lies",
        lambda pfade: [{"EXIF:DateTimeOriginal": "2026:08:22 18:41:23", "EXIF:Model": "X-E5"}],
    )

    notiz = tmp_path / "offen" / "2026-08-22_1841-1841"
    notiz.mkdir(parents=True)
    (notiz / "ort.md").write_text(
        "# x\n\n## Ort\n\n## Gehoert zusammen mit\n\nGehoert zum vorherigen Ordner\n",
        encoding="utf-8",
    )

    lauf = pipeline.fahre(
        quelle, tmp_path / "ziel", notiz_ordner=tmp_path / "offen", schreiben_aktiv=False
    )

    assert not lauf.offen, (
        "die beantwortete Einzelaufnahme steht wieder auf der Frageliste — "
        f"Minuten- gegen Sekundengenauigkeit: {[(s.von, s.bis) for s, _ in lauf.offen]}"
    )
    assert len(lauf.beantwortet) == 1


def test_die_motive_kommen_in_die_dateien(tmp_path, monkeypatch):
    """Die Verdrahtung — und dieselbe Klasse, die gestern `geotag` betraf.

    Ein Modul in der Modulliste ist noch kein Aufruf im Ablauf. `geotag`
    existierte samt Tests und wurde nie gerufen; die Bilder trugen deshalb
    Sammelkoordinaten. Hier ist es der Motivlauf: ohne diesen Test entstuende
    ein Baum ohne ein einziges Motiv-Stichwort, und der Lauf meldete es
    fehlerfrei.
    """
    import json as _json
    import shutil

    if shutil.which("exiftool") is None:
        import pytest as _p

        _p.skip("exiftool nicht verfuegbar")

    quelle = tmp_path / "kamera"
    quelle.mkdir()
    felder = []
    from PIL import Image

    for i, sek in enumerate((0, 30)):
        # Ein ECHTES JPEG: in eine Attrappe kann exiftool nicht schreiben, und
        # dann entstehen null Sidecars -- der Test schluege aus dem falschen
        # Grund an.
        Image.new("RGB", (200, 150), (80 + i * 40, 100, 140)).save(quelle / f"M{i}.JPG")
        felder.append(
            {
                "EXIF:DateTimeOriginal": f"2026:08:24 06:19:{sek:02d}",
                "EXIF:Model": "X-E5",
            }
        )
    monkeypatch.setattr(inventar.exif, "lies", lambda pfade: felder[: len(pfade)])

    def transport(url, koerper, kopf, zeitgrenze):
        nutzlast = {
            "sicher": True,
            "motive": ["Sonnenaufgang", "Bergkette"],
            "beschreibung": "Ein Satz zum Bild.",
            "belichtung": "gut",
        }
        antwort = {
            "content": [{"text": _json.dumps(nutzlast)}],
            "usage": {"input_tokens": 2184, "output_tokens": 187},
        }
        return 200, _json.dumps(antwort).encode()

    lauf = pipeline.fahre(
        quelle,
        tmp_path / "ziel",
        schreiben_aktiv=True,
        modell=("anthropic", "test-modell"),
        schluessel="x",
        transport=transport,
    )

    assert lauf.motive is not None, "der Motivlauf ist nicht verdrahtet"
    assert lauf.motive.messung.aufrufe > 0, "es wurde nichts angefragt"

    # JPEG traegt die Daten EINGEBETTET, keinen Sidecar (Spec Paragraf 10) --
    # die erste Testfassung suchte nach *.xmp und fand zu Recht nichts.
    import subprocess as _sp

    bilder = sorted((tmp_path / "ziel" / "2026-08-24").glob("*.JPG"))
    assert bilder, f"keine Bilder im Ziel: {list((tmp_path / 'ziel' / '2026-08-24').iterdir())}"
    roh = _sp.run(
        [
            "exiftool",
            "-json",
            "-s",
            "-Subject",
            "-HierarchicalSubject",
            "-Description",
            str(bilder[0]),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    d = _json.loads(roh)[0]
    alles = str(d)
    assert "Motiv" in alles, f"kein Motiv-Stichwort in der Datei: {d}"
    assert "Sonnenaufgang" in alles, f"das Stichwort des Modells fehlt: {d}"
    assert "Ein Satz zum Bild." in alles, f"die Beschreibung fehlt: {d}"


def test_ohne_modell_laeuft_der_rest_weiter(tmp_path, monkeypatch):
    """Untergrenze: die Bildanalyse ist ein Zusatz, kein Fundament. Wer keinen
    Schluessel hat, soll trotzdem Ort, Serie und Technik bekommen."""
    quelle = tmp_path / "kamera"
    quelle.mkdir()
    from PIL import Image

    Image.new("RGB", (200, 150), (90, 110, 130)).save(quelle / "N0.JPG")
    monkeypatch.setattr(
        inventar.exif,
        "lies",
        lambda pfade: [{"EXIF:DateTimeOriginal": "2026:08:24 06:19:00", "EXIF:Model": "X-E5"}],
    )

    lauf = pipeline.fahre(quelle, tmp_path / "ziel", schreiben_aktiv=True)

    assert lauf.motive is None, "ohne Modellangabe darf nichts angefragt werden"
    assert lauf.angereichert.sidecars > 0 or lauf.angereichert.eingebettet > 0, (
        "ohne Bildanalyse ist gar nichts geschrieben worden"
    )


def test_die_pipeline_reicht_die_fortschrittsmeldung_durch(tmp_path, monkeypatch):
    """Zum DRITTEN Mal dieselbe Klasse: gebaut, aber nicht durchgereicht.

    `motivlauf` kennt `melde` und meldet zuverlaessig — die Pipeline nahm den
    Parameter gar nicht erst an. Der erste Startversuch brach mit
    `TypeError: fahre() got an unexpected keyword argument 'melde'` ab.

    Vorher: `geotag` existierte und wurde nie gerufen. Davor: `motivlauf`
    existierte und wurde nie gerufen. Ein Modul in der Modulliste ist noch kein
    Aufruf im Ablauf — und ein Parameter im inneren Aufruf ist noch keiner im
    aeusseren.
    """
    import json as _json
    import shutil

    if shutil.which("exiftool") is None:
        import pytest as _p

        _p.skip("exiftool nicht verfuegbar")

    from PIL import Image

    quelle = tmp_path / "kamera"
    quelle.mkdir()
    Image.new("RGB", (200, 150), (70, 90, 120)).save(quelle / "P0.JPG")
    monkeypatch.setattr(
        inventar.exif,
        "lies",
        lambda pfade: [{"EXIF:DateTimeOriginal": "2026:08:24 06:19:00", "EXIF:Model": "X-E5"}],
    )

    def transport(url, koerper, kopf, zeitgrenze):
        nutzlast = {"sicher": True, "motive": ["Wald"], "beschreibung": "x", "belichtung": "gut"}
        return 200, _json.dumps(
            {
                "content": [{"text": _json.dumps(nutzlast)}],
                "usage": {"input_tokens": 2000, "output_tokens": 100},
            }
        ).encode()

    meldungen = []
    pipeline.fahre(
        quelle,
        tmp_path / "ziel",
        schreiben_aktiv=True,
        modell=("anthropic", "test"),
        schluessel="x",
        transport=transport,
        melde=meldungen.append,
        melde_alle=1,
    )

    assert meldungen, "die Pipeline reicht die Fortschrittsmeldung nicht durch"


def test_die_pipeline_laedt_den_urheber_und_reicht_ihn_durch(tmp_path, monkeypatch) -> None:
    """Der WEG von aussen nach innen — dritte Naht derselben Klasse.

    Das Modul kann geladen und die Anreicherung kann den Parameter annehmen,
    und trotzdem steht kein Name in den Bildern, wenn die Pipeline dazwischen
    nicht lädt. Genau das ist heute Nacht dreimal passiert.
    """
    datei = tmp_path / "konfig.json"
    datei.write_text('{"urheber": {"name": "Erika Muster", "email": "e@m.de"}}', encoding="utf-8")
    monkeypatch.setenv(konfig.DATEI_VARIABLE, str(datei))

    gesehen: dict[str, object] = {}
    monkeypatch.setattr(
        pipeline.anreichern,
        "schreibe",
        lambda eintraege, **kw: gesehen.update(kw) or anreichern.Ergebnis(),
    )

    import shutil

    if shutil.which("exiftool") is None:
        import pytest as _p

        _p.skip("exiftool nicht verfuegbar")

    from PIL import Image

    quelle = tmp_path / "kamera"
    quelle.mkdir()
    Image.new("RGB", (60, 40), (10, 20, 30)).save(quelle / "P0.JPG")
    monkeypatch.setattr(
        inventar.exif,
        "lies",
        lambda pfade: [{"EXIF:DateTimeOriginal": "2019:05:04 12:00:00", "EXIF:Model": "X-E5"}],
    )

    pipeline.fahre(quelle, tmp_path / "ziel", schreiben_aktiv=True)

    assert gesehen.get("urheber_angaben") is not None, "Urheber kam nie an"
    assert gesehen["urheber_angaben"].name == "Erika Muster"


def test_die_pipeline_nimmt_modell_und_schluesselort_aus_der_konfiguration(
    tmp_path, monkeypatch
) -> None:
    """Was in der Konfiguration steht, muss auch wirken.

    Ein Feld, das dokumentiert ist und nichts tut, ist schlimmer als ein
    fehlendes: der Anwender traegt es ein, sieht kein Ergebnis und sucht den
    Fehler bei sich. Also geht dieser Test den Weg von der Datei bis zum
    Aufruf -- Modell UND Schluesselort.
    """
    import json as _json
    import shutil

    if shutil.which("exiftool") is None:
        import pytest as _p

        _p.skip("exiftool nicht verfuegbar")

    from PIL import Image

    schluessel_datei = tmp_path / "keys.json"
    schluessel_datei.write_text('{"anthropic": "sk-aus-der-konfig"}', encoding="utf-8")
    kfg = tmp_path / "konfig.json"
    kfg.write_text(
        _json.dumps(
            {
                "schluessel_datei": str(schluessel_datei),
                "modell": {"anbieter": "anthropic", "name": "modell-aus-der-konfig"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(konfig.DATEI_VARIABLE, str(kfg))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MKN_LLM_SCHLUESSEL_DATEI", raising=False)

    quelle = tmp_path / "kamera"
    quelle.mkdir()
    Image.new("RGB", (200, 150), (10, 20, 30)).save(quelle / "P0.JPG")
    monkeypatch.setattr(
        inventar.exif,
        "lies",
        lambda pfade: [{"EXIF:DateTimeOriginal": "2026:08:24 06:19:00", "EXIF:Model": "X-E5"}],
    )

    gesehen: dict[str, object] = {}

    def transport(url, koerper, kopf, zeitgrenze):
        gesehen["schluessel"] = kopf.get("x-api-key")
        gesehen["modell"] = _json.loads(koerper)["model"]
        return 200, _json.dumps(
            {
                "content": [{"text": _json.dumps({"sicher": False})}],
                "usage": {"input_tokens": 10, "output_tokens": 1},
            }
        ).encode()

    pipeline.fahre(quelle, tmp_path / "ziel", schreiben_aktiv=True, transport=transport)

    assert gesehen.get("modell") == "modell-aus-der-konfig", "Modell kam nicht aus der Konfig"
    assert gesehen.get("schluessel") == "sk-aus-der-konfig", (
        "Schluesselort kam nicht aus der Konfig"
    )


def test_anker_sammeln_holt_die_urteile_zu_den_notizen(tmp_path, monkeypatch) -> None:
    """Der WEG von der Notiz bis zum Anker — die vierte Naht dieser Nacht.

    `notizurteil` kann Saetze lesen, `zu_ankern` kann Urteile verwerten. Wenn
    dazwischen niemand das Modell FRAGT, bleibt beides folgenlos, und der Lauf
    verhaelt sich wie zuvor: neun von zwanzig Antworten verwertet, elf
    weggeworfen. Genau diese Klasse Fehler ist heute Nacht viermal aufgetreten
    (geotag, motivlauf, melde, Gemini-Adresse).
    """
    import json as _json

    ordner = tmp_path / "antworten" / "2026-08-26_1541-1542"
    ordner.mkdir(parents=True)
    (ordner / "ort.md").write_text(
        "# 2026-08-26 15:41 bis 15:42\n\n## Ort\n\n\n## Gehoert zusammen mit\n\n"
        "Schon Zugspitze ganz oben ... erste Bilder\n",
        encoding="utf-8",
    )

    gefragt: list[str] = []

    def transport(url, koerper, kopf, zeitgrenze=120.0):
        gefragt.append(url)
        return 200, _json.dumps(
            {
                "content": [
                    {"type": "thinking", "thinking": "", "signature": "x"},
                    {
                        "type": "text",
                        "text": _json.dumps(
                            {"art": "zuordnung", "ort": "Zugspitze", "sicher": True}
                        ),
                    },
                ],
                "usage": {"input_tokens": 100, "output_tokens": 20},
            }
        ).encode()

    fp = [Anker(zeit=datetime(2026, 8, 26, 15, 0), lat=47.42, lon=10.98, name="Zugspitze")]

    anker = pipeline.anker_sammeln(
        notiz_ordner=ordner.parent,
        weitere=fp,
        modell=("anthropic", "test"),
        schluessel="k",
        transport=transport,
    )

    assert gefragt, "das Modell wurde nie gefragt"
    aus_notiz = [a for a in anker if a.name == "Zugspitze" and a.zeit.hour == 15]
    assert len(aus_notiz) >= 2, "die Notiz hat keinen eigenen Anker ergeben"


def test_die_frage_nennt_die_nachbarsessions(tmp_path) -> None:
    """Ohne Nachbarn kann "vorheriger Ordner" nicht aufgeloest werden.

    Der Satz ist dann nicht schwer zu beantworten, sondern UNMOEGLICH: es gibt
    keine Information, auf die er sich beziehen koennte. Wer nur den Satz
    schickt, bekommt zwangslaeufig eine unbrauchbare Antwort und haelt das
    Modell fuer schwach.
    """
    import json as _json

    for name, satz in (
        ("2026-08-22_1210-1212", "Lenggries im findpinguines"),
        ("2026-08-22_1841-1841", "Gehört ebenfalls dazu - vorheriger Ordner"),
    ):
        d = tmp_path / "antworten" / name
        d.mkdir(parents=True)
        (d / "ort.md").write_text(
            f"# x\n\n## Ort\n\n\n## Gehoert zusammen mit\n\n{satz}\n", "utf-8"
        )

    fragen: list[str] = []

    def transport(url, koerper, kopf, zeitgrenze=120.0):
        fragen.append(_json.loads(koerper)["messages"][0]["content"][0]["text"])
        return 200, _json.dumps(
            {
                "content": [{"type": "text", "text": '{"art": "kein_ort", "sicher": true}'}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        ).encode()

    pipeline.anker_sammeln(
        notiz_ordner=tmp_path / "antworten",
        modell=("anthropic", "test"),
        schluessel="k",
        transport=transport,
    )

    assert len(fragen) == 2
    # Die Frage zur ZWEITEN Notiz muss die erste kennen.
    assert "2026-08-22_1210-1212" in fragen[1]
