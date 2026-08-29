"""Serienerkennung: was die Kamera sagt, und was danach nur ein Kandidat ist.

Stufe 1 (`aus_kamera`) liest die Reihenfelder der Kamera. Sie raet nicht — aber
sie weiss auch nicht bei jeder Kamera gleich viel, und dieser Unterschied wird
im Ergebnis gefuehrt statt eingeebnet:

- Die **Fujifilm X-E5** nummeriert die Bilder einer Reihe selbst durch
  (`SequenceNumber` 1..n, Neustart bei der naechsten Reihe). Das ist eine
  Aussage der Kamera → `sicher=True`.
- Die **Nikon D850** schreibt keinen Reihenzaehler. Ihre MakerNotes kennen nur
  `AutoBracketOrder` und den Belichtungswert je Bild; die Zusammengehoerigkeit
  muss daraus ABGELEITET werden → `sicher=False`. Die Ableitung ist gut, aber
  sie bleibt eine Ableitung, und nur `sicher` entscheidet spaeter, dass niemand
  mehr auf das Bild schaut.

Stufe 2 (`kandidaten`) raet dann bewusst grosszuegig; ueber ihre Treffer
entscheidet erst der Blick auf das Bild.
"""

from __future__ import annotations

from collections.abc import Sequence

from mkn_foto.modell import Aufnahme, Serie

_MIN_SERIENLAENGE = 2


def aus_kamera(aufnahmen: Sequence[Aufnahme]) -> list[Serie]:
    """Serien, die aus den Reihenfeldern der Kamera hervorgehen.

    Chronologisch durchnummeriert — die Nummer steht im Dateinamen, zwei
    Serien mit derselben Nummer waeren zwei Reihen unter einem Namen.
    """
    gefunden = _fuji_serien(aufnahmen) + _nikon_serien(aufnahmen)
    gefunden.sort(key=lambda s: (s.aufnahmen[0].zeitpunkt, s.aufnahmen[0].stamm))
    return [
        Serie(
            typ=s.typ,
            nummer=nummer,
            aufnahmen=s.aufnahmen,
            quelle=s.quelle,
            sicher=s.sicher,
        )
        for nummer, s in enumerate(gefunden, start=1)
    ]


def _chronologisch(aufnahmen: Sequence[Aufnahme]) -> list[Aufnahme]:
    """Zeit UND Stamm — die Kamera schreibt nur Sekunden.

    Im gemessenen Bestand tragen bis zu sechs Bilder einer Reihe denselben
    Zeitstempel. Eine Sortierung allein nach Zeit haengt dort an der
    Eingabereihenfolge; ein dadurch scheinbar zurueckfallender Zaehler
    zerschneidet die Reihe.
    """
    return sorted(aufnahmen, key=lambda a: (a.zeitpunkt, a.stamm))


def _fuji_serien(aufnahmen: Sequence[Aufnahme]) -> list[Serie]:
    """Trennung am Neustart der Sequenznummer, NICHT am Zeitabstand.

    Im Bestand vom 27.08. liegen zwischen zwei Reihen zweimal nur zwei bis
    drei Sekunden — weniger als innerhalb mancher Reihe.
    """
    gruppen: list[list[Aufnahme]] = []
    letzte_sequenz: int | None = None
    for a in _chronologisch(aufnahmen):
        if a.exif.get("MakerNotes:AutoBracketing") != 1:
            letzte_sequenz = None
            continue
        sequenz = a.exif.get("MakerNotes:SequenceNumber")
        if letzte_sequenz is None or sequenz <= letzte_sequenz:
            gruppen.append([])
        gruppen[-1].append(a)
        letzte_sequenz = sequenz
    return _zu_serien(gruppen, typ="hdr", sicher=True)


def _nikon_serien(aufnahmen: Sequence[Aufnahme]) -> list[Serie]:
    """Trennung an der Rueckkehr des Belichtungswerts, NICHT am Zeitabstand.

    Eine Reihe durchlaeuft ihre Stufen genau einmal; taucht ein Wert wieder
    auf, hat die naechste begonnen. Der Zeitabstand traegt hier nicht: die
    gemessene 7er-Reihe des 27.08. wurde von Hand ueber dreieinhalb Minuten
    belichtet, mit 130 Sekunden Lucke mittendrin, waehrend zwischen zwei
    verschiedenen Reihen nur 32 Sekunden lagen.

    Die Regel ist ausserdem unabhaengig von `AutoBracketOrder`: ob die Kamera
    bei 0 oder beim negativsten Wert beginnt, aendert nichts daran, dass sich
    innerhalb einer Reihe keine Stufe wiederholt.

    Die Werte werden EXAKT verglichen, nicht gerundet. Eine erste Fassung
    rundete vorsichtshalber auf drei Stellen — die Mutation ueberlebte, weil
    kein Fall existiert, den das rettet: im gemessenen Bestand sind die
    wiederkehrenden Stufen bitgleich (`0` und `-2` kommen als dieselbe Zahl
    zurueck). Eine Vorsichtsmassnahme ohne Fall sieht nach Sorgfalt aus und
    prueft nichts.
    """
    gruppen: list[list[Aufnahme]] = []
    benutzte_werte: set[float] = set()
    for a in _chronologisch(aufnahmen):
        modus = a.exif.get("MakerNotes:ShootingMode", "")
        if "Exposure Bracketing" not in str(modus):
            gruppen.append([])
            benutzte_werte = set()
            continue
        wert = float(a.exif.get("MakerNotes:ExposureBracketValue", 0.0))
        if not gruppen or wert in benutzte_werte:
            gruppen.append([])
            benutzte_werte = set()
        gruppen[-1].append(a)
        benutzte_werte.add(wert)
    return _zu_serien(gruppen, typ="hdr", sicher=False)


def _zu_serien(gruppen: list[list[Aufnahme]], *, typ: str, sicher: bool) -> list[Serie]:
    return [
        Serie(typ=typ, nummer=0, aufnahmen=tuple(gruppe), quelle="kamera", sicher=sicher)
        for gruppe in gruppen
        if len(gruppe) >= _MIN_SERIENLAENGE
    ]
