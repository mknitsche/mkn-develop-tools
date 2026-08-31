"""Die Abnahme eines Laufs: ist der Zielbaum vollstaendig und widerspruchsfrei?

**Warum es diese Datei gibt.** KT-1 vor dem Lauf ueber die Karwendeltage:
*"dabei ist sichergestellt, dass es vollstaendig ist und keine falschen anzahlen
gibt, oder das jpeg und raw keine paeaerchen mehr sind usw usw"*. Ein Lauf, der
"FERTIG" meldet, hat damit noch nichts belegt -- am 2026-08-30 meldete einer
genau das nach 36 Sekunden, ohne eine einzige Datei angereichert zu haben.

Die Pruefung vergleicht Quelle und Ziel und beantwortet sechs Fragen. Sie
aendert nichts; sie zaehlt.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from mkn_foto import vollzaehligkeit

pytestmark = pytest.mark.skipif(
    shutil.which("exiftool") is None, reason="exiftool nicht verfuegbar"
)


def _bild(pfad: Path, zeit: str = "2026:08:24 06:19:00", modell: str = "X-E5") -> Path:
    """Eine Datei, die das Inventar als Aufnahme erkennt.

    Bildinhalt von Pillow, Aufnahmedaten von exiftool. Die Endung darf abweichen
    -- `inventar` nimmt den Typ aus dem Pfad, exiftool aus dem Inhalt, und fuer
    eine RAW-Attrappe genuegt das: eine echte RAF kann exiftool nicht erzeugen.
    """
    import tempfile

    from PIL import Image

    pfad.parent.mkdir(parents=True, exist_ok=True)
    # Zwei Fallen auf einmal, beide firsthand aufgelaufen:
    #
    # 1. exiftool waehlt das Schreibformat nach der ENDUNG und weigert sich bei
    #    `.RAF`. Die Datei bliebe ohne Aufnahmezeit und fiele aus dem Inventar
    #    ("ohne DateTimeOriginal, uebersprungen") -- der Test merkt es nicht.
    # 2. Deshalb wird als `.jpg` geschrieben und umbenannt. Der naheliegende
    #    Zwischenname `pfad.with_suffix(".jpg")` ist auf macOS aber DIESELBE
    #    Datei wie `....JPG` (case-insensitiv): das Anlegen der zweiten Haelfte
    #    ueberschrieb die erste und verschob sie, es blieb EINE Datei statt
    #    eines Paares. Mehrere Tests waren dadurch aus dem falschen Grund gruen.
    #
    # Ein eindeutiger Zwischenname schliesst beides aus.
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        roh = Path(f.name)
    Image.new("RGB", (60, 40), (90, 120, 60)).save(roh, format="JPEG")
    subprocess.run(
        [
            "exiftool",
            "-q",
            "-overwrite_original",
            f"-EXIF:DateTimeOriginal={zeit}",
            f"-EXIF:Model={modell}",
            str(roh),
        ],
        capture_output=True,
        check=False,
    )
    shutil.move(str(roh), str(pfad))
    return pfad


def _paar(ordner: Path, stamm: str, **kw) -> Path:
    """Eine Aufnahme, die als RAW UND JPEG vorliegt -- die uebliche Form."""
    jpg = _bild(ordner / f"{stamm}.JPG", **kw)
    raf = _bild(ordner / f"{stamm}.RAF", **kw)
    # Die Untergrenze fuer den Helfer selbst: eine fruehere Fassung liess auf
    # macOS nur EINE der beiden Dateien zurueck, und kein Test sah es. Ein
    # Helfer, der die Vorbedingung nicht herstellt, macht jeden Test darueber
    # zur Behauptung (LP-36).
    assert jpg.exists() and raf.exists(), f"Paar unvollstaendig angelegt: {stamm}"
    return raf


def test_ein_sauberer_lauf_meldet_nichts(tmp_path) -> None:
    """Die Untergrenze: ueber einem fehlerfreien Lauf schweigt die Pruefung.

    Ohne diesen Test koennte sie alles beanstanden und saehe trotzdem wachsam
    aus -- eine Pruefung, die immer meldet, wird nach zwei Laeufen ignoriert.
    """
    quelle, ziel = tmp_path / "q", tmp_path / "z"
    _paar(quelle, "DSCF0001")
    _paar(ziel / "2026-08-24", "2026-08-24_061900_XE5_std_DSCF0001")

    bericht = vollzaehligkeit.pruefe(quelle, ziel)

    assert bericht.sauber, f"sauberer Lauf beanstandet: {bericht.befunde}"
    assert bericht.aufnahmen_quelle == 1
    assert bericht.aufnahmen_ziel == 1


def test_der_umbenannte_stamm_ist_kein_verlust(tmp_path) -> None:
    """**Der Fallstrick, an dem eine naive Pruefung 100 % Verlust meldet.**

    Firsthand am Probelauf vom 2026-08-30: ein Vergleich ueber
    `(Zeitpunkt, Kamera, Stamm)` meldete **42 fehlende UND 42 zusaetzliche**
    Aufnahmen -- bei einem Lauf, der nachweislich fehlerfrei war. Der Stamm ist
    im Ziel ein anderer (`DSCF3877` gegen
    `2026-08-30_152700_XE5_std_DSCF3877`), und wer das nicht weiss, sucht einen
    Fehler, den es nicht gibt.

    Die Notation traegt den Originalnamen bewusst am Ende (`namen.py`: *"damit
    eine umbenannte Datei zu ihrem Kamera-Original zurueckfindet"*). Genau von
    dort muss die Zuordnung ihn zurueckgewinnen.
    """
    quelle, ziel = tmp_path / "q", tmp_path / "z"
    _paar(quelle, "DSCF3877", zeit="2026:08:30 15:27:00")
    _paar(ziel / "2026-08-30", "2026-08-30_152700_XE5_std_DSCF3877", zeit="2026:08:30 15:27:00")

    bericht = vollzaehligkeit.pruefe(quelle, ziel)

    assert not bericht.fehlend, f"die umbenannte Aufnahme gilt als verloren: {bericht.fehlend}"
    assert not bericht.zusaetzlich, f"die umbenannte Aufnahme gilt als fremd: {bericht.zusaetzlich}"


def test_eine_fehlende_aufnahme_wird_gemeldet(tmp_path) -> None:
    """Die Hauptfrage: ist etwas auf dem Weg verloren gegangen?"""
    quelle, ziel = tmp_path / "q", tmp_path / "z"
    _paar(quelle, "DSCF0001")
    _paar(quelle, "DSCF0002", zeit="2026:08:24 06:20:00")
    _paar(ziel / "2026-08-24", "2026-08-24_061900_XE5_std_DSCF0001")

    bericht = vollzaehligkeit.pruefe(quelle, ziel)

    assert not bericht.sauber
    assert len(bericht.fehlend) == 1, f"erwartet 1 fehlend, war {bericht.fehlend}"
    assert "DSCF0002" in bericht.fehlend[0]


def test_ein_zerrissenes_paar_wird_gemeldet(tmp_path) -> None:
    """**KT-1s Direktive: das Paar ist die Einheit.**

    *"die gepaarten bilder sind als paar zu behandeln - so wie es jede
    bildbearbeitungssw macht"*. Kommt nur die eine Haelfte im Ziel an, ist die
    Aufnahme zwar da, aber die Einheit ist zerbrochen -- und genau das sieht man
    einer Aufnahmezahl nicht an.
    """
    quelle, ziel = tmp_path / "q", tmp_path / "z"
    _paar(quelle, "DSCF0001")
    _bild(ziel / "2026-08-24" / "2026-08-24_061900_XE5_std_DSCF0001.JPG")

    bericht = vollzaehligkeit.pruefe(quelle, ziel)

    assert not bericht.sauber
    assert bericht.zerrissen, "das halbe Paar wurde nicht bemerkt"
    assert ".RAF" in bericht.zerrissen[0]


def test_ein_ueberzaehliger_sidecar_neben_jpeg_wird_gemeldet(tmp_path) -> None:
    """Die Traeger-Regel, von der Abnahmeseite geprueft.

    Ein JPEG ohne RAW traegt seine Angaben eingebettet; ein Sidecar daneben ist
    dieselbe Aussage an zwei Stellen (Spec Paragraf 10). Im Lauf vom 2026-08-30
    lagen so bis zu 65 ueberzaehlige Dateien im Zielbaum.
    """
    quelle, ziel = tmp_path / "q", tmp_path / "z"
    _bild(quelle / "D85_0001.JPG", modell="NIKON D850")
    z = _bild(ziel / "2026-08-24" / "2026-08-24_061900_D850_std_D85_0001.JPG", modell="NIKON D850")
    z.with_suffix(".xmp").write_text("<x:xmpmeta/>", encoding="utf-8")

    bericht = vollzaehligkeit.pruefe(quelle, ziel)

    assert not bericht.sauber
    assert bericht.doppelter_traeger, "der ueberzaehlige Sidecar wurde nicht bemerkt"


def test_eine_unerklaerte_datei_wird_gemeldet(tmp_path) -> None:
    """Wildwuchs im Zielbaum -- Dateien, die zu keiner Aufnahme gehoeren."""
    quelle, ziel = tmp_path / "q", tmp_path / "z"
    _paar(quelle, "DSCF0001")
    _paar(ziel / "2026-08-24", "2026-08-24_061900_XE5_std_DSCF0001")
    (ziel / "2026-08-24" / "DSCF0001.JPG_original").write_bytes(b"muell")

    bericht = vollzaehligkeit.pruefe(quelle, ziel)

    assert not bericht.sauber
    assert bericht.unerklaert, "die unerklaerte Datei wurde nicht bemerkt"


def test_ungleiche_inhalte_bei_raw_und_jpeg_werden_gemeldet(tmp_path) -> None:
    """**Die andere Haelfte von KT-1s Direktive — und ohne sie ist die Pruefung blind.**

    *"auch alle inhalte muessen bei jpeg und raw gleich sein"*. Eine Pruefung,
    die nur Dateien zaehlt, meldet einen Lauf als sauber, in dem 29 von 42
    Sidecars ihre Stichworte doppelt trugen und die JPEGs einfach -- firsthand
    genau so geschehen: gegen den Zielbaum VOR dem Traeger-Fix meldete die erste
    Fassung dieser Pruefung `sauber=True`.

    Das ist die teuerste Art Luecke: das Werkzeug antwortet, es antwortet
    zuversichtlich, und es hat die Frage nie gestellt (LP-32).
    """
    quelle, ziel = tmp_path / "q", tmp_path / "z"
    _paar(quelle, "DSCF0001")
    tag = ziel / "2026-08-24"
    _paar(tag, "2026-08-24_061900_XE5_std_DSCF0001")
    # Das JPEG traegt ein Stichwort, der Sidecar der RAW ein anderes.
    subprocess.run(
        [
            "exiftool",
            "-q",
            "-overwrite_original",
            "-XMP-lr:HierarchicalSubject+=Motiv|Wald",
            str(tag / "2026-08-24_061900_XE5_std_DSCF0001.JPG"),
        ],
        capture_output=True,
        check=False,
    )
    subprocess.run(
        [
            "exiftool",
            "-q",
            "-o",
            str(tag / "2026-08-24_061900_XE5_std_DSCF0001.xmp"),
            "-XMP-lr:HierarchicalSubject+=Motiv|Wald",
            "-XMP-lr:HierarchicalSubject+=Motiv|Wald",
            str(tag / "2026-08-24_061900_XE5_std_DSCF0001.RAF"),
        ],
        capture_output=True,
        check=False,
    )

    bericht = vollzaehligkeit.pruefe(quelle, ziel)

    assert not bericht.sauber
    assert bericht.ungleich, "die ungleichen Inhalte wurden nicht bemerkt"


def test_gleiche_inhalte_werden_nicht_beanstandet(tmp_path) -> None:
    """Die Untergrenze zur vorigen Zusicherung.

    Ohne sie koennte die Inhaltspruefung JEDES Paar beanstanden und saehe
    trotzdem wachsam aus. Geprueft wird auf gleiche MENGE, nicht auf gleiche
    Reihenfolge: exiftool gibt Listen in Schreibreihenfolge zurueck, und die
    unterscheidet sich zwischen eingebettet und Sidecar regelmaessig, ohne dass
    inhaltlich etwas fehlt.
    """
    quelle, ziel = tmp_path / "q", tmp_path / "z"
    _paar(quelle, "DSCF0001")
    tag = ziel / "2026-08-24"
    _paar(tag, "2026-08-24_061900_XE5_std_DSCF0001")
    for befehl in (
        [
            "exiftool",
            "-q",
            "-overwrite_original",
            "-XMP-lr:HierarchicalSubject+=Motiv|Wald",
            "-XMP-lr:HierarchicalSubject+=Technik|Einzelbild",
            str(tag / "2026-08-24_061900_XE5_std_DSCF0001.JPG"),
        ],
        [
            "exiftool",
            "-q",
            "-o",
            str(tag / "2026-08-24_061900_XE5_std_DSCF0001.xmp"),
            "-XMP-lr:HierarchicalSubject+=Technik|Einzelbild",
            "-XMP-lr:HierarchicalSubject+=Motiv|Wald",
            str(tag / "2026-08-24_061900_XE5_std_DSCF0001.RAF"),
        ],
    ):
        subprocess.run(befehl, capture_output=True, check=False)

    bericht = vollzaehligkeit.pruefe(quelle, ziel)

    assert not bericht.ungleich, f"gleiche Inhalte beanstandet: {bericht.ungleich}"


def test_ein_sidecar_aus_der_quelle_ist_kein_befund(tmp_path) -> None:
    """**Was schon vorher dalag, hat das Werkzeug nicht verursacht.**

    Ein JPEG ohne RAW traegt seine Angaben eingebettet; ein Sidecar daneben ist
    normalerweise "zwei Traeger". Liegt er aber schon in der QUELLE, ist er KT-1s
    eigene Arbeit aus Capture One — im Karwendel-Bestand sechs solche Faelle, mit
    seinen Bewertungen darin. Das Werkzeug hat sie korrekt mitkopiert (RAW und
    Sidecar nie getrennt bewegen); sie als Befund zu melden waere falsch, und sie
    zu loeschen waere schlimmer.

    Die Pruefung muss den Unterschied kennen, sonst meldet sie bei jedem Lauf
    dieselben sechs Zeilen — und eine Pruefung, die immer dasselbe meldet, wird
    nach zwei Laeufen ignoriert.
    """
    quelle, ziel = tmp_path / "q", tmp_path / "z"
    q_jpg = _bild(quelle / "D85_0001.JPG", modell="NIKON D850")
    q_jpg.with_suffix(".xmp").write_text("<x:xmpmeta/>", encoding="utf-8")

    z_jpg = _bild(
        ziel / "2026-08-24" / "2026-08-24_061900_D850_std_D85_0001.JPG", modell="NIKON D850"
    )
    z_jpg.with_suffix(".xmp").write_text("<x:xmpmeta/>", encoding="utf-8")

    bericht = vollzaehligkeit.pruefe(quelle, ziel)

    assert not bericht.doppelter_traeger, (
        f"ein aus der Quelle uebernommener Sidecar wird als Befund gemeldet: "
        f"{bericht.doppelter_traeger}"
    )


def test_ein_neu_entstandener_sidecar_bleibt_ein_befund(tmp_path) -> None:
    """Die Untergrenze — sonst waere die Ausnahme ein Freibrief.

    Der Fall, gegen den die Regel gebaut ist: das Werkzeug legt einen Sidecar
    neben ein JPEG, in das es unmittelbar danach einbettet. Genau das geschah im
    Lauf vom 2026-08-30 bis zu 65 Mal.
    """
    quelle, ziel = tmp_path / "q", tmp_path / "z"
    _bild(quelle / "D85_0002.JPG", modell="NIKON D850")  # OHNE Sidecar

    z_jpg = _bild(
        ziel / "2026-08-24" / "2026-08-24_061900_D850_std_D85_0002.JPG", modell="NIKON D850"
    )
    z_jpg.with_suffix(".xmp").write_text("<x:xmpmeta/>", encoding="utf-8")

    bericht = vollzaehligkeit.pruefe(quelle, ziel)

    assert bericht.doppelter_traeger, "ein neu entstandener Sidecar wird nicht gemeldet"
