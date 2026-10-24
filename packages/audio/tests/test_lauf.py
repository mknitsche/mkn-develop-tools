"""Der Lauf: Arbeitsverzeichnis, Fingerabdruecke, Wiederaufnahme, Weichen.

Kein Test braucht Chatterbox: der Arbeiter ist der Schein-Arbeiter (echter Kindprozess,
gleiches Protokoll), das Textmodell entfaellt. ffmpeg und ffprobe laufen echt -- der Lauf
endet in einer M4B, und was in ihr steht, beweist nur ffprobe.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unicodedata
import wave
from datetime import date
from pathlib import Path

import pytest

import mkn_audio.lauf as lauf_modul
from mkn_audio.arbeiter_client import Arbeiter, ArbeiterFehler
from mkn_audio.hoertext.glaetten import PROMPT as PROMPT_GLAETTEN
from mkn_audio.konfig import Konfig
from mkn_audio.lauf import Ergebnis, Gewichen, _kapitelname, konvertiere
from mkn_audio.lesen import KeinText
from mkn_audio.regie import PROMPT_VERSTEHEN
from mkn_audio.stimmen import lade_tabelle
from mkn_audio.typen import Dokument, Kapitel, Mp4Fehler
from muster_quellen import (
    COVER_BYTES,
    epub_mit_kapiteln,
    muster_pdf_leer,
    muster_png,
    xhtml,
)

SCHEIN = Path(__file__).with_name("schein_arbeiter.py")
HEUTE = date(2026, 10, 24)

KAP1 = xhtml(
    "<h1>Erstes Kapitel</h1>"
    "<p>Die Sonne geht heute früh über dem See auf. Ein leiser Wind bewegt das Schilf.</p>"
    "<p>Am Ufer wartet ein kleines Boot auf seinen Besitzer. Niemand ist hier zu sehen.</p>",
)
KAP2 = xhtml(
    "<h1>Zweites Kapitel</h1>"
    "<p>Gegen Mittag kommt ein Fischer den Weg herunter. Er trägt ein Netz auf der Schulter.</p>"
    "<p>Der Fischer löst die Leine und rudert langsam hinaus. Das Schilf schließt sich.</p>",
)


class Zaehler(Arbeiter):
    """Der Schein-Arbeiter, der mitschreibt, was gesprochen und gehoert wird.

    `hoere` gibt den Text zurueck, der zu der WAV gesprochen wurde -- als Datei neben der
    WAV gemerkt, damit es auch fuer Aufnahmen aus einem frueheren Lauf stimmt.
    """

    def __init__(self) -> None:
        super().__init__(Path(sys.executable), skript=SCHEIN)
        self.gesprochen: list[str] = []
        self.sprachen: list[str] = []
        self.vorlagen: dict[str, str] = {}  # gesprochener Text -> Dateiname der Vorlage
        self.gehoert: list[Path] = []

    def sprich(self, text, *, ziel, **kw):
        self.gesprochen.append(text)
        self.sprachen.append(kw["sprache"])
        self.vorlagen[text] = Path(kw["vorlage"]).name
        antwort = super().sprich(text, ziel=ziel, **kw)
        Path(str(ziel) + ".txt").write_text(text, encoding="utf-8")
        return antwort

    def hoere(self, wav, sprache):
        self.gehoert.append(Path(wav))
        return Path(str(wav) + ".txt").read_text(encoding="utf-8")


@pytest.fixture
def umgebung(tmp_path, schreibe_tabelle):
    """Tabelle mit zwei Stimmen (verschiedene Vorlagen), Konfiguration, Arbeits- und Zielort."""
    tabelle = schreibe_tabelle("stimme-a", "stimme-b", standard="stimme-a")
    (tmp_path / "vorlagen").mkdir()
    (tmp_path / "vorlagen" / "stimme-a.wav").write_bytes(b"vorlage-a")
    (tmp_path / "vorlagen" / "stimme-b.wav").write_bytes(b"vorlage-b")
    t = lade_tabelle(tabelle)
    konfig = Konfig(
        stimmen_tabelle=tabelle,
        arbeitsort=tmp_path / "arbeit",
        arbeiter_python=Path(sys.executable),
    )
    ziel = tmp_path / "ziel"
    ziel.mkdir()
    return t, konfig, ziel


@pytest.fixture
def epub(tmp_path):
    return epub_mit_kapiteln(tmp_path / "quelle.epub", {"kap1.xhtml": KAP1, "kap2.xhtml": KAP2})


def lauf(umgebung, quelle, arbeiter, **kw) -> Ergebnis:
    t, konfig, ziel = umgebung
    stimme = kw.pop("stimme", t.standard)
    kw.setdefault("heute", HEUTE)
    kw.setdefault("textmodell", None)
    return konvertiere(quelle, ziel, stimme, arbeiter=arbeiter, konfig=konfig, **kw)


def ffprobe(pfad: Path) -> dict:
    roh = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_chapters",
            "-show_format",
            "-of",
            "json",
            str(pfad),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(roh)


def ton_dateien(konfig: Konfig) -> list[Path]:
    return sorted(konfig.arbeitsort.glob("*/ton/*.wav"))


# -- Ganzer Lauf ----------------------------------------------------------------------


def test_ganzer_lauf_erzeugt_m4b_und_bericht(umgebung, epub):
    _, _, ziel = umgebung
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, epub, arbeiter)

    (m4b,) = ergebnis.dateien
    assert m4b == ziel / "2026-10-24 Das Musterbuch_v01.m4b"
    info = ffprobe(m4b)
    audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
    assert len(audio) == 1
    assert audio[0]["codec_name"] == "aac"
    assert audio[0]["channels"] == 1
    # Kapitelmarken tragen die Titel der Quelle, nicht den ausgeschriebenen Hoertext.
    assert [k["tags"]["title"] for k in info["chapters"]] == ["Erstes Kapitel", "Zweites Kapitel"]
    assert ergebnis.bericht == ziel / "2026-10-24 Das Musterbuch Bericht_v01.md"
    bericht = ergebnis.bericht.read_text(encoding="utf-8")
    assert "stimme-a_v01" in bericht
    assert "Tonlage" in bericht
    assert "Sprechtempo" in bericht
    assert ergebnis.dauer_s == pytest.approx(float(info["format"]["duration"]), abs=1.5)


def test_zweiter_lauf_ueberschreibt_nichts(umgebung, epub):
    with Zaehler() as arbeiter:
        erst = lauf(umgebung, epub, arbeiter)
        zweit = lauf(umgebung, epub, arbeiter)
    assert erst.dateien[0].name.endswith("_v01.m4b")
    assert zweit.dateien[0].name.endswith("_v02.m4b")
    assert erst.dateien[0].exists()


def test_mp3_je_kapitel(umgebung, epub):
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, epub, arbeiter, format="mp3")
    assert len(ergebnis.dateien) == 2
    assert all(d.suffix == ".mp3" for d in ergebnis.dateien)


def test_unbekanntes_format_bricht(umgebung, epub):
    with Zaehler() as arbeiter, pytest.raises(Mp4Fehler, match="flac"):
        lauf(umgebung, epub, arbeiter, format="flac")


def test_auswahl_nur_kapitel_1(umgebung, epub):
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, epub, arbeiter, auswahl="1")
    assert len(ffprobe(ergebnis.dateien[0])["chapters"]) == 1
    assert not any("Fischer" in t for t in arbeiter.gesprochen)
    assert any("Sonne" in t for t in arbeiter.gesprochen)


# -- Wiederaufnahme -------------------------------------------------------------------


def test_wiederaufnahme_rechnet_nichts_doppelt(umgebung, epub):
    _, konfig, _ = umgebung
    with Zaehler() as erst:
        with pytest.raises(Gewichen):
            lauf(umgebung, epub, erst, soll_weichen=lambda: len(erst.gesprochen) >= 3)
        assert len(erst.gesprochen) == 3
        assert len(ton_dateien(konfig)) == 3

    with Zaehler() as zweit:
        ergebnis = lauf(umgebung, epub, zweit)
    insgesamt = erst.gesprochen + zweit.gesprochen
    # Jedes Stueck genau einmal gesprochen: keine Doppelrechnung ueber den Abbruch hinweg.
    assert len(insgesamt) == len(set(insgesamt))
    assert not set(erst.gesprochen) & set(zweit.gesprochen)
    assert len(ton_dateien(konfig)) == len(insgesamt)
    assert ergebnis.dateien[0].exists()


def test_vollstaendig_gerechneter_lauf_spricht_nichts_mehr(umgebung, epub):
    with Zaehler() as erst:
        lauf(umgebung, epub, erst)
    with Zaehler() as zweit:
        lauf(umgebung, epub, zweit)
    assert zweit.gesprochen == []
    assert zweit.gehoert == []  # auch die Pruefung ist fertig und wird nicht wiederholt


def test_gewichen_ist_ein_paketfehler():
    assert issubclass(Gewichen, Mp4Fehler)


def test_halbe_datei_gilt_nicht(umgebung, epub):
    _, konfig, _ = umgebung
    with Zaehler() as erst, pytest.raises(Gewichen):
        lauf(umgebung, epub, erst, soll_weichen=lambda: len(erst.gesprochen) >= 3)
    # Stromausfall zwischen WAV und Messwerten: eine WAV ohne JSON, dazu ein Rest `.tmp`.
    halb = ton_dateien(konfig)[0]
    halb.with_suffix(".json").unlink()
    halb.write_bytes(b"RIFF")
    (halb.parent / "ffff.wav.tmp").write_bytes(b"muell")

    with Zaehler() as zweit:
        ergebnis = lauf(umgebung, epub, zweit)
    gesprochen = len(erst.gesprochen) + len(zweit.gesprochen)
    # Die zwei fertigen bleiben, die halbe wird neu gesprochen: eine mehr als Stuecke.
    assert gesprochen == len(ton_dateien(konfig)) + 1
    assert halb.stat().st_size > 100
    assert ffprobe(ergebnis.dateien[0])["chapters"]


def test_andere_stimme_rechnet_nur_ab_sprechen(umgebung, epub, monkeypatch):
    t, _, _ = umgebung
    zaehl = {"lies": 0, "hoertext": 0, "gliedere": 0}
    for name in zaehl:
        echt = getattr(lauf_modul, name)

        def umhuellt(*a, _echt=echt, _name=name, **kw):
            zaehl[_name] += 1
            return _echt(*a, **kw)

        monkeypatch.setattr(lauf_modul, name, umhuellt)

    with Zaehler() as erst:
        lauf(umgebung, epub, erst, stimme=t.hole("stimme-a"))
    assert zaehl == {"lies": 1, "hoertext": 1, "gliedere": 1}

    with Zaehler() as zweit:
        lauf(umgebung, epub, zweit, stimme=t.hole("stimme-b"))
    # Lesen, Hoertext und Gliedern kommen aus dem Arbeitsverzeichnis ...
    assert zaehl == {"lies": 1, "hoertext": 1, "gliedere": 1}
    # ... aber jedes Stueck wird mit der anderen Stimme neu gesprochen.
    assert sorted(zweit.gesprochen) == sorted(erst.gesprochen)


def test_andere_auswahl_rechnet_hoertext_neu_aber_nicht_den_lesetext(umgebung, epub, monkeypatch):
    zaehl = {"lies": 0, "hoertext": 0}
    for name in zaehl:
        echt = getattr(lauf_modul, name)

        def umhuellt(*a, _echt=echt, _name=name, **kw):
            zaehl[_name] += 1
            return _echt(*a, **kw)

        monkeypatch.setattr(lauf_modul, name, umhuellt)

    with Zaehler() as arbeiter:
        lauf(umgebung, epub, arbeiter, auswahl="1")
        lauf(umgebung, epub, arbeiter, auswahl="2")
    assert zaehl == {"lies": 1, "hoertext": 2}


def test_geaenderte_quelle_findet_nichts_wieder(umgebung, tmp_path):
    a = epub_mit_kapiteln(tmp_path / "a.epub", {"kap1.xhtml": KAP1})
    b = epub_mit_kapiteln(tmp_path / "b.epub", {"kap1.xhtml": KAP2})
    with Zaehler() as arbeiter:
        lauf(umgebung, a, arbeiter)
        n = len(arbeiter.gesprochen)
        lauf(umgebung, b, arbeiter)
    assert len(arbeiter.gesprochen) > n


# -- Pruefung ---------------------------------------------------------------------------


def test_neu_gesprochenes_stueck_ersetzt_die_messwerte(umgebung, epub):
    _, konfig, _ = umgebung
    ziel_satz = "Ein leiser Wind bewegt das Schilf."

    class Wackelig(Zaehler):
        """Beim ersten Mal zu kurz und unverstaendlich, beim zweiten Mal in Ordnung."""

        def sprich(self, text, *, ziel, **kw):
            antwort = super().sprich(text, ziel=ziel, **kw)
            if text == ziel_satz:
                if self.gesprochen.count(ziel_satz) == 1:
                    antwort["zu_kurz"] = True
                else:
                    antwort["sprechrate"] = 21.0
            return antwort

        def hoere(self, wav, sprache):
            echt = super().hoere(wav, sprache)
            if echt == ziel_satz and self.gesprochen.count(ziel_satz) == 1:
                return "murmel"
            return echt

    with Wackelig() as arbeiter:
        ergebnis = lauf(umgebung, epub, arbeiter)
    assert arbeiter.gesprochen.count(ziel_satz) == 2
    gespeichert = [json.loads(p.with_suffix(".json").read_text()) for p in ton_dateien(konfig)]
    # Die Aufnahme wurde ersetzt; die Messwerte des Ersatzes gelten, die der alten nicht mehr.
    assert [g for g in gespeichert if g["sprechrate"] == 21.0] != []
    assert not any(g["zu_kurz"] for g in gespeichert)
    assert "keine" in ergebnis.bericht.read_text(encoding="utf-8").split("Auffällige Stellen")[1]


def test_befund_mit_zeitstempel_im_bericht(umgebung, epub):
    class Taub(Zaehler):
        """Versteht nie, was gesprochen wurde: jede gehoerte Stelle bleibt auffaellig."""

        def hoere(self, wav, sprache):
            super().hoere(wav, sprache)
            return "unverstaendlich"

    with Taub() as arbeiter:
        ergebnis = lauf(umgebung, epub, arbeiter)
    text = ergebnis.bericht.read_text(encoding="utf-8")
    abschnitt = text.split("Auffällige Stellen")[1]
    assert "Wortfehlerrate" in abschnitt
    assert "bei 0" in abschnitt  # Zeitstempel mm:ss, nie ein Strich: die Stelle ist bekannt
    assert "Kapitel" in abschnitt


# -- Kopf: Titel, Datum, Cover, Sprache, Aussprache --------------------------------------


def test_leerer_titel_nimmt_den_quelldateinamen_nfc(umgebung, tmp_path):
    nfd = unicodedata.normalize("NFD", "Äpfel und Birnen")
    quelle = epub_mit_kapiteln(tmp_path / f"{nfd}.epub", {"kap1.xhtml": KAP1})
    # Titel im OPF leer machen
    import zipfile

    neu = tmp_path / f"{nfd}-neu.epub"
    with zipfile.ZipFile(quelle) as alt, zipfile.ZipFile(neu, "w") as aus:
        for eintrag in alt.infolist():
            daten = alt.read(eintrag.filename)
            if eintrag.filename.endswith("content.opf"):
                daten = daten.replace(b"Das Musterbuch", b"")
            aus.writestr(eintrag, daten)
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, neu, arbeiter)
    (m4b,) = ergebnis.dateien
    erwartet = unicodedata.normalize("NFC", "Äpfel und Birnen-neu")
    assert m4b.name == f"2026-10-24 {erwartet}_v01.m4b"
    assert unicodedata.is_normalized("NFC", m4b.name)


def test_datum_kommt_aus_dem_werkzeug_wenn_nicht_gegeben(umgebung, epub):
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, epub, arbeiter, heute=None)
    assert ergebnis.dateien[0].name.startswith(date.today().isoformat())


def test_brauchbares_cover_kommt_in_die_m4b(umgebung, tmp_path):
    png = muster_png(tmp_path / "cover.png").read_bytes()
    quelle = _epub_mit_cover(tmp_path / "mit.epub", png)
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, quelle, arbeiter)
    bild = [s for s in ffprobe(ergebnis.dateien[0])["streams"] if s["codec_type"] == "video"]
    assert len(bild) == 1
    assert not any("Cover" in w for w in ergebnis.warnungen)


def test_unbrauchbares_cover_wird_frueh_gemeldet_und_der_lauf_geht_weiter(umgebung, tmp_path):
    # PNG-Kopf, aber kein Bild: ffmpeg wuerde erst beim Verpacken scheitern, nach dem Sprechen.
    quelle = _epub_mit_cover(tmp_path / "kaputt.epub", COVER_BYTES)
    gemeldet: list[str] = []
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, quelle, arbeiter, fortschritt=gemeldet.append)
    assert any("Cover" in w for w in ergebnis.warnungen)
    assert "Cover" in ergebnis.bericht.read_text(encoding="utf-8")
    assert [s for s in ffprobe(ergebnis.dateien[0])["streams"] if s["codec_type"] == "video"] == []
    # frueh: die Warnung entsteht vor dem ersten gesprochenen Stueck
    assert gemeldet.index(next(m for m in gemeldet if "Cover" in m)) < gemeldet.index(
        next(m for m in gemeldet if m.startswith("Sprechen"))
    )


def _epub_mit_cover(pfad: Path, cover: bytes) -> Path:
    from muster_quellen import epub_schreiben, opf

    items = [
        ("kap1", "kap1.xhtml", "application/xhtml+xml", ""),
        ("cov", "bilder/cover.png", "image/png", "cover-image"),
    ]
    return epub_schreiben(
        pfad,
        {
            "content.opf": opf(items=items, spine=["kap1"], cover_id="cov"),
            "kap1.xhtml": KAP1,
            "bilder/cover.png": cover,
        },
    )


def test_stimme_bestimmt_die_sprache_nicht_die_quelle(umgebung, tmp_path):
    quelle = epub_mit_kapiteln(tmp_path / "en.epub", {"kap1.xhtml": KAP1})
    import zipfile

    neu = tmp_path / "en-neu.epub"
    with zipfile.ZipFile(quelle) as alt, zipfile.ZipFile(neu, "w") as aus:
        for eintrag in alt.infolist():
            daten = alt.read(eintrag.filename)
            if eintrag.filename.endswith("content.opf"):
                daten = daten.replace(b"de-DE", b"en-GB")
            aus.writestr(eintrag, daten)
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, neu, arbeiter)
    assert set(arbeiter.sprachen) == {"de"}
    assert any("en" in w and "de" in w for w in ergebnis.warnungen)


def test_aussprache_json_neben_der_quelle(umgebung, tmp_path):
    kap = xhtml("<h1>Kapitel</h1><p>Das Xylophon klingt heute besonders schön im Saal.</p>")
    quelle = epub_mit_kapiteln(tmp_path / "klang.epub", {"kap1.xhtml": kap})
    (tmp_path / "aussprache.json").write_text('{"Xylophon": "Ksülofon"}', encoding="utf-8")
    with Zaehler() as arbeiter:
        lauf(umgebung, quelle, arbeiter)
    assert any("Ksülofon" in t for t in arbeiter.gesprochen)
    assert not any("Xylophon" in t for t in arbeiter.gesprochen)


def test_kaputte_aussprache_json_bricht(umgebung, epub, tmp_path):
    (tmp_path / "aussprache.json").write_text('["kein", "Objekt"]', encoding="utf-8")
    with Zaehler() as arbeiter, pytest.raises(Mp4Fehler, match=r"aussprache\.json"):
        lauf(umgebung, epub, arbeiter)


def test_ohne_textmodell_steht_es_im_bericht(umgebung, epub):
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, epub, arbeiter)
    assert any("Sprachmodell" in w for w in ergebnis.warnungen)
    assert "Sprachmodell" in ergebnis.bericht.read_text(encoding="utf-8")


# -- Fortschritt ------------------------------------------------------------------------


def test_fortschritt_je_stufe_und_je_zwanzig_stuecke(umgebung, tmp_path):
    saetze = " ".join(f"Dies ist der besondere Satz mit der Nummer {w}." for w in WOERTER)
    kap = xhtml(f"<h1>Zahlen</h1><p>{saetze}</p>")
    quelle = epub_mit_kapiteln(tmp_path / "viele.epub", {"kap1.xhtml": kap})
    gemeldet: list[str] = []
    with Zaehler() as arbeiter:
        lauf(umgebung, quelle, arbeiter, fortschritt=gemeldet.append)
    n = len(arbeiter.gesprochen)
    assert n > 20
    sprechen = [m for m in gemeldet if m.startswith("Sprechen ")]
    assert sprechen[0] == "Sprechen 20/" + str(n)
    assert sprechen[-1] == f"Sprechen {n}/{n}"
    for stufe in ("Lesen", "Hörtext", "Gliedern", "Prüfen", "Mastern", "Verpacken"):
        assert any(m.startswith(stufe) for m in gemeldet), stufe


WOERTER = [
    "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn",
    "elf", "zwölf", "dreizehn", "vierzehn", "fünfzehn", "sechzehn", "siebzehn",
    "achtzehn", "neunzehn", "zwanzig", "einundzwanzig", "zweiundzwanzig",
    "dreiundzwanzig", "vierundzwanzig",
]  # fmt: skip


# -- Quelle ohne Text ---------------------------------------------------------------------


def test_quelle_ohne_text_bricht_und_hinterlaesst_keine_ausgabe(umgebung, tmp_path):
    _, _, ziel = umgebung
    leer = muster_pdf_leer(tmp_path / "leer.pdf")
    with Zaehler() as arbeiter, pytest.raises(KeinText):
        lauf(umgebung, leer, arbeiter)
    assert list(ziel.iterdir()) == []
    assert arbeiter.gesprochen == []


def test_fehlende_vorlage_bricht_vor_dem_sprechen(umgebung, epub, tmp_path):
    (tmp_path / "vorlagen" / "stimme-a.wav").unlink()
    with Zaehler() as arbeiter, pytest.raises(Mp4Fehler, match="stimme-a"):
        lauf(umgebung, epub, arbeiter)
    assert arbeiter.gesprochen == []


# -- Arbeiter-Ausfall: ein Versuch mehr, dann Stille mit Befund ------------------------------

SATZ_X = "Ein leiser Wind bewegt das Schilf."


def _wav_dauer(pfad: Path) -> float:
    with wave.open(str(pfad), "rb") as w:
        return w.getnframes() / w.getframerate()


def _ton_json(konfig: Konfig) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(konfig.arbeitsort.glob("*/ton/*.json"))]


def _auffaellige_stellen(ergebnis: Ergebnis) -> str:
    return ergebnis.bericht.read_text(encoding="utf-8").split("Auffällige Stellen")[1]


def _epub_mit_saetzen(tmp_path: Path, *saetze: str) -> Path:
    absaetze = "".join(f"<p>{satz}</p>" for satz in saetze)
    return epub_mit_kapiteln(
        tmp_path / "quelle.epub", {"kap1.xhtml": xhtml(f"<h1>Einziges Kapitel</h1>{absaetze}")}
    )


def test_einmaliger_arbeiter_ausfall_kostet_nur_einen_versuch(
    umgebung, epub, tmp_path, monkeypatch
):
    _, konfig, _ = umgebung
    monkeypatch.setenv("SCHEIN_TOD_BEI", SATZ_X)
    monkeypatch.setenv("SCHEIN_TOD_MARKE", str(tmp_path / "tod.marke"))

    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, epub, arbeiter)

    assert (tmp_path / "tod.marke").exists()  # der Arbeiter ist wirklich gestorben ...
    assert arbeiter.gesprochen.count(SATZ_X) == 2  # ... und der zweite Versuch hat es geschafft
    assert "nicht gesprochen" not in _auffaellige_stellen(ergebnis)
    assert "keine" in _auffaellige_stellen(ergebnis)
    # Das Stueck gilt als gesprochen: Messwerte liegen im Cache (wie jedes andere).
    assert len(_ton_json(konfig)) == len(ton_dateien(konfig))


def test_gift_stueck_wird_stille_mit_befund(umgebung, epub, monkeypatch):
    _, konfig, _ = umgebung
    # Dasselbe Stueck scheitert immer: eine Fehlerantwort des Arbeiters.
    monkeypatch.setenv("SCHEIN_FEHLER_BEI", SATZ_X)
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, epub, arbeiter)

    assert arbeiter.gesprochen.count(SATZ_X) == 2  # genau EIN neuer Versuch
    (m4b,) = ergebnis.dateien
    assert m4b.is_file()
    stellen = _auffaellige_stellen(ergebnis)
    assert "nicht gesprochen (Fehlerantwort)" in stellen
    assert "Kapitel »Erstes Kapitel«" in stellen
    assert " bei " in stellen  # Zeitstempel mm:ss, auch fuer das ersetzte Stueck
    assert any("nicht gesprochen" in w for w in ergebnis.warnungen)
    # Als Stille eingesetzt, aber NICHT als gesprochen gemerkt: WAV ja, Messwerte nein.
    stille = [w for w in ton_dateien(konfig) if not w.with_suffix(".json").is_file()]
    assert len(stille) == 1
    assert _wav_dauer(stille[0]) == pytest.approx(len(SATZ_X) / 14, abs=0.01)


def test_gift_stueck_wird_beim_naechsten_lauf_erneut_versucht(umgebung, epub, monkeypatch):
    _, konfig, _ = umgebung
    monkeypatch.setenv("SCHEIN_FEHLER_BEI", SATZ_X)
    with Zaehler() as arbeiter:
        erster = lauf(umgebung, epub, arbeiter)
    assert "nicht gesprochen" in _auffaellige_stellen(erster)

    monkeypatch.delenv("SCHEIN_FEHLER_BEI")  # der Arbeiter ist wieder gesund
    with Zaehler() as arbeiter:
        zweiter = lauf(umgebung, epub, arbeiter)

    assert arbeiter.gesprochen == [SATZ_X]  # nur das offene Stueck, nichts doppelt
    assert "nicht gesprochen" not in _auffaellige_stellen(zweiter)
    assert "keine" in _auffaellige_stellen(zweiter)
    assert not any("nicht gesprochen" in w for w in zweiter.warnungen)
    assert len(_ton_json(konfig)) == len(ton_dateien(konfig))  # jetzt ist alles gesprochen
    # Das neu gesprochene Stueck ist gepruft worden wie jedes andere (Pruefung neu gelaufen).
    assert zweiter.dauer_s > 0


def test_mehrere_ausfaelle_hintereinander_brechen_laut(umgebung, tmp_path, monkeypatch):
    """Vier Stuecke hintereinander: das ist kein Gift-Stueck, sondern ein kaputter Arbeiter."""
    quelle = _epub_mit_saetzen(
        tmp_path,
        "Der Hund schlief unter dem Tisch.",
        "Giftig eins liegt am Weg.",
        "Giftig zwei liegt am Weg.",
        "Giftig drei liegt am Weg.",
        "Giftig vier liegt am Weg.",
        "Danach wurde es wieder ruhig.",
    )
    monkeypatch.setenv("SCHEIN_FEHLER_BEI", "Giftig")
    with Zaehler() as arbeiter, pytest.raises(ArbeiterFehler, match="hintereinander") as info:
        lauf(umgebung, quelle, arbeiter)
    # Der Abbruch nach mehreren Ausfaellen ist EINE eigene Klasse, egal was der letzte trug.
    assert info.value.klasse == "Folge"
    assert isinstance(info.value.__cause__, ArbeiterFehler)
    # Der vierte scheitert zweimal, dann ist Schluss: das Ende wird nicht mehr versucht.
    assert "Danach wurde es wieder ruhig." not in arbeiter.gesprochen


def test_drei_ausfaelle_hintereinander_sind_noch_gift_stuecke(umgebung, tmp_path, monkeypatch):
    quelle = _epub_mit_saetzen(
        tmp_path,
        "Der Hund schlief unter dem Tisch.",
        "Giftig eins liegt am Weg.",
        "Giftig zwei liegt am Weg.",
        "Giftig drei liegt am Weg.",
        "Danach wurde es wieder ruhig.",
    )
    monkeypatch.setenv("SCHEIN_FEHLER_BEI", "Giftig")
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, quelle, arbeiter)
    assert _auffaellige_stellen(ergebnis).count("nicht gesprochen") == 3


def test_vereinzelte_ausfaelle_zaehlen_nicht_zusammen(umgebung, tmp_path, monkeypatch):
    """Ein gesprochenes Stueck dazwischen setzt die Reihe zurueck."""
    quelle = _epub_mit_saetzen(
        tmp_path,
        "Giftig eins liegt am Weg.",
        "Giftig zwei liegt am Weg.",
        "Der Hund schlief unter dem Tisch.",
        "Giftig drei liegt am Weg.",
        "Giftig vier liegt am Weg.",
        "Danach wurde es wieder ruhig.",
        "Giftig fuenf liegt am Weg.",
    )
    monkeypatch.setenv("SCHEIN_FEHLER_BEI", "Giftig")
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, quelle, arbeiter)
    assert _auffaellige_stellen(ergebnis).count("nicht gesprochen") == 5


# -- Regie: Verstehen, Ansagen, zweite Stimme -----------------------------------------------

VORSPANN = "Sie hören ein Buch: „Das Musterbuch“."
KOPFSEITE = (
    VORSPANN,
    "Rund eine Minute in zwei Abschnitten: Erstes Kapitel und Zweites Kapitel.",
    "Es beginnt mit Erstes Kapitel.",
)
ABSPANN = "Das war das Musterbuch."


class Regisseur:
    """Schein-Textmodell fuer den ganzen Lauf: Rollen, Ansagen und Glaetten nach Prompt.

    Alles ist Haupttext; die Ansagen sind Vorspann und Abspann. Geglaettet wird nichts
    (der Text kommt unveraendert zurueck). Zaehlt die Aufrufe je Aufgabe.
    """

    def __init__(self) -> None:
        self.aufrufe = {"verstehen": 0, "inszenieren": 0, "glaetten": 0}

    def __call__(self, prompt, bilder):
        if prompt.startswith(PROMPT_GLAETTEN):
            self.aufrufe["glaetten"] += 1
            return prompt.removeprefix(PROMPT_GLAETTEN)
        if prompt.startswith(PROMPT_VERSTEHEN):
            self.aufrufe["verstehen"] += 1
            return json.dumps({"dokumentart": "Roman", "rollen": {}})
        self.aufrufe["inszenieren"] += 1
        return json.dumps(
            {
                "dokumentart": "ein Buch",
                "titel": "Das Musterbuch",
                "ueberleitungen": {},
                "abspann": ABSPANN,
            }
        )


def test_regie_stufe_wird_zwischengespeichert(umgebung, epub):
    t, _, _ = umgebung
    modell = Regisseur()
    gemeldet: list[str] = []
    with Zaehler() as erst:
        lauf(umgebung, epub, erst, textmodell=modell, fortschritt=gemeldet.append)
    assert (modell.aufrufe["verstehen"], modell.aufrufe["inszenieren"]) == (1, 1)
    assert "Regie" in gemeldet
    assert VORSPANN in erst.gesprochen

    # Andere Stimme: Regie kommt aus dem Arbeitsverzeichnis, das Modell wird nicht befragt.
    gemeldet.clear()
    with Zaehler() as zweit:
        lauf(
            umgebung, epub, zweit, stimme=t.hole("stimme-b"), textmodell=modell,
            fortschritt=gemeldet.append,
        )  # fmt: skip
    assert (modell.aufrufe["verstehen"], modell.aufrufe["inszenieren"]) == (1, 1)
    assert "Regie (vorhanden)" in gemeldet
    assert VORSPANN in zweit.gesprochen


def test_regie_neue_auswahl_rechnet_regie_neu(umgebung, epub):
    """Die Regie sieht nur die gewaehlten Kapitel: eine andere Auswahl ist eine andere Regie."""
    modell = Regisseur()
    with Zaehler() as arbeiter:
        lauf(umgebung, epub, arbeiter, textmodell=modell, auswahl="1")
        lauf(umgebung, epub, arbeiter, textmodell=modell, auswahl="2")
    assert modell.aufrufe["verstehen"] == 2


def test_ohne_textmodell_keine_regie_aber_lauf_gelingt(umgebung, epub):
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, epub, arbeiter)
    assert VORSPANN not in arbeiter.gesprochen
    assert any("keine Regie" in w for w in ergebnis.warnungen)
    bericht = ergebnis.bericht.read_text(encoding="utf-8")
    assert "keine Regie" in bericht
    assert "Ansage-Stimme" not in bericht
    assert [k["tags"]["title"] for k in ffprobe(ergebnis.dateien[0])["chapters"]] == [
        "Erstes Kapitel",
        "Zweites Kapitel",
    ]


@pytest.fixture
def umgebung_ansage(tmp_path, schreibe_tabelle):
    """Wie `umgebung`, aber `stimme-a` sagt mit `stimme-b` an."""
    tabelle = schreibe_tabelle(
        "stimme-b", "stimme-a", standard="stimme-a", extra='ansage_stimme = "stimme-b"\n'
    )
    (tmp_path / "vorlagen").mkdir()
    (tmp_path / "vorlagen" / "stimme-a.wav").write_bytes(b"vorlage-a")
    (tmp_path / "vorlagen" / "stimme-b.wav").write_bytes(b"vorlage-b")
    konfig = Konfig(
        stimmen_tabelle=tabelle,
        arbeitsort=tmp_path / "arbeit",
        arbeiter_python=Path(sys.executable),
    )
    ziel = tmp_path / "ziel"
    ziel.mkdir()
    return lade_tabelle(tabelle), konfig, ziel


def test_ansage_mit_zweiter_stimme_gesprochen(umgebung_ansage, epub, monkeypatch):
    gemastert: list[str] = []  # Name der Stimme je Kapitel, in Reihenfolge
    echt = lauf_modul.master

    def merke(roh, stimme, wav):
        gemastert.append(stimme.name)
        return echt(roh, stimme, wav)

    monkeypatch.setattr(lauf_modul, "master", merke)

    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung_ansage, epub, arbeiter, textmodell=Regisseur())

    # Ansagen mit Vorlage und Reglern von stimme-b, alles andere mit stimme-a ...
    ansagen = {*KOPFSEITE, ABSPANN}
    assert {arbeiter.vorlagen[a] for a in ansagen} == {"stimme-b.wav"}
    uebrige = {t for t in arbeiter.vorlagen if t not in ansagen}
    assert uebrige
    assert {arbeiter.vorlagen[t] for t in uebrige} == {"stimme-a.wav"}
    # ... Vorspann- und Abspann-Kapitel (nur Ansagen) mit Klang und Tempo der Ansage-Stimme.
    assert gemastert == ["stimme-b", "stimme-a", "stimme-a", "stimme-b"]
    # Kapitelmarken: Ansage-Kapitel heissen nach ihrer Art, echte Kapitel behalten ihren Titel.
    assert [k["tags"]["title"] for k in ffprobe(ergebnis.dateien[0])["chapters"]] == [
        "Einleitung",
        "Erstes Kapitel",
        "Zweites Kapitel",
        "Abspann",
    ]
    bericht = ergebnis.bericht.read_text(encoding="utf-8")
    assert "Ansage-Stimme:** stimme-b_v01" in bericht
    assert f"neu formuliert (vorspann): „{' '.join(KOPFSEITE)}“" in bericht


def test_kapitelmarke_einleitung():
    """Die Kopfseite heisst in der Kapitelliste "Einleitung", der Schluss "Abspann"."""
    dok = Dokument(
        "T",
        None,
        "de",
        (
            Kapitel("", ("Sie hören ein Buch.",), ("vorspann",)),
            Kapitel("Erstes", ("Text.",)),
            Kapitel("", ("Das war es.",), ("abspann",)),
            Kapitel("", ("Ohne Titel.",)),
        ),
    )
    assert [_kapitelname(dok, k) for k in range(4)] == [
        "Einleitung",
        "Erstes",
        "Abspann",
        "Kapitel 2",  # die Ansage-Kapitel zaehlen nicht mit
    ]


def test_ansage_art_ueberlebt_den_zweiten_lauf(umgebung_ansage, epub):
    """Die Art der Stuecke ueberlebt das Zwischenspeichern: nichts wird neu gesprochen."""
    _, konfig, _ = umgebung_ansage
    with Zaehler() as erst:
        lauf(umgebung_ansage, epub, erst, textmodell=Regisseur())
    with Zaehler() as zweit:
        lauf(umgebung_ansage, epub, zweit, textmodell=Regisseur())
    assert zweit.gesprochen == []
    assert len(ton_dateien(konfig)) == len(erst.gesprochen)


def test_bildquelle_gibt_bilder_an_die_regie(umgebung, tmp_path, monkeypatch):
    bild = muster_png(tmp_path / "seite.png")
    gesehen: list[tuple] = []
    echt = lauf_modul.verstehe

    def merke(dok, *, textmodell, bilder=()):
        gesehen.append(bilder)
        return echt(dok, textmodell=textmodell, bilder=bilder)

    monkeypatch.setattr(lauf_modul, "verstehe", merke)

    class Leser(Regisseur):
        def __call__(self, prompt, bilder):
            if bilder and not prompt.startswith(PROMPT_VERSTEHEN):  # Lesen des Bildes
                return "Ein erfundener Satz auf dem Bild.\n\nNoch ein erfundener Satz dazu."
            return super().__call__(prompt, bilder)

    with Zaehler() as arbeiter:
        lauf(umgebung, bild, arbeiter, textmodell=Leser())

    (bilder,) = gesehen
    assert [(mime, daten[:4]) for mime, daten in bilder] == [("image/png", b"\x89PNG")]


def test_quelle_ohne_bild_gibt_der_regie_keine_bilder(umgebung, epub, monkeypatch):
    gesehen: list[tuple] = []
    echt = lauf_modul.verstehe

    def merke(dok, *, textmodell, bilder=()):
        gesehen.append(bilder)
        return echt(dok, textmodell=textmodell, bilder=bilder)

    monkeypatch.setattr(lauf_modul, "verstehe", merke)
    with Zaehler() as arbeiter:
        lauf(umgebung, epub, arbeiter, textmodell=Regisseur())
    assert gesehen == [()]


def test_lauf_legt_bereichs_manifest_ab(umgebung, epub):
    # Das gemeinsame Bereichs-Manifest (Format: README) entsteht bei jedem Lauf.
    import json

    with Zaehler() as arbeiter:
        lauf(umgebung, epub, arbeiter)
    (manifest,) = list(Path(umgebung[1].arbeitsort).rglob("manifest.json"))
    daten = json.loads(manifest.read_text(encoding="utf-8"))
    assert daten["quelle"]["pfad"] == epub.name
    assert [a["titel"] for a in daten["abschnitte"]] == ["Erstes Kapitel", "Zweites Kapitel"]
    assert all(b["art"] for a in daten["abschnitte"] for b in a["bereiche"])


# -- Regie-Modus ----------------------------------------------------------------------------


def _merke_modus(monkeypatch) -> list[str]:
    modi: list[str] = []
    echt = lauf_modul.inszeniere

    def merke(dok, rollenbild, *, textmodell, modus="voll"):
        modi.append(modus)
        return echt(dok, rollenbild, textmodell=textmodell, modus=modus)

    monkeypatch.setattr(lauf_modul, "inszeniere", merke)
    return modi


def test_epub_nimmt_modus_buch(umgebung, epub, tmp_path, monkeypatch):
    modi = _merke_modus(monkeypatch)
    with Zaehler() as arbeiter:
        lauf(umgebung, epub, arbeiter, textmodell=Regisseur())
    assert modi == ["buch"]

    # Eine andere Quelle bekommt die volle Regie ...
    text = tmp_path / "artikel.md"
    text.write_text("# Ein Artikel\n\nDie Sonne geht heute früh auf. Ein Wind weht.\n", "utf-8")
    modi.clear()
    with Zaehler() as arbeiter:
        lauf(umgebung, text, arbeiter, textmodell=Regisseur())
    assert modi == ["voll"]

    # ... und was der Aufrufer sagt, gilt vor der Voreinstellung.
    modi.clear()
    with Zaehler() as arbeiter:
        lauf(umgebung, epub, arbeiter, textmodell=Regisseur(), regie_modus="voll")
    assert modi == ["voll"]


def test_regie_modus_aus_fragt_das_modell_nicht(umgebung, epub):
    modell = Regisseur()
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, epub, arbeiter, textmodell=modell, regie_modus="aus")
    assert (modell.aufrufe["verstehen"], modell.aufrufe["inszenieren"]) == (0, 0)
    assert VORSPANN not in arbeiter.gesprochen
    assert any("Regie ausgeschaltet" in w for w in ergebnis.warnungen)


def test_regie_modus_wechsel_rechnet_die_regie_neu(umgebung, epub):
    modell = Regisseur()
    with Zaehler() as arbeiter:
        lauf(umgebung, epub, arbeiter, textmodell=modell, regie_modus="voll")
        lauf(umgebung, epub, arbeiter, textmodell=modell, regie_modus="buch")
    assert modell.aufrufe["verstehen"] == 2


def test_unbekannter_regie_modus_bricht_vor_der_arbeit(umgebung, epub):
    with Zaehler() as arbeiter, pytest.raises(Mp4Fehler, match="Regie-Modus"):
        lauf(umgebung, epub, arbeiter, regie_modus="halb")
    assert arbeiter.gesprochen == []


def test_geaenderter_code_liest_neu_spricht_aber_nichts_doppelt(umgebung, epub, monkeypatch):
    # Kapitel-1-Abnahme 24.10.: ein Leser-Fix wirkte nicht, weil "Lesen (vorhanden)" den alten
    # Stand bei gleicher Paketversion wiederverwendete. Der Code-Stand gehoert in den Fingerabdruck
    # der Textstufen; der Ton haengt am Text, gleiche Stuecke bleiben also gesprochen.
    gemeldet: list[str] = []
    with Zaehler() as erst:
        lauf(umgebung, epub, erst)
    monkeypatch.setattr(lauf_modul, "STAND_LESEN", "ein anderer Stand")
    with Zaehler() as zweit:
        lauf(umgebung, epub, zweit, fortschritt=gemeldet.append)
    assert "Lesen" in gemeldet
    assert "Lesen (vorhanden)" not in gemeldet
    assert zweit.gesprochen == []


def test_geaenderter_code_einer_spaeteren_stufe_fragt_die_regie_nicht_neu(
    umgebung, epub, monkeypatch
):
    # Critic 24.10.: ein Fix am Gliedern darf Lesen und Regie (Sprachmodell, neue Ansagen,
    # verschobene Stueckgrenzen) nicht neu ausloesen.
    modell = Regisseur()
    gemeldet: list[str] = []
    with Zaehler() as erst:
        lauf(umgebung, epub, erst, textmodell=modell)
    monkeypatch.setattr(lauf_modul, "STAND_GLIEDERN", "ein anderer Stand")
    with Zaehler() as zweit:
        lauf(umgebung, epub, zweit, textmodell=modell, fortschritt=gemeldet.append)
    assert (modell.aufrufe["verstehen"], modell.aufrufe["inszenieren"]) == (1, 1)
    assert "Regie (vorhanden)" in gemeldet
    assert zweit.gesprochen == []


def test_code_stand_folgt_dem_inhalt_der_eigenen_dateien(tmp_path):
    (tmp_path / "stufe").mkdir()
    (tmp_path / "stufe" / "a.py").write_text("x = 1\n")
    (tmp_path / "fremd.py").write_text("y = 1\n")
    vorher = lauf_modul._code_stand(tmp_path, ("stufe",))
    (tmp_path / "fremd.py").write_text("y = 2\n")
    assert lauf_modul._code_stand(tmp_path, ("stufe",)) == vorher
    (tmp_path / "stufe" / "a.py").write_text("x = 2\n")
    assert lauf_modul._code_stand(tmp_path, ("stufe",)) != vorher


class RegisseurMitUeberleitung(Regisseur):
    def __call__(self, prompt, bilder):
        antwort = super().__call__(prompt, bilder)
        if prompt.startswith((PROMPT_GLAETTEN, PROMPT_VERSTEHEN)):
            return antwort
        daten = json.loads(antwort)
        daten["ueberleitungen"] = {"1": "Gegen Mittag kommt ein Fischer."}
        return json.dumps(daten)


def test_ueberleitung_im_kapitel_klingt_wie_die_ansage_stimme(umgebung_ansage, epub, monkeypatch):
    # Bis 24.10. bekam ein gemischtes Kapitel (Ueberleitung + Text) Klang und Tempo der
    # Hauptstimme -- die Klangkorrektur der Maennerstimme verschlechtert die Frauenstimme.
    gemastert: list[str] = []
    echt = lauf_modul.master

    def merke(roh, stimme, wav):
        gemastert.append(stimme.name)
        return echt(roh, stimme, wav)

    monkeypatch.setattr(lauf_modul, "master", merke)
    with Zaehler() as arbeiter:
        ergebnis = lauf(
            umgebung_ansage,
            epub,
            arbeiter,
            textmodell=RegisseurMitUeberleitung(),
            regie_modus="voll",
        )
    assert arbeiter.vorlagen["Gegen Mittag kommt ein Fischer."] == "stimme-b.wav"
    # Vorspann, Kapitel 1, dann Kapitel 2 in zwei Laeufen (Ueberleitung, Text), dann Abspann.
    assert gemastert == ["stimme-b", "stimme-a", "stimme-b", "stimme-a", "stimme-b"]
    assert len(ffprobe(ergebnis.dateien[0])["chapters"]) == 4


def test_gleicher_inhalt_unter_neuem_namen_bekommt_den_neuen_titel(umgebung, tmp_path):
    # Der Leser nimmt bei Text den Dateinamen als Titel; der Zwischenspeicher darf ihn
    # deshalb nicht allein nach dem Inhalt wiederfinden.
    alt = tmp_path / "Erste Probe.txt"
    neu = tmp_path / "Zweite Probe.txt"
    for pfad in (alt, neu):
        pfad.write_text("Ein Satz zum Vorlesen. Und noch einer.\n", encoding="utf-8")
    with Zaehler() as arbeiter:
        lauf(umgebung, alt, arbeiter)
        ergebnis = lauf(umgebung, neu, arbeiter)
    (m4b,) = ergebnis.dateien
    assert m4b.name == "2026-10-24 Zweite Probe_v01.m4b"
