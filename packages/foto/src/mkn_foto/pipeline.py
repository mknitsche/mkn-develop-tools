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
import logging
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from mkn_foto import (
    anreichern,
    bericht,
    deckung,
    entscheidung,
    geotag,
    gpx,
    inventar,
    konfig,
    mediathek,
    messung,
    motivlauf,
    notizen,
    ort,
    schreiben,
    serien,
    spots,
)
from mkn_foto.modell import Anker, Aufnahme, Ort, Serie, Spot

_LOG = logging.getLogger(__name__)

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

    **Eine Funktion, nicht zwei.** Diese hier hatte den Schutz gegen die
    Zonenfalle, `gpx.in_kamerazeit` hatte ihn nicht -- zwei Fassungen derselben
    Aufgabe, und der Fehler sass in der ungeschuetzten. Ein Kommentar, der eine
    Falle beschreibt, schuetzt nur die Datei, in der er steht.
    """
    return gpx.in_kamerazeit(Anker(zeit=zeit, lat=0.0, lon=0.0, name=None), ZONE)


@dataclass
class Lauf:
    """Was ein Durchlauf vorgefunden und getan hat. Zahlen, keine Behauptungen."""

    aufnahmen: list[Aufnahme] = field(default_factory=list)
    serien: list[Serie] = field(default_factory=list)
    """NUR belegte Serien -- die benennen Dateien und faerben sie."""

    kandidaten: list[Serie] = field(default_factory=list)
    """Die ZEITFENSTER aus Stufe 2 -- grosszuegig geschnitten, noch keine
    Aussage. Was darin zusammengehoert, entscheidet die Messung (`gruppen`).

    Sie hiessen frueher "Vermutungen der Heuristik" und wurden gesetzt, aber
    nirgends gelesen: ueber 1.234 Kursbilder wurde deshalb null Panorama
    erkannt."""

    gruppen: list = field(default_factory=list)
    """Was die Deckungsmessung aus den Fenstern gemacht hat: Gruppen mit Klasse
    (`kandidat` | `wiederholung` | `einzeln`), Schritten und Rastervermutung."""
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
    modell: tuple[str, str] | None = None,
    schluessel: str | None = None,
    transport=None,
    protokoll: messung.Protokoll | None = None,
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
        gelesen = notizen.lies(Path(notiz_ordner))
        # Und HIER wird das Modell gefragt. Ohne diesen Aufruf koennen
        # `notizurteil` und `zu_ankern` beide alles richtig machen und der Lauf
        # verhaelt sich trotzdem wie vorher -- neun von zwanzig Antworten
        # verwertet, elf weggeworfen. Genau diese Naht ist in dieser Nacht
        # viermal gerissen (geotag, motivlauf, melde, Gemini-Adresse).
        urteile = _notizen_lesen(gelesen, modell, schluessel, transport, protokoll)
        gesammelt.extend(notizen.zu_ankern(gelesen, benannt, urteile=urteile))

    gesammelt.sort(key=lambda a: a.zeit)
    return ort.verwirf_widerlegte(gesammelt) if bereinigen else gesammelt


def _notizen_lesen(
    gelesen: Sequence[notizen.Notiz],
    modell: tuple[str, str] | None,
    schluessel: str | None,
    transport,
    protokoll: messung.Protokoll | None = None,
) -> dict[str, object]:
    """Laesst jede Notiz vom Modell LESEN statt nach Stichworten absuchen.

    Ohne Modell bleibt die Zuordnung leer; `zu_ankern` faellt dann auf die alte
    Stichwortsuche zurueck, damit ein Lauf ohne Modell nicht schlechter wird als
    vorher.

    Ein Fehler bei EINER Notiz nimmt die anderen nicht mit: bei zwanzig
    Antworten ist eine unlesbare normal, und ein Abbruch waere die teuerste
    denkbare Antwort darauf.
    """
    if modell is None or not gelesen:
        return {}

    from mkn_foto import notizurteil
    from mkn_kern import anfrage, modelle

    wahl = modelle.Wahl(anbieter=modell[0], modell=modell[1])
    if schluessel is None:
        schluessel = wahl.schluessel(ablage=konfig.lade().schluessel_datei)
    kopf = motivlauf._kopf(wahl, schluessel)
    reihe = sorted(gelesen, key=lambda n: n.von)
    namen = tuple(n.ordner for n in reihe)

    urteile: dict[str, object] = {}
    for i, n in enumerate(reihe):
        # Die Nachbarn gehoeren zur Frage: ohne sie kann "vorheriger Ordner"
        # nicht aufgeloest werden. Wer nur den Satz schickt, bekommt eine
        # Antwort, die nicht falsch ist, sondern unmoeglich.
        nachbarn = tuple(x for x in namen[max(0, i - 2) : i + 3] if x != n.ordner)
        frage = notizurteil.prompt(" ".join(n.text.split()), ordner=n.ordner, nachbarn=nachbarn)
        begonnen = time.monotonic()
        try:
            antwort = anfrage.sende(wahl.url(), wahl.baue_anfrage(frage), kopf, transport=transport)
        except anfrage.AnfrageFehler as exc:
            _LOG.warning("Notiz nicht gelesen: %s (%s)", n.ordner, exc)
            if protokoll is not None:
                # Ein Fehlschlag hat Zeit gekostet, und ein Lauf ohne seine
                # Fehlschlaege sieht schneller aus, als er war.
                protokoll.nimm(
                    messung.Messwert(
                        name=n.ordner,
                        dauer_s=time.monotonic() - begonnen,
                        art="notiz",
                        fehler=str(exc),
                    )
                )
            continue
        # Diese Anfragen kosten Geld und standen in keiner Messung. Aufgefallen
        # ist es an KT-1s Kontostand: die Lauf-Zahl stimmte mit der Plattform
        # auf 0,16 % ueberein -- bis auf rund 74.000 Tokens, und ein Teil davon
        # war genau das hier. Die schlechteste Art von Luecke: sie faellt nicht
        # auf, weil alles andere stimmt.
        if protokoll is not None:
            protokoll.nimm(
                messung.Messwert.aus_antwort(
                    n.ordner, antwort, dauer_s=time.monotonic() - begonnen, art="notiz"
                )
            )
        urteile[n.ordner] = notizurteil.aus_antwort(antwort)

    return urteile


def fahre(
    quelle: Path,
    ziel: Path,
    *,
    anker: Sequence[Anker] = (),
    anker_protokoll: messung.Protokoll | None = None,
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
        # NEU -- die Messung, und zwar auf den KOPIEN. Sie ist zustandslos,
        # kostet nichts und laeuft nach einem Abbruch einfach neu; die Kopien
        # sind ab hier der Zustand, an dem die Wiederaufnahme haengt.
        lauf.gruppen = _vermesse_fenster(lauf)
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
        # Wer in einer Belichtungsreihe steckt, dessen Belichtung ist Absicht.
        in_belichtungsreihe = {
            id(a) for s in serien_auf_kopien if s.typ == "hdr" for a in s.aufnahmen
        }
        # Was in der Konfiguration steht, muss auch wirken: ein dokumentiertes
        # Feld, das nichts tut, ist schlimmer als ein fehlendes -- der Anwender
        # traegt es ein, sieht kein Ergebnis und sucht den Fehler bei sich.
        # Der AUFRUF hat Vorrang: wer ein Modell uebergibt, meint es.
        einstellungen = konfig.lade()
        modell = modell or einstellungen.modell
        if modell is not None:
            # Die Anker-Anfragen (Notizen lesen) gehoeren in DIESELBE Rechnung:
            # gemessen ist noch nicht ausgewiesen, und eine Zahl, die in keinem
            # Bericht steht, hat die Luecke nur verschoben.
            lauf.motive = _bildanalyse(
                mit_ort,
                serien_auf_kopien,
                lauf.gruppen,
                modell,
                schluessel,
                transport,
                melde,
                melde_alle,
                einstellungen.schluessel_datei,
            )
            if anker_protokoll is not None:
                for wert in anker_protokoll.werte:
                    lauf.motive.messung.nimm(wert)
            in_kandidat = {
                id(a)
                for g in lauf.gruppen
                if getattr(g, "klasse", "") == "kandidat"
                for a in g.aufnahmen
            }
            for aufnahme, _ in mit_ort:
                urteil = lauf.motive.fuer(_erstes_bild(aufnahme))
                if urteil is None:
                    continue
                schreibbar = urteil.zum_schreiben()
                if not schreibbar:
                    # Regel A: unsicher wird nicht geschrieben, sondern
                    # gekennzeichnet -- KT-1s Violett.
                    #
                    # Der GRUND unterscheidet die beiden Faelle, und er ist das,
                    # wonach gefiltert wird: bei einer gemessenen Kandidaten-
                    # Gruppe steht die Serienfrage offen, sonst die Motivfrage.
                    # Beides violett, aber `Pruefen|Serie` sammelt genau die
                    # Panorama-Vorschlaege, die KT-1 ansehen soll.
                    unklar[id(aufnahme)] = "Serie" if id(aufnahme) in in_kandidat else "Motiv"
                    continue
                if schreibbar.get("beschreibung"):
                    beschreibungen[id(aufnahme)] = schreibbar["beschreibung"]
                if (
                    schreibbar.get("belichtung") in ("unterbelichtet", "ueberbelichtet")
                    and id(aufnahme) not in in_belichtungsreihe
                ):
                    # ABER NICHT bei einer Belichtungsreihe. Eine HDR-Serie
                    # BESTEHT aus absichtlich ueber- und unterbelichteten
                    # Bildern -- das ist ihr Zweck, kein Mangel.
                    #
                    # Ohne diese Ausnahme meldet das Modell folgerichtig
                    # "unterbelichtet", Violett schlaegt Blau (KT-1s Rangfolge,
                    # richtig), und die Serie wird unsichtbar. Gemessen an
                    # seinem Baum vom 2026-08-30: 394 Bilder mit `Technik|hdr`,
                    # davon 156 blau und **238 violett**. Der Fehler traf die
                    # Mehrheit, und kein Test konnte ihn finden -- das Werkzeug
                    # tat genau, was ihm gesagt wurde. Gefunden hat es KT-1, im
                    # Bildbetrachter.
                    unklar[id(aufnahme)] = "Belichtung"

        # Vollzug VOR dem Anreichern: `benenne_um` gibt den Aufnahmen ihre neuen
        # Pfade, und `anreichern` schreibt danach in genau diese Dateien. Umgekehrt
        # laege die Anreicherung unter dem alten Namen und der Sidecar neben einer
        # Datei, die es nicht mehr gibt.
        # Der Vollzug liefert die Serien, die es beim Stichwortbau noch nicht
        # gab: `serien_auf_kopien` entstand VOR dem Urteil. Ohne sie truege eine
        # Datei den Namen `pan01-01v02` und das Stichwort `Technik|Einzelbild` --
        # ein Widerspruch in derselben Datei, firsthand am Karwendel-Lauf.
        serien_auf_kopien = serien_auf_kopien + _vollziehe_serien(lauf)

        lauf.angereichert = anreichern.schreibe(
            mit_ort,
            serien=serien_auf_kopien,
            beschreibungen=beschreibungen,
            unklar=unklar,
            motive=_motive_je_aufnahme(lauf, mit_ort),
            # Wer die Bilder gemacht hat, steht in der Datei des Anwenders --
            # nie im Code dieses oeffentlichen Pakets. Fehlt sie, wird kein
            # Urheber geschrieben; das ist ein gueltiger Zustand.
            urheber_angaben=einstellungen.urheber,
            # Die Namen gehoeren dem Anwender: Lightroom vergleicht sie mit den
            # Namen SEINES Farbbeschriftungssatzes, und die sind uebersetzt.
            farbe_serie=einstellungen.farbe_serie,
            farbe_unklar=einstellungen.farbe_unklar,
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

    # Die gemessenen Gruppen tragen ORIGINAL-Aufnahmen; angereichert und
    # umbenannt wird aber die Kopie. Ohne diese Abbildung zeigte das Urteil auf
    # Dateien im Quellbaum -- die nie angefasst werden duerfen.
    lauf.gruppen = [
        dataclasses.replace(
            g,
            aufnahmen=tuple(
                kopie_je_original[id(a)] for a in g.aufnahmen if id(a) in kopie_je_original
            ),
        )
        for g in lauf.gruppen
    ]
    lauf.gruppen = [g for g in lauf.gruppen if g.aufnahmen]

    return paare, serien_auf_kopien


def _messbefund(gruppe) -> str:
    """Was die Messung ueber diese Gruppe weiss — in Worten fuer das Modell.

    **Ohne diesen Text sieht das Modell nur den Kontaktbogen** und urteilt ueber
    Bilder, deren Verschiebung gegeneinander bereits gemessen ist. Firsthand am
    2026-08-30: KT-1s Panorama von der Sebalduskirche besteht aus einem Schwenk
    (36 % Versatz) und einer Wiederholung derselben Stelle. Auf dem blossen
    Bogen sind zwei der drei Bilder fast gleich — das Modell nannte die Gruppe
    folgerichtig `wiederholung`, mit `sicher: true`. Es hatte nicht unrecht;
    ihm fehlte die Haelfte.

    Der Schlusssatz ist kein Schmuck: die Messung kann eine Gehsequenz nicht von
    einem Schwenk trennen (Design § 3a, gemessen). Das Modell darf ihre Zahlen
    also nicht fuer eine Antwort halten, sondern nur fuer das, was sie sind —
    eine Beobachtung ueber die Geometrie. Die Bedeutung sieht es selbst.
    """
    if not getattr(gruppe, "schritte", ()):
        return ""
    zeilen = ["Was die Deckungsmessung an diesen Bildern festgestellt hat:"]
    for s in gruppe.schritte:
        versatz = max(abs(s.deckung.dx), abs(s.deckung.dy))
        richtung = "waagerecht" if abs(s.deckung.dx) >= abs(s.deckung.dy) else "senkrecht"
        if s.art == "schwenk":
            was = f"verschoben um {versatz:.0%} der Bildkante, {richtung}"
        else:
            was = f"fast derselbe Ausschnitt (nur {versatz:.0%} Versatz)"
        zeilen.append(f"  Bild {s.von + 1} zu Bild {s.nach + 1}: {was}")
    if getattr(gruppe, "reihen", ()) and len(gruppe.reihen) > 1:
        zeilen.append(f"  Daraus geschaetzt: {len(gruppe.reihen)} Reihen ({gruppe.reihen}).")
    zeilen.append(
        "Diese Messung sagt nur, WIE die Bilder zueinander liegen -- nicht, ob "
        "sie zusammengehoeren. Eine Bilderfolge beim Gehen sieht genauso aus wie "
        "ein Schwenk. Das entscheidest du am Bild."
    )
    return "\n".join(zeilen)


def _vollziehe_serien(lauf: Lauf) -> list[Serie]:
    """Benennt die Gruppen um, die das Modell SICHER als Panorama bestaetigt hat.

    **Regel A, hier an ihrer teuersten Stelle.** Ein Ort, der falsch ist, laesst
    sich korrigieren; ein falscher DATEINAME ist nach dem Schreiben nicht mehr
    als Vermutung erkennbar — er sieht aus wie eine Tatsache. Deshalb benennt
    nur ein `sicher`-Urteil, und nur die Mitglieder, die das Modell in `bilder`
    ausdruecklich nennt. Alles andere bleibt `std` und geht auf die Liste.

    Die Nummern werden je Typ vergeben: `hdr` und `pan` zaehlen getrennt, sonst
    truege eine Kamera-Reihe dieselbe Nummer wie ein Panorama.
    """
    if lauf.motive is None or not lauf.gruppen:
        return []

    vollzogen: list[Serie] = []
    nummer = 0
    for g in lauf.gruppen:
        if g.klasse != "kandidat":
            continue
        urteil = lauf.motive.fuer(_erstes_bild(g.aufnahmen[0]))
        if urteil is None or not getattr(urteil, "sicher", False):
            continue
        if getattr(urteil, "serie", None) != "panorama":
            continue
        gewaehlt = _mitglieder_laut_urteil(g, urteil)
        if len(gewaehlt) < 2:
            # Ein Panorama aus einem Bild gibt es nicht. Faellt die Auswahl des
            # Modells darunter, ist das kein Vollzug, sondern ein Widerspruch —
            # die Gruppe bleibt `std`.
            continue
        nummer += 1
        vollzogen.append(
            Serie(typ="pan", nummer=nummer, aufnahmen=gewaehlt, quelle="bild", sicher=True)
        )

    if not vollzogen:
        return []

    umbenannt = schreiben.benenne_um(vollzogen)
    lauf.serien.extend(vollzogen)

    # **Die Urteile muessen mitwandern.** `motivlauf.Ergebnis` fuehrt sie ueber
    # DATEIPFADE; nach dem Umbenennen zeigen die alten Schluessel ins Leere, und
    # `anreichern` findet fuer genau die benannten Panoramen kein Urteil mehr.
    #
    # Firsthand am Karwendel-Lauf: die Motive standen im Sidecar (den `_merke`
    # VOR der Umbenennung geschrieben hatte) und fehlten im JPEG (das
    # `anreichern` DANACH suchte). 23 Panoramen mit halben Angaben, und dem
    # Ergebnis sieht man es nicht an -- die Datei ist da, sie ist nur leerer als
    # ihr Nachbar.
    if lauf.motive is not None:
        for alt_pfad, neu_pfad in umbenannt.items():
            if alt_pfad in lauf.motive.urteile:
                lauf.motive.urteile[neu_pfad] = lauf.motive.urteile[alt_pfad]
            if alt_pfad in lauf.motive.mitglieder:
                vertreter = lauf.motive.mitglieder[alt_pfad]
                lauf.motive.mitglieder[neu_pfad] = umbenannt.get(vertreter, vertreter)
    return vollzogen


def _mitglieder_laut_urteil(gruppe, urteil) -> tuple[Aufnahme, ...]:
    """Die Mitglieder, die das Modell in `bilder` genannt hat — 1-basiert.

    Nennt es nichts oder etwas Unmoegliches, gilt die ganze Gruppe: das ist der
    Regelfall (`bilder` = alle) und zugleich die vorsichtige Lesart, denn eine
    leere Auswahl wuerde unten an der Zwei-Bilder-Grenze ohnehin verworfen.
    Nummern ausserhalb der Gruppe werden still uebergangen — sie koennen nur aus
    einem Missverstaendnis stammen, und ein Absturz waere die teuerste Antwort
    darauf.
    """
    roh = getattr(urteil, "bilder", ()) or ()
    gewaehlt = tuple(gruppe.aufnahmen[n - 1] for n in roh if 1 <= n <= len(gruppe.aufnahmen))
    return gewaehlt or tuple(gruppe.aufnahmen)


def _vermesse_fenster(lauf: Lauf) -> list:
    """Misst die Deckung innerhalb jedes Zeitfensters — auf den Kopien.

    **Der Schritt, den es bisher nicht gab.** `lauf.kandidaten` wurde gesetzt und
    nirgends gelesen; damit war Stufe 3 nicht etwa fehlerhaft, sondern gar nicht
    vorhanden. Ueber 1.234 Kursbilder ergab das null Panoramen — auch fuer die
    Reihe, die die Spec selbst als "echtes Poster-Raster" fuehrt.

    Gemessen wird auf den Kopien im Zielbaum, nicht auf den Originalen: die
    Wiederaufnahme liest spaeter die Namen DORT, alle Stufen teilen sich EINE
    Vorschau-Extraktion, und ab hier haengt der Lauf nicht mehr an der Quelle.

    Die Vorschauen kommen stapelweise (ein exiftool-Aufruf fuer viele Dateien,
    gemessen Faktor 8,5) und liegen in einem Wegwerf-Ordner; ein harter Abbruch
    hinterlaesst dort nichts, was in einem der beiden Baeume stoert.
    """
    if not lauf.kandidaten or lauf.geschrieben is None:
        return []

    je_id = dict(lauf.geschrieben.kopien)
    quellen: dict[int, Path] = {}
    for f in lauf.kandidaten:
        for a in f.aufnahmen:
            pfade = je_id.get(id(a))
            if pfade:
                quellen[id(a)] = _erstes_bild(dataclasses.replace(a, dateien=pfade))

    if not quellen:
        return []

    with tempfile.TemporaryDirectory(prefix="mkn-foto-deckung-") as raum:
        vorschau_je_quelle = deckung.vorschauen_stapel(list(quellen.values()), Path(raum))
        schritte_je_fenster: dict[int, list] = {}
        for i, f in enumerate(lauf.kandidaten):
            bilder = []
            for a in f.aufnahmen:
                pfad = vorschau_je_quelle.get(quellen.get(id(a)))
                if pfad is None:
                    # Ohne Bild keine Messung. Das trifft den Film im Bestand
                    # und jede Datei ohne extrahierbare Vorschau; sie bleibt
                    # `std` und faellt nicht still aus, sondern erscheint als
                    # Einzelbild.
                    bilder = []
                    break
                bilder.append(deckung.vorbereiten(pfad))
            schritte_je_fenster[i] = deckung.kette(bilder) if bilder else []
        return serien.vermesse(lauf.kandidaten, schritte_je_fenster)


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
    mit_ort,
    serien_auf_kopien,
    gruppen,
    modell,
    schluessel,
    transport,
    melde=None,
    melde_alle=25,
    schluessel_datei=None,
) -> motivlauf.Ergebnis:
    """Setzt die Eintraege fuer den Motivlauf zusammen: Serien als Gruppe,
    der Rest einzeln."""
    from mkn_kern import modelle

    wahl = modelle.Wahl(anbieter=modell[0], modell=modell[1])
    # Der Ort der Schluesseldatei kommt aus der Konfiguration, sofern der
    # Aufrufer keinen Schluessel direkt mitgibt. Gelesen wird zur Laufzeit,
    # gespeichert wird nichts.
    if schluessel is None:
        schluessel = wahl.schluessel(ablage=schluessel_datei)
    in_serie: dict[int, Serie] = {}
    for s in serien_auf_kopien:
        for a in s.aufnahmen:
            in_serie[id(a)] = s

    # Gemessene Gruppen zuerst: ein Kandidat geht mit der SERIEN-Frage hinaus,
    # eine Wiederholung als Gruppe mit der Motiv-Frage. Beide ersetzen die
    # Einzelaufrufe ihrer Mitglieder, statt zu ihnen hinzuzukommen -- daran
    # haengt die Kostenrechnung des ganzen Verfahrens.
    in_gruppe: dict[int, object] = {}
    for g in gruppen or ():
        if g.klasse == "einzeln":
            continue
        for a in g.aufnahmen:
            in_gruppe[id(a)] = g

    eintraege: list[tuple] = []
    erledigt: set[int] = set()
    for aufnahme, _ in mit_ort:
        if id(aufnahme) in erledigt:
            continue
        s = in_serie.get(id(aufnahme))
        g = in_gruppe.get(id(aufnahme))
        if s is not None:
            # Eine von der KAMERA bezeugte Reihe hat Vorrang: sie steht fest,
            # und ueber sie muss niemand mehr urteilen.
            mitglieder = [_erstes_bild(m) for m in s.aufnahmen]
            eintraege.append((mitglieder[0], mitglieder))
            erledigt.update(id(m) for m in s.aufnahmen)
        elif g is not None:
            mitglieder = [_erstes_bild(m) for m in g.aufnahmen]
            art = "serie" if g.klasse == "kandidat" else "motiv"
            eintraege.append((mitglieder[0], mitglieder, art, _messbefund(g)))
            erledigt.update(id(m) for m in g.aufnahmen)
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
