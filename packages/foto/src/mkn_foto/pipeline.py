"""Die Verdrahtung: vom Kamerabaum zum angereicherten Baum plus Entscheidungsliste.

Jeder Einzelschritt lebt in seinem eigenen Modul und hat dort seine Tests. Hier
steht nur die Reihenfolge — und die ist der Punkt, denn drei Dinge gehen genau
beim Zusammenstecken schief und nirgends sonst:

- **Die GPX-Zeit muss umgerechnet werden**, bevor irgendetwas sie mit einem
  Aufnahmezeitpunkt vergleicht. GPX traegt UTC, EXIF traegt lokale Zeit ohne
  Zone; roh weitergereicht ergibt das im Sommer zwei Stunden Versatz — und
  fuer jedes Bild eine Koordinate, die plausibel aussieht und falsch ist.
- **Widerlegte Anker muessen VOR der Ortsbestimmung raus.** Danach hat der
  Ausreisser den Radius bereits aufgeblaeht; firsthand gesehen, wie ein
  einzelner 935-m-Ausreisser aus einem belegten Ort einen blossen Vorschlag
  machte.
- **Was keinen belegten Ort hat, wird nicht geschrieben**, sondern vorgelegt.
  Das ist KT-1s oberste Regel: im Zweifel nicht schreiben, sondern fragen.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from mkn_foto import (
    anreichern,
    bericht,
    entscheidung,
    geotag,
    gpx,
    inventar,
    mediathek,
    motivlauf,
    notizen,
    ort,
    schreiben,
    serien,
    spots,
    urheber,
)
from mkn_foto.modell import Anker, Aufnahme, Ort, Serie, Spot

ZONE = "Europe/Berlin"
"""Die Zone, in der die Kameras standen. Wie in `gpx`: aufgeloest ueber die
Zonendatenbank, nie als fester Versatz -- der waere ueber einen
Zeitumstellungs-Tag hinweg falsch."""

RADIUS_VON_HAND_M = 250
"""Der Radius eines von Hand benannten Ortes.

Bewusst groesser als der geometrische Mindestradius (25 m) und bewusst kein
Zugriff auf dessen private Konstante: das ist eine ANDERE Frage. Ein
Footprint-Name wie "Lenggries" bezeichnet eine Stelle, an der jemand stand,
nicht den Punkt, an dem jeder Ausloeser fiel — und die Session bewegt sich
darum herum. Eine Koordinate ohne ehrliche Fehlerangabe behauptet Genauigkeit,
die sie nicht hat; der Wert geht als `GPSHPositioningError` mit in die Datei."""

VON_HAND = "schild"
"""Die Herkunft eines Ortes, den ein Mensch benannt hat. `Ort.quelle` kennt
diesen Wert bereits -- er ist nicht `vorschlag` und gilt damit als belegt."""

OFFEN = "vorschlag"
"""Der Wert in `Ort.quelle`, der sagt: nicht belegt genug zum Schreiben."""


def _in_kamerazeit_anker(a: Anker) -> Anker:
    """Dieselbe Umrechnung auf einen ganzen Anker — oeffentlich genug fuer den
    Test, der die Zeitform prueft, ohne eine echte Mediathek zu brauchen."""
    return Anker(zeit=_in_kamerazeit(a.zeit), lat=a.lat, lon=a.lon, name=a.name)


def _in_kamerazeit(zeit: datetime) -> datetime:
    """Bringt jede Zeit auf die Form, in der eine Aufnahme ihre traegt.

    Zonenlos bleibt zonenlos -- eine bereits umgerechnete Zeit noch einmal
    anzufassen waere falsch, und `astimezone` auf einer naiven Zeit nimmt still
    die Zone des Rechners an. Genau dieser stille Weg ist der teure.
    """
    if zeit.tzinfo is None:
        return zeit
    return zeit.astimezone(ZoneInfo(ZONE)).replace(tzinfo=None)


@dataclass
class Lauf:
    """Was ein Durchlauf vorgefunden und getan hat. Zahlen, keine Behauptungen."""

    aufnahmen: list[Aufnahme] = field(default_factory=list)
    serien: list[Serie] = field(default_factory=list)
    """NUR belegte Serien -- die benennen Dateien und faerben sie."""

    kandidaten: list[Serie] = field(default_factory=list)
    """Vermutungen der Heuristik. Sie benennen NICHTS (Regel A), sondern warten
    auf das Urteil am Bild. Im Protokoll stehen sie, damit sie nicht verloren
    gehen -- und damit sichtbar ist, wie viel noch auf Stufe 3 wartet."""
    spots: list[Spot] = field(default_factory=list)
    orte: dict[int, Ort] = field(default_factory=dict)
    anker: list[Anker] = field(default_factory=list)
    offen: list[tuple[Spot, Ort | None]] = field(default_factory=list)
    """Weder verortet NOCH beantwortet — nur DAS wird vorgelegt."""

    beantwortet: list[tuple[Spot, str]] = field(default_factory=list)
    """Vom Menschen beantwortet, aber ohne Ortsangabe: "Loeschen - war im Hotel",
    "ist schwarz - falsch belichtet". Das sind VOLLSTAENDIGE Antworten, sie
    liefern nur keine Koordinate.

    Die Unterscheidung fehlte und hat KT-1 am 2026-08-30 elf von zwoelf Ordnern
    erneut vorgelegt: "da sind aber die drin, die ich schon beantwortet habe".
    OFFEN hiess damals NICHT VERORTET — und das ist nicht dasselbe."""
    geschrieben: schreiben.Ergebnis | None = None
    angereichert: anreichern.Ergebnis | None = None
    motive: motivlauf.Ergebnis | None = None
    """Was das Modell in den Bildern gesehen hat. `None`, wenn kein Modell
    angegeben war -- die Bildanalyse ist ein Zusatz, kein Fundament."""

    protokoll: Path | None = None
    entscheidungsdatei: Path | None = None

    @property
    def belegt(self) -> int:
        """Aufnahmen mit belegtem Ort — die Zahl, an der der Lauf gemessen wird."""
        return sum(len(s.aufnahmen) for s in self.spots if id(s) in self.orte)


def anker_sammeln(
    *,
    gpx_datei: Path | None = None,
    bibliothek: Path | None = None,
    album: str | None = None,
    notiz_ordner: Path | None = None,
    weitere: Sequence[Anker] = (),
    bereinigen: bool = True,
) -> list[Anker]:
    """Fuehrt alle Ortsquellen zu EINER chronologischen Liste zusammen.

    Zwei Quellen fuer dieselbe Frage sind nur dann mehr wert als eine, wenn sie
    gemischt werden: die Ortsbestimmung prueft die zeitlichen NACHBARN eines
    Punktes: haengt man die Quellen hintereinander, sind die Nachbarn falsch.

    `bereinigen=False` gibt den Rohstand zurueck — gedacht fuer den Vergleich,
    nicht fuer den Betrieb.
    """
    gesammelt: list[Anker] = list(weitere)

    if gpx_datei is not None:
        spur, wege = gpx.lies(Path(gpx_datei))
        for p in [*spur, *wege]:
            # Die Umrechnung passiert HIER, an der Grenze — danach traegt jeder
            # Anker im System dieselbe Zeitform wie eine Aufnahme.
            gesammelt.append(Anker(zeit=gpx.in_kamerazeit(p), lat=p.lat, lon=p.lon, name=p.name))

    if bibliothek is not None and album is not None:
        # Auch hier an der Grenze umrechnen: die Mediathek liefert UTC MIT Zone
        # (Core-Data-Epoche), das EXIF traegt lokale Zeit OHNE. Ungeprueft
        # gemischt bricht schon das Sortieren -- "can't compare offset-naive and
        # offset-aware datetimes", firsthand beim ersten echten Lauf ueber 283
        # Handybilder. Der Test dafuer hatte einen handgebauten naiven Anker
        # benutzt und konnte den Fall deshalb nicht sehen (LP-34).
        gesammelt.extend(
            _in_kamerazeit_anker(a) for a in mediathek.lies_album(Path(bibliothek), album)
        )

    if notiz_ordner is not None:
        # Die dritte Quelle, und die belastbarste: was ein Mensch beantwortet
        # hat. Sie braucht die benannten Wegpunkte als Schluessel -- ein Ortsname
        # in einer Notiz wird erst durch den Footprint zur Koordinate. Deshalb
        # steht sie NACH den beiden anderen.
        benannt = [a for a in gesammelt if a.name]
        gesammelt.extend(notizen.zu_ankern(notizen.lies(Path(notiz_ordner)), benannt))

    gesammelt.sort(key=lambda a: a.zeit)
    return ort.verwirf_widerlegte(gesammelt) if bereinigen else gesammelt


def fahre(
    quelle: Path,
    ziel: Path,
    *,
    anker: Sequence[Anker] = (),
    notiz_ordner: Path | None = None,
    entscheidungen: Path | None = None,
    schreiben_aktiv: bool = True,
    modell: tuple[str, str] | None = None,
    schluessel: str | None = None,
    transport=None,
    melde=None,
    melde_alle: int = 25,
) -> Lauf:
    """Der ganze Weg: lesen, ordnen, verorten, schreiben, vorlegen.

    `schreiben_aktiv=False` fuehrt alles aus, ohne eine Datei anzulegen — der
    Trockenlauf, mit dem sich die Zahlen ansehen lassen, bevor 51 GB wandern.
    """
    lauf = Lauf(anker=list(anker))

    lauf.aufnahmen = inventar.lies_baum(Path(quelle))
    if not lauf.aufnahmen:
        return lauf

    sicher = serien.aus_kamera(lauf.aufnahmen)
    lauf.kandidaten = serien.kandidaten(lauf.aufnahmen, sicher)
    # REGEL A: nur was BELEGT ist, bekommt einen Namen. `kandidaten` liefert
    # Vermutungen aus Zeit und gleichen Einstellungen -- die Spec misst dafuer
    # ein Drittel Trefferquote (§ 4). Wer sie benennt, gibt zwei von drei Dateien
    # einen falschen Namen, und der Name ist das, wonach spaeter gesucht wird.
    # Sie sind nicht verloren: sie stehen als Kandidat im Protokoll und warten
    # auf das Urteil am Bild (Stufe 3).
    lauf.serien = list(sicher)

    roh = spots.schneide(lauf.aufnahmen)
    lauf.spots = ort.fasse_gleichen_ort_zusammen(roh, lauf.anker)

    beantwortet = _beantwortete_orte(notiz_ordner, lauf.anker)
    alle_antworten = notizen.lies(Path(notiz_ordner)) if notiz_ordner else []

    for s in lauf.spots:
        # Eine menschliche Antwort geht VOR der Geometrie: sie ist eine Aussage,
        # keine Schaetzung. Die Abdeckungspruefung in `fuer_spot` misst, wie gut
        # die Anker eine Session einrahmen -- bei EINEM Anker aus einer Notiz
        # reicht das nie, und der Spot bliebe `vorschlag`. Firsthand trugen vier
        # Spots nach dem Einlesen den richtigen Namen und standen trotzdem wieder
        # auf der Liste; KT-1 haette dieselbe Frage zweimal beantwortet.
        aus_notiz = _passende_antwort(s, beantwortet)
        if aus_notiz is not None:
            lauf.orte[id(s)] = aus_notiz
            continue

        gefunden = ort.fuer_spot(s, lauf.anker)
        # `quelle` traegt die HERKUNFT (gpx | schild | anker), nicht das Wort
        # "belegt" -- der Zweifel steht als `vorschlag` darin. Die erste Fassung
        # verglich gegen "belegt" und haette damit JEDEN Spot als offen behandelt:
        # nichts verortet, alles vorgelegt, und der Lauf haette das fehlerfrei
        # gemeldet. Ein Enum-Wert aus dem Gedaechtnis statt aus der Quelle (HC-10).
        if gefunden is not None and gefunden.quelle != OFFEN:
            lauf.orte[id(s)] = gefunden
        elif (antwort := _antwort_text(s, alle_antworten)) is not None:
            # Beantwortet, nur ohne Ort. NICHT vorlegen -- das hiesse, dem
            # Menschen seine eigene Arbeit zurueckzugeben.
            lauf.beantwortet.append((s, antwort))
        else:
            # Kein Beleg heisst: vorlegen, nicht raten. Ein Vorschlag geht als
            # Vorschlag mit — er ist eine Frage, die sich mit Ja beantworten
            # laesst, und das ist mehr wert als eine leere Zeile.
            lauf.offen.append((s, gefunden))

    if schreiben_aktiv:
        lauf.geschrieben = schreiben.kopiere(lauf.aufnahmen, Path(ziel), serien=lauf.serien)
        # Und JETZT die Anreicherung -- in den ZIELbaum, nie in die Originale.
        # Dieser Schritt fehlte am 2026-08-30 komplett: der Baum hiess
        # "angereichert" und enthielt 1.227 RAW-Dateien mit 139 Sidecars, alle
        # davon schon vorher vorhanden. Die ganze Ortsarbeit lag im
        # Arbeitsspeicher und war mit dem Prozessende weg.
        mit_ort, serien_auf_kopien = _fuer_anreicherung(lauf)

        # Die Bildanalyse VOR dem Anreichern: ihre Ergebnisse gehen in dieselben
        # Dateien. Ein Modul in der Modulliste ist noch kein Aufruf im Ablauf --
        # genau dieser Fehler liess gestern `geotag` unbenutzt, und die Bilder
        # trugen Sammelkoordinaten statt eigener Positionen.
        beschreibungen: dict[int, str] = {}
        unklar: dict[int, str] = {}
        if modell is not None:
            lauf.motive = _bildanalyse(
                mit_ort, serien_auf_kopien, modell, schluessel, transport, melde, melde_alle
            )
            for aufnahme, _ in mit_ort:
                urteil = lauf.motive.fuer(_erstes_bild(aufnahme))
                if urteil is None:
                    continue
                schreibbar = urteil.zum_schreiben()
                if not schreibbar:
                    # Regel A: unsicher wird nicht geschrieben, sondern
                    # gekennzeichnet -- KT-1s Violett.
                    unklar[id(aufnahme)] = "Motiv"
                    continue
                if schreibbar.get("beschreibung"):
                    beschreibungen[id(aufnahme)] = schreibbar["beschreibung"]
                if schreibbar.get("belichtung") in ("unterbelichtet", "ueberbelichtet"):
                    unklar[id(aufnahme)] = "Belichtung"

        lauf.angereichert = anreichern.schreibe(
            mit_ort,
            serien=serien_auf_kopien,
            beschreibungen=beschreibungen,
            unklar=unklar,
            motive=_motive_je_aufnahme(lauf, mit_ort),
            # Wer die Bilder gemacht hat, steht in der Datei des Anwenders --
            # nie im Code dieses oeffentlichen Pakets. Fehlt sie, wird kein
            # Urheber geschrieben; das ist ein gueltiger Zustand.
            urheber_angaben=urheber.lade(),
        )

    if entscheidungen is not None and lauf.offen:
        entscheidung.bereite_vor(lauf.offen, Path(entscheidungen))
        # Die Eingabe zentral, die Bilder verteilt -- so herum, weil KT-1 EINE
        # Stelle zum Schreiben braucht und die Bilder nun einmal je Fall liegen.
        lauf.entscheidungsdatei = bericht.entscheidungsdatei(Path(entscheidungen), lauf.offen)

    if schreiben_aktiv:
        lauf.protokoll = bericht.protokoll(
            Path(ziel),
            verortet=[(s, lauf.orte[id(s)]) for s in lauf.spots if id(s) in lauf.orte],
            beantwortet=lauf.beantwortet,
            offen=lauf.offen,
        )

    return lauf


def _beantwortete_orte(
    notiz_ordner: Path | None, anker: Sequence[Anker]
) -> list[tuple[notizen.Notiz, Ort]]:
    """Paart jede beantwortete Notiz mit dem Ort, den sie benennt."""
    if notiz_ordner is None:
        return []
    benannt = [a for a in anker if a.name]
    gelesen = notizen.lies(Path(notiz_ordner))
    paare: list[tuple[notizen.Notiz, Ort]] = []
    for n in gelesen:
        aus_notiz = notizen.zu_ankern([n], benannt)
        if not aus_notiz:
            continue
        a = aus_notiz[0]
        paare.append(
            (
                n,
                Ort(
                    lat=a.lat,
                    lon=a.lon,
                    radius_m=RADIUS_VON_HAND_M,
                    name=a.name,
                    quelle=VON_HAND,
                ),
            )
        )
    return paare


def _passende_antwort(spot: Spot, beantwortet: Sequence[tuple[notizen.Notiz, Ort]]) -> Ort | None:
    """Findet die Notiz, deren Zeitfenster diesen Spot trifft.

    Verglichen wird auf UEBERLAPPUNG, nicht auf Gleichheit: die Ordnernamen
    tragen Minuten, die Spots Sekunden — und ein Spot kann seit dem Schreiben
    der Notiz mit einem Nachbarn zusammengefasst worden sein.
    """
    for n, gefunden in beantwortet:
        if spot.von <= n.bis and n.von <= spot.bis:
            return gefunden
    return None


def _antwort_text(spot: Spot, gelesen: Sequence[notizen.Notiz]) -> str | None:
    """Der Antworttext, falls dieser Spot schon einmal beantwortet wurde.

    Verglichen wird auf Ueberlappung der Zeitfenster, wie bei `_passende_antwort`:
    der Ordnername traegt Minuten, der Spot Sekunden, und ein Spot kann seit der
    Antwort mit einem Nachbarn zusammengefasst worden sein.
    """
    for n in gelesen:
        if spot.von <= n.bis and n.von <= spot.bis:
            return n.text
    return None


def _fuer_anreicherung(
    lauf: Lauf,
) -> tuple[list[tuple[Aufnahme, Ort | None]], list[Serie]]:
    """Baut die Kopien-Objekte GENAU EINMAL und gibt Orte und Serien darauf zurueck.

    Angereichert wird die Kopie, nicht das Original -- die Aufnahme bekommt hier
    also die neuen Pfade untergeschoben. `dataclasses.replace` statt Mutation:
    die Originalaufnahme bleibt unberuehrt, sonst zeigte das Inventar nach dem
    Lauf auf den Zielbaum.

    **Warum EINE Funktion und nicht zwei.** Die erste Fassung hatte zwei --
    eine fuer die Orte, eine fuer die Serien. Beide riefen `replace` auf und
    erzeugten damit VERSCHIEDENE Objekte; `anreichern` ordnet Stichworte aber
    ueber die Objekt-Identitaet zu, und die Zuordnung griff ins Leere. Alles
    blieb gruen: Sidecars entstanden, Orte standen drin, nur die Serienangabe
    fehlte lautlos. Gefunden, weil der Test auf die SERIENMARKE prueft statt auf
    das Wort "Technik" -- letzteres steht durch das Einzelbild-Stichwort ohnehin
    in jedem Sidecar.
    """
    if lauf.geschrieben is None:
        return [], []

    # Je BILD, nicht je Session: `ort_fuer_bild` interpoliert aus der Spur und
    # faellt nur zurueck, wo sie nichts hergibt. Die erste Fassung schrieb hier
    # die Sammelkoordinate des Spots an jedes Mitglied -- 141 Bilder auf einem
    # Punkt, und `geotag` wurde nie aufgerufen.
    ort_je_aufnahme = {id(a): ort_fuer_bild(a, lauf) for a in lauf.aufnahmen}

    je_id = dict(lauf.geschrieben.kopien)
    kopie_je_original: dict[int, Aufnahme] = {}
    paare: list[tuple[Aufnahme, Ort | None]] = []
    for a in lauf.aufnahmen:
        pfade = je_id.get(id(a))
        if not pfade:
            continue
        kopie = dataclasses.replace(a, dateien=pfade)
        kopie_je_original[id(a)] = kopie
        paare.append((kopie, ort_je_aufnahme.get(id(a))))

    serien_auf_kopien: list[Serie] = []
    for s in lauf.serien:
        mitglieder = tuple(
            kopie_je_original[id(a)] for a in s.aufnahmen if id(a) in kopie_je_original
        )
        if mitglieder:
            serien_auf_kopien.append(dataclasses.replace(s, aufnahmen=mitglieder))

    return paare, serien_auf_kopien


def ort_fuer_bild(aufnahme: Aufnahme, lauf: Lauf) -> Ort | None:
    """Die Position DIESES Bildes — interpoliert, sonst der Ort seiner Session.

    Die Reihenfolge ist der Kern von KT-1s Geotagging-Klage (2026-08-30): die
    Spur gibt bei 63 s Median-Abstand fuer jedes Bild eine eigene Position her.
    Der Session-Ort ist nur der RUECKFALL fuer die Faelle, in denen sie das nicht
    tut — am 25.08. gibt es null Spurpunkte, dort traegt er alles.

    `geotag` liefert von sich aus nichts, wenn die Unsicherheit zu gross waere;
    genau dann greift der Rueckfall, und nur dann.
    """
    genau = geotag.fuer_aufnahme(aufnahme, lauf.anker)
    if genau is not None:
        # Der NAME kommt weiterhin vom Spot: die Interpolation kennt Koordinaten,
        # aber keine Ortsnamen. Beides zusammen ist mehr als jedes fuer sich.
        vom_spot = _session_ort(aufnahme, lauf)
        if vom_spot is not None and vom_spot.name and not genau.name:
            return dataclasses.replace(genau, name=vom_spot.name)
        return genau
    return _session_ort(aufnahme, lauf)


def _session_ort(aufnahme: Aufnahme, lauf: Lauf) -> Ort | None:
    for s in lauf.spots:
        if any(a is aufnahme for a in s.aufnahmen):
            return lauf.orte.get(id(s))
    return None


def _erstes_bild(aufnahme: Aufnahme) -> Path:
    """Der Pfad, unter dem der Motivlauf diese Aufnahme kennt."""
    for endung in (".NEF", ".RAF", ".JPG", ".JPEG"):
        if endung in aufnahme.dateien:
            return aufnahme.dateien[endung]
    return next(iter(aufnahme.dateien.values()))


def _bildanalyse(
    mit_ort, serien_auf_kopien, modell, schluessel, transport, melde=None, melde_alle=25
) -> motivlauf.Ergebnis:
    """Setzt die Eintraege fuer den Motivlauf zusammen: Serien als Gruppe,
    der Rest einzeln."""
    from mkn_kern import modelle

    wahl = modelle.Wahl(anbieter=modell[0], modell=modell[1])
    in_serie: dict[int, Serie] = {}
    for s in serien_auf_kopien:
        for a in s.aufnahmen:
            in_serie[id(a)] = s

    eintraege: list[tuple[Path, list[Path] | None]] = []
    erledigt: set[int] = set()
    for aufnahme, _ in mit_ort:
        if id(aufnahme) in erledigt:
            continue
        s = in_serie.get(id(aufnahme))
        if s is not None:
            mitglieder = [_erstes_bild(m) for m in s.aufnahmen]
            eintraege.append((mitglieder[0], mitglieder))
            erledigt.update(id(m) for m in s.aufnahmen)
        else:
            eintraege.append((_erstes_bild(aufnahme), None))
            erledigt.add(id(aufnahme))

    vorhanden = motivlauf.aus_baum([e[0] for e in eintraege])
    return motivlauf.fahre(
        eintraege,
        wahl,
        schluessel=schluessel,
        transport=transport,
        vorhandene=vorhanden,
        melde=melde,
        melde_alle=melde_alle,
    )


def _motive_je_aufnahme(lauf: Lauf, mit_ort) -> dict[int, tuple[str, ...]]:
    """Bildet jede Aufnahme auf die Motiv-Stichworte ihres Urteils ab."""
    if lauf.motive is None:
        return {}
    zuordnung: dict[int, tuple[str, ...]] = {}
    for aufnahme, _ in mit_ort:
        urteil = lauf.motive.fuer(_erstes_bild(aufnahme))
        if urteil is None:
            continue
        worte = urteil.zum_schreiben().get("motive")
        if worte:
            zuordnung[id(aufnahme)] = tuple(worte)
    return zuordnung
