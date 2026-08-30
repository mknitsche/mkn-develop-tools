"""Misst, wie stark sich zwei Bilder ueberlappen und in welche Richtung sie
gegeneinander verschoben sind -- reines Pillow, kein Modellaufruf, keine neue
Abhaengigkeit.

Tragendes Verfahren: PoC `deckung3.py` (Design
`docs/superpowers/specs/2026-08-30-foto-serien-stufe3-design.md` § 2), an
Prueffall, Poster-Raster und beiden Gegenfaellen (Klamm, SW-Anlaeufe) verprobt.

**Zwei Sackgassen, gemessen und verworfen -- nicht nachbauen:**

- `FIND_EDGES` + Absolutdifferenz (PoC `deckung.py`): Kantenbilder haben keine
  Toleranz gegen Versatz -- schon 1 px zerstoert die Uebereinstimmung.
  Weichzeichnen statt Kanten (`normiere` unten).
- Statistik auf `"F"`-Bildern (PoC `deckung2.py`): `ImageStat` rechnet ueber
  Histogramme und liefert auf Float-Bildern Unsinn (ein Kontrollbild mit
  Werten 0-99 bekam Mittelwert 127 statt 49,5 -- der 8-bit-Histogrammleser
  interpretiert Float-Werte als waeren sie schon 0-255-skaliert),
  `ImageChops.multiply` wirft dort einen `ValueError` ("image has wrong
  mode"), und `ImageMath.eval` existiert in aktuellem Pillow nicht mehr.
  **Alles bleibt in 8-bit `"L"`.**

**Die Grenze der Messung -- sie gehoert zum Verfahren, nicht nur zur Doku
(Design § 3a):** dieses Modul kann Panorama nicht von Gehsequenz trennen --
beide erzeugen geometrisch dasselbe Deckungs-Signal, der Unterschied ist die
Absicht, und die steht in keinem Pixel. Es liefert darum nie ein Urteil,
sondern Gruppengrenzen, Wiederholung, Raster und Richtung als Vorbereitung
fuer das Modell-Urteil (`bildurteil.py`, nicht Teil dieses Moduls).

**Restrisiko, akzeptiert (Design § 9c):** `ImageChops.multiply` rechnet das
Kreuzmoment `a*b/255` PIXELWEISE 8-bit-quantisiert (Integer-Rundung je
Pixel, nicht am Ende) -- ein Selbstvergleich landet deshalb nicht exakt bei
1,0, sondern nahe daran (gemessen an echten Fotos: 0,990). Praktisch ohne
Folge fuer die hier genutzten Schwellen, aber der Grund, warum keine
Assertion `== 1.0` im Modul oder seinen Tests steht.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat

BREITE = 160
"""Laengste Kante der Arbeitskopie. Gemessen: 0,25-0,26 s je Paarmessung bei
dieser Groesse, stabil ueber alle Messreihen (Design § 2)."""

MIN_DECKUNG = 0.25
"""Mindest-Ueberlappung als Anteil der Flaeche. Darunter sind Treffer
Zufall -- die Gegenprobe des Verfassers fand einen Scheintreffer bei 11 %
Restflaeche (Design § 2)."""

VERBUNDEN_MIN_KORR = 0.75
"""Ab dieser Korrelation gelten zwei Bilder als verbunden. Herkunft: fremde
Paare der Fotorunde erreichen hoechstens 0,628, verbundene mindestens 0,872
(schwaechstes Raster-Paar) -- 0,75 haelt ~19 % Abstand nach unten und ~14 %
nach oben (Design § 2)."""

SCHRITT_MIN_VERSATZ = 0.10
"""Ab diesem Versatz auf der dominanten Achse gilt ein verbundener Schritt
als Schwenk statt Wiederholung. Herkunft: belegte Wiederholungs-Schritte
liegen bei <= 0,05 (Prueffall 0,019 -- Egidienkirche-Anlaeufe 0,05 -- HDR-
Reihen ~0), der kleinste echte Schwenk-Schritt liegt bei 0,188
(Poster-Raster) -- 0,10 halbiert die Luecke (Design § 2)."""

NEBENACHSE_MAX = 0.15
"""Trennt Reihen-Schritte von Reihenwechseln (`raster`). Herkunft:
Reihen-Schritte tragen quer zur Laufrichtung <= 0,07, Reihenwechsel auf
ihrer Nebenachse <= 0,08 -- die jeweils dominante Achse traegt 0,19-0,60.
0,15 trennt mit >= 2x Marge zu beiden Seiten (Design § 5)."""

_MIN_STREUUNG = 1.0
"""Struktur-Waechter: darunter gilt ein Bildausschnitt als strukturlos
(z. B. reiner Himmel) -- unmessbar, verbindet nicht, trennt nicht
(Design § 3)."""

_SUCH_SCHRITT = 3
"""Rasterweite der Vollsuche in Pixeln. Bleibt eine Vollsuche (keine
Grob/Fein-Zweistufigkeit) -- das Zeitbudget haelt, und eine Vollsuche sieht
diagonale Schritte ohne Sonderfall (Design § 2)."""


@dataclass(frozen=True)
class Deckung:
    """Ergebnis einer Bildpaar-Messung.

    `dx`/`dy` sind Anteile der Bild-Kante (-1..1), nicht Pixel -- so bleiben
    sie direkt mit `SCHRITT_MIN_VERSATZ`/`NEBENACHSE_MAX` vergleichbar, auch
    wenn Breite und Hoehe der Arbeitskopie unterschiedlich sind.
    """

    korrelation: float | None
    """`None` heisst UNMESSBAR: keine Verschiebung erreichte die
    Mindest-Ueberlappung, oder beide Ausschnitte waren strukturlos. Das ist
    keine Aussage ueber Naehe oder Ferne -- ein unmessbares Paar verbindet
    nicht und trennt nicht (Design § 3)."""

    dx: float
    dy: float

    k0: float | None
    """Korrelation bei Nullverschiebung (0,0) -- ein Wiederholungs-Indiz
    (SW-Anlaeufe 0,83-0,88 gegen Klamm meist < 0,75), aber bewusst KEINE
    eigene Konstante und KEIN Eingang in die Klassifikation (Design § 2:
    das Grenzband ist zu duenn, der Versatz leistet die Trennung bereits
    mit doppelter Marge). Nur zum Ausweisen im Protokoll."""


@dataclass(frozen=True)
class Schritt:
    """Eine gemessene Verbindung zwischen zwei Bildern einer Kette.

    `von`/`nach` sind Indices in der Bildfolge, die `kette()` erhalten hat --
    `von` liegt bei einem Rueckgriff NICHT zwingend bei `nach - 1`.
    """

    von: int
    nach: int
    deckung: Deckung
    art: str
    """`schwenk` (Versatz >= `SCHRITT_MIN_VERSATZ` auf der dominanten Achse)
    oder `wiederholung` (darunter -- dasselbe Bild noch einmal)."""


def normiere(bild: Image.Image, *, breite: int = BREITE) -> Image.Image:
    """Bringt ein bereits ausgerichtetes Graustufenbild auf Messmass.

    `thumbnail` verkleinert nur (nie vergroessern), `autocontrast` gleicht
    Belichtungsdrift aus, `GaussianBlur(1.0)` gibt der Suche Toleranz gegen
    kleinen Versatz und Parallaxe (Design § 2) -- OHNE das faellt schon ein
    Pixel Versatz messbar ab (die Sackgasse der FIND_EDGES-Fassung).
    """
    kopie = bild.copy()
    kopie.thumbnail((breite, breite), Image.LANCZOS)
    kopie = ImageOps.autocontrast(kopie)
    return kopie.filter(ImageFilter.GaussianBlur(1.0))


def vorbereiten(pfad: Path) -> Image.Image:
    """Oeffnet eine Vorschau, richtet sie aus und normiert sie fuer die Messung.

    `ImageOps.exif_transpose` ist PFLICHT, keine Kuer, und steht bewusst VOR
    `convert("L")`: die Fuji-Vorschau eines Hochformat-Bildes ist QUER
    gespeichert und traegt die Drehung nur als EXIF-Orientation -- Pillow
    dreht beim Oeffnen nicht von selbst. Ohne diesen Schritt sind alle
    Richtungs- und Rasteraussagen hochkant aufgenommener Bilder um 90 Grad
    verdreht. Die Orientation UEBERLEBT den Stapel-Extrakt aus
    `vorschauen_stapel` (firsthand: `DSCF3536.RAF` traegt Rotate 90 CW, der
    per `-b -PreviewImage -w` geschriebene Extrakt ebenso) -- der Transpose
    greift also auch auf diesem Weg.
    """
    with Image.open(pfad) as roh:
        grau = ImageOps.exif_transpose(roh).convert("L")
    return normiere(grau)


def korrelation(a: Image.Image, b: Image.Image, dx: int, dy: int) -> float | None:
    """Pearson-Korrelation im ueberlappenden Bereich bei Verschiebung (dx, dy).

    `None`, wenn die Ueberlappung unter `MIN_DECKUNG` faellt oder einer der
    beiden Ausschnitte strukturlos ist (Streuung < `_MIN_STREUUNG` --
    Struktur-Waechter, Design § 3: ein unmessbares Paar verbindet nicht und
    trennt nicht).

    Rechnet komplett in 8-bit `"L"`: Mittelwert und Streuung liefert
    `ImageStat.Stat` exakt, das Kreuzmoment `E[a*b]` liefert
    `ImageChops.multiply` (rechnet `a*b/255`, also `mean*255`). Auf `"F"`
    wirft `multiply` einen `ValueError` und `ImageStat` liefert Unsinn --
    deshalb bleibt alles in `"L"` (Moduldocstring).
    """
    w, h = a.size
    ax0, bx0 = max(dx, 0), max(-dx, 0)
    ay0, by0 = max(dy, 0), max(-dy, 0)
    ow, oh = w - abs(dx), h - abs(dy)
    if ow <= 0 or oh <= 0 or ow * oh < MIN_DECKUNG * w * h:
        return None
    ka = a.crop((ax0, ay0, ax0 + ow, ay0 + oh))
    kb = b.crop((bx0, by0, bx0 + ow, by0 + oh))
    sa, sb = ImageStat.Stat(ka), ImageStat.Stat(kb)
    ma, mb, da, db = sa.mean[0], sb.mean[0], sa.stddev[0], sb.stddev[0]
    if da < _MIN_STREUUNG or db < _MIN_STREUUNG:
        return None
    prod = ImageStat.Stat(ImageChops.multiply(ka, kb)).mean[0] * 255.0
    return (prod - ma * mb) / (da * db)


def beste(a: Image.Image, b: Image.Image, *, schritt: int = _SUCH_SCHRITT) -> Deckung:
    """Vollsuche ueber dx UND dy -- die beste gefundene Verschiebung.

    Die Nullverschiebung (0, 0) wird ZUSAETZLICH ausdruecklich ausgewertet,
    weil das `schritt`-px-Raster sie verfehlen kann (die Arbeitskopie ist
    nach `thumbnail` selten exakt `BREITE x BREITE`) -- ohne diese Pruefung
    findet ein Selbstvergleich sich nie (Design § 2).
    """
    w, h = a.size
    bester_k: float | None = None
    bester_dx, bester_dy = 0, 0
    for dx in range(-w + 1, w, schritt):
        for dy in range(-h + 1, h, schritt):
            k = korrelation(a, b, dx, dy)
            if k is not None and (bester_k is None or k > bester_k):
                bester_k, bester_dx, bester_dy = k, dx, dy
    k0 = korrelation(a, b, 0, 0)
    if k0 is not None and (bester_k is None or k0 > bester_k):
        bester_k, bester_dx, bester_dy = k0, 0, 0

    if bester_k is None:
        return Deckung(korrelation=None, dx=0.0, dy=0.0, k0=k0)
    return Deckung(korrelation=bester_k, dx=bester_dx / w, dy=bester_dy / h, k0=k0)


def kette(bilder: Sequence[Image.Image]) -> list[Schritt]:
    """Verbindet eine chronologische, bereits normierte Bildfolge.

    Jedes Bild wird zuerst gegen seinen direkten Vorgaenger gemessen.
    Schlaegt das fehl, wird RUECKWAERTS durch alle bisherigen Mitglieder der
    laufenden Gruppe gesucht (juengstes zuerst, Abbruch beim ersten Treffer)
    -- OHNE feste Tiefe: der Rueckgriff muss mindestens eine volle
    Raster-Zeile zurueckreichen, und die Zeilenlaenge ist vorab nicht
    bekannt (Design § 3). Der Fall dafuer ist konkret: ein Raster, das NICHT
    im Schlangenmuster laeuft, springt am Zeilenende zurueck -- das Paar
    (Ende Zeile 1 -> Anfang Zeile 2) hat oft keine 25 % Ueberlappung mehr,
    waehrend (Anfang Zeile 1 -> Anfang Zeile 2) sauber deckt.

    Ein STRUKTURELL unmessbares Bild (jeder Vergleich liefert `None`) endet
    die Gruppe NICHT -- es bleibt als "unvermessen" offen, ein spaeteres
    Bild kann noch an die Zeit VOR ihm anschliessen. Ein tatsaechlich
    GEMESSENES, aber zu schwaches Ergebnis (Korrelation < `VERBUNDEN_MIN_KORR`
    fuer JEDEN Rueckgriff-Kandidaten) beendet die Gruppe dagegen wirklich --
    das naechste Bild beginnt eine neue.
    """
    schritte: list[Schritt] = []
    gruppen_start = 0
    for i in range(1, len(bilder)):
        treffer: tuple[int, Deckung] | None = None
        irgendein_messwert = False
        for j in range(i - 1, gruppen_start - 1, -1):
            d = beste(bilder[j], bilder[i])
            if d.korrelation is None:
                continue
            irgendein_messwert = True
            if d.korrelation >= VERBUNDEN_MIN_KORR:
                treffer = (j, d)
                break
        if treffer is None:
            if irgendein_messwert:
                gruppen_start = i
            continue
        j, d = treffer
        art = "schwenk" if max(abs(d.dx), abs(d.dy)) >= SCHRITT_MIN_VERSATZ else "wiederholung"
        schritte.append(Schritt(von=j, nach=i, deckung=d, art=art))
    return schritte


def raster(schritte: Sequence[Schritt]) -> list[int]:
    """Zerlegt eine verbundene Kette in Reihen -- Bildanzahl je Reihe.

    **Reihenwechsel = Schritt, dessen Nebenachse (quer zur mehrheitlichen
    Laufrichtung der Kette) `NEBENACHSE_MAX` ueberschreitet** (Design § 5,
    bewiesen am Poster-Raster: 14 gemessene Schritte ergeben exakt 4/4/7).
    Die Laufrichtung ist die Achse, auf der die MEHRHEIT der Schritte
    dominiert -- das haelt auch das Schlangenmuster aus (Reihe 2 laeuft
    entgegengesetzt zu Reihe 1 und 3): die Zeilenzaehlung haengt NUR an der
    Nebenachse, nie am Vorzeichen der Hauptachse.

    Verworfen (Design § 5 Punkt 3): absolute Positions-Cluster mit
    0,5-Bildhoehen-Abstand -- die gemessenen Reihenwechsel verschieben nur
    ~0,29 Bildhoehen, ein solcher Cluster haette alle Reihen verschmolzen.
    """
    if not schritte:
        return [1]
    dx_dominant = sum(1 for s in schritte if abs(s.deckung.dx) >= abs(s.deckung.dy))
    haupt_ist_dx = dx_dominant >= len(schritte) - dx_dominant

    reihen = [1]
    for s in schritte:
        nebenachse = abs(s.deckung.dy) if haupt_ist_dx else abs(s.deckung.dx)
        if nebenachse > NEBENACHSE_MAX:
            reihen.append(1)
        else:
            reihen[-1] += 1
    return reihen


def vorschauen_stapel(quellen: Sequence[Path], ziel_ordner: Path) -> dict[Path, Path]:
    """Extrahiert die eingebettete Vorschau vieler Dateien in MOEGLICHST EINEM
    exiftool-Aufruf statt einer Schleife um Einzelprozesse.

    Gemessen (2026-08-30): ~0,03-0,04 s je Datei im Stapel gegen ~0,21 s je
    Einzelprozess (Design § 6, Faktor ~8,5) -- ueber einen Bestand von
    hunderten Aufnahmen der Unterschied zwischen Sekunden und Minuten.

    Nutzt gezielt `PreviewImage` (nicht die herstellerabhaengige Kaskade aus
    `vorschau.hole`): die Messung verkleinert ohnehin auf `BREITE`, ein
    kleiner Auszug reicht, und `PreviewImage` existiert bei Fuji UND Nikon.

    Gibt eine Abbildung Quelle -> Ziel zurueck, NUR fuer Quellen mit
    erfolgreicher Extraktion -- eine Quelle ohne brauchbare Vorschau (kein
    Tag, oder die Extraktion schlaegt fehl) fehlt im Ergebnis, statt den
    Lauf abzureissen (`vorschau.hole`s Befund: exiftool meldet bei fehlendem
    Tag Exit 0 ohne Ausgabedatei -- der Rueckgabewert allein sagt nichts).
    """
    ziel_ordner = Path(ziel_ordner)
    ziel_ordner.mkdir(parents=True, exist_ok=True)

    ergebnis: dict[Path, Path] = {}
    for gruppe in _ohne_namenskollision(quellen):
        subprocess.run(
            [
                "exiftool",
                "-q",
                "-b",
                "-PreviewImage",
                "-w",
                str(ziel_ordner / "%f_prev.jpg"),
                *(str(q) for q in gruppe),
            ],
            capture_output=True,
            check=False,
        )
        for q in gruppe:
            kandidat = ziel_ordner / f"{q.stem}_prev.jpg"
            if _ist_gueltiges_jpeg(kandidat):
                ergebnis[q] = kandidat
    return ergebnis


def _ohne_namenskollision(quellen: Sequence[Path]) -> list[list[Path]]:
    """Teilt in moeglichst wenige Gruppen, so dass innerhalb jeder Gruppe kein
    Dateistamm doppelt vorkommt.

    `exiftool -w %f_prev.jpg` benennt nach dem QUELL-Dateistamm -- zwei
    Quellen mit gleichem Stamm (z. B. `DSCF0001` aus zwei verschiedenen
    Kamera-Numerierungszyklen) wuerden sich sonst denselben Zielnamen teilen
    und eine Extraktion stumm ueberschreiben. Der Regelfall (ein Tag, eine
    Kamera, eindeutige Staemme) ergibt GENAU EINE Gruppe und damit den EINEN
    Aufruf, den `vorschauen_stapel` verspricht.
    """
    gruppen: list[list[Path]] = []
    belegte_staemme: list[set[str]] = []
    for q in quellen:
        for g, staemme in zip(gruppen, belegte_staemme, strict=True):
            if q.stem not in staemme:
                g.append(q)
                staemme.add(q.stem)
                break
        else:
            gruppen.append([q])
            belegte_staemme.append({q.stem})
    return gruppen


def _ist_gueltiges_jpeg(pfad: Path) -> bool:
    """Groesse UND beide Klammern -- ein abgeschnittener Auszug traegt den
    Kopf ebenso wie ein ganzer (`vorschau.py`s Befund, hier wiederholt, weil
    `exiftool -w` ohne `-b`-Erfolgspruefung dieselbe Falle hat)."""
    if not pfad.exists() or pfad.stat().st_size < 1000:
        return False
    roh = pfad.read_bytes()
    return roh[:3] == b"\xff\xd8\xff" and roh[-2:] == b"\xff\xd9"
