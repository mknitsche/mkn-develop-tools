"""Der Schreibschritt: kopieren und umbenennen, ohne je ein Original anzufassen.

Die drei Zusicherungen, um die es hier wirklich geht:

1. **Das Original bleibt bitgleich.** Nicht "wir verschieben nicht" als Absicht,
   sondern gemessen: Pruefsumme und Zeitstempel vorher und nachher.
2. **Ein Sidecar wird nie von seinem RAW getrennt.** `.xmp` steht nicht in
   `BILD_ENDUNGEN` und ist damit fuer das Inventar unsichtbar — wer nur die
   inventarisierten Dateien kopiert, laesst KT-1s Capture-One-Arbeit zurueck.
3. **Ein zweiter Lauf legt nichts doppelt an.** Sonst waechst der Baum bei jedem
   Versuch, und Experimentieren waere nicht mehr zulaessig.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path

import pytest
from mkn_foto import schreiben
from mkn_foto.modell import Aufnahme, Serie


def _aufnahme(tmp_path: Path, stamm: str, *, endungen=(".RAF",), zeit=None, kamera="XE5"):
    quelle = tmp_path / "original"
    quelle.mkdir(exist_ok=True)
    dateien = {}
    for e in endungen:
        p = quelle / f"{stamm}{e}"
        p.write_bytes(f"inhalt-{stamm}{e}".encode())
        dateien[e] = p
    return Aufnahme(
        zeitpunkt=zeit or datetime(2026, 8, 27, 10, 31, 22),
        kamera=kamera,
        stamm=stamm,
        dateien=dateien,
        exif={},
    )


def _pruefsumme(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_original_bleibt_bitgleich(tmp_path):
    a = _aufnahme(tmp_path, "DSCF3541", endungen=(".RAF", ".JPG"))
    vorher = {e: (_pruefsumme(p), p.stat().st_mtime) for e, p in a.dateien.items()}

    schreiben.kopiere([a], tmp_path / "ziel")

    for e, p in a.dateien.items():
        assert p.exists(), f"das Original {p.name} ist verschwunden — verschoben statt kopiert"
        assert _pruefsumme(p) == vorher[e][0], f"{p.name} wurde veraendert"
        assert p.stat().st_mtime == vorher[e][1], f"{p.name} hat einen neuen Zeitstempel"


def test_raw_und_jpeg_bekommen_denselben_stamm(tmp_path):
    """Ein Paar, das im Ziel auseinanderfaellt, ist kein Paar mehr."""
    a = _aufnahme(tmp_path, "DSCF3541", endungen=(".RAF", ".JPG"))

    ergebnis = schreiben.kopiere([a], tmp_path / "ziel")

    tag = tmp_path / "ziel" / "2026-08-27"
    namen = sorted(p.name for p in tag.iterdir())
    assert namen == [
        "2026-08-27_103122_XE5_std_DSCF3541.JPG",
        "2026-08-27_103122_XE5_std_DSCF3541.RAF",
    ], f"unerwartete Namen: {namen}"
    assert ergebnis.kopiert == 2


def test_sidecar_wandert_mit(tmp_path):
    """`.xmp` steht nicht in BILD_ENDUNGEN und ist fuer das Inventar unsichtbar.
    Wer nur die inventarisierten Dateien kopiert, laesst die Bearbeitung zurueck."""
    a = _aufnahme(tmp_path, "DSCF3541", endungen=(".RAF",))
    sidecar = a.dateien[".RAF"].with_suffix(".xmp")
    sidecar.write_text("<x:xmpmeta/>", encoding="utf-8")

    ergebnis = schreiben.kopiere([a], tmp_path / "ziel")

    ziel = tmp_path / "ziel" / "2026-08-27" / "2026-08-27_103122_XE5_std_DSCF3541.xmp"
    assert ziel.exists(), (
        "der Sidecar ist zurueckgeblieben — RAW und Sidecar duerfen nie getrennt werden"
    )
    assert ziel.read_text(encoding="utf-8") == "<x:xmpmeta/>"
    assert ergebnis.sidecars == 1


def test_zweiter_lauf_legt_nichts_doppelt_an(tmp_path):
    a = _aufnahme(tmp_path, "DSCF3541", endungen=(".RAF",))
    ziel = tmp_path / "ziel"

    schreiben.kopiere([a], ziel)
    zweites = schreiben.kopiere([a], ziel)

    tag = ziel / "2026-08-27"
    assert len(list(tag.iterdir())) == 1, (
        f"doppelt angelegt: {sorted(p.name for p in tag.iterdir())}"
    )
    assert zweites.kopiert == 0
    assert zweites.uebersprungen == 1


def test_serie_landet_im_namen(tmp_path):
    """Ohne diese Zusicherung waere ein Schreiber, der die Serien-Zuordnung
    ignoriert und alles als `std` ablegt, genauso gruen."""
    a1 = _aufnahme(tmp_path, "DSCF3541", zeit=datetime(2026, 8, 27, 10, 31, 22))
    a2 = _aufnahme(tmp_path, "DSCF3542", zeit=datetime(2026, 8, 27, 10, 31, 25))
    serie = Serie(typ="pan", nummer=1, aufnahmen=(a1, a2), quelle="kamera", sicher=True)

    schreiben.kopiere([a1, a2], tmp_path / "ziel", serien=[serie])

    tag = tmp_path / "ziel" / "2026-08-27"
    namen = sorted(p.name for p in tag.iterdir())
    assert namen == [
        "2026-08-27_103122_XE5_pan01-01v02_DSCF3541.RAF",
        "2026-08-27_103125_XE5_pan01-02v02_DSCF3542.RAF",
    ], f"Serien-Abschnitt fehlt oder falsch: {namen}"


def test_zu_wenig_platz_bricht_laut_ab(tmp_path, monkeypatch):
    """Lieber gar nicht anfangen als die Platte vollschreiben und mittendrin
    stehenbleiben — dann liegt ein halber Baum da, dem man das nicht ansieht."""
    a = _aufnahme(tmp_path, "DSCF3541", endungen=(".RAF",))

    def kein_platz(_):
        # Feldreihenfolge: f_bsize, f_frsize, f_blocks, f_bfree, f_bavail, ...
        # f_bavail (Index 4) auf 0 -- die erste Fassung setzte dort eine 1 und
        # liess damit 4.096 Byte frei, mehr als die Testdateien brauchen. Der Test
        # war rot und hat seinen eigenen Fehler gezeigt, nicht den des Codes.
        return os.statvfs_result((4096, 4096, 100, 0, 0, 0, 0, 0, 0, 255))

    monkeypatch.setattr(schreiben.os, "statvfs", kein_platz)

    with pytest.raises(schreiben.ZuWenigPlatz) as fehler:
        schreiben.kopiere([a], tmp_path / "ziel")
    assert not (tmp_path / "ziel" / "2026-08-27").exists(), "trotz Abbruch wurde geschrieben"
    assert "Byte" in str(fehler.value) or "byte" in str(fehler.value).lower()


def test_sidecar_wird_je_aufnahme_nur_einmal_kopiert(tmp_path):
    """Ein RAW+JPEG-Paar hat EINEN Sidecar, nicht zwei.

    Die erste Fassung kopierte ihn je Endung — beide Male auf denselben
    Zielnamen. Kein Datenverlust, aber doppelte Arbeit und ein Zaehler, der
    luegt: der Lauf ueber die echte Reise meldete 272 Sidecars, im Ziel lagen
    139. Eine Zahl, die etwas anderes zaehlt als sie behauptet, ist schlimmer
    als keine.
    """
    a = _aufnahme(tmp_path, "DSCF3541", endungen=(".RAF", ".JPG"))
    a.dateien[".RAF"].with_suffix(".xmp").write_text("<x:xmpmeta/>", encoding="utf-8")

    ergebnis = schreiben.kopiere([a], tmp_path / "ziel")

    tag = tmp_path / "ziel" / "2026-08-27"
    sidecars = list(tag.glob("*.xmp"))
    assert len(sidecars) == 1, f"mehrere Sidecar-Dateien: {[p.name for p in sidecars]}"
    assert ergebnis.sidecars == 1, (
        f"der Zaehler meldet {ergebnis.sidecars}, im Ziel liegt {len(sidecars)}"
    )


def test_kopiere_meldet_die_zieldateien_je_aufnahme(tmp_path):
    """Die Anreicherung muss in den ZIELbaum schreiben, nie in die Originale.

    Dafuer braucht sie die Zuordnung Aufnahme -> neue Pfade. Eine flache Liste
    aller Ziele reicht nicht: sie sagt nicht, welche Datei zu welcher Aufnahme
    gehoert, und die Anreicherung schriebe dann den Ort der einen Session an das
    Bild der anderen.
    """
    a1 = _aufnahme(tmp_path, "DSCF3541", endungen=(".RAF", ".JPG"))
    a2 = _aufnahme(tmp_path, "DSCF3542", endungen=(".RAF",))

    ergebnis = schreiben.kopiere([a1, a2], tmp_path / "ziel")

    assert len(ergebnis.kopien) == 2, f"unerwartete Zuordnung: {ergebnis.kopien}"
    zu_a1 = dict(ergebnis.kopien)[id(a1)]
    assert set(zu_a1) == {".RAF", ".JPG"}
    assert all(p.parent.name == "2026-08-27" for p in zu_a1.values())
    assert all(str(tmp_path / "ziel") in str(p) for p in zu_a1.values()), (
        "die gemeldeten Pfade zeigen auf die Originale statt in den Zielbaum"
    )


def test_ein_zweiter_lauf_findet_die_schon_vorhandenen_kopien(tmp_path: Path) -> None:
    """Ein uebersprungenes Bild ist DA -- es fehlt nur die Kopie, nicht die Datei.

    **Der Anlass, firsthand.** Am 2026-08-30 um 07:30 lief die Pipeline ueber
    denselben Zielbaum ein zweites Mal. Sie meldete nach 36 Sekunden "FERTIG",
    1.293 Aufnahmen, 0 Sidecars, 0 Modellaufrufe -- und tat nichts. Die Ursache
    stand hier: `kopiere` zaehlte die vorhandenen Dateien als `uebersprungen`
    und trug sie NICHT in `kopien` ein. Die Anreicherung bekam eine leere Liste
    und hatte folgerichtig nichts zu tun. Alles gruen, alles wertlos.

    Der Fehler ist der Unterschied zwischen "nicht kopiert" und "nicht da".
    Ein Werkzeug, das beim zweiten Lauf ueber denselben Baum nichts mehr tut,
    ist nicht idempotent -- es ist einmalig, und das merkt niemand, solange
    niemand zweimal laeuft.
    """
    quelle = tmp_path / "q"
    quelle.mkdir()
    a = _aufnahme(quelle, "DSCF1", endungen=(".RAF", ".JPG"))
    ziel = tmp_path / "z"

    erst = schreiben.kopiere([a], ziel)
    zweit = schreiben.kopiere([a], ziel)

    assert erst.kopiert == 2, "erster Lauf muss kopieren"
    assert zweit.uebersprungen == 1, "zweiter Lauf darf nicht erneut kopieren"
    # Und das ist der Punkt: die Zuordnung muss trotzdem stehen.
    assert dict(zweit.kopien) == dict(erst.kopien), (
        "der zweite Lauf muss dieselben Zielpfade kennen wie der erste"
    )
