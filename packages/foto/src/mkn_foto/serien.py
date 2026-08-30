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
from dataclasses import dataclass

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


# --- Stufe 2: Kandidaten --------------------------------------------------

_FENSTER_MAX_LUECKE_S = 60.0
"""Wie lange eine Pause sein darf, ohne das Fenster zu schneiden.

**Das ist die einzige IRREVERSIBLE Stelle der ganzen Kette** — und darum eine
Abwaegung, kein Messwert. Ein zu enges Fenster zerreisst eine Reihe, BEVOR
irgendjemand misst; der Fehler ist danach unsichtbar, weil die Bilder nie
zusammen betrachtet wurden. Ein zu weites kostet Messsekunden und
schlimmstenfalls Cent-Betraege am Modell.

Beide belegten Panoramen laegen auch im alten 10-s-Fenster (Prueffall 5/7 s,
Poster-Raster 15 Bilder in 25 s). Aber ein Stativ-Umbau zwischen zwei Zeilen
eines Rasters ist real, und dort waere der Schaden nicht mehr gutzumachen."""

_KANDIDAT_MIN_LAENGE = 2
"""Die kleinste Gruppe, die ein Fenster bildet.

**Die Mindestlaenge ist kein Entscheider mehr.** Sie war es, und sie hat KT-1s
Panorama verworfen: `DSCF3894`-`3896` entstand als Gruppe voellig korrekt
(Brennweite und Blende konstant, Luecken 5 s und 7 s, davor 442 s und dahinter
187 s Trennung) und fiel einzig an der Zahl 4 durch.

Die Auswahl uebernimmt jetzt die Deckungsmessung, die ohnehin Schwenk von
Wiederholung trennt. Was die 4 an Schutz leistete, leisten Deckungs-Schwelle und
Regel A. KT-1 woertlich: *"ggf. sind 2 bilder bereits der anfang des
panoramas"*."""

# Was konstant bleiben MUSS. Die Belichtungszeit steht bewusst NICHT hier:
# bei Zeitautomatik misst die Kamera jedes Bild neu, und ein Kriterium
# "alles konstant" verpasst genau die Panoramen — firsthand gemessen an einer
# Reihe mit f/8 und 34 mm konstant, waehrend die Zeit von 1/300 auf 1/240 lief.
#
# `Orientation` kam dazu: ein Wechsel zwischen Quer- und Hochformat ist eine
# neue Bildabsicht, und er hat eine zweite, technische Folge -- gemischte Achsen
# machen jede Richtungsaussage der Messung wertlos. Firsthand schneidet das
# Merkmal in der Fotorunde zwei Fenster korrekt: [3881 | 3882, 3883] und
# [3891, 3892 | 3893].
_MERKMALE = ("EXIF:FocalLength", "EXIF:FNumber", "EXIF:Orientation")


def kandidaten(aufnahmen: Sequence[Aufnahme], schon_erkannt: Sequence[Serie]) -> list[Serie]:
    """Moegliche Serien, ueber die erst der Blick auf das Bild entscheidet.

    Diese Stufe raet, und sie soll grosszuegig raten: der teure Fehler ist
    nicht der falsche Verdacht — den raeumt Stufe 3 aus —, sondern der
    uebersehene Fall, denn was hier nicht vorgeschlagen wird, sieht niemand
    mehr an.

    Aufnahmen, die schon in einer bezeugten Serie stecken, bleiben aussen vor
    UND trennen: sonst waechst ein Kandidat quer durch eine bezeugte Reihe
    hindurch zusammen, und dieselbe Aufnahme traegt zwei Zuordnungen, von
    denen der Dateiname nur eine tragen kann.
    """
    belegt = {id(a) for s in schon_erkannt for a in s.aufnahmen}
    gruppen: list[list[Aufnahme]] = []
    vorige: Aufnahme | None = None
    for a in _chronologisch(aufnahmen):
        if id(a) in belegt:
            vorige = None
            continue
        neu = (
            vorige is None
            or (a.zeitpunkt - vorige.zeitpunkt).total_seconds() > _FENSTER_MAX_LUECKE_S
            or a.kamera != vorige.kamera
            or any(_weicht_ab(a, vorige, merkmal) for merkmal in _MERKMALE)
        )
        if neu:
            gruppen.append([])
        gruppen[-1].append(a)
        vorige = a

    lang_genug = [g for g in gruppen if len(g) >= _KANDIDAT_MIN_LAENGE]
    return [
        Serie(typ="pan", nummer=nummer, aufnahmen=tuple(g), quelle="heuristik", sicher=False)
        for nummer, g in enumerate(lang_genug, start=1)
    ]


def _weicht_ab(a: Aufnahme, b: Aufnahme, merkmal: str) -> bool:
    return a.exif.get(merkmal) != b.exif.get(merkmal)


# --- Die Klammer: aus gemessenen Schritten werden Gruppen mit Klasse -------


@dataclass(frozen=True)
class Gruppe:
    """Eine zusammenhaengend gemessene Folge — und was mit ihr geschehen soll."""

    aufnahmen: tuple[Aufnahme, ...]

    klasse: str
    """`kandidat` (geht ans Modell) | `wiederholung` (Gruppen-Motivaufruf, kein
    Name) | `einzeln` (wie bisher)."""

    schritte: tuple = ()
    """Die gemessenen Verbindungen — fuer das Protokoll, damit ein Urteil
    nachvollziehbar bleibt und Grenzfaelle sichtbar werden."""

    reihen: tuple[int, ...] = ()
    """Bildanzahl je Reihe, aus den Schrittrichtungen abgeleitet. Nur bei
    Kandidaten gefuellt; sonst leer."""


def vermesse(fenster: Sequence[Serie], schritte_je_fenster: dict[int, Sequence]) -> list[Gruppe]:
    """Macht aus Zeitfenstern und ihren gemessenen Schritten klassifizierte Gruppen.

    **Die Klammer zwischen Messung und Urteil.** `deckung` liefert Zahlen ueber
    Bildpaare; hier wird daraus entschieden, was ueberhaupt ans Modell geht.

    Die Regel ist bewusst grosszuegig (Design § 3): **eine Gruppe mit mindestens
    EINEM Schwenk-Schritt ist ein Kandidat.** Ein Kandidat kostet einen
    Modellaufruf, ein uebersehener Fall kostet das Panorama -- und was hier nicht
    vorgeschlagen wird, sieht niemand mehr an.

    **Was hier NICHT entschieden wird, ist die Panorama-Frage selbst.** Die kann
    die Messung nachweislich nicht beantworten: eine Gehsequenz durch eine Klamm
    sieht panoramiger aus als ein echtes Panorama (Design § 3a, gemessen).
    Die Klassifikation bereitet vor, das Urteil faellt am Bild.

    `schritte_je_fenster` ordnet dem Index eines Fensters seine gemessenen
    Schritte zu. Die Zuordnung laeuft ueber den Index und nicht ueber die
    Aufnahme-Identitaet, weil ein Schritt zwei Aufnahmen verbindet und keiner
    von beiden gehoert.
    """
    from mkn_foto import deckung as _deckung

    ergebnis: list[Gruppe] = []
    for i, f in enumerate(fenster):
        schritte = list(schritte_je_fenster.get(i, ()))
        for glied in _zusammenhaengend(len(f.aufnahmen), schritte):
            mitglieder = tuple(f.aufnahmen[n] for n in sorted(glied))
            eigene = tuple(s for s in schritte if s.von in glied and s.nach in glied)
            if not eigene:
                ergebnis.append(Gruppe(aufnahmen=mitglieder, klasse="einzeln"))
                continue
            hat_schwenk = any(s.art == "schwenk" for s in eigene)
            ergebnis.append(
                Gruppe(
                    aufnahmen=mitglieder,
                    klasse="kandidat" if hat_schwenk else "wiederholung",
                    schritte=eigene,
                    reihen=tuple(_deckung.raster(eigene)) if hat_schwenk else (),
                )
            )
    return ergebnis


def _zusammenhaengend(anzahl: int, schritte: Sequence) -> list[set[int]]:
    """Zerlegt die Indices eines Fensters in verbundene Glieder.

    Ein Schritt verbindet zwei Bilder; alles, was ueber Schritte erreichbar ist,
    gehoert zusammen. Der Rueckgriff der Messung kann dabei ueber mehrere
    Positionen springen (ein Raster ohne Schlangenmuster), deshalb wird die
    Erreichbarkeit gerechnet und nicht die Nachbarschaft angenommen.
    """
    glied_von: dict[int, set[int]] = {n: {n} for n in range(anzahl)}
    for s in schritte:
        a, b = glied_von[s.von], glied_von[s.nach]
        if a is b:
            continue
        vereint = a | b
        for n in vereint:
            glied_von[n] = vereint
    gesehen: list[set[int]] = []
    for n in range(anzahl):
        if not any(n in g for g in gesehen):
            gesehen.append(glied_von[n])
    return gesehen
