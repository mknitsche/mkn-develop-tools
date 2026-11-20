"""Der Befehl: ohne Wahl der Leser keine Anfrage, Fehler mit Exit 1."""

import json

import pytest

from conftest import ScheinLeser, angabe, schreibe_pdf
from mkn_dokument import kommandozeile


def test_ohne_leser_wahl_exit_1_mit_hinweis(tmp_path, capsys):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf")
    assert kommandozeile.haupt(["lesen", str(pdf), "--aus", str(tmp_path / "aus")]) == 1
    assert "MKN_DOKUMENT_LESER_A" in capsys.readouterr().err


def test_fehlende_datei_exit_1(tmp_path, capsys):
    code = kommandozeile.haupt(
        [
            "lesen",
            str(tmp_path / "fehlt.pdf"),
            "--aus",
            str(tmp_path / "aus"),
            "--leser-a",
            "anthropic:m",
            "--leser-b",
            "gemini:n",
        ]
    )
    assert code == 1 and "fehlt" in capsys.readouterr().err


def test_lauf_meldet_zaehlung_und_ergebnisort(tmp_path, capsys, monkeypatch):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf")
    antwort = [{"angaben": [angabe("6,25")]}]
    leser = iter([ScheinLeser("a", antwort), ScheinLeser("b", antwort)])
    monkeypatch.setattr(kommandozeile, "_leser", lambda angabe, variable: next(leser))
    assert kommandozeile.haupt(["lesen", str(pdf), "--aus", str(tmp_path / "aus")]) == 0
    aus = capsys.readouterr().out
    assert "1 Seite(n): uebernommen 1" in aus and "ergebnis.json" in aus


def test_zwei_leser_desselben_anbieters_werden_abgewiesen(tmp_path, capsys):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf")
    code = kommandozeile.haupt(
        ["lesen", str(pdf), "--aus", str(tmp_path / "aus"), "--leser-a", "anthropic:m", "--leser-b", "anthropic:n"]
    )
    assert code == 1 and "derselben Herkunft" in capsys.readouterr().err
    assert not (tmp_path / "aus").exists()


# --- seiten und ablesen --------------------------------------------------------------------------------------------


def _seiten_antwort(**anders):
    return {
        "seitenart": "inhalt", "aussteller": "Probelabor Nord", "datum": "01.02.2020", "datum_bezeichnung": "",
        "inhaltsart": "labor", "texte": [{"ueberschrift": "", "art": "absatz", "text": "Ein Satz."}], "diagramme": [],
    } | anders  # fmt: skip


def test_seiten_setzt_fach_angaben_ein_und_meldet_zaehlung(tmp_path, capsys, monkeypatch):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf")
    a, b = ScheinLeser("a", [_seiten_antwort()]), ScheinLeser("b", [_seiten_antwort(seitenart="brief")])
    auftraege = []
    for leser in (a, b):
        lies = leser.lies
        leser.lies = lambda text, bild, lies=lies: auftraege.append(text) or lies(text, bild)
    leser = iter([a, b])
    monkeypatch.setattr(kommandozeile, "_leser", lambda angabe, variable: next(leser))
    code = kommandozeile.haupt(
        ["seiten", str(pdf), "--aus", str(tmp_path / "aus"), "--dokumentart", "eines Probebelegs",
         "--seitenarten", "leer,befund", "--inhaltsarten", "labor, bild", "--datum-hinweis", "der Tag der Probe"]
    )  # fmt: skip
    assert code == 0
    aus = capsys.readouterr().out
    assert "1 Seite(n): " in aus and "kopf_uneins 1" in aus and "texte_uebernommen 1" in aus and "seiten.json" in aus
    assert "eines Probebelegs" in auftraege[0] and "[leer, befund]" in auftraege[0] and "[labor, bild]" in auftraege[0]
    assert "datum: der Tag der Probe." in auftraege[0]


def test_seiten_mit_leerem_wort_exit_1(tmp_path, capsys, monkeypatch):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf")
    leser = iter([ScheinLeser("a", []), ScheinLeser("b", [])])
    monkeypatch.setattr(kommandozeile, "_leser", lambda angabe, variable: next(leser))
    assert kommandozeile.haupt(["seiten", str(pdf), "--aus", str(tmp_path / "aus"), "--seitenarten", "leer,,x"]) == 1
    assert "leer" in capsys.readouterr().err


def _ablese_antwort():
    achsen = [
        {"name": "Drehzahl [1/s]", "anker": [{"zahl": str(v), "lage": [800, 100 + 6 * v]} for v in range(0, 101, 25)]},
        {"name": "Druck", "anker": [{"zahl": str(v), "lage": [800 - 3 * v, 100]} for v in range(0, 201, 50)]},
    ]
    punkte = [
        {"reihe": "Druck", "marke": "", "lage": [800 - 3 * y, 100 + 6 * x], "x_wert": str(x), "y_wert": str(y)}
        for x, y in ((20, 80), (60, 120), (100, 160))
    ]
    return {"achsen": achsen, "punkte": punkte}


def test_ablesen_liest_auftrag_aus_datei_und_meldet_zaehlung(tmp_path, capsys, monkeypatch):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf")
    auftrag = {
        "seite": 1,
        "diagramm": "Probekurve",
        "reihen": [{"name": "Druck", "achse_y": "druck", "achse_x": "drehzahl", "toleranz": {"y": 3, "x": 3}}],
    }
    (tmp_path / "auftrag.json").write_text(json.dumps(auftrag))
    leser = iter([ScheinLeser("a", [_ablese_antwort()]), ScheinLeser("b", [_ablese_antwort()])])
    monkeypatch.setattr(kommandozeile, "_leser", lambda angabe, variable: next(leser))
    code = kommandozeile.haupt(
        ["ablesen", str(pdf), "--aus", str(tmp_path / "aus"), "--auftrag", str(tmp_path / "auftrag.json")]
    )
    assert code == 0
    aus = capsys.readouterr().out
    assert "Seite 1: uebernommen 3" in aus and "ablesung.json" in aus


@pytest.mark.parametrize("inhalt", [None, "kein json", json.dumps({"seite": 1})])
def test_ablesen_ohne_oder_mit_kaputtem_auftrag_exit_1(tmp_path, capsys, monkeypatch, inhalt):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf")
    datei = tmp_path / "auftrag.json"
    if inhalt is not None:
        datei.write_text(inhalt)
    leser = iter([ScheinLeser("a", []), ScheinLeser("b", [])])
    monkeypatch.setattr(kommandozeile, "_leser", lambda angabe, variable: next(leser))
    assert kommandozeile.haupt(["ablesen", str(pdf), "--aus", str(tmp_path / "aus"), "--auftrag", str(datei)]) == 1
    assert capsys.readouterr().err.startswith("mkn-dokument: ")
