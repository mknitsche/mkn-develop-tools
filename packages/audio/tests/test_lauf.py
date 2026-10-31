"""Der Lauf: Arbeitsverzeichnis, Fingerabdruecke, Wiederaufnahme, Weichen.

Kein Test braucht Chatterbox: der Arbeiter ist der Schein-Arbeiter (echter Kindprozess,
gleiches Protokoll), das Textmodell entfaellt. ffmpeg und ffprobe laufen echt -- der Lauf
endet in einer M4B, und was in ihr steht, beweist nur ffprobe.
"""

from __future__ import annotations

import ast
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
    muster_pdf_seitentitel,
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
    """Der Lauf mit dem lokalen Sprecher. Ohne `stimme` gelten Text- und Ansage-Stimme von
    `[standard.local.de]`; mit `stimme` (ohne `ansage`) spricht diese Stimme auch die Ansagen."""
    from mkn_audio.sprecher import SprecherLokal

    t, konfig, ziel = umgebung
    text, standard_ansage, _ = t.standard_fuer("local", "de")
    stimme = kw.pop("stimme", text)
    kw.setdefault("ansage", standard_ansage if stimme is text else stimme)
    kw.setdefault("heute", HEUTE)
    kw.setdefault("textmodell", None)
    sprecher = SprecherLokal(arbeiter, t.wege["local"])
    return konvertiere(quelle, ziel, stimme, sprecher=sprecher, konfig=konfig, **kw)


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


def test_m4b_kapitelmarken_tragen_satzschreibung(umgebung, tmp_path):
    """Seitentitel eines zweispaltigen PDF stehen in Satzschreibung in der Kapitelliste."""
    quelle = muster_pdf_seitentitel(tmp_path / "seitentitel.pdf")
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, quelle, arbeiter)

    (m4b,) = ergebnis.dateien
    assert [k["tags"]["title"] for k in ffprobe(m4b)["chapters"]] == [
        "Ein Anfang im Garten",
        "Wenn sich Gewohnheiten verändern",
    ]


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

VORSPANN = "Sie hören ein Buch „Das Musterbuch“."
KOPFSEITE = (
    VORSPANN,
    "Es dauert rund eine Minute und hat zwei Abschnitte: „Erstes Kapitel“ und „Zweites Kapitel“.",
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
    # Der Titel spricht die Ansage-Stimme (Spec E2): ohne zweite Stimme ist es die Hauptstimme.
    assert "Ansage-Stimme:** stimme-a_v01 (gleiche Stimme)" in bericht
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

    # Ansagen und Kapiteltitel mit Vorlage und Reglern von stimme-b, alles andere mit stimme-a ...
    titel = {"Erstes Kapitel", "Zweites Kapitel"}
    ansagen = {*KOPFSEITE, ABSPANN, *titel}
    assert {arbeiter.vorlagen[a] for a in ansagen} == {"stimme-b.wav"}
    uebrige = {t for t in arbeiter.vorlagen if t not in ansagen}
    assert uebrige
    assert {arbeiter.vorlagen[t] for t in uebrige} == {"stimme-a.wav"}
    # ... Vorspann- und Abspann-Kapitel (nur Ansagen) mit Klang und Tempo der Ansage-Stimme,
    # in den Kapiteln erst der Titel (Ansage-Stimme), dann der Text.
    assert gemastert == ["stimme-b", "stimme-b", "stimme-a", "stimme-b", "stimme-a", "stimme-b"]
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


def test_kapitel_mit_ueberschrift_ist_kein_ansagekapitel():
    """Eine Zwischenueberschrift ist Quelltext (`QUELL_ARTEN`): das Kapitel zaehlt mit."""
    dok = Dokument(
        "T",
        None,
        "de",
        (
            Kapitel("", ("Sie hören ein Buch.",), ("vorspann",)),
            Kapitel("", ("Ein Zwischentitel",), ("ueberschrift",)),
            Kapitel("", ("Ohne Titel.",)),
        ),
    )
    assert [_kapitelname(dok, k) for k in range(3)] == ["Einleitung", "Kapitel 1", "Kapitel 2"]


def _fremde_importe(paket: Path, teile: tuple[str, ...]) -> list[str]:
    """Importe aus `mkn_audio`, die die Dateien unter `teile` machen, aber `teile` nicht deckt."""
    gedeckt = {t.removesuffix(".py") for t in teile}
    dateien = [
        datei
        for teil in teile
        for datei in ((paket / teil).rglob("*.py") if (paket / teil).is_dir() else [paket / teil])
    ]
    fremd = []
    for datei in dateien:
        paket_davor = ".".join(("mkn_audio", *datei.relative_to(paket).parent.parts))
        for knoten in ast.walk(ast.parse(datei.read_text(encoding="utf-8"))):
            if isinstance(knoten, ast.Import):
                module = [a.name for a in knoten.names]
            elif isinstance(knoten, ast.ImportFrom):
                if knoten.level:  # relativ: vom Paket der Datei aus
                    basis = paket_davor.split(".")[: len(paket_davor.split(".")) - knoten.level + 1]
                    modul = ".".join([*basis, *([knoten.module] if knoten.module else [])])
                else:
                    modul = knoten.module or ""
                # `from mkn_audio import sprache` importiert das Modul `mkn_audio.sprache`
                module = (
                    [f"{modul}.{a.name}" for a in knoten.names] if modul == "mkn_audio" else [modul]
                )
            else:
                continue
            for name in module:
                teil = name.split(".")
                if teil[0] != "mkn_audio":
                    continue
                if len(teil) < 2 or teil[1] not in gedeckt:
                    fremd.append(f"{datei.relative_to(paket)}: {name}")
    return fremd


def _teile_von(konstante: str) -> tuple[str, ...]:
    """Die Teile, aus denen `lauf.py` den Code-Stand `konstante` rechnet (aus dem Quelltext)."""
    baum = ast.parse(Path(lauf_modul.__file__).read_text(encoding="utf-8"))
    for knoten in baum.body:
        if (
            isinstance(knoten, ast.Assign)
            and [getattr(z, "id", None) for z in knoten.targets] == [konstante]
            and isinstance(knoten.value, ast.Call)
        ):
            return ast.literal_eval(knoten.value.args[1])
    raise AssertionError(f"{konstante} nicht in lauf.py gefunden")


def test_lesen_importiert_nur_was_stand_lesen_deckt():
    """Waechter (LP-40): die Lesestufe haengt nur an Code, den `STAND_LESEN` mitrechnet.

    Sonst aendert sich ihr Ergebnis, ohne dass ihr Fingerabdruck es merkt, und ein alter
    Zwischenstand wird weiterverwendet. Geprueft wird jede Datei, die `STAND_LESEN` deckt
    (auch `sprache.py`, wo `satzschreibung` liegt). Mutation: `satzschreibung` importiert aus
    `hoertext` -> rot.
    """
    paket = Path(lauf_modul.__file__).parent
    teile = _teile_von("STAND_LESEN")
    assert "lesen" in teile and "sprache.py" in teile  # Untergrenze: es gibt etwas zu pruefen

    assert _fremde_importe(paket, teile) == []


def test_import_waechter_erkennt_fremden_import(tmp_path):
    """Gegenprobe des Waechters an einer Kopie: ein Import aus `hoertext` faellt auf."""
    (tmp_path / "lesen").mkdir()
    (tmp_path / "lesen" / "a.py").write_text(
        "from mkn_audio.sprache import x\nfrom . import b\nfrom ..typen import Kapitel\n",
        encoding="utf-8",
    )
    (tmp_path / "sprache.py").write_text(
        "def f():\n    from mkn_audio.hoertext.abkuerzungen import wortformen\n"
        "from mkn_audio import gliedern\n",
        encoding="utf-8",
    )
    (tmp_path / "typen.py").write_text("", encoding="utf-8")

    fremd = _fremde_importe(tmp_path, ("lesen", "sprache.py", "typen.py"))

    assert sorted(fremd) == [
        "sprache.py: mkn_audio.gliedern",
        "sprache.py: mkn_audio.hoertext.abkuerzungen",
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
    # Vorspann; Kapitel 1: Titel, Text, Ueberleitung; Kapitel 2: Titel, Text; Abspann.
    vorspann, kapitel1, kapitel2, abspann = ["b"], ["b", "a", "b"], ["b", "a"], ["b"]
    assert gemastert == [f"stimme-{v}" for v in (*vorspann, *kapitel1, *kapitel2, *abspann)]
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


# -- Lauf mit Sprecher auf Bloecken (Plan B2) ---------------------------------------------
# `mkn_audio.sprecher` entsteht mit B2: der Import steht im Test, damit diese Datei bis dahin
# gesammelt wird und nur die neuen Tests rot sind.


def lauf_mit_sprecher(umgebung, quelle, arbeiter, *, sprecher=None, **kw) -> Ergebnis:
    """Wie `lauf`, aber ueber die Sprecher-Schnittstelle; Ansage-Stimme ohne Angabe = Stimme."""
    from mkn_audio.sprecher import SprecherLokal

    t, konfig, ziel = umgebung
    stimme = kw.pop("stimme", t.hole("stimme-a"))
    kw.setdefault("ansage", stimme)
    kw.setdefault("heute", HEUTE)
    kw.setdefault("textmodell", None)
    sprecher = sprecher or SprecherLokal(arbeiter, t.wege["local"])
    return konvertiere(quelle, ziel, stimme, sprecher=sprecher, konfig=konfig, **kw)


def test_lauf_mit_sprecher_lokal_wie_bisher(umgebung, epub):
    """`SprecherLokal` traegt den Lauf wie der Arbeiter vorher; Titel spricht die Ansage-Stimme."""
    t, _, _ = umgebung
    with Zaehler() as arbeiter:
        ergebnis = lauf_mit_sprecher(umgebung, epub, arbeiter, ansage=t.hole("stimme-b"))

    (m4b,) = ergebnis.dateien
    kapitel = ffprobe(m4b)["chapters"]
    assert [k["tags"]["title"] for k in kapitel] == ["Erstes Kapitel", "Zweites Kapitel"]
    assert arbeiter.vorlagen["Erstes Kapitel"] == "stimme-b.wav"
    assert arbeiter.vorlagen["Zweites Kapitel"] == "stimme-b.wav"
    text = {v for satz, v in arbeiter.vorlagen.items() if "Kapitel" not in satz}
    assert text == {"stimme-a.wav"}
    assert (ergebnis.weg, ergebnis.modell, ergebnis.verbrauch) == (
        "local",
        "chatterbox-multilingual",
        None,
    )
    assert "chatterbox-multilingual" in ergebnis.bericht.read_text(encoding="utf-8")


def test_ton_schluessel_je_block_fortsetzen(umgebung, epub):
    """Abbruch nach 3 Bloecken: der zweite Lauf spricht nur den Rest, jede Aufnahme liegt
    unter dem Ton-Schluessel, den der Sprecher fuer ihren Block nennt."""
    from mkn_audio.sprecher import Block, SprecherLokal

    t, konfig, _ = umgebung
    stimme = t.hole("stimme-a")
    with Zaehler() as erst:
        with pytest.raises(Gewichen):
            lauf_mit_sprecher(umgebung, epub, erst, soll_weichen=lambda: len(erst.gesprochen) >= 3)
        assert len(erst.gesprochen) == 3
        assert len(ton_dateien(konfig)) == 3

    with Zaehler() as zweit:
        sprecher = SprecherLokal(zweit, t.wege["local"])
        ergebnis = lauf_mit_sprecher(umgebung, epub, zweit, sprecher=sprecher)

    insgesamt = erst.gesprochen + zweit.gesprochen
    assert zweit.gesprochen  # Untergrenze: es blieb etwas zu sprechen
    assert len(insgesamt) == len(set(insgesamt))
    assert not set(erst.gesprochen) & set(zweit.gesprochen)
    erwartet = {
        sprecher.ton_schluessel(
            Block(nr=0, stueck_nrs=(0,), text=satz, kapitel=0, ansage=False), stimme
        )
        for satz in insgesamt
    }
    assert {p.stem for p in ton_dateien(konfig)} == erwartet
    assert ergebnis.dateien[0].exists()


def test_ohne_hoeren_steht_ungeprueft_im_bericht(umgebung, epub):
    """Kann der Sprecher nicht hoeren, ist die Abschrift ungeprueft -- Warnung, nie Entwarnung."""
    from mkn_audio.sprecher import SprecherLokal

    class OhneOhr(SprecherLokal):
        def kann_hoeren(self) -> bool:
            return False

    t, _, _ = umgebung
    with Zaehler() as arbeiter:
        ergebnis = lauf_mit_sprecher(
            umgebung, epub, arbeiter, sprecher=OhneOhr(arbeiter, t.wege["local"])
        )

    assert arbeiter.gesprochen  # Untergrenze: der Lauf hat gesprochen
    assert arbeiter.gehoert == []
    assert "Abschrift: nicht geprüft (kein Arbeiter)" in ergebnis.bericht.read_text(
        encoding="utf-8"
    )


def test_schema1_hinweis_steht_im_bericht(umgebung, epub):
    """Eine Tabelle im alten Format laeuft, und der Bericht sagt, dass sie gehoben werden soll."""
    with Zaehler() as arbeiter:
        ergebnis = lauf_mit_sprecher(umgebung, epub, arbeiter)

    assert "Schema 1" in ergebnis.bericht.read_text(encoding="utf-8")


def test_lauf_prueft_die_kapitelmarken_der_m4b(umgebung, epub, monkeypatch):
    """Die Marken der fertigen M4B liegen in den Pausen: kein Befund, und gepruft wurde wirklich.

    Untergrenze: der Waechter ist gerufen worden, mit der M4B und einer Marke je Kapitel.
    """
    gerufen: list[tuple[Path, list[float]]] = []
    echt = lauf_modul.pruefe_kapitelmarken

    def merke(audio, marken, **kw):
        gerufen.append((Path(audio), list(marken)))
        return echt(audio, marken, **kw)

    monkeypatch.setattr(lauf_modul, "pruefe_kapitelmarken", merke)
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, epub, arbeiter)

    ((audio, marken),) = gerufen
    assert audio == ergebnis.dateien[0]
    assert len(marken) == 2 and marken[0] == 0.0 and marken[1] > 0
    assert not any("Kapitelmarke" in w for w in ergebnis.warnungen)


def test_kapitelmarken_waechter_liest_die_marken_der_fertigen_datei(umgebung, epub, monkeypatch):
    """Waechter (LP-40): sitzt die Marke in der M4B mitten im Ton, ist das ein Befund.

    Die Marken kommen aus der FERTIGEN Datei (ffprobe), nicht aus der Rechnung des Laufs: wird
    die Rechnung in `verpacken._kapitel_zeiten` um 8 s verschoben, stimmt die Rechnung des Laufs
    weiter, die Datei nicht. Schutzgut: falsche Information (Kapitelsprung mitten in ein Wort).
    Mutation: im Lauf die Marken wieder aus `kapitel_start` nehmen -> dieser Test wird rot.
    """
    import mkn_audio.verpacken as verpacken

    echt = verpacken._kapitel_zeiten

    def verschoben(kapitel, pause_kapitel):
        zeiten, gesamt = echt(kapitel, pause_kapitel)
        (s0, e0), (s1, e1) = zeiten
        return [(s0, e0 + 8000), (s1 + 8000, e1 + 8000)], gesamt

    monkeypatch.setattr(verpacken, "_kapitel_zeiten", verschoben)
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, epub, arbeiter)

    assert any("Kapitelmarke 2 liegt nicht in einer Pause" in w for w in ergebnis.warnungen)


def test_mp3_kapitelmarken_stehen_als_ungeprueft_im_bericht(umgebung, epub):
    """Ein Format ohne Kapitel hat nichts zu pruefen -- und das steht da (LP-32), nie still ok."""
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, epub, arbeiter, format="mp3")

    assert any("Kapitelmarken: ungeprüft (Format ohne Kapitel)" in w for w in ergebnis.warnungen)
    assert "Kapitelmarken: ungeprüft" in ergebnis.bericht.read_text(encoding="utf-8")


def test_m4b_ohne_kapitel_in_der_datei_steht_als_ungeprueft(umgebung, epub, monkeypatch):
    """Liefert ffprobe fuer eine M4B keine Kapitel, ist die Pruefung nicht gelaufen (LP-32)."""
    monkeypatch.setattr(lauf_modul, "lies_kapitelmarken", lambda *a, **kw: ())
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, epub, arbeiter)

    assert any("Kapitelmarken: ungeprüft" in w for w in ergebnis.warnungen)


def test_kapitelmarke_ausserhalb_der_pause_steht_im_bericht(umgebung, epub, monkeypatch):
    """Meldet der Waechter einen Befund, steht er als Hinweis im Bericht -- nie still."""
    monkeypatch.setattr(
        lauf_modul,
        "pruefe_kapitelmarken",
        lambda *a, **kw: ("Kapitelmarke 2 liegt nicht in einer Pause (bei 00:07)",),
    )
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, epub, arbeiter)

    assert "Kapitelmarke 2 liegt nicht in einer Pause" in ergebnis.bericht.read_text(
        encoding="utf-8"
    )
    assert any("Kapitelmarke 2" in w for w in ergebnis.warnungen)


# -- Lauf auf dem Weg gemini (Plan C2) ------------------------------------------------------
# Der Sprecher ist `SprecherGemini` am Schein-Transport (`schein_google`), Uhr und Schlaf sind
# eingespeist. ffmpeg und ffprobe laufen echt wie bei den lokalen Laeufen. `mkn_audio.gemini`
# entsteht mit Plan C1; der Import steht darum in `lauf_gemini`.

SAETZE = (
    "Der Gärtner gießt am Morgen die Rosen.",
    "Die Amsel singt im hohen Kirschbaum.",
    "Am Nachmittag ruht er unter der Linde.",
    "Ein Igel raschelt im trockenen Laub.",
)
LANG_SATZ = (
    "Der alte Gärtner geht am frühen Morgen durch den stillen Garten "
    "und schaut lange nach den Rosen am {tag}."
)
TAGE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag")
FUCHS = (
    "Ein roter Fuchs schleicht am frühen Morgen durch den stillen Garten "
    "und schaut lange nach den Hühnern im Stall."
)


@pytest.fixture
def umgebung_gemini(tmp_path):
    """Tabelle Schema 2 (Gemini-Standard Charon/Kore), Konfiguration, Arbeits- und Zielort."""
    from schein_google import schreibe_tabelle_schema2

    tabelle = schreibe_tabelle_schema2(tmp_path)
    konfig = Konfig(
        stimmen_tabelle=tabelle,
        arbeitsort=tmp_path / "arbeit",
        arbeiter_python=Path(sys.executable),
    )
    ziel = tmp_path / "ziel"
    ziel.mkdir()
    return lade_tabelle(tabelle), konfig, ziel


def md_quelle(ordner: Path, *absaetze: str, name: str = "garten.md") -> Path:
    """Eine Markdown-Quelle: ein Kapitel »Gartenjahr« mit diesen Absaetzen."""
    pfad = ordner / name
    pfad.write_text("# Gartenjahr\n\n" + "\n\n".join(absaetze) + "\n", encoding="utf-8")
    return pfad


def lauf_gemini(umgebung, quelle, schein, *, weg=None, verbrauch=None, vorbereiten=None, **kw):
    """Der Lauf mit `SprecherGemini`; Text- und Ansage-Stimme aus `[standard.gemini.de]`.

    Gibt `(Ergebnis, Sprecher, Uhr)` zurueck. `weg` ersetzt die `WegKonfig` der Tabelle (so
    setzt das PKA Katalogpreise), `vorbereiten(sprecher)` laeuft vor dem Lauf.
    """
    from mkn_audio.gemini import SprecherGemini
    from schein_google import Uhr

    t, konfig, ziel = umgebung
    text, ansage, _ = t.standard_fuer("gemini", "de")
    uhr = Uhr()
    sprecher = SprecherGemini(
        schluessel="nur-ein-test",
        konfig=weg or t.wege["gemini"],
        transport=schein,
        uhr=uhr,
        schlaf=uhr.schlaf,
        verbrauch=verbrauch,
    )
    if vorbereiten is not None:
        vorbereiten(sprecher)
    kw.setdefault("heute", HEUTE)
    kw.setdefault("textmodell", None)
    ergebnis = konvertiere(
        quelle, ziel, text, sprecher=sprecher, ansage=ansage, konfig=konfig, **kw
    )
    return ergebnis, sprecher, uhr


def _saetze_in(text: str) -> int:
    return sum(s in text for s in SAETZE)


def test_sperre_einmal_wiederholung_spricht(umgebung_gemini, tmp_path):
    """Eine Sperre ist nicht deterministisch: der erste Schritt ist EINE Wiederholung."""
    from schein_google import ScheinGoogle, sperre, text_von

    gesperrt = []

    def regel(n, rumpf):
        if _saetze_in(text_von(rumpf)) == 4 and not gesperrt:
            gesperrt.append(n)
            return sperre()
        return None

    schein = ScheinGoogle(regel=regel)
    ergebnis, _, _ = lauf_gemini(umgebung_gemini, md_quelle(tmp_path, " ".join(SAETZE)), schein)

    assert schein.status.count(400) == 1
    assert [_saetze_in(t) for t in schein.texte if _saetze_in(t)] == [4, 4]  # nicht geteilt
    assert ergebnis.dateien[0].exists()
    assert "Sperren: 1 (durch Wiederholung gelöst)" in ergebnis.bericht.read_text(encoding="utf-8")


def test_sperre_teilt_in_zwei_dann_vier(umgebung_gemini, tmp_path):
    """Bleibt die Sperre, wird an Satzgrenzen in 2, dann in 4 Teile geteilt. Die Teile liegen
    unter eigenen Ton-Schluesseln; der Block bleibt die Einheit des Berichts."""
    from mkn_audio.sprecher import Block
    from schein_google import ScheinGoogle, sperre, text_von

    schein = ScheinGoogle(regel=lambda n, r: sperre() if _saetze_in(text_von(r)) >= 2 else None)
    ergebnis, sprecher, _ = lauf_gemini(
        umgebung_gemini, md_quelle(tmp_path, " ".join(SAETZE)), schein
    )

    gesprochen = [t.strip() for t, st in zip(schein.texte, schein.status, strict=True) if st == 200]
    assert sorted(t for t in gesprochen if t in SAETZE) == sorted(SAETZE)  # vier Viertel
    assert schein.status.count(200) == 5  # Titel + vier Teile
    assert sum(1 for t in schein.texte if _saetze_in(t) == 2) >= 2  # die Haelften wurden versucht
    _, konfig, _ = umgebung_gemini
    abgelegt = {p.stem for p in konfig.arbeitsort.glob("*/ton/*.wav")}
    charon = umgebung_gemini[0].hole("deutsch-gemini-charon")
    for satz in SAETZE:
        # Critic R B9: die Teile sprechen unter ihren Schluesseln, bleiben aber nicht liegen
        teil = Block(nr=0, stueck_nrs=(0,), text=satz, kapitel=0, ansage=False)
        assert sprecher.ton_schluessel(teil, charon) not in abgelegt, satz
    assert len(abgelegt) == 2  # Titel und der ganze Block
    assert not list(konfig.arbeitsort.glob("*/ton/.mkn-mp4-*"))  # Arbeitsordner geraeumt
    bericht = ergebnis.bericht.read_text(encoding="utf-8")
    assert "**Blöcke:** 2" in bericht  # Titel und Text, nicht sechs
    assert "Sperren: 1 (durch Teilen gelöst)" in bericht


def test_sperre_bleibt_nach_vier_teilen_bricht_laut_mit_stelle(umgebung_gemini, tmp_path):
    """Review Focus 1: ein Block, den Google sperrt und der auch geteilt gesperrt bleibt -- der
    Lauf bricht laut ab und nennt Kapitel, Block und erste Woerter; niemals Stille, niemals
    ein zweites Modell. Der gesperrte Satz steht vorn: Blockanfang und Stelle fallen zusammen.
    """
    import re

    from mkn_audio.sprecher import SprecherFehler
    from schein_google import MODELL, ScheinGoogle, sperre, text_von

    _, _, ziel = umgebung_gemini
    schein = ScheinGoogle(regel=lambda n, r: sperre() if SAETZE[0] in text_von(r) else None)

    with pytest.raises(SprecherFehler) as info:
        lauf_gemini(umgebung_gemini, md_quelle(tmp_path, " ".join(SAETZE)), schein)

    meldung = str(info.value)
    assert info.value.klasse == "Sperre"
    assert "Gartenjahr" in meldung or re.search(r"Kapitel\s+1\b", meldung), meldung
    assert re.search(r"Block\s+\d+", meldung), meldung
    assert "Der Gärtner gießt" in meldung
    assert schein.modelle == {MODELL}  # genau EINE Modell-ID in allen Ruempfen
    assert any(t.strip() == SAETZE[0] for t in schein.texte)  # bis auf den Einzelsatz geteilt
    assert list(ziel.iterdir()) == []  # kein Hoerstueck mit Stille an der Stelle


def test_fehlerantwort_viermal_dann_stille(umgebung_gemini, tmp_path):
    """500 viermal (Wartezeit 20 s): Stille der erwarteten Dauer und Befund, kein Abbruch.

    Die Erwartung ist `len(text) / 16` (Spec 8.3): der Lauf hat keinen Median, weil kein Block
    100 Zeichen erreicht -- die feste lokale Rate (14 Z/s) waere hier falsch.
    """
    from mkn_audio.sprecher import Block
    from schein_google import ScheinGoogle, fehler, text_von

    absatz = "Der Gärtner gießt am Morgen die Rosen im Garten hinter dem alten Haus."
    schein = ScheinGoogle(regel=lambda n, r: fehler(500) if "Rosen" in text_von(r) else None)
    ergebnis, sprecher, uhr = lauf_gemini(umgebung_gemini, md_quelle(tmp_path, absatz), schein)

    assert schein.anfragen_mit("Rosen") == 4
    assert sum(uhr.schlaefe) == 3 * 20
    assert "nicht gesprochen (Fehlerantwort)" in ergebnis.bericht.read_text(encoding="utf-8")
    gesendet = next(t for t in schein.texte if "Rosen" in t)
    charon = umgebung_gemini[0].hole("deutsch-gemini-charon")
    schluessel = sprecher.ton_schluessel(Block(0, (0,), gesendet, 0, False), charon)
    (stille,) = umgebung_gemini[1].arbeitsort.glob(f"*/ton/{schluessel}.wav")
    assert _wav_dauer(stille) == pytest.approx(len(gesendet) / 16, abs=0.05)
    assert ergebnis.dateien[0].exists()


def _fuchs_regel(erster: float, zweiter: float):
    """Der Fuchs-Absatz kommt beim ersten Mal mit `erster` x, danach mit `zweiter` x der
    erwarteten Dauer (16 Z/s); alle anderen Bloecke genau mit 16 Z/s."""
    from schein_google import text_von

    wuerfe = []

    def regel(n, rumpf):
        text = text_von(rumpf)
        if "Fuchs" not in text:
            return None
        wuerfe.append(n)
        return (erster if len(wuerfe) == 1 else zweiter) * len(text) / 16

    return regel


@pytest.mark.parametrize(
    ("erster", "zweiter", "laut"),
    [(0.6, 0.6, True), (0.9, 0.9, False), (0.6, 1.0, False)],
    ids=["zweimal-ausserhalb", "im-band", "neu-gesprochen-im-band"],
)
def test_ausreisser_neu_dann_laut(umgebung_gemini, tmp_path, erster, zweiter, laut):
    """Waechter (LP-40): ein Block ausserhalb 0,75-1,3 des Lauf-Medians wird einmal neu
    gesprochen; liegt er wieder ausserhalb, bricht der Lauf laut mit Stelle ab.

    Schutzgut: falsche Information (ein 140-s-Block ist Wiederholungs- oder
    Halluzinationsverdacht, Spec 8.3). Sechs Absaetze zu je einem Satz ueber 100 Zeichen,
    `block_zeichen` 130: jeder Absatz ein Block, Median 16 Z/s. Mutation (nach C2 GREEN,
    Auftrag 08): `WEGE["gemini"].pruefband` auf (0.5, 1.3) -> der Fall `zweimal-ausserhalb`
    wird rot.
    """
    import re

    from mkn_audio.sprecher import SprecherFehler
    from mkn_audio.stimmen import WegKonfig
    from schein_google import MODELL, ScheinGoogle

    absaetze = [LANG_SATZ.format(tag=t) for t in TAGE[:3]] + [FUCHS]
    absaetze += [LANG_SATZ.format(tag=t) for t in TAGE[3:]]
    quelle = md_quelle(tmp_path, *absaetze)
    schein = ScheinGoogle(regel=_fuchs_regel(erster, zweiter))
    weg = WegKonfig(modell=MODELL, block_zeichen=130)

    if laut:
        with pytest.raises(SprecherFehler) as info:
            lauf_gemini(umgebung_gemini, quelle, schein, weg=weg)
        meldung = str(info.value)
        assert info.value.klasse == "Ausreisser"
        assert "Gartenjahr" in meldung or re.search(r"Kapitel\s+1\b", meldung), meldung
        assert re.search(r"Block\s+\d+", meldung), meldung
        assert "Ein roter Fuchs" in meldung
    else:
        ergebnis, _, _ = lauf_gemini(umgebung_gemini, quelle, schein, weg=weg)
        assert ergebnis.dateien[0].exists()
    assert len(schein.texte) == 1 + 7 + (erster != 0.9)  # Titel, sieben Bloecke, Neusprechen
    assert schein.anfragen_mit("Fuchs") == (1 if erster == 0.9 else 2)


def test_nach_ausreisser_abbruch_spricht_der_naechste_lauf_den_block_frisch(
    umgebung_gemini, tmp_path
):
    """Schutzgut falsche Information: nach dem Abbruch stehen weder die Aufnahme des zweiten
    Wurfs noch die Messwerte des ersten im Zwischenstand -- ein Fortsetzen misst sonst Ton und
    Zahl, die nicht zusammengehoeren. Der zweite Lauf spricht genau diesen Block neu (jetzt im
    Band) und hat danach nichts mehr neu zu sprechen.
    """
    from mkn_audio.sprecher import SprecherFehler
    from mkn_audio.stimmen import WegKonfig
    from schein_google import MODELL, ScheinGoogle

    absaetze = [LANG_SATZ.format(tag=t) for t in TAGE[:3]] + [FUCHS]
    absaetze += [LANG_SATZ.format(tag=t) for t in TAGE[3:]]
    quelle = md_quelle(tmp_path, *absaetze)
    weg = WegKonfig(modell=MODELL, block_zeichen=130)

    erster = ScheinGoogle(regel=_fuchs_regel(0.6, 0.6))
    with pytest.raises(SprecherFehler) as info:
        lauf_gemini(umgebung_gemini, quelle, erster, weg=weg)
    assert info.value.klasse == "Ausreisser"

    zweiter = ScheinGoogle(regel=_fuchs_regel(1.0, 1.0))
    ergebnis, _, _ = lauf_gemini(umgebung_gemini, quelle, zweiter, weg=weg)

    assert zweiter.anfragen_mit("Fuchs") == 1  # frisch gesprochen, im Band
    assert len(zweiter.texte) == 1  # alle anderen Bloecke kamen aus dem Zwischenstand
    bericht = ergebnis.bericht.read_text(encoding="utf-8")
    assert "Neu gesprochen nach der Prüfung (Ausreißer): 0" in bericht


def test_verbrauch_je_antwort_mit_audio(umgebung_gemini, tmp_path):
    """Je Antwort mit Audio genau ein Rueckruf: Teile einer Sperre, Neusprechen und Startprobe
    zaehlen, gesperrte Anfragen (400) und Treffer im Zwischenstand nie. `Ergebnis.verbrauch`
    zaehlt nur die Anfragen DIESES Aufrufs.
    """
    from mkn_audio.stimmen import WegKonfig
    from schein_google import MODELL, ScheinGoogle, sperre, text_von

    def merker(liste):
        return lambda *a, **kw: liste.append(a[0] if a else kw.get("modell"))

    gesperrt_zwei = " ".join(SAETZE[:2])  # beide Saetze zusammen gesperrt, einzeln frei
    quelle = md_quelle(tmp_path, gesperrt_zwei, *(LANG_SATZ.format(tag=t) for t in TAGE[:5]), FUCHS)
    fuchs = _fuchs_regel(0.6, 1.0)

    def regel(n, rumpf):
        if _saetze_in(text_von(rumpf)) == 2:
            return sperre()
        return fuchs(n, rumpf)

    weg = WegKonfig(modell=MODELL, block_zeichen=130)
    schein = ScheinGoogle(regel=regel)
    rueckrufe: list[str] = []
    ergebnis, _, _ = lauf_gemini(
        umgebung_gemini, quelle, schein, weg=weg, verbrauch=merker(rueckrufe)
    )

    assert schein.status.count(400) >= 2  # Erstversuch und Wiederholung: kein Rueckruf
    assert any(t.strip() == SAETZE[0] for t in schein.texte)  # Teile gesprochen
    assert schein.anfragen_mit("Fuchs") == 2  # Neusprechen
    assert len(rueckrufe) == schein.status.count(200)
    assert set(rueckrufe) == {MODELL}
    assert ergebnis.verbrauch is not None
    assert ergebnis.verbrauch.anfragen == len(rueckrufe)

    # Startprobe: ein Rueckruf je Stimme.
    from mkn_audio.gemini import SprecherGemini

    probe: list[str] = []
    t, _, _ = umgebung_gemini
    SprecherGemini(
        schluessel="nur-ein-test", konfig=weg, transport=ScheinGoogle(), verbrauch=merker(probe)
    ).startprobe(list(t.standard_fuer("gemini", "de")[:2]))
    assert len(probe) == 2

    # Fortsetzen: alles liegt im Zwischenstand -- keine Anfrage, kein Rueckruf.
    schein2 = ScheinGoogle(regel=regel)
    zweiter: list[str] = []
    ergebnis2, _, _ = lauf_gemini(
        umgebung_gemini, quelle, schein2, weg=weg, verbrauch=merker(zweiter)
    )
    assert schein2.ruempfe == []
    assert zweiter == []
    assert ergebnis2.verbrauch is not None and ergebnis2.verbrauch.anfragen == 0


def _mit_token(faktor: float = 1.0):
    """Laesst `lies_antwort` Token melden: Audio-Token = 25 je Sekunde x `faktor`.

    Die Feldnamen der echten Antwort liest C1 aus einer echten Antwort (HC-10); der Test haengt
    darum an der Schnittstelle `lies_antwort -> (daten, mime, token)`, nicht an Feldnamen.
    """

    def vorbereiten(sprecher):
        echt = sprecher.lies_antwort

        def lies(antwort):
            daten, mime, token = echt(antwort)
            sekunden = len(daten) / 48_000  # PCM 16 bit mono 24 kHz
            audio = round(25 * sekunden * faktor)
            return daten, mime, {**token, "tokens_text": 100, "tokens_audio": audio}

        sprecher.lies_antwort = lies

    return vorbereiten


def test_kosten_schaetzung_und_ausweis(umgebung_gemini, tmp_path):
    """Schaetzung vor dem Sprechen, Ausweis nach dem Lauf mit Preisstand -- und ohne Preise
    oder ohne Token-Angabe ein Satz statt einer Zahl (LP-32)."""
    from datetime import date

    from mkn_audio.gemini import schaetze_kosten_usd
    from mkn_audio.stimmen import WegKonfig
    from schein_google import MODELL, ScheinGoogle

    mit_preisen = WegKonfig(
        modell=MODELL,
        preis_usd_je_1m_text_token=1.00,
        preis_usd_je_1m_audio_token=20.00,
        preisstand=date(2026, 10, 30),
    )
    ohne_preise = WegKonfig(modell=MODELL)
    assert schaetze_kosten_usd(131_000, mit_preisen) == pytest.approx(4.13, abs=0.01)
    assert schaetze_kosten_usd(131_000, ohne_preise) is None

    # Die Preise kommen aus der WegKonfig des Sprechers (so setzt das PKA Katalogpreise), nicht
    # aus der Tabelle -- die Tabelle dieses Tests hat keine.
    erst, _, _ = lauf_gemini(
        umgebung_gemini,
        md_quelle(tmp_path, SAETZE[0], name="eins.md"),
        ScheinGoogle(),
        weg=mit_preisen,
        vorbereiten=_mit_token(),
    )
    bericht = erst.bericht.read_text(encoding="utf-8")
    assert "USD" in bericht and "2026-10-30" in bericht

    zweit, _, _ = lauf_gemini(
        umgebung_gemini,
        md_quelle(tmp_path, SAETZE[1], name="zwei.md"),
        ScheinGoogle(),
        weg=ohne_preise,
        vorbereiten=_mit_token(),
    )
    assert "Preise nicht konfiguriert" in zweit.bericht.read_text(encoding="utf-8")

    dritt, _, _ = lauf_gemini(
        umgebung_gemini,
        md_quelle(tmp_path, SAETZE[2], name="drei.md"),
        ScheinGoogle(),
        weg=mit_preisen,
    )
    assert "Token nicht gemeldet" in dritt.bericht.read_text(encoding="utf-8")


@pytest.mark.parametrize(("faktor", "warnt"), [(1.10, True), (1.02, False)])
def test_token_gegen_dauer_warnt_ab_fuenf_prozent(umgebung_gemini, tmp_path, faktor, warnt):
    """Audio-Token / 25 muss der gemessenen Dauer auf +-5 % entsprechen, sonst Warnung."""
    from schein_google import ScheinGoogle

    ergebnis, _, _ = lauf_gemini(
        umgebung_gemini,
        md_quelle(tmp_path, " ".join(SAETZE)),
        ScheinGoogle(),
        vorbereiten=_mit_token(faktor),
    )

    assert any("Token" in w for w in ergebnis.warnungen) is warnt, ergebnis.warnungen


# -- Datenschutz-Hinweis im Lauf (Plan C3) --------------------------------------------------
# Die Kontaktangabe ist erfunden; eine E-Mail-Adresse zaehlt immer (Spec 9), auch ohne Regie.

KONTAKT = "Antworten bitte an erika@beispiel.example bis Ende der Woche."


def test_lauf_gemini_ohne_cloud_ok_bricht_vor_erster_anfrage(umgebung_gemini, tmp_path):
    """Hinweise und keine Freigabe: `RueckfrageNoetig` VOR der ersten Anfrage an Google --
    sonst waere der Text schon gesendet, wenn die Frage kommt."""
    from mkn_audio.typen import Mp4Fehler
    from mkn_audio.vertraulich import RueckfrageNoetig
    from schein_google import ScheinGoogle

    _, _, ziel = umgebung_gemini
    quelle = md_quelle(tmp_path, SAETZE[0], KONTAKT)
    gesehen: list[tuple] = []

    def frage(hinweise) -> bool:
        gesehen.append(tuple(hinweise))
        return False

    for cloud_ok in (False, frage):
        schein = ScheinGoogle()
        with pytest.raises(RueckfrageNoetig):
            lauf_gemini(umgebung_gemini, quelle, schein, cloud_ok=cloud_ok)
        assert schein.ruempfe == []  # Transport-Zaehler 0
    assert issubclass(RueckfrageNoetig, Mp4Fehler)
    ((hinweis,),) = gesehen
    assert hinweis.klasse == "Kontaktdaten"
    assert list(ziel.iterdir()) == []


def test_lauf_gemini_mit_cloud_ok_nennt_hinweise_im_bericht(umgebung_gemini, tmp_path):
    """Mit Freigabe wird gesprochen, und der Bericht nennt die Hinweise -- maskiert."""
    from schein_google import ScheinGoogle

    schein = ScheinGoogle()
    ergebnis, _, _ = lauf_gemini(
        umgebung_gemini, md_quelle(tmp_path, SAETZE[0], KONTAKT), schein, cloud_ok=True
    )

    bericht = ergebnis.bericht.read_text(encoding="utf-8")
    assert schein.ruempfe  # Untergrenze: es wurde gesprochen
    assert "Datenschutz-Hinweise" in bericht
    assert "Kontaktdaten" in bericht
    assert "erika@beispiel.example" not in bericht


def test_lauf_local_prueft_nicht(umgebung, tmp_path):
    """Der lokale Weg sendet keinen Text an Google: keine Erkennung, keine Rueckfrage."""
    quelle = md_quelle(tmp_path, SAETZE[0], KONTAKT)
    with Zaehler() as arbeiter:
        ergebnis = lauf(umgebung, quelle, arbeiter, cloud_ok=False)

    assert ergebnis.dateien[0].exists()
    assert "Datenschutz" not in ergebnis.bericht.read_text(encoding="utf-8")


# -- Nacharbeit R: textgleiche Bloecke (B5), Teil-Aufnahmen (B9) -----------------------------


def test_textgleiche_bloecke_derselben_stimme_werden_einmal_gesprochen(umgebung_gemini, tmp_path):
    """Critic R B5: zwei Zwischentitel gleichen Wortlauts teilen sich den inhaltsadressierten
    Ton-Schluessel. Bei `parallel` 3 sprach der Lauf beide gleichzeitig auf dieselbe Datei
    (FileNotFoundError beim Umbenennen, sonst doppelt bezahlt). Jetzt: eine Anfrage, beide
    Bloecke mit Ton und denselben Messwerten.
    Mutation (rot): die Entdoppelung in `lauf.py` entfernen (Auftraege je Block statt je
    Schluessel).
    """
    from schein_google import ScheinGoogle

    schein = ScheinGoogle(verzoegerung_s=0.05)
    quelle = md_quelle(
        tmp_path,
        "Der Gärtner gießt am Morgen die Rosen.",
        "## Zusammenfassung",
        "Die Amsel singt im hohen Kirschbaum.",
        "## Zusammenfassung",
        "Ein Igel raschelt im trockenen Laub.",
        "## Zusammenfassung",
        "Am Nachmittag ruht er unter der Linde.",
    )

    ergebnis, _, _ = lauf_gemini(umgebung_gemini, quelle, schein)

    assert ergebnis.dateien[0].exists()
    assert schein.anfragen_mit("Zusammenfassung") == 1  # einmal gesprochen, einmal bezahlt


def test_textgleiche_ausreisser_werden_einmal_neu_gesprochen(umgebung_gemini, tmp_path):
    """Critic R B5, Pruefung: zwei Bloecke gleichen Wortlauts sind EINE Aufnahme. Liegt sie
    ausserhalb des Bands, wird sie einmal neu gesprochen (nicht je Block) und der neue Wurf
    gilt fuer beide Bloecke.
    Mutation (rot): in `lauf.py` die Entdoppelung der Pruefbloecke entfernen -> vier statt
    zwei Fuchs-Anfragen.
    """
    from mkn_audio.stimmen import WegKonfig
    from schein_google import MODELL, ScheinGoogle

    absaetze = [LANG_SATZ.format(tag=t) for t in TAGE[:4]] + [FUCHS, FUCHS]
    quelle = md_quelle(tmp_path, *absaetze)
    schein = ScheinGoogle(regel=_fuchs_regel(0.6, 1.0))
    weg = WegKonfig(modell=MODELL, block_zeichen=130)

    ergebnis, _, _ = lauf_gemini(umgebung_gemini, quelle, schein, weg=weg)

    assert ergebnis.dateien[0].exists()
    assert schein.anfragen_mit("Fuchs") == 2  # einmal gesprochen (zu kurz), einmal neu


def test_teil_aufnahmen_treffen_keine_datei_eines_anderen_blocks(tmp_path):
    """Critic R B9: ein Teil, dessen Text einem anderen Block derselben Stimme gleicht, darf
    dessen Aufnahme nicht ueberschreiben (die Teile lagen inhaltsadressiert neben dem Ziel) und
    keine Teil-WAV hinterlassen.
    Mutation (rot): in `gemini.py` die Teil-Aufnahme wieder neben das Ziel schreiben.
    """
    from mkn_audio.gemini import SprecherGemini
    from mkn_audio.sprecher import Block
    from mkn_audio.stimmen import WegKonfig
    from schein_google import MODELL, ScheinGoogle, gemini_stimme, sperre, text_von

    schein = ScheinGoogle(regel=lambda n, r: sperre() if _saetze_in(text_von(r)) >= 2 else None)
    sprecher = SprecherGemini(
        schluessel="nur-ein-test",
        konfig=WegKonfig(modell=MODELL),
        transport=schein,
        schlaf=lambda s: None,
    )
    stimme = gemini_stimme()
    ganz = Block(nr=1, stueck_nrs=(1,), text=" ".join(SAETZE), kapitel=0, ansage=False)
    fremd = Block(nr=2, stueck_nrs=(2,), text=SAETZE[0], kapitel=0, ansage=False)
    ordner = tmp_path / "ton"
    ordner.mkdir()
    fremde_datei = ordner / f"{sprecher.ton_schluessel(fremd, stimme)}.wav"
    fremde_datei.write_bytes(b"aufnahme-eines-anderen-blocks")
    ziel = ordner / f"{sprecher.ton_schluessel(ganz, stimme)}.wav"

    sprecher.sprich(ganz, stimme, ziel)

    assert schein.status.count(200) == 4  # vier Viertel gesprochen
    assert fremde_datei.read_bytes() == b"aufnahme-eines-anderen-blocks"
    assert sorted(p.name for p in ordner.iterdir()) == sorted([fremde_datei.name, ziel.name])
