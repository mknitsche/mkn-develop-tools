"""Der lokale Sprecher: ein Block je Stueck, Ton-Schluessel wie vor dem Umbau, Startprobe.

Der Arbeiter ist der Schein-Arbeiter (echter Kindprozess, gleiches Protokoll); Chatterbox
braucht kein Test.

`mkn_audio.sprecher` und `WegKonfig` entstehen erst mit Plan B2/B1: sie werden im Test
importiert (`_modul`), damit die Datei bis dahin gesammelt wird und jeder Test einzeln rot ist
statt die ganze Suite an einem Sammelfehler anzuhalten.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

from mkn_audio.arbeiter_client import Arbeiter
from mkn_audio.stimmen import Stimme
from mkn_audio.typen import Mp4Fehler, Stueck

SCHEIN = Path(__file__).with_name("schein_arbeiter.py")

# Erfundene Vorlage: der Ton-Schluessel haengt an ihren Bytes, nicht an ihrem Pfad.
VORLAGE_BYTES = b"erfundene Vorlage fuer den Ton-Schluessel"
SATZ = "Ein erfundener Satz über den Garten am Fluss."


def _modul() -> ModuleType:
    import mkn_audio.sprecher as modul

    return modul


def _lokal(arbeiter: Arbeiter):
    from mkn_audio.stimmen import WegKonfig

    return _modul().SprecherLokal(arbeiter, WegKonfig(modell="chatterbox-multilingual"))


class Zaehler(Arbeiter):
    """Der Schein-Arbeiter, der festhaelt, mit welcher Vorlage er was gesprochen hat."""

    def __init__(self) -> None:
        super().__init__(Path(sys.executable), skript=SCHEIN)
        self.gesprochen: list[tuple[str, str]] = []  # (Text, Dateiname der Vorlage)

    def sprich(self, text, *, ziel, **kw):
        self.gesprochen.append((text, Path(kw["vorlage"]).name))
        return super().sprich(text, ziel=ziel, **kw)


@pytest.fixture
def stimme(tmp_path) -> Stimme:
    """Fixture-Stimme mit festen Reglern; die Vorlage liegt mit erfundenen Bytes daneben."""
    vorlage = tmp_path / "vorlagen" / "test-lokal.wav"
    vorlage.parent.mkdir()
    vorlage.write_bytes(VORLAGE_BYTES)
    return Stimme(
        name="test-lokal",
        beschreibung="Teststimme",
        vorlage=vorlage,
        sprache="de",
        exaggeration=0.45,
        cfg_weight=0.45,
        temperature=0.75,
        tempo=0.9,
        stand="probe",
    )


@pytest.fixture
def arbeiter():
    with Zaehler() as a:
        yield a


def test_sprecher_lokal_ein_block_je_stueck(arbeiter):
    """local buendelt nicht: jedes Stueck ist ein Block mit Text, Kapitel und Rolle."""
    stuecke = [
        Stueck(kapitel=0, absatz=0, nr=1, text="Ein Kapitel", art="titel", ansage=True),
        Stueck(kapitel=0, absatz=1, nr=2, text=SATZ, art="text"),
        Stueck(kapitel=1, absatz=0, nr=3, text="Noch ein erfundener Satz.", art="text"),
    ]

    bloecke = _lokal(arbeiter).buendle(stuecke)

    assert [b.stueck_nrs for b in bloecke] == [(1,), (2,), (3,)]
    assert [b.text for b in bloecke] == [s.text for s in stuecke]
    assert [b.kapitel for b in bloecke] == [0, 0, 1]
    assert [b.ansage for b in bloecke] == [True, False, False]
    assert len({b.nr for b in bloecke}) == 3  # jeder Block hat seinen eigenen Schluessel-Platz


def test_ton_schluessel_local_unveraendert(arbeiter, stimme):
    """Ein halb gesprochenes Buch laeuft nach dem Umbau weiter (Review Focus 6).

    Erwartungswert VOR dem Umbau mit der Formel aus `lauf.py` (Z. 501-511, Stand ac8e3cc24)
    berechnet und gegen die Schluessel eines echten Laufs mit diesem Stand gegengeprueft:
    fingerabdruck("ton", text, modell, sprache, vorlage_hash, exaggeration, cfg_weight,
    temperature, pausen_kuerzen)[:16] mit
      text           = SATZ ("Ein erfundener Satz über den Garten am Fluss.")
      modell         = "chatterbox-multilingual"
      sprache        = "de"
      vorlage_hash   = sha256(VORLAGE_BYTES)
                     = 7a5948ccb099796eba76cf0c1a07d55ccad5e5002f917d3afd3db137a64157f1
      exaggeration   = 0.45, cfg_weight = 0.45, temperature = 0.75
      pausen_kuerzen = True (Vorgabe)
    Aendert sich der Wert, spricht jedes lokal angefangene Buch von vorn.
    """
    block = _modul().Block(nr=1, stueck_nrs=(1,), text=SATZ, kapitel=0, ansage=False)

    assert _lokal(arbeiter).ton_schluessel(block, stimme) == "fed08d3d73361af4"


def test_startprobe_lokal_fehlende_vorlage_bricht(arbeiter, stimme, tmp_path):
    """Die Vorlage wird VOR dem Sprechen geprueft; fehlt sie, bricht die Probe mit dem Namen."""
    ohne = Stimme(
        name="ohne-vorlage",
        beschreibung="Teststimme",
        vorlage=tmp_path / "vorlagen" / "gibtsnicht.wav",
        exaggeration=0.45,
        cfg_weight=0.45,
        temperature=0.75,
        tempo=0.9,
        stand="probe",
    )
    sprecher = _lokal(arbeiter)

    sprecher.startprobe([stimme])  # Gegenprobe: mit Vorlage spricht die Probe einmal
    assert [v for _, v in arbeiter.gesprochen] == ["test-lokal.wav"]

    with pytest.raises(Mp4Fehler, match="ohne-vorlage"):
        sprecher.startprobe([stimme, ohne])
    assert len(arbeiter.gesprochen) == 1  # nichts gesprochen, bevor alle Vorlagen geprueft sind
