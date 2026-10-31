"""Der Gemini-Sprecher: Anfrage, Antwort, Format, Buendeln, Startprobe, Fehlerklassen.

Kein Test braucht Netz oder Schluessel: der Transport ist `schein_google.ScheinGoogle`, der
jeden Rumpf aufzeichnet. Die Zusicherungen an die Anfrage haengen am GESEHENEN Rumpf (Spec
14.1: "der Transport sieht den Rumpf"), nicht an `baue_rumpf` allein. Wartezeiten laufen
ueber einen eingespeisten `schlaf`, der nur mitschreibt. `mkn_audio.gemini` entsteht mit
Plan C1; der Import steht darum in den Tests, damit die Datei bis dahin gesammelt wird.
"""

from __future__ import annotations

import io
import json
import wave
from pathlib import Path

import pytest
from mkn_kern import anfrage

from mkn_audio.arbeitsverzeichnis import fingerabdruck
from mkn_audio.sprecher import Auftrag, Block, SprecherFehler
from mkn_audio.stimmen import WegKonfig
from mkn_audio.typen import Mp4Fehler, Stueck
from schein_google import (
    MODELL,
    PCM_MIME,
    ScheinGoogle,
    Uhr,
    audio_antwort,
    fehler,
    gemini_stimme,
    limit,
    ohne_audio,
    pcm,
    stimme_von,
    text_von,
    wav_bytes,
)

SCHLUESSEL = "nur-ein-test"
SATZ = "Der Gärtner gießt am Morgen die Rosen, und die Amsel singt im hohen Kirschbaum."


def sprecher(schein: ScheinGoogle, *, schlaf=None, **kw):
    """Ein `SprecherGemini` am Schein; `schlaf` schreibt ohne Angabe nur mit."""
    from mkn_audio.gemini import SprecherGemini

    konfig = kw.pop("konfig", WegKonfig(modell=MODELL))
    return SprecherGemini(
        schluessel=SCHLUESSEL,
        konfig=konfig,
        transport=schein,
        schlaf=schlaf if schlaf is not None else (lambda s: None),
        **kw,
    )


def block(text: str = SATZ, nr: int = 1, *, kapitel: int = 0, ansage: bool = False) -> Block:
    return Block(nr=nr, stueck_nrs=(nr,), text=text, kapitel=kapitel, ansage=ansage)


def wav_info(pfad: Path) -> tuple[int, int, int, int]:
    """(Kanaele, Breite in Bytes, Rate, Frames)."""
    with wave.open(str(pfad), "rb") as w:
        return w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()


def erste_samples(pfad: Path, n: int = 32) -> list[int]:
    with wave.open(str(pfad), "rb") as w:
        roh = w.readframes(n)
    return [int.from_bytes(roh[i : i + 2], "little", signed=True) for i in range(0, len(roh), 2)]


# -- C1: Anfrage ---------------------------------------------------------------------------


def test_rumpf_ohne_mime_type_und_ohne_systeminstruction(tmp_path):
    """Die eine Anfrageform (Spec 8.1), am gesehenen Rumpf: kein `mime_type`, kein
    `sample_rate`, kein `systemInstruction`; Stil nur als `speech_metadata`."""
    from mkn_audio.gemini import URL

    schein = ScheinGoogle()
    s = sprecher(schein)

    s.sprich(block(), gemini_stimme(), tmp_path / "ohne-stil.wav")
    s.sprich(block(), gemini_stimme(stil="ruhig"), tmp_path / "mit-stil.wav")

    ohne, mit = schein.ruempfe
    for rumpf in (ohne, mit):
        assert rumpf["model"] == MODELL
        assert rumpf["response_format"] == {"type": "audio"}
        assert rumpf["generation_config"]["speech_config"] == [{"voice": "Charon"}]
        assert rumpf["input"][0]["type"] == "user_input"
        assert rumpf["input"][0]["content"][0]["type"] == "text"
        assert text_von(rumpf) == SATZ  # das woertliche Transkript, keine Regieanweisung
        roh = json.dumps(rumpf)
        for verboten in ("systemInstruction", "system_instruction", "mime_type", "sample_rate"):
            assert verboten not in roh
    assert not ohne["input"][0]["content"][0].get("annotations")
    assert mit["input"][0]["content"][0]["annotations"] == [
        {"type": "speech_metadata", "style": "ruhig"}
    ]
    assert schein.urls == [URL, URL]
    assert URL == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert all(k.get("x-goog-api-key") == SCHLUESSEL for k in schein.koepfe)


# -- C1: Antwort und Format ------------------------------------------------------------------


@pytest.mark.parametrize("mime", [PCM_MIME, "AUDIO/l16;Codec=PCM;Rate=24000"])
def test_pcm_antwort_wird_wav_24k(tmp_path, mime):
    """PCM 24 kHz (Gross-/Kleinschreibung egal) wird eine WAV im Paketmass."""
    schein = ScheinGoogle(regel=lambda n, r: audio_antwort(bytes(48_000), mime=mime))
    ziel = tmp_path / "ton.wav"

    messwerte = sprecher(schein).sprich(block(), gemini_stimme(), ziel)

    assert wav_info(ziel) == (1, 2, 24_000, 24_000)
    assert messwerte["dauer"] == pytest.approx(1.0, abs=0.01)
    assert messwerte["sprechrate"] == pytest.approx(len(SATZ) / 1.0, rel=0.01)
    assert messwerte["versuche"] >= 1


def test_wav_antwort_wird_gelesen(tmp_path):
    daten = wav_bytes(0.5)
    schein = ScheinGoogle(regel=lambda n, r: audio_antwort(daten, mime="audio/wav"))
    ziel = tmp_path / "ton.wav"

    messwerte = sprecher(schein).sprich(block(), gemini_stimme(), ziel)

    assert wav_info(ziel) == (1, 2, 24_000, 12_000)
    assert messwerte["dauer"] == pytest.approx(0.5, abs=0.01)
    with wave.open(str(ziel), "rb") as w:
        assert w.readframes(12_000) == pcm(0.5)


@pytest.mark.parametrize(
    ("daten", "mime", "frames"),
    [
        # Kopf meldet PCM, Bytes sind RIFF: die Bytes gewinnen, der Kopf ist kein Ton.
        (wav_bytes(0.5, stumm=True), PCM_MIME, 12_000),
        # Kopf meldet WAV, Bytes sind kopfloses PCM: als PCM 24 kHz gelesen.
        (bytes(24_000), "audio/wav", 12_000),
    ],
)
def test_format_bytes_schlagen_mime_type(tmp_path, daten, mime, frames):
    """Review Focus 2: widersprechen sich `mime_type` und Bytes, entscheiden die Bytes --
    ein WAV-Kopf wird nie als Samples geschrieben (sonst knackt es am Blockanfang)."""
    schein = ScheinGoogle(regel=lambda n, r: audio_antwort(daten, mime=mime))
    ziel = tmp_path / "ton.wav"

    sprecher(schein).sprich(block(), gemini_stimme(), ziel)

    assert wav_info(ziel) == (1, 2, 24_000, frames)
    assert erste_samples(ziel) == [0] * 32


def test_pcm_anderer_rate_geht_ueber_ffmpeg_auf_24k(tmp_path):
    """Meldet der Typ eine andere PCM-Rate, bringt ffmpeg den Ton auf das Paketmass (Spec 8.1)."""
    daten = pcm(1.0, rate=16_000)
    ziel = tmp_path / "ton.wav"

    dauer = sprecher(ScheinGoogle()).schreibe_ton(daten, "audio/L16;codec=pcm;rate=16000", ziel)

    kanaele, breite, rate, frames = wav_info(ziel)
    assert (kanaele, breite, rate) == (1, 2, 24_000)
    assert frames == pytest.approx(24_000, abs=240)
    assert dauer == pytest.approx(1.0, abs=0.01)
    assert any(abs(x) > 1000 for x in erste_samples(ziel, 2400))  # Ton kam an, keine Stille


def test_riff_abweichenden_masses_geht_ueber_ffmpeg_auf_24k_mono(tmp_path):
    """Eine WAV mit 48 kHz Stereo wird auf 24 kHz mono gewandelt, nicht roh uebernommen."""
    puffer = io.BytesIO()
    mono = pcm(1.0, rate=48_000)
    stereo = b"".join(mono[i : i + 2] * 2 for i in range(0, len(mono), 2))
    with wave.open(puffer, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48_000)
        w.writeframes(stereo)
    ziel = tmp_path / "ton.wav"

    dauer = sprecher(ScheinGoogle()).schreibe_ton(puffer.getvalue(), "audio/wav", ziel)

    kanaele, breite, rate, frames = wav_info(ziel)
    assert (kanaele, breite, rate) == (1, 2, 24_000)
    assert frames == pytest.approx(24_000, abs=240)
    assert dauer == pytest.approx(1.0, abs=0.01)


def test_ungerade_pcm_bytezahl_ist_fehlerantwort(tmp_path):
    ziel = tmp_path / "ton.wav"
    with pytest.raises(SprecherFehler) as aus:
        sprecher(ScheinGoogle()).schreibe_ton(bytes(1001), PCM_MIME, ziel)
    assert aus.value.klasse == "Fehlerantwort"
    assert not ziel.exists()


def test_kaputte_riff_ist_fehlerantwort(tmp_path):
    ziel = tmp_path / "ton.wav"
    with pytest.raises(SprecherFehler) as aus:
        sprecher(ScheinGoogle()).schreibe_ton(b"RIFF" + bytes(40), "audio/wav", ziel)
    assert aus.value.klasse == "Fehlerantwort"
    assert not ziel.exists()


def test_riff_ohne_frames_laesst_vorhandene_aufnahme_unberuehrt(tmp_path):
    """Eine Antwort ohne Frames wird vor dem Ersetzen verworfen: die gute Aufnahme bleibt."""
    ziel = tmp_path / "ton.wav"
    gute = b"gute-aufnahme-bytes"
    ziel.write_bytes(gute)
    leer = io.BytesIO()
    with wave.open(leer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
    with pytest.raises(SprecherFehler) as aus:
        sprecher(ScheinGoogle()).schreibe_ton(leer.getvalue(), "audio/wav", ziel)
    assert aus.value.klasse == "Fehlerantwort"
    assert ziel.read_bytes() == gute
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ton.wav"]


def test_pcm_ohne_rate_im_typ_bricht(tmp_path):
    with pytest.raises(Mp4Fehler, match="Rate"):
        sprecher(ScheinGoogle()).schreibe_ton(bytes(100), "audio/L16;codec=pcm", tmp_path / "t.wav")


def test_unbekannter_mime_type_bricht(tmp_path):
    """Jeder andere MIME-Typ ist ein Fehler, nie ein Ton (Spec 8.1)."""
    s = sprecher(ScheinGoogle())
    with pytest.raises(Mp4Fehler, match="audio/mpeg"):
        s.schreibe_ton(b"ID3" + bytes(1000), "audio/mpeg", tmp_path / "ton.wav")
    assert not (tmp_path / "ton.wav").exists()


def test_token_felder_fehlen_ist_none(tmp_path):
    """Ohne Nutzungsangabe stehen die Token als `None` -- nie 0 als Ersatz (LP-32)."""
    schein = ScheinGoogle()  # Antworten ohne `usage`
    s = sprecher(schein)
    _, antwort_roh = schein.ton(0.5)

    daten, mime, token = s.lies_antwort(json.loads(antwort_roh))
    messwerte = s.sprich(block(), gemini_stimme(), tmp_path / "ton.wav")

    assert daten == pcm(0.5) and mime == PCM_MIME
    assert token.get("tokens_text") is None and token.get("tokens_audio") is None
    assert "tokens_text" in messwerte and messwerte["tokens_text"] is None
    assert "tokens_audio" in messwerte and messwerte["tokens_audio"] is None


def test_modell_parameter_ueberschreibt_tabelle(tmp_path):
    schein = ScheinGoogle()
    s = sprecher(schein, konfig=WegKonfig(modell="modell-der-tabelle"), modell="modell-des-laufs")

    s.sprich(block(), gemini_stimme(), tmp_path / "ton.wav")

    assert s.modell == "modell-des-laufs"
    assert schein.modelle == {"modell-des-laufs"}


# -- C1: Ton-Schluessel ----------------------------------------------------------------------


def test_ton_schluessel_gemini_aendert_sich_mit_stimme_stil_modell():
    """Der Schluessel folgt der Formel des Plans; jedes Feld darin aendert ihn."""
    s = sprecher(ScheinGoogle())
    basis = gemini_stimme()
    b = block()
    schluessel = s.ton_schluessel(b, basis)

    assert (
        schluessel
        == fingerabdruck(
            "ton", SATZ, "gemini", MODELL, basis.name, basis.version, "Charon", "", "de"
        )[:16]
    )
    assert s.ton_schluessel(b, gemini_stimme()) == schluessel  # gleich bleibt gleich
    andere = {
        "stimme": s.ton_schluessel(b, gemini_stimme(stimme="Kore")),
        "stil": s.ton_schluessel(b, gemini_stimme(stil="ruhig")),
        "name": s.ton_schluessel(b, gemini_stimme(name="anderer-name")),
        "version": s.ton_schluessel(b, gemini_stimme(version=2)),
        "sprache": s.ton_schluessel(b, gemini_stimme(sprache="en")),
        "text": s.ton_schluessel(block("Ein anderer Satz."), basis),
        "modell": sprecher(ScheinGoogle(), modell="anderes-modell").ton_schluessel(b, basis),
    }
    for feld, wert in andere.items():
        assert wert != schluessel, feld
    assert len(set(andere.values())) == len(andere)


# -- C1: Buendeln ----------------------------------------------------------------------------


def _stuecke() -> list[Stueck]:
    """Zwei Kapitel mit Titel, zwei Absaetzen, Zwischenueberschrift, Ueberleitung (Ansage
    mitten im Text) und einem ueberlangen Stueck. Saetze je rund 40 Zeichen."""
    satz = "Ein ruhiger Satz ueber den Garten Nr {}."
    folge: list[tuple[int, int, str, str, bool]] = [
        (0, -1, "Das erste Kapitel", "titel", True),
        (0, 0, satz.format(1), "text", False),
        (0, 0, satz.format(2), "text", False),
        (0, 1, satz.format(3), "text", False),
        (0, 1, satz.format(4), "text", False),
        (0, 2, "Eine Zwischenueberschrift", "ueberschrift", True),
        (0, 3, satz.format(5), "text", False),
        (0, 4, "Nun folgt ein neuer Abschnitt im Garten.", "text", True),  # Ueberleitung
        (0, 5, satz.format(6), "text", False),
        (0, 5, "x" * 150 + ".", "text", False),  # laenger als block_zeichen
        (0, 5, satz.format(7), "text", False),
        (1, -1, "Das zweite Kapitel", "titel", True),
        (1, 0, satz.format(8), "text", False),
        (1, 0, satz.format(9), "text", False),
    ]
    return [
        Stueck(kapitel=k, absatz=a, nr=nr, text=t, art=art, ansage=ansage)
        for nr, (k, a, t, art, ansage) in enumerate(folge)
    ]


def test_buendeln_grenzen():
    """Bloecke aus ganzen Stuecken bis `block_zeichen`, nie ueber Kapitel, Ueberschrift,
    Rollenwechsel oder Titel->Text; Absatzgrenze als Leerzeile; Ueberlanges allein."""
    stuecke = _stuecke()
    nach_nr = {st.nr: st for st in stuecke}
    s = sprecher(ScheinGoogle(), konfig=WegKonfig(modell=MODELL, block_zeichen=100))

    bloecke = s.buendle(stuecke)

    # Reihenfolge erhalten, nichts verloren, nichts doppelt.
    assert [nr for b in bloecke for nr in b.stueck_nrs] == [st.nr for st in stuecke]
    assert len({b.nr for b in bloecke}) == len(bloecke)
    assert any(len(b.stueck_nrs) > 1 for b in bloecke)  # Untergrenze: es wird gebuendelt
    for b in bloecke:
        teile = [nach_nr[nr] for nr in b.stueck_nrs]
        assert {t.kapitel for t in teile} == {b.kapitel}
        assert {t.ansage for t in teile} == {b.ansage}  # kein Rollenwechsel im Block
        arten = {t.art for t in teile}
        assert arten in ({"titel"}, {"ueberschrift"}, {"text"})  # Titel/Ueberschrift allein
        assert all(t.text in b.text for t in teile)
        if len(teile) > 1:
            assert len(b.text) <= 100
        absaetze = list(dict.fromkeys(t.absatz for t in teile))
        assert b.text.count("\n\n") == len(absaetze) - 1  # Leerzeile genau an Absatzgrenzen
    lang = next(b for b in bloecke if "x" * 150 in b.text)
    assert len(lang.stueck_nrs) == 1


def test_buendeln_teilt_an_der_eingabegrenze():
    """Zeichen/3 als obere Token-Schaetzung: ueber 8192 wird geteilt, auch bei grossem
    `block_zeichen` (sonst riskierte der Lauf eine abgeschnittene Antwort)."""
    satz = "Ein ruhiger Satz ueber den Garten, der sich lange hinzieht und nicht endet. " * 4
    stuecke = [Stueck(kapitel=0, absatz=0, nr=i, text=satz.strip(), art="text") for i in range(100)]
    s = sprecher(ScheinGoogle(), konfig=WegKonfig(modell=MODELL, block_zeichen=100_000))

    bloecke = s.buendle(stuecke)

    assert len(bloecke) > 1
    assert all(len(b.text) / 3 <= 8192 for b in bloecke)
    assert [nr for b in bloecke for nr in b.stueck_nrs] == list(range(100))


# -- C1: Startprobe --------------------------------------------------------------------------


def test_startprobe_gemini_ein_satz_je_stimme():
    schein = ScheinGoogle()
    s = sprecher(schein)

    s.startprobe([gemini_stimme(), gemini_stimme("deutsch-gemini-kore", "Kore")])

    assert [stimme_von(r) for r in schein.ruempfe] == ["Charon", "Kore"]
    assert schein.modelle == {MODELL}
    probe = {text_von(r) for r in schein.ruempfe}
    assert len(probe) == 1 and next(iter(probe)).strip()  # derselbe feste Satz


def test_startprobe_gemini_401_ist_zugang():
    schein = ScheinGoogle(regel=lambda n, r: fehler(401, "unauthenticated", "API key not valid"))
    s = sprecher(schein)

    with pytest.raises(SprecherFehler) as info:
        s.startprobe([gemini_stimme(), gemini_stimme("deutsch-gemini-kore", "Kore")])

    assert info.value.klasse == "Zugang"
    assert len(schein.ruempfe) == 1  # keine Wiederholung, keine zweite Stimme


# -- C2: Fehlerklassen, Drossel, Parallelitaet --------------------------------------------------


def auftraege(ordner: Path, anzahl: int) -> list[Auftrag]:
    """`anzahl` Bloecke mit verschiedenem Text, alle von Charon."""
    ordner.mkdir(parents=True, exist_ok=True)
    stimme = gemini_stimme()
    return [
        Auftrag(block(f"Block {i}: {SATZ}", nr=i), stimme, ordner / f"{i}.wav")
        for i in range(anzahl)
    ]


def test_429_pausiert_vergabe_und_zaehlt_nicht_als_ausfall(tmp_path):
    """Review Focus 3: ein erschoepftes Limit heisst warten -- waehrend des Wartens geht keine
    neue Anfrage hinaus, und ein 429 zaehlt nie als Block-Ausfall (`MAX_AUSFAELLE_FOLGE`).

    Teil 1 (parallel 3): die erste Anfrage laeuft ins Limit, alle anderen brauchen 50 ms. Jeder
    Schlaf haelt 0,3 s wirklich an; in diesem Fenster duerfen keine Anfragen dazukommen -- ohne
    Drossel schickten die zwei freien Faeden in der Zeit die naechsten Bloecke.
    Teil 2 (parallel 1): mehr 429 hintereinander, als Ausfaelle in Folge erlaubt sind -- alle
    Bloecke kommen mit Ton zurueck, keiner als Fehler.
    """
    from mkn_audio.lauf import MAX_AUSFAELLE_FOLGE

    schein = ScheinGoogle(regel=lambda n, r: limit() if n == 0 else None, verzoegerung_s=0.05)
    uhr = Uhr(echt_s=0.3)
    fenster: list[tuple[int, int]] = []

    def schlaf(sekunden: float) -> None:
        vorher = len(schein.ruempfe)
        uhr.schlaf(sekunden)
        fenster.append((vorher, len(schein.ruempfe)))

    s = sprecher(schein, uhr=uhr, schlaf=schlaf, konfig=WegKonfig(modell=MODELL, parallel=3))
    ergebnisse = list(
        s.sprich_viele(
            auftraege(tmp_path / "eins", 6), soll_weichen=lambda: False, fortschritt=lambda m: None
        )
    )

    assert sum(uhr.schlaefe) == 15  # die erste Wartezeit
    assert fenster  # Untergrenze: es wurde gewartet
    assert all(vorher == nachher for vorher, nachher in fenster), fenster
    assert len(ergebnisse) == 6
    assert not [e for _, e in ergebnisse if isinstance(e, SprecherFehler)]

    folge = MAX_AUSFAELLE_FOLGE + 1
    schein2 = ScheinGoogle(regel=lambda n, r: limit() if n < folge else None)
    uhr2 = Uhr()
    s2 = sprecher(
        schein2, uhr=uhr2, schlaf=uhr2.schlaf, konfig=WegKonfig(modell=MODELL, parallel=1)
    )
    ergebnisse2 = list(
        s2.sprich_viele(
            auftraege(tmp_path / "zwei", 3), soll_weichen=lambda: False, fortschritt=lambda m: None
        )
    )

    assert len(ergebnisse2) == 3
    assert not [e for _, e in ergebnisse2 if isinstance(e, SprecherFehler)]
    assert sum(uhr2.schlaefe) == 15 + 45 + 120 + 240


def test_429_fuenfmal_ist_limit(tmp_path):
    """Fuenf Wartezeiten (zusammen ein volles 10-Minuten-Fenster), dann `Limit` -- ein Zustand
    des Kontos, kein Block-Ausfall."""
    from mkn_audio.gemini import WARTEN_429

    schein = ScheinGoogle(regel=lambda n, r: limit())
    uhr = Uhr()
    s = sprecher(schein, uhr=uhr, schlaf=uhr.schlaf)

    with pytest.raises(SprecherFehler) as info:
        s.sprich(block(), gemini_stimme(), tmp_path / "ton.wav")

    assert WARTEN_429 == (15, 45, 120, 240, 300)
    assert info.value.klasse == "Limit"
    assert sum(uhr.schlaefe) == 15 + 45 + 120 + 240 + 300
    assert len(schein.ruempfe) in (5, 6)  # nach jeder Wartezeit ein neuer Versuch
    assert not (tmp_path / "ton.wav").exists()


def _drei_429(tmp_path: Path, anzahl: int = 8):
    """parallel 3, die ersten drei Anfragen laufen ins Limit, jede Ton-Antwort braucht 20 ms."""
    schein = ScheinGoogle(regel=lambda n, r: limit() if n < 3 else None, verzoegerung_s=0.02)
    uhr = Uhr()
    s = sprecher(schein, uhr=uhr, schlaf=uhr.schlaf, konfig=WegKonfig(modell=MODELL, parallel=3))
    meldungen: list[str] = []
    ergebnisse = list(
        s.sprich_viele(
            auftraege(tmp_path, anzahl), soll_weichen=lambda: False, fortschritt=meldungen.append
        )
    )
    return schein, ergebnisse, meldungen


def test_drei_429_halbieren_permits(tmp_path):
    """Nach drei 429 in einem Lauf nur noch `parallel // 2` (mindestens 1) gleichzeitig.

    Gemessen werden die Anfragen, die nach der Antwort auf die dritte 429-Anfrage begannen
    (10 ms Abstand, damit die Halbierung verbucht ist); Untergrenze: es gibt mindestens drei.
    """
    schein, ergebnisse, _ = _drei_429(tmp_path)

    assert schein.status[:3] == [429, 429, 429]
    ab = max(schein.ende[:3]) + 0.01
    assert sum(1 for b in schein.beginn if b >= ab) >= 3
    assert schein.max_gleichzeitig_ab(ab) == 1
    assert len(ergebnisse) == 8
    assert not [e for _, e in ergebnisse if isinstance(e, SprecherFehler)]


def test_drossel_und_halbierung_melden_sich(tmp_path):
    _, _, meldungen = _drei_429(tmp_path)

    assert any("gedrosselt" in m for m in meldungen), meldungen
    assert any("parallel-halbiert" in m for m in meldungen), meldungen


def test_stand_alle_zehn_bloecke(tmp_path):
    """Alle 10 Bloecke ein Stand (LP-30) -- nicht je Block, aber auch nicht stumm."""
    s = sprecher(ScheinGoogle(), konfig=WegKonfig(modell=MODELL, parallel=3))
    meldungen: list[str] = []

    ergebnisse = list(
        s.sprich_viele(
            auftraege(tmp_path, 20), soll_weichen=lambda: False, fortschritt=meldungen.append
        )
    )

    assert len(ergebnisse) == 20
    assert 2 <= len(meldungen) < 20, meldungen
    assert any("10" in m for m in meldungen) and any("20" in m for m in meldungen), meldungen


@pytest.mark.parametrize(
    "antwort",
    [fehler(400, "invalid_argument"), fehler(401), fehler(403), fehler(404, "not_found")],
    ids=["400-ohne-sperrcode", "401", "403", "404"],
)
def test_zugang_ohne_wiederholung(tmp_path, antwort):
    """Schluessel, Modell, Form oder Rumpf falsch: sofort `Zugang`, genau ein Rumpf."""
    schein = ScheinGoogle(regel=lambda n, r: antwort)
    uhr = Uhr()

    with pytest.raises(SprecherFehler) as info:
        sprecher(schein, uhr=uhr, schlaf=uhr.schlaf).sprich(
            block(), gemini_stimme(), tmp_path / "ton.wav"
        )

    assert info.value.klasse == "Zugang"
    assert len(schein.ruempfe) == 1
    assert uhr.schlaefe == []


@pytest.mark.parametrize(
    ("antwort", "warten"),
    [
        (fehler(500), 20),
        (fehler(503), 20),
        (TimeoutError("Schein: keine Antwort"), 10),
        (anfrage.AnfrageFehler("Schein: Verbindung fehlgeschlagen"), 10),
        (ohne_audio(), 5),
    ],
    ids=["500", "503", "zeitueberschreitung", "netz", "ohne-audio"],
)
def test_fehlerantwort_wartezeiten_je_ursache(tmp_path, antwort, warten):
    """Je Ursache die Wartezeit der Spec (8.3), vier Versuche, dann `Fehlerantwort`.

    Die Zeitgrenze jeder Anfrage ist `zeitgrenze_s` des Wegs.
    """
    schein = ScheinGoogle(regel=lambda n, r: antwort)
    uhr = Uhr()
    s = sprecher(
        schein, uhr=uhr, schlaf=uhr.schlaf, konfig=WegKonfig(modell=MODELL, zeitgrenze_s=42.0)
    )

    with pytest.raises(SprecherFehler) as info:
        s.sprich(block(), gemini_stimme(), tmp_path / "ton.wav")

    assert info.value.klasse == "Fehlerantwort"
    assert len(schein.ruempfe) == 4
    assert sum(uhr.schlaefe) == 3 * warten
    assert schein.zeitgrenzen == [42.0] * 4
