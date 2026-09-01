"""Der Kommandozeilen-Einstieg — damit `pip install mkn-foto` ein Werkzeug ergibt.

Bis hierher war das Paket eine Bibliothek: jeder Lauf brauchte ein von Hand
geschriebenes Skript, das `sys.path` zurechtbiegt und `pipeline.fahre()` aufruft.
Fuer ein veroeffentlichtes Projekt ist das die groesste Luecke ueberhaupt.

**Die Optionsnamen sind deutsch, und zwar abgeleitet statt gewaehlt:** die
oeffentliche Schnittstelle des Pakets ist bereits deutsch — `konfig.json` traegt
`ziel`, `urheber`, `farben`, `schluessel_datei`. Wer diese Datei schreibt, erwartet
`--ziel`. Englisch ist allein die Dokumentation, nicht die Schnittstelle.

**Nichts wird geraten.** Fehlt das Ziel, bricht der Lauf ab, statt einen Ordner zu
erfinden: ein geratenes Ziel schreibt Dutzende Gigabyte an eine Stelle, die niemand
gesucht hat. Dieselbe Haltung wie in `konfig.lade`, das eine kaputte Konfiguration
laut macht, statt sie als „keine Konfiguration" zu behandeln.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from mkn_foto import konfig, pipeline

__all__ = ["baue_parser", "haupt"]


def baue_parser() -> argparse.ArgumentParser:
    """Die Optionen des echten Laufs — nicht mehr.

    Jede Option hier entspricht einem Argument, das die von Hand geschriebenen
    Laufskripte tatsaechlich gesetzt haben. Was dort nie vorkam, fehlt bewusst:
    eine Option, die niemand braucht, ist trotzdem fuer immer zu pflegen.
    """
    p = argparse.ArgumentParser(
        prog="mkn-foto",
        description=(
            "Liest einen Aufnahme-Baum, erkennt Serien, loest Orte aus einer "
            "GPS-Spur auf und schreibt beides in eine Kopie der Dateien."
        ),
        epilog=(
            "Die Quelle bleibt unberuehrt; geschrieben wird ausschliesslich unter "
            "--ziel. Ein zweiter Lauf ueber denselben Baum ueberspringt, was schon "
            "kopiert ist, und reichert es trotzdem an."
        ),
    )
    p.add_argument("quelle", type=Path, help="Ordner mit den Aufnahmen (bleibt unveraendert)")
    p.add_argument(
        "--ziel",
        type=Path,
        default=None,
        help="Zielbaum. Ohne diese Option gilt 'ziel' aus der Konfiguration.",
    )
    p.add_argument("--gpx", type=Path, default=None, help="GPS-Spur der Reise (.gpx)")
    p.add_argument("--bibliothek", type=Path, default=None, help="Fotos-Mediathek (.photoslibrary)")
    p.add_argument("--album", default=None, help="Album in der Mediathek, aus dem Orte kommen")
    p.add_argument("--notizen", type=Path, default=None, help="Ordner mit beantworteten Ortsfragen")
    p.add_argument(
        "--entscheidungen",
        type=Path,
        default=None,
        help="Ordner, in den die offenen Ortsfragen gelegt werden",
    )
    p.add_argument(
        "--probelauf",
        action="store_true",
        help="Alles rechnen, nichts schreiben — der Blick auf die Zahlen vorab.",
    )
    p.add_argument(
        "--konfig", type=Path, default=None, help="Andere Konfigurationsdatei als die uebliche"
    )
    return p


def _bericht(lauf, dauer_s: float) -> str:
    """Die Zahlen, die nach jedem Lauf zaehlen.

    Bewusst dieselben wie in den Laufskripten: ohne sie muesste der Mensch am Ende
    im Kopf nachrechnen, ob der Lauf getan hat, was er sollte.

    `lauf.geschrieben` darf `None` sein — die Pipeline kehrt bei leerer Quelle
    sofort zurueck und setzt es nie. Die erste Fassung griff blind darauf zu und
    zerlegte den ersten echten Probelauf, waehrend alle Tests gruen waren: die
    Test-Attrappe setzte das Feld immer.
    """
    zeilen = [
        "",
        f"=== LAUF FERTIG ({dauer_s / 60:.1f} min) ===",
        f"Aufnahmen        {len(lauf.aufnahmen)}",
        f"Spots            {len(lauf.spots)}  verortet {len(lauf.orte)}  offen {len(lauf.offen)}",
    ]
    if lauf.aufnahmen:
        anteil = lauf.belegt * 100 // len(lauf.aufnahmen)
        zeilen.append(f"Bilder verortet  {lauf.belegt} ({anteil} %)")
    g = lauf.geschrieben
    if g is None:
        zeilen.append("Dateien kopiert  0   (nichts zu schreiben)")
    else:
        zeilen.append(
            f"Dateien kopiert  {g.kopiert}   Sidecars {g.sidecars}   "
            f"uebersprungen {g.uebersprungen}"
        )
    return "\n".join(zeilen)


def haupt(argumente: Sequence[str] | None = None) -> int:
    """Fuehrt einen Lauf aus. Gibt den Exit-Code zurueck.

    **Der Rueckgabewert ist die eigentliche Zusicherung dieser Funktion.** Ein
    Werkzeug, das im Fehlerfall 0 meldet, laesst jede Automatisierung darueber auf
    einer Luege aufbauen — der Lauf lief nie, und der Aufrufer haelt ihn fuer
    erledigt. Darum endet hier JEDER Weg, der nicht bis zum Bericht kommt, mit
    einem Wert ungleich 0 und einer Zeile auf stderr.
    """
    args = baue_parser().parse_args(argumente)

    try:
        einstellungen = konfig.lade(args.konfig)
    except konfig.KonfigFehler as fehler:
        print(f"mkn-foto: {fehler}", file=sys.stderr)
        return 2

    quelle = args.quelle.expanduser()
    if not quelle.exists():
        print(f"mkn-foto: Quelle gibt es nicht: {quelle}", file=sys.stderr)
        return 2
    if not quelle.is_dir():
        print(f"mkn-foto: Quelle muss ein Ordner sein, nicht eine Datei: {quelle}", file=sys.stderr)
        return 2

    ziel = args.ziel.expanduser() if args.ziel else einstellungen.ziel
    if ziel is None:
        print(
            "mkn-foto: kein ziel. Entweder --ziel angeben oder 'ziel' in die "
            "Konfiguration schreiben. Geraten wird es nicht: ein falsches Ziel "
            "verteilt Dutzende Gigabyte an eine Stelle, die niemand sucht.",
            file=sys.stderr,
        )
        return 2

    try:
        anker = pipeline.anker_sammeln(
            gpx_datei=args.gpx,
            bibliothek=args.bibliothek,
            album=args.album,
            notiz_ordner=args.notizen,
        )
        print(f"Anker: {len(anker)}", flush=True)

        beginn = time.time()
        lauf = pipeline.fahre(
            quelle,
            ziel,
            anker=anker,
            # Die Notizen werden ZWEIMAL gebraucht: beim Sammeln der Anker und beim
            # Fahren. Wer sie nur einem der beiden gibt, legt entweder bereits
            # beantwortete Orte erneut vor oder verliert die Anker daraus.
            notiz_ordner=args.notizen,
            entscheidungen=args.entscheidungen,
            schreiben_aktiv=not args.probelauf,
        )
    except Exception as fehler:
        # Absichtlich breit: welche Ausnahme aus der Tiefe kommt (fehlendes
        # exiftool, unlesbare GPX, volle Platte), ist fuer den Aufrufer zweitrangig.
        # Entscheidend ist, dass sie SICHTBAR wird und der Exit-Code sie traegt —
        # ein Traceback auf der Konsole waere zwar laut, aber der Rueckgabewert
        # bliebe dem Zufall des Interpreters ueberlassen.
        print(f"mkn-foto: Lauf abgebrochen: {fehler}", file=sys.stderr)
        return 1

    if not lauf.aufnahmen:
        # Kein Fehler, sondern eine Auskunft — und meistens ein vertippter Pfad.
        # Ohne diese Zeile sieht ein leerer Lauf aus wie ein Erfolg ueber unbekannt
        # vielen Bildern.
        print(f"mkn-foto: keine Aufnahmen unter {quelle} gefunden — nichts zu tun.")
        return 0

    print(_bericht(lauf, time.time() - beginn))
    if args.probelauf:
        print("\n(Probelauf — es wurde nichts geschrieben.)")
    return 0


if __name__ == "__main__":  # pragma: no cover — vom Konsolenskript nicht benutzt
    raise SystemExit(haupt())
