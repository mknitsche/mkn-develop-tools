"""Verpacken: M4B mit Kapitelmarken, MP3 je Kapitel, Ausgabenamen.

Geprueft wird mit ffprobe an der fertigen Datei: Kapitel, Tags, Streams -- nicht an der
Befehlszeile, die sie erzeugt hat.
"""

from __future__ import annotations

import struct
import subprocess
import unicodedata
import zlib
from pathlib import Path

import pytest

from mkn_audio.mastern import master
from mkn_audio.typen import Dokument, Kapitel, Mp4Fehler
from mkn_audio.verpacken import ausgabe_name, m4b, mp3
from test_mastern import dauer, ffprobe, lautheit, mache_stimme, schreibe_sinus


def mache_png() -> bytes:
    def chunk(art: bytes, daten: bytes) -> bytes:
        rumpf = art + daten
        return struct.pack(">I", len(daten)) + rumpf + struct.pack(">I", zlib.crc32(rumpf))

    zeilen = b"".join(b"\x00" + b"\xff\x00\x00" * 8 for _ in range(8))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(zeilen))
        + chunk(b"IEND", b"")
    )


def mache_jpeg(pfad: Path) -> bytes:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=16x16",
         "-frames:v", "1", str(pfad)],
        check=True,
    )  # fmt: skip
    return pfad.read_bytes()


def mache_dok(
    cover: bytes | None = None, titel: str = "Testbuch", autor: str | None = "Erika Muster"
):
    return Dokument(
        titel=titel,
        autor=autor,
        sprache="de",
        kapitel=(Kapitel("Eins", ("a",)), Kapitel("Zwei", ("b",))),
        cover=cover,
    )


@pytest.fixture
def zwei_kapitel(tmp_path):
    a = schreibe_sinus(tmp_path / "a.wav", 3.0, moduliert=True)
    b = schreibe_sinus(tmp_path / "b.wav", 2.0, moduliert=True)
    return [("Kapitel Eins", a), ("Kapitel Zwei", b)]


# -- m4b ------------------------------------------------------------------------------


def test_m4b_bleibt_nach_der_kodierung_unter_null_dbtp(tmp_path):
    """Die Kapitel kommen gemastert (True Peak <= -1,5 dBTP), der AAC-Kodierer setzt
    Ueberschwinger obendrauf -- bei harten Hochton-Einsaetzen (hier 8-kHz-Stoesse wie Zischlaute
    der Sprachsynthese) bis ueber 0 dBTP. Nach dem Verpacken bleibt die Spitze darunter und die
    Lautheit beim Master. Schutzgut: falsche Ausgabe (Uebersteuerung im Player)."""
    roh = tmp_path / "roh.wav"
    stoesse = "0.2*sin(2*PI*180*t)+0.8*sin(2*PI*8000*t)*lt(mod(t\\,0.5)\\,0.03)"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", f"aevalsrc='{stoesse}':s=24000", "-t", "10", "-c:a", "pcm_s16le", str(roh)],
        check=True,
    )  # fmt: skip
    gemastert = tmp_path / "kapitel.wav"
    master(roh, mache_stimme(), gemastert)
    lautheit_master, spitze_master = lautheit(gemastert)
    assert spitze_master <= -1.4  # Untergrenze: die Quelle ist regelgerecht gemastert
    ziel = tmp_path / "buch.m4b"

    m4b([("Eins", gemastert)], mache_dok(), ziel, pause_kapitel=0.0)

    lautheit_m4b, spitze_m4b = lautheit(ziel)
    assert spitze_m4b < 0.0
    assert lautheit_m4b == pytest.approx(lautheit_master, abs=1.0)


def test_m4b_kapitelmarken_und_titel(tmp_path, zwei_kapitel):
    ziel = tmp_path / "buch.m4b"

    ergebnis = m4b(zwei_kapitel, mache_dok(), ziel, pause_kapitel=2.0)

    assert ergebnis == ziel
    info = ffprobe("-show_chapters", "-show_format", "-show_streams", str(ziel))
    kapitel = info["chapters"]
    assert [k["tags"]["title"] for k in kapitel] == ["Kapitel Eins", "Kapitel Zwei"]
    assert float(kapitel[0]["start_time"]) == pytest.approx(0.0, abs=0.01)
    assert float(kapitel[1]["start_time"]) == pytest.approx(3.0 + 2.0, abs=0.01)
    assert float(kapitel[1]["end_time"]) == pytest.approx(3.0 + 2.0 + 2.0, abs=0.1)
    tags = {k.lower(): v for k, v in info["format"]["tags"].items()}
    assert tags["title"] == "Testbuch"
    assert tags["artist"] == "Erika Muster"
    assert tags["album"] == "Testbuch"
    assert tags["genre"] == "H\u00f6rbuch"
    strom = info["streams"][0]
    assert (strom["codec_name"], strom["channels"], strom["sample_rate"]) == ("aac", 1, "24000")
    # ABR-Ziel 64 kbit/s: ein einfaches Testsignal bleibt darunter, ueber 70 darf nichts liegen
    assert 20_000 <= int(strom["bit_rate"]) <= 70_000
    assert float(info["format"]["duration"]) == pytest.approx(7.0, abs=0.2)
    assert [p.name for p in tmp_path.glob("*.teil")] == []


def test_m4b_ohne_cover_hat_keinen_bildstrom(tmp_path, zwei_kapitel):
    ziel = tmp_path / "buch.m4b"

    m4b(zwei_kapitel, mache_dok(cover=None), ziel, pause_kapitel=1.0)

    arten = [s["codec_type"] for s in ffprobe("-show_streams", str(ziel))["streams"]]
    # `data`: die Kapitel-Textspur, die ffmpeg fuer QuickTime/Apple-Player zusaetzlich schreibt
    assert arten == ["audio", "data"]


@pytest.mark.parametrize("art", ["png", "jpg"])
def test_m4b_cover_als_attached_pic(tmp_path, zwei_kapitel, art):
    cover = mache_png() if art == "png" else mache_jpeg(tmp_path / "c.jpg")
    ziel = tmp_path / "buch.m4b"

    m4b(zwei_kapitel, mache_dok(cover=cover), ziel, pause_kapitel=1.0)

    bild = [s for s in ffprobe("-show_streams", str(ziel))["streams"] if s["codec_type"] == "video"]
    assert len(bild) == 1
    assert bild[0]["disposition"]["attached_pic"] == 1


def test_m4b_unbekanntes_cover_bricht_laut(tmp_path, zwei_kapitel):
    with pytest.raises(Mp4Fehler, match="Cover"):
        m4b(zwei_kapitel, mache_dok(cover=b"kein bild"), tmp_path / "b.m4b", pause_kapitel=1.0)
    assert not (tmp_path / "b.m4b").exists()


def test_m4b_sonderzeichen_im_kapiteltitel(tmp_path):
    a = schreibe_sinus(tmp_path / "a.wav", 1.0)
    titel = "A=B; C#D \\ E"
    ziel = tmp_path / "buch.m4b"

    m4b([(titel, a)], mache_dok(titel="Wer=Wie; #1"), ziel, pause_kapitel=1.0)

    info = ffprobe("-show_chapters", "-show_format", str(ziel))
    assert info["chapters"][0]["tags"]["title"] == titel
    assert info["format"]["tags"]["title"] == "Wer=Wie; #1"


def test_m4b_autor_fehlt_setzt_keinen_artist(tmp_path, zwei_kapitel):
    ziel = tmp_path / "buch.m4b"

    m4b(zwei_kapitel, mache_dok(autor=None), ziel, pause_kapitel=1.0)

    tags = ffprobe("-show_format", str(ziel))["format"]["tags"]
    assert "artist" not in {k.lower() for k in tags}


def test_m4b_ohne_kapitel_bricht(tmp_path):
    with pytest.raises(Mp4Fehler, match="Kapitel"):
        m4b([], mache_dok(), tmp_path / "b.m4b", pause_kapitel=1.0)


def test_m4b_fehlende_wav_bricht_ohne_halbe_datei(tmp_path, zwei_kapitel):
    kapitel = [*zwei_kapitel, ("Drei", tmp_path / "gibtsnicht.wav")]

    with pytest.raises(Mp4Fehler, match="gibtsnicht"):
        m4b(kapitel, mache_dok(), tmp_path / "b.m4b", pause_kapitel=1.0)
    assert sorted(p.name for p in tmp_path.glob("*.m4b*")) == []


def test_m4b_andere_abtastrate_bricht(tmp_path, zwei_kapitel):
    import wave

    falsch = tmp_path / "falsch.wav"
    with wave.open(str(falsch), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16_000)
        w.writeframes(b"\x00\x00" * 16_000)

    with pytest.raises(Mp4Fehler, match="24000"):
        m4b([*zwei_kapitel, ("Falsch", falsch)], mache_dok(), tmp_path / "b.m4b", pause_kapitel=1.0)


# -- mp3 ------------------------------------------------------------------------------


def test_mp3_je_kapitel_mit_id3(tmp_path, zwei_kapitel):
    ordner = tmp_path / "aus"
    dok = mache_dok(cover=mache_png())

    dateien = mp3(zwei_kapitel, dok, ordner, datum="2026-10-24")

    assert [d.name for d in dateien] == [
        "2026-10-24 Testbuch \u2013 01 Kapitel Eins_v01.mp3",
        "2026-10-24 Testbuch \u2013 02 Kapitel Zwei_v01.mp3",
    ]
    for nr, datei in enumerate(dateien, 1):
        info = ffprobe("-show_format", "-show_streams", str(datei))
        tags = {k.lower(): v for k, v in info["format"]["tags"].items()}
        assert tags["title"] == zwei_kapitel[nr - 1][0]
        assert tags["album"] == "Testbuch"
        assert tags["artist"] == "Erika Muster"
        assert tags["track"] == f"{nr}/2"
        assert tags["genre"] == "H\u00f6rbuch"
        audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
        assert (audio["codec_name"], audio["channels"]) == ("mp3", 1)
        assert 55_000 <= int(audio["bit_rate"]) <= 75_000
        assert any(s["codec_type"] == "video" for s in info["streams"])
        assert float(info["format"]["duration"]) == pytest.approx(
            dauer(zwei_kapitel[nr - 1][1]), abs=0.2
        )
    assert [p.name for p in ordner.glob("*.teil")] == []


def test_mp3_zweiter_lauf_zaehlt_version_hoch(tmp_path, zwei_kapitel):
    ordner = tmp_path / "aus"
    mp3(zwei_kapitel, mache_dok(), ordner, datum="2026-10-24")

    zweite = mp3(zwei_kapitel, mache_dok(), ordner, datum="2026-10-24")

    assert all(d.name.endswith("_v02.mp3") for d in zweite)


def test_mp3_ohne_cover_hat_keinen_bildstrom(tmp_path, zwei_kapitel):
    dateien = mp3(zwei_kapitel, mache_dok(), tmp_path / "aus", datum="2026-10-24")

    arten = [s["codec_type"] for s in ffprobe("-show_streams", str(dateien[0]))["streams"]]
    assert arten == ["audio"]


# -- ausgabe_name ---------------------------------------------------------------------


def test_ausgabe_name_format(tmp_path):
    name = ausgabe_name(tmp_path, "2026-10-24", "Testbuch", ".m4b")

    assert name == tmp_path / "2026-10-24 Testbuch_v01.m4b"


def test_ausgabe_name_zaehlt_version_hoch(tmp_path):
    (tmp_path / "2026-10-24 Testbuch_v01.m4b").write_bytes(b"x")
    (tmp_path / "2026-10-24 Testbuch_v02.m4b").write_bytes(b"x")

    assert ausgabe_name(tmp_path, "2026-10-24", "Testbuch", ".m4b").name == (
        "2026-10-24 Testbuch_v03.m4b"
    )
    # eine andere Endung ist ein anderer Name
    assert ausgabe_name(tmp_path, "2026-10-24", "Testbuch", ".md").name == (
        "2026-10-24 Testbuch_v01.md"
    )


def test_ausgabe_name_nfc(tmp_path):
    nfd = unicodedata.normalize("NFD", "M\u00e4rchen \u00fcber \u00d6l")
    assert nfd != unicodedata.normalize("NFC", nfd)

    name = ausgabe_name(tmp_path, "2026-10-24", nfd, ".m4b").name

    assert name == unicodedata.normalize("NFC", "2026-10-24 M\u00e4rchen \u00fcber \u00d6l_v01.m4b")
    assert name == unicodedata.normalize("NFC", name)


def test_ausgabe_name_zusatz(tmp_path):
    name = ausgabe_name(tmp_path, "2026-10-24", "Testbuch", ".md", "Bericht").name

    assert name == "2026-10-24 Testbuch Bericht_v01.md"


def test_ausgabe_name_ohne_verbotene_zeichen(tmp_path):
    name = ausgabe_name(tmp_path, "2026-10-24", "A/B: C\x00D\nE  F", ".m4b").name

    assert name == "2026-10-24 A B C D E F_v01.m4b"


def test_ausgabe_name_titel_auf_120_zeichen(tmp_path):
    name = ausgabe_name(tmp_path, "2026-10-24", "x" * 300, ".m4b").name

    assert name == f"2026-10-24 {'x' * 120}_v01.m4b"


def test_ausgabe_name_bleibt_im_dateisystem_limit(tmp_path):
    # Umlaute zaehlen 2 Bytes: 120 Zeichen Titel plus langer Kapiteltitel duerfen
    # den Dateinamen (255 Bytes inkl. Temporaer-Endung) nicht sprengen.
    name = ausgabe_name(
        tmp_path, "2026-10-24", "\u00e4" * 300, ".mp3", "\u2013 01 " + "\u00f6" * 300
    )

    assert len(name.name.encode()) + len(".teil") <= 255
    assert "\u2013 01" in name.name  # die Nummer des Kapitels bleibt erhalten
    assert name.name.endswith("_v01.mp3")


def test_ausgabe_name_leerer_titel_bricht(tmp_path):
    with pytest.raises(Mp4Fehler, match="Titel"):
        ausgabe_name(tmp_path, "2026-10-24", " / : ", ".m4b")


def test_ausgabe_name_falsches_datum_bricht(tmp_path):
    with pytest.raises(Mp4Fehler, match="Datum"):
        ausgabe_name(tmp_path, "24.10.2026", "Testbuch", ".m4b")
