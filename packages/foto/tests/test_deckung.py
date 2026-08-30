"""Zusicherungen zur Deckungsmessung (Design § 2, § 3, § 5, § 8).

Jede Zusicherung hier hat eine MUTATION, die sie rot macht (LP-40) -- die
Mutationen sind in den Docstrings genannt und wurden vor dem Schreiben dieser
Tests am tragenden PoC (`scratchpad/poc/deckung3.py`) empirisch durchprobiert,
nicht nur behauptet.

**Warum kein `PIL.Image.effect_noise`:** es ist NICHT reproduzierbar (jeder
Aufruf liefert andere Pixel, kein Seed-Parameter) -- ein Test darauf waere
flaky. `_deterministische_szene` unten baut stattdessen ein reproduzierbares
Pseudo-Rauschen ueber `random.Random(seed)`.
"""

from __future__ import annotations

import random
import shutil
from pathlib import Path

import pytest
from mkn_foto import deckung
from PIL import Image, ImageFilter

pytestmark = pytest.mark.skipif(
    shutil.which("exiftool") is None, reason="exiftool nicht verfuegbar"
)


def _deterministische_szene(breite: int, hoehe: int, *, sigma: float = 0.0, seed: int = 42):
    """Reproduzierbares Pseudo-Rauschen als 'L'-Bild, wahlweise weichgezeichnet."""
    rng = random.Random(seed)
    daten = bytes(rng.randrange(256) for _ in range(breite * hoehe))
    roh = Image.frombytes("L", (breite, hoehe), daten)
    return roh.filter(ImageFilter.GaussianBlur(sigma)) if sigma else roh


# --- Echte Bestaende (nur lesend, HC-4) --------------------------------
# Wie test_vorschau.py: liegen ausserhalb des Repos, fehlen sie wird
# uebersprungen statt falsch bestanden.

_FOTORUNDE = Path("/Volumes/MN SSD 1TB /Foto-Sicherung-org/2026-08-30 Fotorunde Nuernberg")
_MITTENWALD_D850 = Path(
    "/Volumes/MN SSD 1TB /Foto-Sicherung-org/2026-08-24.29 FotoUrlaubMittenwald/2026-08-26/D850"
)
_MITTENWALD_XE5 = Path(
    "/Volumes/MN SSD 1TB /Foto-Sicherung-org/2026-08-24.29 FotoUrlaubMittenwald/2026-08-27/X-E5"
)


def _skip_falls_fehlt(pfad: Path) -> None:
    if not pfad.exists():
        pytest.skip(f"Testbestand fehlt: {pfad}")


# --- 1. Beide Achsen, volle Suche --------------------------------------


def test_beide_achsen_volle_suche_findet_diagonale_verschiebung():
    """Mutation: die Suche auf eine Achse beschraenken (z. B. `dy` immer 0)
    -- dann faende sie den `dy`-Anteil des Versatzes nicht mehr."""
    breite, hoehe, versatz_x, versatz_y = 160, 160, 40, 30
    szene = _deterministische_szene(breite + versatz_x, hoehe + versatz_y)
    a = deckung.normiere(szene.crop((0, 0, breite, hoehe)))
    b = deckung.normiere(szene.crop((versatz_x, versatz_y, versatz_x + breite, versatz_y + hoehe)))

    ergebnis = deckung.beste(a, b)

    assert ergebnis.korrelation is not None
    assert abs(ergebnis.dx * breite - versatz_x) <= 3
    assert abs(ergebnis.dy * hoehe - versatz_y) <= 3


# --- 2. Nullverschiebung im Raster --------------------------------------


def test_nullverschiebung_im_raster_wird_gefunden():
    """Ein Selbstvergleich MUSS bei (0, 0) landen -- auch wenn das
    `_SUCH_SCHRITT`-Raster die Null gar nicht trifft (hier erzwungen durch
    Bildmasse, bei denen `(w-1) % schritt != 0` gilt: 159x105).

    Mutation: die ausdrueckliche (0,0)-Auswertung aus `beste()` entfernen --
    dann findet der Selbstvergleich den naechstgelegenen Rasterpunkt
    (empirisch: (1, 1) statt (0, 0), Korrelation 0,975 statt 0,990)."""
    _skip_falls_fehlt(_FOTORUNDE / "DSCF3894.JPG")
    a = deckung.vorbereiten(_FOTORUNDE / "DSCF3894.JPG")
    # Bewusst um 1 px je Kante beschnitten: (160,106) traefe das 3er-Raster
    # exakt bei 0, (159,105) tut es nicht (158 % 3 == 2, 104 % 3 == 2).
    a = a.crop((0, 0, a.width - 1, a.height - 1))

    ergebnis = deckung.beste(a, a)

    assert ergebnis.dx == 0
    assert ergebnis.dy == 0
    assert ergebnis.korrelation is not None
    assert ergebnis.korrelation >= 0.95


# --- 3. Belichtungsinvarianz --------------------------------------------


def test_belichtungsinvarianz_bleibt_verbunden_trotz_ev_unterschied():
    """~1 EV dunkler (Faktor 0,71) darf die Deckung nicht zerreissen.

    Mutation: `autocontrast` aus `normiere()` entfernen -- die Korrelation
    faellt weit ausserhalb des gueltigen Wertebereichs (empirisch: -3,3 statt
    0,83), weil `ImageChops.multiply` das Kreuzmoment pixelweise 8-bit-
    quantisiert und die gestauchte Dynamik des dunkleren Bildes dabei
    unverhaeltnismaessig viel Praezision verliert."""
    szene = _deterministische_szene(320, 320, sigma=3.0)
    hell = deckung.normiere(szene)
    dunkel = deckung.normiere(szene.point(lambda p: int(p * 0.71)))

    r = deckung.korrelation(hell, dunkel, 0, 0)

    assert r is not None
    assert r >= deckung.VERBUNDEN_MIN_KORR


# --- 4. Toleranz statt Kanten --------------------------------------------


def test_toleranz_statt_kanten_ein_pixel_versatz_bleibt_messbar():
    """Die gemessene Sackgasse aus `poc/deckung.py`: ohne Weichzeichnen
    zerstoert schon 1 px Versatz die Uebereinstimmung.

    Mutation: `GaussianBlur` aus `normiere()` entfernen -- die Korrelation
    faellt von deutlich positiv auf nahe null (empirisch: 0,48 -> -0,02)."""
    roh = _deterministische_szene(161, 160)
    a = deckung.normiere(roh.crop((0, 0, 160, 160)))
    b = deckung.normiere(roh.crop((1, 0, 161, 160)))

    r = deckung.korrelation(a, b, 0, 0)

    assert r is not None
    assert r >= 0.3


# --- 5. L-Mode-Zusicherung -----------------------------------------------


def test_l_mode_zusicherung_korrelation_exakt():
    """Ein Kontrollbild bekannter Statistik (Werte 0..99, Mittel 49,5,
    Varianz 833,25 exakt) muss die analytisch berechenbare Korrelation
    liefern.

    Mutation: die Rechnung auf `'F'`-Bilder umstellen -- `ImageStat` liefert
    dort Unsinn (dasselbe Kontrollbild: Mittelwert 127,02 statt 49,5,
    firsthand nachgemessen) und `ImageChops.multiply` wirft auf `'F'` sogar
    einen `ValueError` ('image has wrong mode')."""
    a = Image.frombytes("L", (10, 10), bytes(range(100)))
    assert a.mode == "L"

    r = deckung.korrelation(a, a, 0, 0)

    # analytisch: (E[a^2]_8bit-quantisiert - mean^2) / variance, siehe
    # Moduldocstring "Restrisiko" -- die 8-bit-Quantisierung von
    # ImageChops.multiply verhindert eine exakte 1.0 selbst im Selbstvergleich.
    assert r == pytest.approx(0.8694869486948695, abs=1e-9)


# --- 6. Struktur-Waechter --------------------------------------------------


def test_struktur_waechter_zwei_flaechen_sind_unmessbar():
    """Zwei strukturlose Bilder (Streuung < 1, z. B. reiner Himmel) sind
    UNMESSBAR -- sie verbinden nicht und trennen nicht (Design § 3).

    Mutation: die Streuungspruefung (`da < _MIN_STREUUNG or db < _MIN_STREUUNG`)
    aus `korrelation()` entfernen -- bei zwei exakt flachen Bildern ist die
    Streuung exakt 0, die Division wirft dann eine `ZeroDivisionError`
    (immer noch 'rot', nur als Fehler statt als falsche Zahl)."""
    a = deckung.normiere(Image.new("L", (100, 100), 200))
    b = deckung.normiere(Image.new("L", (100, 100), 210))

    ergebnis = deckung.beste(a, b)

    assert ergebnis.korrelation is None


# --- 7. Raster-Ableitung an der goldenen Kette ----------------------------

#: Die 14 Nachbar-Paare von D85_2560-2574 (Poster-Raster, Zugspitzblick),
#: firsthand gemessen 2026-08-30 mit `poc/raster_test.py` gegen den echten
#: Bestand (siehe Design § 5 -- dieselben Zahlen). korr, dx-Prozent, dy-Prozent.
_GOLDENE_KETTE_D850_2560_2574 = [
    (0.949, 28.1, -3.7),
    (0.970, 26.2, 1.9),
    (0.972, 22.5, 1.9),
    (0.969, -7.5, -29.0),
    (0.953, -31.9, -3.7),
    (0.932, -26.2, -0.9),
    (0.918, -20.6, 1.9),
    (0.872, -1.9, -29.0),
    (0.889, 22.5, -6.5),
    (0.924, 24.4, 1.9),
    (0.939, 20.6, 4.7),
    (0.930, 20.6, -0.9),
    (0.922, 18.8, -0.9),
    (0.917, 22.5, -0.9),
]


def _schritte_aus_prozentwerten(werte) -> list[deckung.Schritt]:
    return [
        deckung.Schritt(
            von=i,
            nach=i + 1,
            deckung=deckung.Deckung(korrelation=r, dx=dx / 100, dy=dy / 100, k0=None),
            art="schwenk",
        )
        for i, (r, dx, dy) in enumerate(werte)
    ]


def test_raster_ableitung_an_goldener_kette():
    """Die 14 gemessenen Poster-Raster-Schritte ergeben exakt 4/4/7 --
    Zeichen fuer Zeichen die Aufteilung, die am Bild abgezaehlt wurde
    (Design § 5), aus reiner Richtungslogik.

    Mutation A: `NEBENACHSE_MAX` auf 0,05 setzen -- das 6,5-%-Zittern von
    Schritt 8 (D85_2568>2569) ueberschreitet dann die Schwelle und erzeugt
    eine Phantom-Zeile (empirisch: [4, 4, 1, 6] statt [4, 4, 7]).
    Mutation B: Vorzeichen ignorieren wuerde das Schlangenmuster (Reihe 2
    laeuft entgegengesetzt zu Reihe 1 und 3) faelschlich als Reihenwechsel
    lesen -- die hier gebaute Zusicherung haengt bewusst NUR an der
    Nebenachsen-Groesse, nie am Vorzeichen, und deckt damit auch diesen
    Fall ab."""
    schritte = _schritte_aus_prozentwerten(_GOLDENE_KETTE_D850_2560_2574)

    reihen = deckung.raster(schritte)

    assert reihen == [4, 4, 7]


# --- 8. Zeilenwechsel-Rueckgriff ohne feste Tiefe -------------------------


def test_zeilenwechsel_rueckgriff_ohne_feste_tiefe():
    """Ein Nicht-Schlangen-Raster (jede Zeile scannt in dieselbe Richtung)
    springt am Zeilenende zurueck: Bild 10 (Beginn Zeile 2) hat mit seinem
    direkten Vorgaenger Bild 9 (Ende Zeile 1) keine Ueberlappung mehr, wohl
    aber mit Bild 1 (Beginn Zeile 1, senkrecht darueber).

    Mutation: den Rueckgriff auf eine feste Tiefe begrenzen (z. B. 8) -- bei
    einer laengeren Zeile faende `kette()` die Verbindung zu Bild 1 dann
    nicht mehr, die Kette zerfiele in zwei Gruppen fuer EIN physisches
    Panorama (Design § 3)."""
    breite, hoehe = 100, 100
    schritt_x, y_versatz, zeilenlaenge = 45, 60, 9
    szene = _deterministische_szene(
        breite + schritt_x * (zeilenlaenge - 1), hoehe + y_versatz, sigma=10.0
    )
    zeile1 = [
        deckung.normiere(szene.crop((i * schritt_x, 0, i * schritt_x + breite, hoehe)))
        for i in range(zeilenlaenge)
    ]
    zeile2_start = deckung.normiere(szene.crop((0, y_versatz, breite, y_versatz + hoehe)))
    bilder = [*zeile1, zeile2_start]

    schritte = deckung.kette(bilder)

    # Bild 9 (Index 8) und Bild 10 (Index 9) verbinden NICHT direkt --
    assert not any(s.von == 8 and s.nach == 9 for s in schritte)
    # -- aber ueber den Rueckgriff verbindet Bild 1 (Index 0) mit Bild 10:
    assert any(s.von == 0 and s.nach == 9 for s in schritte)
    # und die Zeile 1 selbst bleibt durchgaengig verbunden (0->1->...->8):
    verbindungen = {s.nach: s.von for s in schritte}
    for i in range(1, zeilenlaenge):
        assert verbindungen[i] == i - 1


# --- Transpose am Stapel-Extrakt (LP-34) ----------------------------------


def test_transpose_wirkt_am_stapel_extrakt(tmp_path):
    """LP-34: die Fixture ist eine ECHTE, per `-b -PreviewImage -w`
    extrahierte Vorschau einer Rotate-90-RAF -- kein gewoehnliches JPG,
    sonst prueft der Test einen Pfad, den es so nicht gibt.

    Gate-Beleg (2026-08-30, hier erneut firsthand bestaetigt): `DSCF3536.RAF`
    traegt `Orientation: Rotate 90 CW`, der Stapel-Extrakt ebenso
    (4416x2944 quer) -- `ImageOps.exif_transpose` dreht das auf 2944x4416.

    Mutation: `ImageOps.exif_transpose` aus `vorbereiten()` entfernen -- die
    Arbeitskopie bliebe QUER (breiter als hoch), obwohl das Bild ein
    Hochformat zeigt."""
    quelle = _MITTENWALD_XE5 / "DSCF3536.RAF"
    _skip_falls_fehlt(quelle)

    extrakte = deckung.vorschauen_stapel([quelle], tmp_path)
    assert quelle in extrakte

    bild = deckung.vorbereiten(extrakte[quelle])

    assert bild.height > bild.width


# --- vorschauen_stapel: Grundfunktion + Kollisionsschutz -------------------


def test_vorschauen_stapel_verarbeitet_mehrere_dateien_in_einem_aufruf(tmp_path):
    """Der Regelfall: mehrere echte RAWs, EIN Ergebnis je Quelle, gueltige
    JPEGs."""
    quellen = [_MITTENWALD_D850 / f"D85_{n}.NEF" for n in (2560, 2561, 2562)]
    for q in quellen:
        _skip_falls_fehlt(q)

    ergebnis = deckung.vorschauen_stapel(quellen, tmp_path)

    assert set(ergebnis) == set(quellen)
    for ziel in ergebnis.values():
        assert deckung._ist_gueltiges_jpeg(ziel)


def test_ohne_namenskollision_haelt_regelfall_bei_einer_gruppe():
    """Eindeutige Staemme (der Regelfall: ein Tag, eine Kamera) ergeben
    GENAU EINE Gruppe -- das ist die Voraussetzung fuer 'EIN exiftool-Aufruf
    fuer viele Dateien' (Design § 6)."""
    quellen = [Path(f"/a/DSCF{n}.RAF") for n in range(3894, 3900)]

    gruppen = deckung._ohne_namenskollision(quellen)

    assert gruppen == [quellen]


def test_ohne_namenskollision_trennt_gleiche_staemme_in_getrennte_gruppen():
    """Zwei Quellen mit gleichem Dateistamm aus verschiedenen Ordnern (z. B.
    zwei Nummerierungszyklen derselben Kamera) duerfen sich nicht denselben
    Zielnamen teilen."""
    a = Path("/tag1/DSCF0001.RAF")
    b = Path("/tag2/DSCF0001.RAF")

    gruppen = deckung._ohne_namenskollision([a, b])

    assert gruppen == [[a], [b]]


# --- Beleg-Laeufe gegen echte Bilder (Design § 8, DoD) ---------------------


def test_beleg_prueffall_schwenk_dann_wiederholung():
    """DSCF3894-3896 (Sebalduskirche): 3894->3895 muss als Schwenk gelten
    (Versatz ~35 %), 3895->3896 als Wiederholung (~2 %) -- die exakte
    Aufteilung, die KT-1 am Kontaktbogen sah, bevor irgendjemand der Messung
    gesagt hat wonach sie sucht (Design § 1)."""
    dateien = [_FOTORUNDE / f"DSCF{n}.JPG" for n in (3894, 3895, 3896)]
    for d in dateien:
        _skip_falls_fehlt(d)

    bilder = [deckung.vorbereiten(d) for d in dateien]
    schritte = deckung.kette(bilder)

    nach_index = {s.nach: s for s in schritte}
    assert nach_index[1].von == 0
    assert nach_index[1].art == "schwenk"
    assert abs(nach_index[1].deckung.dy) == pytest.approx(0.355, abs=0.05)
    assert nach_index[2].von == 1
    assert nach_index[2].art == "wiederholung"


def test_beleg_poster_raster_ergibt_vier_vier_sieben(tmp_path):
    """D85_2560-2574 (Zugspitzblick, 15 Bilder): die Kette aus den echten
    Vorschauen muss dieselbe 4/4/7-Aufteilung liefern wie die goldene Kette
    oben -- mit den Reihenwechseln an genau den Positionen 2563->2564 und
    2567->2568.

    Die Quellen sind NEF-RAWs -- Pillow kann sie nicht direkt oeffnen, darum
    zuerst `vorschauen_stapel` (derselbe Weg, den die Pipeline gehen wird)."""
    dateien = [_MITTENWALD_D850 / f"D85_{n}.NEF" for n in range(2560, 2575)]
    for d in dateien:
        _skip_falls_fehlt(d)

    extrakte = deckung.vorschauen_stapel(dateien, tmp_path)
    assert set(extrakte) == set(dateien)
    bilder = [deckung.vorbereiten(extrakte[d]) for d in dateien]
    schritte = deckung.kette(bilder)

    # 14 direkte Verbindungen, kein Rueckgriff noetig -- alle Korrelationen
    # liegen komfortabel ueber VERBUNDEN_MIN_KORR (Design § 5: 0,872-0,972).
    assert [(s.von, s.nach) for s in schritte] == [(i, i + 1) for i in range(14)]

    reihen = deckung.raster(schritte)
    assert reihen == [4, 4, 7]

    # Reihenwechsel-Positionen aus den Reihen-Groessen ableiten:
    grenzen = []
    laufend = 0
    for groesse in reihen[:-1]:
        laufend += groesse
        grenzen.append(laufend)
    assert grenzen == [4, 8]  # 2563->2564 (Index 3->4), 2567->2568 (Index 7->8)
