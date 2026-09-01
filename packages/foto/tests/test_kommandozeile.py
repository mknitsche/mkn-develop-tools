"""TODO-664 — mkn-foto braucht einen Kommandozeilen-Einstieg.

Ohne ihn bekommt `pip install mkn-foto` eine Bibliothek und kein Werkzeug: jeder
bisherige Lauf lief ueber ein von Hand geschriebenes Skript, das `sys.path`
zurechtbiegt und `pipeline.fahre()` direkt aufruft. Fuer ein veroeffentlichtes
Projekt ist das die groesste Luecke ueberhaupt — groesser als jede fehlende
Dokumentationsdatei.

Die Optionsnamen sind DEUTSCH, und das ist abgeleitet statt erfunden: die
oeffentliche Schnittstelle des Pakets ist bereits deutsch (`konfig.json` traegt
`ziel`, `urheber`, `farben`, `schluessel_datei`). Wer diese Datei schreibt,
erwartet `--ziel` und nicht `--to`. Nur die Doku ist englisch.

Besonderes Augenmerk auf EXIT-CODES: ein Werkzeug, das im Fehlerfall 0 meldet,
ist die Klasse „Erfolg trotz Fehlschlag" — jede Automatisierung darueber baut
dann auf einer Luege auf.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from mkn_foto import kommandozeile, modell, pipeline, schreiben


def _LaufAttrappe() -> pipeline.Lauf:
    """Ein fertiger Lauf — gebaut aus dem ECHTEN `pipeline.Lauf`, nicht nachgestellt.

    Die erste Fassung war eine eigene Klasse mit den Feldern, die der Bericht
    anfasst. Sie setzte `geschrieben` IMMER — die Wirklichkeit laesst es bei leerer
    Quelle auf `None`, und genau daran ist der erste echte Probelauf zerschellt,
    waehrend alle Tests gruen waren.

    Eine Attrappe, die grosszuegiger ist als die Sache, beweist ueber die Sache
    nichts (LP-34). Der echte Typ kann das nicht: faellt ein Feld weg oder aendert
    sich sein Default, faellt es hier auf.
    """
    bilder = [object(), object(), object(), object()]
    lauf = pipeline.Lauf()
    lauf.aufnahmen = bilder  # type: ignore[assignment]
    # Echte Spots: `Lauf.belegt` ist eine Property, die ueber `spot.aufnahmen`
    # summiert — mit blossen Platzhaltern bricht sie. Auch das hat erst der echte
    # Typ gezeigt.
    spot_a = modell.Spot(aufnahmen=tuple(bilder[:3]))  # type: ignore[arg-type]
    spot_b = modell.Spot(aufnahmen=tuple(bilder[3:]))  # type: ignore[arg-type]
    lauf.spots = [spot_a, spot_b]
    lauf.orte = {id(spot_a): object()}  # type: ignore[dict-item]
    lauf.geschrieben = schreiben.Ergebnis(kopiert=8, sidecars=4, uebersprungen=0)
    return lauf


@pytest.fixture
def quelle(tmp_path: Path) -> Path:
    q = tmp_path / "aufnahmen"
    q.mkdir()
    return q


# --------------------------------------------------------------------------- #
# Der Normalfall
# --------------------------------------------------------------------------- #


def test_ruft_die_pipeline_mit_quelle_und_ziel(quelle: Path, tmp_path: Path, capsys):
    ziel = tmp_path / "angereichert"

    with (
        patch.object(kommandozeile.pipeline, "anker_sammeln", return_value=[]) as m_anker,
        patch.object(kommandozeile.pipeline, "fahre", return_value=_LaufAttrappe()) as m_fahre,
    ):
        rc = kommandozeile.haupt([str(quelle), "--ziel", str(ziel)])

    assert rc == 0
    assert m_anker.call_count == 1
    quelle_arg, ziel_arg = m_fahre.call_args.args
    assert quelle_arg == quelle
    assert ziel_arg == ziel


def test_bericht_nennt_die_kernzahlen(quelle: Path, tmp_path: Path, capsys):
    """Ein Lauf ohne Zahlen am Ende zwingt zum Nachrechnen im Kopf."""
    with (
        patch.object(kommandozeile.pipeline, "anker_sammeln", return_value=[]),
        patch.object(kommandozeile.pipeline, "fahre", return_value=_LaufAttrappe()),
    ):
        kommandozeile.haupt([str(quelle), "--ziel", str(tmp_path / "z")])

    ausgabe = capsys.readouterr().out
    assert "4" in ausgabe, "Anzahl der Aufnahmen fehlt"
    assert "8" in ausgabe, "Anzahl kopierter Dateien fehlt"


# --------------------------------------------------------------------------- #
# Exit-Codes: ein Fehlschlag darf NIE wie Erfolg aussehen
# --------------------------------------------------------------------------- #


def test_fehlende_quelle_meldet_fehler_statt_erfolg(tmp_path: Path, capsys):
    fehlt = tmp_path / "gibtsnicht"

    rc = kommandozeile.haupt([str(fehlt), "--ziel", str(tmp_path / "z")])

    assert rc != 0, (
        "Eine nicht existierende Quelle muss einen Fehler-Exit ergeben — sonst "
        "meldet jede Automatisierung darueber Erfolg fuer einen Lauf, der nie lief."
    )
    assert str(fehlt) in capsys.readouterr().err


def test_quelle_die_eine_datei_ist_wird_abgewiesen(tmp_path: Path, capsys):
    datei = tmp_path / "einzelbild.raf"
    datei.write_text("kein ordner")

    rc = kommandozeile.haupt([str(datei), "--ziel", str(tmp_path / "z")])

    assert rc != 0
    assert "Ordner" in capsys.readouterr().err


def test_ohne_ziel_und_ohne_konfiguration_wird_es_laut(quelle: Path, capsys):
    """Kein stiller Standard: ein geratenes Ziel schreibt 51 GB an die falsche Stelle."""
    rc = kommandozeile.haupt([str(quelle)])

    assert rc != 0
    fehler = capsys.readouterr().err
    assert "ziel" in fehler.lower()


def test_ein_fehler_in_der_pipeline_wird_nicht_verschluckt(quelle: Path, tmp_path: Path, capsys):
    """Wirft die Pipeline, endet das Werkzeug mit Fehler — nicht mit 0 und Stille."""
    with (
        patch.object(kommandozeile.pipeline, "anker_sammeln", return_value=[]),
        patch.object(kommandozeile.pipeline, "fahre", side_effect=RuntimeError("exiftool fehlt")),
    ):
        rc = kommandozeile.haupt([str(quelle), "--ziel", str(tmp_path / "z")])

    assert rc != 0
    assert "exiftool fehlt" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Die Optionen tragen wirklich durch
# --------------------------------------------------------------------------- #


def test_probelauf_schreibt_nichts(quelle: Path, tmp_path: Path):
    """`--probelauf` MUSS bis in die Pipeline durchschlagen.

    Wer einen Trockenlauf anfordert und trotzdem 51 GB geschrieben bekommt, hat
    schlimmeren Schaden als ohne die Option.
    """
    with (
        patch.object(kommandozeile.pipeline, "anker_sammeln", return_value=[]),
        patch.object(kommandozeile.pipeline, "fahre", return_value=_LaufAttrappe()) as m_fahre,
    ):
        kommandozeile.haupt([str(quelle), "--ziel", str(tmp_path / "z"), "--probelauf"])

    assert m_fahre.call_args.kwargs["schreiben_aktiv"] is False


def test_ohne_probelauf_wird_geschrieben(quelle: Path, tmp_path: Path):
    """Untergrenze (LP-36): sonst waere „nie schreiben" eine gruene Loesung."""
    with (
        patch.object(kommandozeile.pipeline, "anker_sammeln", return_value=[]),
        patch.object(kommandozeile.pipeline, "fahre", return_value=_LaufAttrappe()) as m_fahre,
    ):
        kommandozeile.haupt([str(quelle), "--ziel", str(tmp_path / "z")])

    assert m_fahre.call_args.kwargs["schreiben_aktiv"] is True


def test_ortsquellen_gehen_an_anker_sammeln(quelle: Path, tmp_path: Path):
    """GPX, Bibliothek, Album und Notizen sind die vier Ortsquellen des echten Laufs."""
    gpx = tmp_path / "route.gpx"
    gpx.write_text("<gpx/>")
    bib = tmp_path / "Photos.photoslibrary"
    bib.mkdir()
    notizen = tmp_path / "orte-offen"
    notizen.mkdir()

    with (
        patch.object(kommandozeile.pipeline, "anker_sammeln", return_value=[]) as m_anker,
        patch.object(kommandozeile.pipeline, "fahre", return_value=_LaufAttrappe()),
    ):
        kommandozeile.haupt(
            [
                str(quelle),
                "--ziel",
                str(tmp_path / "z"),
                "--gpx",
                str(gpx),
                "--bibliothek",
                str(bib),
                "--album",
                "Karwendel",
                "--notizen",
                str(notizen),
            ]
        )

    kw = m_anker.call_args.kwargs
    assert kw["gpx_datei"] == gpx
    assert kw["bibliothek"] == bib
    assert kw["album"] == "Karwendel"
    assert kw["notiz_ordner"] == notizen


def test_notizen_gehen_auch_an_die_pipeline(quelle: Path, tmp_path: Path):
    """Die Notizen werden ZWEIMAL gebraucht — beim Ankersammeln und beim Fahren.

    Im echten Lauf-Skript steht `notiz_ordner` in beiden Aufrufen. Wer es nur an
    einen von beiden gibt, verliert die Antworten des Menschen an der jeweils
    anderen Stelle: entweder fehlen die Anker, oder bereits beantwortete Orte
    werden erneut vorgelegt.
    """
    notizen = tmp_path / "orte-offen"
    notizen.mkdir()

    with (
        patch.object(kommandozeile.pipeline, "anker_sammeln", return_value=[]),
        patch.object(kommandozeile.pipeline, "fahre", return_value=_LaufAttrappe()) as m_fahre,
    ):
        kommandozeile.haupt([str(quelle), "--ziel", str(tmp_path / "z"), "--notizen", str(notizen)])

    assert m_fahre.call_args.kwargs["notiz_ordner"] == notizen


def test_ziel_aus_der_konfiguration_wenn_die_option_fehlt(quelle: Path, tmp_path: Path):
    """Der dokumentierte Weg: `ziel` steht in konfig.json, der Aufruf nennt es nicht."""
    aus_konfig = tmp_path / "aus-konfig"

    with (
        patch.object(
            kommandozeile.konfig, "lade", return_value=kommandozeile.konfig.Konfig(ziel=aus_konfig)
        ),
        patch.object(kommandozeile.pipeline, "anker_sammeln", return_value=[]),
        patch.object(kommandozeile.pipeline, "fahre", return_value=_LaufAttrappe()) as m_fahre,
    ):
        rc = kommandozeile.haupt([str(quelle)])

    assert rc == 0
    assert m_fahre.call_args.args[1] == aus_konfig


def test_die_option_schlaegt_die_konfiguration(quelle: Path, tmp_path: Path):
    """Wer beim Aufruf ein Ziel nennt, meint es — sonst waere die Option wirkungslos."""
    aus_konfig = tmp_path / "aus-konfig"
    genannt = tmp_path / "beim-aufruf-genannt"

    with (
        patch.object(
            kommandozeile.konfig, "lade", return_value=kommandozeile.konfig.Konfig(ziel=aus_konfig)
        ),
        patch.object(kommandozeile.pipeline, "anker_sammeln", return_value=[]),
        patch.object(kommandozeile.pipeline, "fahre", return_value=_LaufAttrappe()) as m_fahre,
    ):
        kommandozeile.haupt([str(quelle), "--ziel", str(genannt)])

    assert m_fahre.call_args.args[1] == genannt


def test_kaputte_konfiguration_ist_laut(quelle: Path, tmp_path: Path, capsys):
    """Eine kaputte Konfiguration darf nicht als „keine Konfiguration" durchgehen.

    Das Paket haelt diese Regel bereits in `konfig.lade`; das Werkzeug darf sie
    nicht wieder einebnen, indem es die Ausnahme schluckt.
    """
    with patch.object(
        kommandozeile.konfig,
        "lade",
        side_effect=kommandozeile.konfig.KonfigFehler("konfig.json ist kein gueltiges JSON"),
    ):
        rc = kommandozeile.haupt([str(quelle), "--ziel", str(tmp_path / "z")])

    assert rc != 0
    assert "JSON" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Der leere Lauf — firsthand gefunden, von keinem Test der ersten Fassung
# --------------------------------------------------------------------------- #


def test_leere_quelle_meldet_das_klar_statt_abzustuerzen(quelle: Path, tmp_path: Path, capsys):
    """Findet die Pipeline nichts, ist `lauf.geschrieben` None — und der Bericht flog.

    FIRSTHAND macb-S316: der erste echte Probelauf ueber einen leeren Ordner endete
    in `AttributeError: 'NoneType' object has no attribute 'kopiert'`. Alle 13 Tests
    waren zu diesem Zeitpunkt gruen — die Attrappe setzte `geschrieben` immer, die
    Wirklichkeit laesst es bei leerer Quelle auf dem Default `None`
    (`pipeline.Lauf.geschrieben: schreiben.Ergebnis | None = None`).

    Ein leerer Ordner ist zudem kein Fehler, sondern eine Auskunft: meistens hat
    jemand den falschen Pfad getippt, und die Meldung soll das sagen.
    """
    leerer_lauf = pipeline.Lauf()

    with (
        patch.object(kommandozeile.pipeline, "anker_sammeln", return_value=[]),
        patch.object(kommandozeile.pipeline, "fahre", return_value=leerer_lauf),
    ):
        rc = kommandozeile.haupt([str(quelle), "--ziel", str(tmp_path / "z")])

    ausgabe = capsys.readouterr()
    assert rc == 0, "Ein leerer Ordner ist eine Auskunft, kein Fehlschlag."
    assert "keine Aufnahmen" in (ausgabe.out + ausgabe.err), (
        "Der leere Lauf muss benannt werden — sonst sieht er aus wie ein Erfolg "
        "ueber unbekannt vielen Bildern."
    )


def test_bericht_vertraegt_einen_lauf_ohne_schreib_ergebnis():
    """Die Einheit selbst: `geschrieben=None` darf den Bericht nicht sprengen."""
    lauf = pipeline.Lauf()
    lauf.aufnahmen = [object()]  # type: ignore[list-item]

    text = kommandozeile._bericht(lauf, 1.0)

    assert "1" in text
    assert "kopiert" not in text.lower() or "0" in text
