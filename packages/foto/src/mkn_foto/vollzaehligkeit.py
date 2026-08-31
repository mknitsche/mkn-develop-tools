"""Die Abnahme eines Laufs: ist der Zielbaum vollstaendig und widerspruchsfrei?

**Warum dieses Modul existiert.** KT-1 vor dem Lauf ueber die Karwendeltage:
*"dabei ist sichergestellt, dass es vollstaendig ist und keine falschen anzahlen
gibt, oder das jpeg und raw keine paeaerchen mehr sind usw usw"*.

Ein Lauf, der "FERTIG" meldet, hat damit noch nichts belegt. Am 2026-08-30
meldete einer genau das nach 36 Sekunden -- 1.293 Aufnahmen, 0 Sidecars, 0
Modellaufrufe. Die Zahlen im Laufbericht stammen vom Lauf selbst und teilen
folglich seine blinden Flecken. Diese Pruefung sieht statt dessen auf die
Platte: sie vergleicht, was in der Quelle liegt, mit dem, was im Ziel liegt.

**Sie aendert nichts. Sie zaehlt.**

Sechs Fragen, und die erste hat einen Fallstrick, der eine naive Fassung
wertlos macht:

1. Ist jede Aufnahme der Quelle im Ziel wiederzufinden?
2. Ist ein Paar ein Paar geblieben?
3. Traegt jede Datei genau EINEN Metadaten-Traeger?
4. Liegt im Ziel etwas, das zu keiner Aufnahme gehoert?
5. Tragen alle Dateien einer Aufnahme denselben Namen?
6. Tragen beide Haelften eines Paares dieselben Stichworte?
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from mkn_foto import anreichern, inventar
from mkn_foto.modell import Aufnahme

SIDECAR = anreichern.SIDECAR

_ARCHIVNAME = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}_[^_]+_[^_]+_(?P<original>.+)$")
"""Zerlegt einen Zielnamen in seine Bestandteile und gibt den Originalnamen frei.

Die Notation lautet `<datum>_<zeit>_<kamera>_<typ>_<originalname>` und der
Originalname steht bewusst am ENDE (`namen.py`: *"damit eine umbenannte Datei zu
ihrem Kamera-Original zurueckfindet"*). Er darf selbst Unterstriche enthalten --
Nikon nennt ihre Dateien `D85_2560` --, deshalb ist der letzte Teil gierig und
nicht der fuenfte durch Trennen gewonnen.
"""


@dataclass
class Bericht:
    """Was die Pruefung gefunden hat. Zahlen und Namen, keine Bewertung."""

    aufnahmen_quelle: int = 0
    aufnahmen_ziel: int = 0

    fehlend: list[str] = field(default_factory=list)
    """In der Quelle, nicht im Ziel. Der schwerste Befund: hier ist Arbeit
    verloren gegangen."""

    zusaetzlich: list[str] = field(default_factory=list)
    """Im Ziel, nicht in der Quelle. Meist ein Rest aus einem frueheren Lauf."""

    zerrissen: list[str] = field(default_factory=list)
    """Eine Aufnahme, die im Ziel weniger Dateien hat als in der Quelle -- das
    Paar ist zerbrochen. KT-1s Direktive: *"die gepaarten bilder sind als paar zu
    behandeln"*. Einer Aufnahmezahl sieht man das nicht an."""

    doppelter_traeger: list[str] = field(default_factory=list)
    """Eine Datei, die ihre Angaben eingebettet UND daneben traegt. Spec
    Paragraf 10: nie beides fuer dieselbe Datei."""

    unerklaert: list[str] = field(default_factory=list)
    """Dateien im Zielbaum, die zu keiner Aufnahme gehoeren."""

    uneinheitlich: list[str] = field(default_factory=list)
    """Eine Aufnahme, deren Dateien verschiedene Namen tragen."""

    ungleich: list[str] = field(default_factory=list)
    """Ein Paar, dessen Haelften verschiedene Stichworte tragen.

    KT-1s Direktive: *"auch alle inhalte muessen bei jpeg und raw gleich sein"*.
    Das ist die Haelfte, die eine reine Dateizaehlung NICHT sieht -- gegen den
    Zielbaum vor dem Traeger-Fix, in dem 29 von 42 Sidecars ihre Stichworte
    doppelt trugen, meldete die erste Fassung dieser Pruefung `sauber=True`."""

    @property
    def befunde(self) -> list[str]:
        """Alle Beanstandungen mit ihrer Art -- fuer Bericht und Fehlermeldung."""
        gesammelt: list[str] = []
        for art, eintraege in (
            ("fehlend", self.fehlend),
            ("zusaetzlich", self.zusaetzlich),
            ("zerrissenes Paar", self.zerrissen),
            ("zwei Traeger", self.doppelter_traeger),
            ("unerklaert", self.unerklaert),
            ("uneinheitlicher Name", self.uneinheitlich),
            ("ungleiche Inhalte", self.ungleich),
        ):
            gesammelt += [f"{art}: {e}" for e in eintraege]
        return gesammelt

    @property
    def sauber(self) -> bool:
        return not self.befunde


def originalname(stamm: str) -> str:
    """Der Kamera-Name einer Datei — aus dem Archivnamen zurueckgewonnen.

    **Der Fallstrick, an dem eine naive Pruefung 100 % Verlust meldet.**
    Firsthand am Probelauf vom 2026-08-30: ein Vergleich ueber den Stamm meldete
    42 fehlende UND 42 zusaetzliche Aufnahmen bei einem fehlerfreien Lauf, weil
    der Stamm im Ziel ein anderer ist (`DSCF3877` gegen
    `2026-08-30_152700_XE5_std_DSCF3877`). Wer der Meldung glaubt, sucht einen
    Fehler, den es nicht gibt -- und wer sie abschaltet, verliert die Frage.

    Ein Name, der der Notation nicht folgt, ist bereits der Originalname; das
    ist der Normalfall auf der Quellseite.
    """
    treffer = _ARCHIVNAME.match(stamm)
    return treffer.group("original") if treffer else stamm


def _schluessel(a: Aufnahme) -> tuple[str, str, str]:
    """Was eine Aufnahme ueber das Umbenennen hinweg identifiziert."""
    return (f"{a.zeitpunkt:%Y-%m-%d %H:%M:%S}", a.kamera, originalname(a.stamm))


def pruefe(quelle: Path, ziel: Path) -> Bericht:
    """Vergleicht zwei Baeume und meldet, was nicht zusammenpasst."""
    aus_quelle = inventar.lies_baum(Path(quelle))
    aus_ziel = inventar.lies_baum(Path(ziel))
    bericht = Bericht(aufnahmen_quelle=len(aus_quelle), aufnahmen_ziel=len(aus_ziel))

    je_quelle = {_schluessel(a): a for a in aus_quelle}
    je_ziel = {_schluessel(a): a for a in aus_ziel}

    bericht.fehlend = sorted(f"{k[2]} ({k[0]})" for k in je_quelle.keys() - je_ziel.keys())
    bericht.zusaetzlich = sorted(f"{k[2]} ({k[0]})" for k in je_ziel.keys() - je_quelle.keys())

    for k in sorted(je_quelle.keys() & je_ziel.keys()):
        fehlt = set(je_quelle[k].dateien) - set(je_ziel[k].dateien)
        if fehlt:
            bericht.zerrissen.append(f"{k[2]}: {', '.join(sorted(fehlt))} fehlt im Ziel")

    # Sidecars, die schon in der QUELLE neben einem JPEG lagen, sind KT-1s
    # eigene Arbeit aus Capture One -- das Werkzeug hat sie nur mitkopiert, und
    # sie zu melden waere ein Befund ueber einen vorgefundenen Zustand. Im
    # Karwendel-Bestand sind es sechs, mit seinen Bewertungen darin.
    schon_in_quelle = {
        _schluessel(a)
        for a in aus_quelle
        for pfad in a.dateien.values()
        if anreichern.traeger(pfad)[1] and pfad.with_suffix(SIDECAR).exists()
    }

    for a in aus_ziel:
        if len({p.stem for p in a.dateien.values()}) > 1:
            bericht.uneinheitlich.append(
                f"{a.stamm}: {sorted({p.name for p in a.dateien.values()})}"
            )
        for pfad in a.dateien.values():
            _, eingebettet = anreichern.traeger(pfad)
            if (
                eingebettet
                and pfad.with_suffix(SIDECAR).exists()
                and not _hat_roh(a)
                and _schluessel(a) not in schon_in_quelle
            ):
                bericht.doppelter_traeger.append(pfad.name)

    bericht.ungleich = _ungleiche_paare(aus_ziel)
    bericht.unerklaert = sorted(_unerklaerte(Path(ziel), aus_ziel))
    return bericht


STICHWORTFELD = "HierarchicalSubject"
"""Das Feld, an dem sich Gleichheit entscheidet: dort steht alles, was das
Werkzeug schreibt -- Ort, Serie, Technik, Motive."""


def _ungleiche_paare(aufnahmen: list[Aufnahme]) -> list[str]:
    """Paare, deren Haelften verschiedene Stichworte tragen.

    Verglichen wird die MENGE, nicht die Reihenfolge: exiftool gibt Listen in
    Schreibreihenfolge zurueck, und die unterscheidet sich zwischen eingebettet
    und Sidecar regelmaessig, ohne dass inhaltlich etwas fehlt. Wer auf
    Reihenfolge prueft, meldet jedes Paar und wird nach zwei Laeufen ignoriert.
    """
    gemeldet: list[str] = []
    for a in aufnahmen:
        traeger = {}
        for pfad in a.dateien.values():
            ziel, _ = anreichern.traeger(pfad)
            if ziel.exists():
                traeger[pfad.suffix.upper()] = ziel
        if len(traeger) < 2:
            continue
        mengen = {e: _stichworte(z) for e, z in traeger.items()}
        erste = next(iter(mengen.values()))
        if any(m != erste for m in mengen.values()):
            unterschied = sorted(
                set().union(*mengen.values()) - set().intersection(*mengen.values())
            )
            gemeldet.append(
                f"{a.stamm}: {', '.join(unterschied) or 'gleiche Worte, andere Anzahl'}"
            )
    return gemeldet


def _stichworte(traeger: Path) -> frozenset[str]:
    """Die Stichworte einer Datei -- als MENGE, mit ihrer Vielfachheit.

    Ein doppeltes Stichwort ist ein Unterschied: genau daran erkennt man die
    Verdopplung, die KT-1s Direktive verletzte. Ein reines `set` haette sie
    verschluckt, weil beide Seiten dieselben WORTE tragen.
    """
    roh = subprocess.run(
        ["exiftool", "-q", "-json", f"-XMP-lr:{STICHWORTFELD}", str(traeger)],
        capture_output=True,
        check=False,
    ).stdout.decode("utf-8", "replace")
    if not roh.strip():
        return frozenset()
    try:
        daten = json.loads(roh)
    except json.JSONDecodeError:
        return frozenset()
    wert = daten[0].get(STICHWORTFELD) if daten else None
    werte = wert if isinstance(wert, list) else ([wert] if wert else [])
    zaehler: dict[str, int] = {}
    for w in werte:
        zaehler[str(w)] = zaehler.get(str(w), 0) + 1
    return frozenset(f"{w} (x{n})" if n > 1 else w for w, n in zaehler.items())


def _hat_roh(a: Aufnahme) -> bool:
    """Ob zu dieser Aufnahme eine RAW-Datei gehoert.

    Nur dann ist ein Sidecar neben ihrem JPEG kein Widerspruch: er gehoert dann
    zur RAW, und beide teilen sich nach dem Umbenennen denselben Namen.
    """
    return any(not anreichern.traeger(p)[1] for p in a.dateien.values())


def _unerklaerte(ziel: Path, aufnahmen: list[Aufnahme]) -> list[str]:
    """Dateien im Zielbaum, die zu keiner Aufnahme gehoeren.

    Sidecars und der Laufbericht sind erwartet; alles andere ist Wildwuchs --
    zum Beispiel die `.xmp_original`-Sicherungen, von denen nach einem Lauf
    einmal 1.228 zwischen den Bildern lagen.
    """
    bekannt = {p for a in aufnahmen for p in a.dateien.values()}
    bekannt |= {p.with_suffix(SIDECAR) for p in set(bekannt)}
    gefunden: list[str] = []
    for pfad in ziel.rglob("*"):
        if not pfad.is_file() or pfad.name.startswith("."):
            continue
        if pfad.suffix == ".md" or pfad in bekannt:
            continue
        gefunden.append(str(pfad.relative_to(ziel)))
    return gefunden
