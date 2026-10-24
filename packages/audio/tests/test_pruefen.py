"""Pruefen: Verdacht aus Akustik, Spracherkennung nur dort -- und nie ein Abbruch.

Die Stille-Messung laeuft mit dem echten ffmpeg auf echten WAV-Dateien (das ist das
Werkzeug, das der Lauf benutzt); der Arbeiter ist der Schein-Arbeiter, und wo ein
anderes Ergebnis des Hoerens gebraucht wird, ersetzt der Test `arbeiter.hoere`.
"""

from __future__ import annotations

import math
import random
import sys
import wave
from array import array
from pathlib import Path

import pytest

from mkn_audio.arbeiter_client import Arbeiter, ArbeiterFehler
from mkn_audio.pruefen import Befund, Pruefung, pruefe
from mkn_audio.stimmen import Stimme
from mkn_audio.typen import Mp4Fehler, Stueck

SCHEIN = Path(__file__).with_name("schein_arbeiter.py")
RATE = 24_000
# Genau 70 Zeichen: erwartet 5,0 s (70 / 14).
SATZ = "Der alte Hund lief schnell durch den dunklen Wald und bellte laut vor Freude."[:70]


def schreibe_wav(pfad: Path, *teile: tuple[float, bool]) -> None:
    """Eine WAV aus Abschnitten `(Sekunden, Ton?)`: Ton ist ein Sinus, sonst Stille."""
    daten = array("h")
    for sekunden, mit_ton in teile:
        n = int(sekunden * RATE)
        if mit_ton:
            daten.extend(int(8000 * math.sin(2 * math.pi * 220 * i / RATE)) for i in range(n))
        else:
            daten.extend([0] * n)
    with wave.open(str(pfad), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(daten.tobytes())


def stueck(nr: int, text: str = SATZ, art: str = "text") -> Stueck:
    return Stueck(kapitel=0, absatz=nr, nr=nr, text=text, art=art)  # type: ignore[arg-type]


def antwort(text: str, *, dauer: float | None = None, zu_kurz: bool = False) -> dict:
    return {
        "dauer": len(text) / 14 if dauer is None else dauer,
        "sprechrate": 14.0,
        "versuche": 1,
        "zu_kurz": zu_kurz,
    }


@pytest.fixture
def stimme(tmp_path) -> Stimme:
    return Stimme(
        name="test",
        beschreibung="Teststimme",
        vorlage=tmp_path / "vorlage.wav",
        exaggeration=0.45,
        cfg_weight=0.45,
        temperature=0.75,
        tempo=0.9,
        stand="probe",
    )


@pytest.fixture
def arbeiter():
    with Arbeiter(Path(sys.executable), skript=SCHEIN) as a:
        yield a


class Gehoert:
    """Ersatz fuer `arbeiter.hoere`: liefert vorgegebene Texte und zaehlt die Aufrufe."""

    def __init__(self, *texte: str, sonst: str | None = None) -> None:
        self.texte = list(texte)
        self.sonst = sonst
        self.aufrufe: list[tuple[Path, str]] = []

    def __call__(self, wav: Path, sprache: str) -> str:
        self.aufrufe.append((wav, sprache))
        if self.texte:
            return self.texte.pop(0)
        if self.sonst is None:
            raise AssertionError("hoere wurde unerwartet gerufen")
        return self.sonst


def beobachte_sprich(arbeiter: Arbeiter, monkeypatch) -> list[dict]:
    """Schaltet vor `arbeiter.sprich` einen Zaehler, der die Aufrufe festhaelt."""
    aufrufe: list[dict] = []
    echt = arbeiter.sprich

    def sprich(text, **kw):
        aufrufe.append({"text": text, **kw})
        return echt(text, **kw)

    monkeypatch.setattr(arbeiter, "sprich", sprich)
    return aufrufe


def lauf(stuecke, ton, arbeiter, stimme, tmp_path, *, stichprobe=0.0, seed=1):
    return pruefe(
        stuecke,
        ton,
        arbeiter=arbeiter,
        sprache="de",
        stimme=stimme,
        wav_pfad=lambda s: tmp_path / f"{s.nr}.wav",
        stichprobe=stichprobe,
        zufall=random.Random(seed),
    )


def test_zu_kurz_wird_gehoert_und_neu_gesprochen(arbeiter, stimme, tmp_path, monkeypatch):
    s = stueck(1)
    schreibe_wav(tmp_path / "1.wav", (5.0, True))
    sprich = beobachte_sprich(arbeiter, monkeypatch)
    # Beim ersten Hoeren fehlt fast alles, nach dem Neusprechen stimmt es.
    monkeypatch.setattr(arbeiter, "hoere", Gehoert("der alte hund", SATZ))

    ergebnis = lauf([s], {1: antwort(SATZ, zu_kurz=True)}, arbeiter, stimme, tmp_path)

    assert ergebnis == Pruefung(
        auffaellig=(), gehoert=1, neu_gesprochen=1, neuer_ton=ergebnis.neuer_ton
    )
    # Neu gesprochen mit den Reglern der Stimme, ins selbe WAV.
    assert len(sprich) == 1
    assert sprich[0]["text"] == SATZ
    assert sprich[0]["ziel"] == tmp_path / "1.wav"
    assert sprich[0]["vorlage"] == stimme.vorlage
    assert sprich[0]["exaggeration"] == 0.45
    assert sprich[0]["pausen_kuerzen"] is True
    # Wer die Aufnahme weiterbenutzt, bekommt die Messwerte des neuen Sprechens.
    assert ergebnis.neuer_ton[1]["dauer"] == pytest.approx(len(SATZ) / 14)


def test_stichprobe_fuenf_prozent(arbeiter, stimme, tmp_path, monkeypatch):
    stuecke = []
    ton = {}
    for nr in range(100):
        text = f"Satz Nummer {nr + 100} ist da."  # 23 Zeichen, gleich lang, ohne fuehrende Null
        stuecke.append(stueck(nr, text))
        ton[nr] = antwort(text)
        schreibe_wav(tmp_path / f"{nr}.wav", (len(text) / 14, True))
    texte = {tmp_path / f"{s.nr}.wav": s.text for s in stuecke}
    gehoert = []

    def hoere(wav, sprache):
        gehoert.append(wav)
        return texte[wav]

    monkeypatch.setattr(arbeiter, "hoere", hoere)

    ergebnis = lauf(stuecke, ton, arbeiter, stimme, tmp_path, stichprobe=0.05, seed=42)

    assert ergebnis.gehoert == 5
    assert len(set(gehoert)) == 5
    assert ergebnis.neu_gesprochen == 0
    assert ergebnis.auffaellig == ()
    # Derselbe Seed waehlt dieselben Stuecke, ein anderer andere.
    gehoert.clear()
    lauf(stuecke, ton, arbeiter, stimme, tmp_path, stichprobe=0.05, seed=42)
    erste = set(gehoert)
    gehoert.clear()
    lauf(stuecke, ton, arbeiter, stimme, tmp_path, stichprobe=0.05, seed=7)
    assert set(gehoert) != erste


def test_ohne_verdacht_und_ohne_stichprobe_wird_nichts_gehoert(
    arbeiter, stimme, tmp_path, monkeypatch
):
    schreibe_wav(tmp_path / "1.wav", (5.0, True))
    monkeypatch.setattr(arbeiter, "hoere", Gehoert())  # jeder Aufruf waere ein Fehler
    ergebnis = lauf([stueck(1)], {1: antwort(SATZ)}, arbeiter, stimme, tmp_path)
    assert (ergebnis.gehoert, ergebnis.neu_gesprochen, ergebnis.auffaellig) == (0, 0, ())


def test_bleibt_auffaellig_landet_im_bericht(arbeiter, stimme, tmp_path, monkeypatch):
    schreibe_wav(tmp_path / "1.wav", (5.0, True))
    sprich = beobachte_sprich(arbeiter, monkeypatch)
    gehoert = Gehoert(sonst="voellig anderer text")
    monkeypatch.setattr(arbeiter, "hoere", gehoert)

    ergebnis = lauf([stueck(1)], {1: antwort(SATZ, zu_kurz=True)}, arbeiter, stimme, tmp_path)

    # Einmal neu sprechen, nie zweimal; danach Befund statt Abbruch.
    assert len(sprich) == 1
    assert len(gehoert.aufrufe) == 2
    assert ergebnis.neu_gesprochen == 1
    assert ergebnis.gehoert == 1
    (befund,) = ergebnis.auffaellig
    assert isinstance(befund, Befund)
    assert befund.stueck_nr == 1
    assert "Wortfehlerrate" in befund.grund
    assert "nach erneutem Sprechen" in befund.grund
    assert "Arbeiter meldet zu kurz" in befund.grund
    assert befund.zeit_s is None


@pytest.mark.parametrize(
    ("dauer", "gehoert"),
    [(2.74, True), (2.76, False), (12.4, False), (12.6, True)],
)
def test_dauer_grenzen_55_und_250_prozent(arbeiter, stimme, tmp_path, monkeypatch, dauer, gehoert):
    # erwartet 5,0 s: Verdacht unter 2,75 s und ueber 12,5 s.
    schreibe_wav(tmp_path / "1.wav", (5.0, True))
    hoeren = Gehoert(sonst=SATZ)
    monkeypatch.setattr(arbeiter, "hoere", hoeren)
    ergebnis = lauf([stueck(1)], {1: antwort(SATZ, dauer=dauer)}, arbeiter, stimme, tmp_path)
    assert (ergebnis.gehoert == 1) is gehoert


def test_stille_ueber_2_5_s_ist_verdacht_und_gibt_zeitstempel(
    arbeiter, stimme, tmp_path, monkeypatch
):
    # 1 s Ton, 3 s Stille, 1 s Ton: Dauer passt, nur die Stille faellt auf.
    schreibe_wav(tmp_path / "1.wav", (1.0, True), (3.0, False), (1.0, True))
    monkeypatch.setattr(arbeiter, "hoere", Gehoert(sonst="nichts passendes"))
    # Das Neusprechen soll dieselbe Aufnahme hinterlassen (der Schein-Arbeiter braeuchte
    # sonst eine neue, stillefreie): so bleibt die Stille auch im Endstand.
    monkeypatch.setattr(arbeiter, "sprich", lambda text, **kw: antwort(text))

    ergebnis = lauf([stueck(1)], {1: antwort(SATZ)}, arbeiter, stimme, tmp_path)

    (befund,) = ergebnis.auffaellig
    assert "Stille" in befund.grund
    assert befund.zeit_s is not None
    assert befund.zeit_s == pytest.approx(1.0, abs=0.1)


def test_neu_gesprochen_ohne_stille_hat_keinen_zeitstempel(arbeiter, stimme, tmp_path, monkeypatch):
    # Die alte Stille steht im Anlass, aber die neue Aufnahme hat keine mehr: der
    # Zeitstempel einer Stelle, die es nicht mehr gibt, waere falsch.
    schreibe_wav(tmp_path / "1.wav", (1.0, True), (3.0, False), (1.0, True))
    monkeypatch.setattr(arbeiter, "hoere", Gehoert(sonst="nichts passendes"))
    ergebnis = lauf([stueck(1)], {1: antwort(SATZ)}, arbeiter, stimme, tmp_path)
    (befund,) = ergebnis.auffaellig
    assert "Stille" in befund.grund
    assert befund.zeit_s is None


def test_kurze_stille_ist_kein_verdacht(arbeiter, stimme, tmp_path, monkeypatch):
    schreibe_wav(tmp_path / "1.wav", (1.5, True), (2.0, False), (1.5, True))
    monkeypatch.setattr(arbeiter, "hoere", Gehoert())  # jeder Aufruf waere ein Fehler
    ergebnis = lauf([stueck(1)], {1: antwort(SATZ)}, arbeiter, stimme, tmp_path)
    assert ergebnis.gehoert == 0


def test_wortfehlerrate_ignoriert_gross_klein_und_satzzeichen(
    arbeiter, stimme, tmp_path, monkeypatch
):
    schreibe_wav(tmp_path / "1.wav", (5.0, True))
    sprich = beobachte_sprich(arbeiter, monkeypatch)
    monkeypatch.setattr(arbeiter, "hoere", Gehoert(SATZ.upper().replace(" ", ", ")))
    ergebnis = lauf([stueck(1)], {1: antwort(SATZ, zu_kurz=True)}, arbeiter, stimme, tmp_path)
    assert sprich == []
    assert ergebnis.neu_gesprochen == 0
    assert ergebnis.auffaellig == ()


@pytest.mark.parametrize(("falsch", "neu"), [(3, False), (4, True)])
def test_wortfehlerrate_grenze_30_prozent(arbeiter, stimme, tmp_path, monkeypatch, falsch, neu):
    # Zehn Woerter: drei falsche = 30 % (noch gut), vier = 40 % (neu sprechen).
    text = "eins zwei drei vier fuenf sechs sieben acht neun zehn"
    woerter = text.split()
    gehoert = woerter[:-falsch] + ["xx"] * falsch
    schreibe_wav(tmp_path / "1.wav", (len(text) / 14, True))
    sprich = beobachte_sprich(arbeiter, monkeypatch)
    monkeypatch.setattr(arbeiter, "hoere", Gehoert(" ".join(gehoert), text))
    s = stueck(1, text)
    ergebnis = lauf([s], {1: antwort(text, zu_kurz=True)}, arbeiter, stimme, tmp_path)
    assert (len(sprich) == 1) is neu
    assert ergebnis.auffaellig == ()


def test_wortfehlerrate_zaehlt_ausgefallene_und_eingefuegte_woerter(
    arbeiter, stimme, tmp_path, monkeypatch
):
    text = "eins zwei drei vier"
    schreibe_wav(tmp_path / "1.wav", (len(text) / 14, True))
    sprich = beobachte_sprich(arbeiter, monkeypatch)
    # Zwei Woerter fehlen: 2 von 4 = 50 %.
    monkeypatch.setattr(arbeiter, "hoere", Gehoert("eins zwei", text))
    lauf([stueck(1, text)], {1: antwort(text, zu_kurz=True)}, arbeiter, stimme, tmp_path)
    assert len(sprich) == 1


def test_kurzer_titel_wird_nicht_nach_wortfehlerrate_beurteilt(
    arbeiter, stimme, tmp_path, monkeypatch
):
    titel = stueck(1, "Kapitel eins", art="titel")
    schreibe_wav(tmp_path / "1.wav", (1.0, True))
    sprich = beobachte_sprich(arbeiter, monkeypatch)
    monkeypatch.setattr(arbeiter, "hoere", Gehoert())  # kein Hoeren, kein Urteil
    ergebnis = lauf(
        [titel], {1: antwort(titel.text, zu_kurz=True)}, arbeiter, stimme, tmp_path, stichprobe=1.0
    )
    assert sprich == []
    assert ergebnis == Pruefung(auffaellig=(), gehoert=0, neu_gesprochen=0, neuer_ton={})


def test_langer_titel_wird_beurteilt(arbeiter, stimme, tmp_path, monkeypatch):
    titel = stueck(1, "Das erste Kapitel der Reise", art="titel")
    schreibe_wav(tmp_path / "1.wav", (2.0, True))
    monkeypatch.setattr(arbeiter, "hoere", Gehoert(sonst="ganz anders"))
    ergebnis = lauf([titel], {1: antwort(titel.text, zu_kurz=True)}, arbeiter, stimme, tmp_path)
    assert len(ergebnis.auffaellig) == 1


def test_hoeren_scheitert_befund_statt_abbruch(arbeiter, stimme, tmp_path, monkeypatch):
    """Whisper faellt aus: das Stueck ist nicht beurteilt, das steht im Bericht -- kein Abbruch."""
    stuecke = [stueck(1), stueck(2)]
    for s in stuecke:
        schreibe_wav(tmp_path / f"{s.nr}.wav", (5.0, True))

    def hoere(wav, sprache):
        if wav.name == "1.wav":
            raise ArbeiterFehler("Whisper kaputt", "Zeitgrenze")
        return SATZ

    monkeypatch.setattr(arbeiter, "hoere", hoere)
    ton = {1: antwort(SATZ, zu_kurz=True), 2: antwort(SATZ, zu_kurz=True)}
    ergebnis = lauf(stuecke, ton, arbeiter, stimme, tmp_path)

    (befund,) = ergebnis.auffaellig
    assert befund.stueck_nr == 1
    assert befund.grund.startswith("nicht gehört (Zeitgrenze)")
    assert "Arbeiter meldet zu kurz" in befund.grund
    # Das nicht beurteilte Stueck zaehlt nicht als gehoert; das zweite ist ganz normal geprueft.
    assert ergebnis.gehoert == 1
    assert ergebnis.neu_gesprochen == 0


def test_hoeren_scheitert_nach_dem_neusprechen_befund(arbeiter, stimme, tmp_path, monkeypatch):
    schreibe_wav(tmp_path / "1.wav", (5.0, True))
    aufrufe = []

    def hoere(wav, sprache):
        aufrufe.append(wav)
        if len(aufrufe) == 1:
            return "voellig anderer text"
        raise ArbeiterFehler("Whisper kaputt", "Tod")

    monkeypatch.setattr(arbeiter, "hoere", hoere)
    ergebnis = lauf([stueck(1)], {1: antwort(SATZ, zu_kurz=True)}, arbeiter, stimme, tmp_path)

    (befund,) = ergebnis.auffaellig
    assert befund.grund.startswith("nicht gehört (Tod) nach erneutem Sprechen")
    assert ergebnis.neu_gesprochen == 1
    assert 1 in ergebnis.neuer_ton  # das Neusprechen gelang, sein Ton gilt


def test_neusprechen_scheitert_alter_ton_bleibt(arbeiter, stimme, tmp_path, monkeypatch):
    """Das Neusprechen faellt aus (nach EINEM neuen Versuch): alter Ton, Befund, kein Abbruch."""
    schreibe_wav(tmp_path / "1.wav", (5.0, True))
    vorher = (tmp_path / "1.wav").read_bytes()
    versuche = []

    def sprich(text, **kw):
        versuche.append(text)
        raise ArbeiterFehler("Speicher voll", "Speicher")

    monkeypatch.setattr(arbeiter, "sprich", sprich)
    gehoert = Gehoert("voellig anderer text")
    monkeypatch.setattr(arbeiter, "hoere", gehoert)

    ergebnis = lauf([stueck(1)], {1: antwort(SATZ, zu_kurz=True)}, arbeiter, stimme, tmp_path)

    assert len(versuche) == 2  # derselbe Weg wie im Lauf: ein neuer Versuch, dann Schluss
    assert len(gehoert.aufrufe) == 1  # der alte Ton wird nicht noch einmal beurteilt
    assert ergebnis.neuer_ton == {}
    assert ergebnis.neu_gesprochen == 0
    assert (tmp_path / "1.wav").read_bytes() == vorher
    (befund,) = ergebnis.auffaellig
    assert befund.grund.startswith("nicht neu gesprochen (Speicher)")
    assert "Wortfehlerrate" in befund.grund and "Arbeiter meldet zu kurz" in befund.grund


def test_neusprechen_gelingt_beim_zweiten_versuch(arbeiter, stimme, tmp_path, monkeypatch):
    schreibe_wav(tmp_path / "1.wav", (5.0, True))
    echt = arbeiter.sprich
    versuche = []

    def sprich(text, **kw):
        versuche.append(text)
        if len(versuche) == 1:
            raise ArbeiterFehler("Tod", "Tod")
        return echt(text, **kw)

    monkeypatch.setattr(arbeiter, "sprich", sprich)
    monkeypatch.setattr(arbeiter, "hoere", Gehoert("voellig anderer text", SATZ))
    ergebnis = lauf([stueck(1)], {1: antwort(SATZ, zu_kurz=True)}, arbeiter, stimme, tmp_path)
    assert len(versuche) == 2
    assert ergebnis.auffaellig == () and ergebnis.neu_gesprochen == 1


def test_fehlende_messwerte_brechen_laut(arbeiter, stimme, tmp_path):
    schreibe_wav(tmp_path / "1.wav", (5.0, True))
    with pytest.raises(Mp4Fehler, match="1"):
        lauf([stueck(1)], {}, arbeiter, stimme, tmp_path)


def test_fehlende_aufnahme_bricht_laut(arbeiter, stimme, tmp_path):
    # Keine WAV angelegt: ffmpeg scheitert, und das darf nicht wie "keine Stille" aussehen.
    with pytest.raises(Mp4Fehler, match="ffmpeg"):
        lauf([stueck(1)], {1: antwort(SATZ)}, arbeiter, stimme, tmp_path)


def test_mehrere_befunde_kein_abbruch(arbeiter, stimme, tmp_path, monkeypatch):
    stuecke = [stueck(1), stueck(2)]
    for s in stuecke:
        schreibe_wav(tmp_path / f"{s.nr}.wav", (5.0, True))
    monkeypatch.setattr(arbeiter, "hoere", Gehoert(sonst="falsch"))
    ton = {1: antwort(SATZ, zu_kurz=True), 2: antwort(SATZ, zu_kurz=True)}
    ergebnis = lauf(stuecke, ton, arbeiter, stimme, tmp_path)
    assert [b.stueck_nr for b in ergebnis.auffaellig] == [1, 2]
    assert ergebnis.gehoert == 2
    assert ergebnis.neu_gesprochen == 2


def test_ziffern_in_der_abschrift_zaehlen_nicht_als_fehler(arbeiter, stimme, tmp_path, monkeypatch):
    """Whisper schreibt "1990" und "3,5", der Hoertext "neunzehnhundertneunzig" und
    "drei Komma fuenf": das ist dieselbe Aussage und darf weder neu gesprochen werden
    noch als Befund im Bericht stehen."""
    text = "Im Jahr neunzehnhundertneunzig stieg die Quote um drei Komma fünf Prozent an."
    schreibe_wav(tmp_path / "1.wav", (len(text) / 14, True))
    sprich = beobachte_sprich(arbeiter, monkeypatch)
    gehoert = Gehoert("Im Jahr 1990 stieg die Quote um 3,5 Prozent an.")
    monkeypatch.setattr(arbeiter, "hoere", gehoert)

    ergebnis = lauf([stueck(1, text)], {1: antwort(text, zu_kurz=True)}, arbeiter, stimme, tmp_path)

    assert ergebnis.gehoert == 1
    assert ergebnis.neu_gesprochen == 0
    assert ergebnis.auffaellig == ()
    assert sprich == []
    assert len(gehoert.aufrufe) == 1


def test_fremde_sprache_wird_nicht_nach_deutschen_regeln_ausgeschrieben(
    arbeiter, stimme, tmp_path, monkeypatch
):
    """Englisch bleibt, wie es ist: "1990" im Soll und in der Abschrift sind gleich, und
    deutsche Zahlwoerter wuerden die Abschrift erst verfaelschen."""
    text = "In 1990 the rate rose by 3 percent and kept on rising quickly."
    schreibe_wav(tmp_path / "1.wav", (len(text) / 14, True))
    monkeypatch.setattr(arbeiter, "hoere", Gehoert(text))

    ergebnis = pruefe(
        [stueck(1, text)],
        {1: antwort(text, zu_kurz=True)},
        arbeiter=arbeiter,
        sprache="en",
        stimme=stimme,
        wav_pfad=lambda s: tmp_path / f"{s.nr}.wav",
        zufall=random.Random(1),
    )

    assert (ergebnis.gehoert, ergebnis.neu_gesprochen, ergebnis.auffaellig) == (1, 0, ())
