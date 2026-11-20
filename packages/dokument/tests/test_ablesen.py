"""Gezieltes Ablesen: Auftrag, Antwortform, Achsenrechnung, vier Stimmen, Abgleich je Reihe, Lauf.

Alle Diagramme sind konstruiert: Achse waagrecht 0 bis 100 und senkrecht 0 bis 200 auf einem erfundenen Seitenbild
von 2000 x 3000 Bildpunkten; Lagen gehen wie bei einem Leser in ganzen Tausendsteln an das Programm. Gedreht, schraeg
und geschert entsteht durch Umrechnen derselben Punkte.
"""

import copy
import json
import math
import stat

import pytest

from conftest import ScheinLeser, schreibe_pdf
from mkn_dokument import ablesen
from mkn_dokument.auftrag import AntwortUngueltig
from mkn_dokument.leser import LeserFehler

B, H = 2000, 3000
X0, Y0 = 400, 2400  # Ursprung des Diagramms in Bildpunkten
SX, SY = 10.0, 7.5  # Bildpunkte je Einheit waagrecht und senkrecht
WERTE = [(10, 60), (30, 85), (50, 110), (70, 140), (90, 175)]


def gerade(x, y):
    return x, y


def gedreht(grad, um=(1000, 1500)):
    w = math.radians(grad)

    def f(x, y):
        dx, dy = x - um[0], y - um[1]
        return um[0] + dx * math.cos(w) - dy * math.sin(w), um[1] + dx * math.sin(w) + dy * math.cos(w)

    return f


def geschert(grad):
    """Die senkrechte Achse kippt, die waagrechte bleibt: die Achsen stehen nicht mehr rechtwinklig."""
    return lambda x, y: (x + math.tan(math.radians(grad)) * (Y0 - y), y)


def _t(f, x, y):
    px, py = f(x, y)
    return [round(py / H * 1000), round(px / B * 1000)]


def _achsen(f=gerade, x_name="Drehzahl [U/min]", y_name="Druck [bar]", y_anker=None, x_anker=None):
    x_anker = x_anker if x_anker is not None else [(str(v), (X0 + SX * v, Y0)) for v in range(0, 101, 20)]
    y_anker = y_anker if y_anker is not None else [(str(v), (X0, Y0 - SY * v)) for v in range(0, 201, 50)]
    return [
        {"name": x_name, "anker": [{"zahl": z, "lage": _t(f, x, y)} for z, (x, y) in x_anker]},
        {"name": y_name, "anker": [{"zahl": z, "lage": _t(f, x, y)} for z, (x, y) in y_anker]},
    ]


def _punkte(f=gerade, werte=WERTE, reihe="Druck", marken=None, versatz=(0, 0), abgelesen=None):
    punkte = []
    for i, (vx, vy) in enumerate(werte):
        x, y = X0 + SX * vx + versatz[0], Y0 - SY * vy + versatz[1]
        ax, ay = abgelesen[i] if abgelesen else (vx, vy)
        punkte.append(
            {
                "reihe": reihe,
                "marke": marken[i] if marken else "",
                "lage": _t(f, x, y),
                "x_wert": str(ax).replace(".", ","),
                "y_wert": str(ay).replace(".", ","),
            }
        )
    return punkte


def _antwort(f=gerade, **punkte):
    return {"achsen": _achsen(f), "punkte": _punkte(f, **punkte)}


def _auftrag(**reihe):
    return {
        "seite": 1,
        "diagramm": "Kennlinie",
        "reihen": [{"name": "Druck", "achse_y": "druck", "achse_x": "drehzahl", "toleranz": {"y": 3, "x": 3}} | reihe],
    }


def _ab(a, b, auftrag=None):
    return ablesen.gleiche_ab(ablesen.pruefe_auftrag(auftrag or _auftrag()), a, b, B, H)


def _ausgaenge(ergebnis):
    return [(s["ausgang"], s["grund"]) for s in ergebnis["stellen"]]


# --- Zahl, Median, Rundung -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "zahl"),
    [
        ("12", 12.0),
        ("-3,5", -3.5),
        ("+0.25", 0.25),
        (" 7 ", 7.0),
        (chr(0x2212) + "2", -2.0),  # Minuszeichen
        ("1.234", None),  # Tausenderpunkt oder Dezimalpunkt? mehrdeutig, nie geraten
        ("12,500", None),
        ("-7.500", None),
        (chr(0x2212) + "2.500", None),
        ("0.125", 0.125),  # Ganzzahlteil 0: eindeutig ein Dezimalzeichen
        ("0,500", 0.5),
        ("1.25", 1.25),
        ("1234.5", 1234.5),
        ("1.234,5", None),  # zwei Trenner
        ("12 W", None),
        ("ca. 5", None),
        ("", None),
        ("1e3", None),
        ("5.", None),
        ("--5", None),
    ],
)
def test_zahl_aus_text(text, zahl):
    assert ablesen.zahl(text) == zahl


def test_median_und_rundung_auf_die_stellen_der_toleranz():
    assert ablesen.median([60.0, 61.2, 60.4, 61.0]) == pytest.approx(60.7)
    assert ablesen.median([1.0, 3.0, 2.0]) == 2.0
    assert ablesen.stellen(3) == 0 and ablesen.stellen(0.3) == 1 and ablesen.stellen("0,25") == 2
    assert ablesen.runde(60.7, 0) == 61 and isinstance(ablesen.runde(60.7, 0), int)
    assert ablesen.runde(2.25, 1) == 2.3  # kaufmaennisch, nicht zur geraden Ziffer
    assert ablesen.runde(-2.25, 1) == -2.3


# --- Achse aus Ankern ----------------------------------------------------------------------------------------------


def _anker_px(werte_lagen):
    return [(str(v), lage) for v, lage in werte_lagen]


def test_gerade_achse_rechnet_jede_lage_auf_ihren_wert():
    achse = ablesen.achse_aus_ankern(_anker_px([(v, (X0, Y0 - SY * v)) for v in (0, 50, 100, 150, 200)]))
    assert achse.wert((X0, Y0 - SY * 110)) == pytest.approx(110)
    assert achse.wert((X0 + 700, Y0 - SY * 42)) == pytest.approx(42)  # quer zur Achse zaehlt nicht


@pytest.mark.parametrize(
    ("anker", "grund"),
    [
        ([(0, (X0, Y0)), (100, (X0, Y0 - SY * 100))], "zu_wenige_anker"),
        ([(0, (X0, Y0)), (100, (X0, Y0 - SY * 100)), (100, (X0, Y0 - SY * 100))], "zu_wenige_anker"),
        # logarithmisch gedruckt: 1, 10, 100, 1000 in gleichen Abstaenden — die Gerade passt nicht
        ([(1, (X0, 2400)), (10, (X0, 2000)), (100, (X0, 1600)), (1000, (X0, 1200))], "krumm"),
        # ein Anker 40 Bildpunkte neben der Achslinie (1 % der Ankerstrecke von 1500 sind 15)
        ([(0, (X0, Y0)), (100, (X0 + 40, Y0 - SY * 100)), (200, (X0, Y0 - SY * 200))], "neben_der_achse"),
    ],
)
def test_achse_unklar_mit_grund(anker, grund):
    with pytest.raises(ablesen.AchseUnklar) as fehler:
        ablesen.achse_aus_ankern(_anker_px(anker))
    assert fehler.value.grund == grund


def test_anker_ohne_zahl_zaehlt_nicht():
    anker = [("0", (X0, Y0)), ("ca. 50", (X0, Y0 - SY * 50)), ("100", (X0, Y0 - SY * 100))]
    with pytest.raises(ablesen.AchseUnklar, match="zu_wenige_anker"):
        ablesen.achse_aus_ankern(anker)


# --- Abgleich: Geometrie -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "f", [gerade, gedreht(90), gedreht(1), gedreht(-1)], ids=["gerade", "90", "schraeg+1", "schraeg-1"]
)
def test_gerade_gedreht_und_schraeg_werden_uebernommen(f):
    ergebnis = _ab(_antwort(f), _antwort(f))
    assert _ausgaenge(ergebnis) == [("uebernommen", None)] * 5
    for stelle, (vx, vy) in zip(ergebnis["stellen"], WERTE, strict=True):
        assert stelle["achsen"]["y"]["wert"] == vy and stelle["achsen"]["x"]["wert"] == vx
        assert len(stelle["achsen"]["y"]["stimmen"]) == 4
        assert stelle["achsen"]["y"]["spanne"][0] <= vy <= stelle["achsen"]["y"]["spanne"][1]
    assert ergebnis["reihen"][0]["ausgang"] == "abgeglichen"


def test_geschertes_bild_ist_achse_unklar():
    f = geschert(5)
    ergebnis = _ab(_antwort(f), _antwort(f))
    assert _ausgaenge(ergebnis) == [("klaerliste", "achse_unklar")] * 5
    assert ergebnis["reihen"][0]["achsen"]["a"] == {"y": "nicht_rechtwinklig", "x": "nicht_rechtwinklig"}
    assert all(s["achsen"]["y"]["wert"] is None for s in ergebnis["stellen"])


def test_tausenderpunkte_an_achse_und_wert_ergeben_keine_uebernahme():
    zahlen = ["0", "2.500", "5.000", "7.500", "10.000"]
    y_anker = [(z, (X0, Y0 - SY * 50 * i)) for i, z in enumerate(zahlen)]
    a = {"achsen": _achsen(y_anker=y_anker), "punkte": _punkte(werte=[(50, 164)], abgelesen=[(50, "8.200")])}
    auftrag = _auftrag()
    ergebnis = _ab(a, copy.deepcopy(a), auftrag)
    assert ergebnis["reihen"][0]["achsen"]["a"]["y"] == "zu_wenige_anker"
    assert ergebnis["stellen"][0]["ausgang"] == "klaerliste"
    assert ergebnis["stellen"][0]["achsen"]["y"]["stimmen"]["a_abgelesen"] is None


@pytest.mark.parametrize(("grad", "zustand"), [(1.5, "ok"), (2.5, "nicht_rechtwinklig")])
def test_grenze_der_rechtwinkligkeit(grad, zustand):
    f = geschert(grad)
    auftrag = _auftrag(toleranz={"y": 10, "x": 10})  # die Scherung verschiebt die Werte; geprueft wird der Winkel
    ergebnis = _ab(_antwort(f), _antwort(f), auftrag)
    assert ergebnis["reihen"][0]["achsen"]["a"] == {"y": zustand, "x": zustand}
    erwartet = ("uebernommen", None) if zustand == "ok" else ("klaerliste", "achse_unklar")
    assert _ausgaenge(ergebnis) == [erwartet] * 5


@pytest.mark.parametrize(("anteil", "gilt"), [(0.009, True), (0.011, False)])
def test_grenze_anker_neben_der_geraden(anteil, gilt):
    """Mittlerer von fuenf gleich verteilten Ankern um d verschoben: die Gerade nimmt d/5 auf, die groesste
    Abweichung ist 0,8 d. d ist so gewaehlt, dass sie genau ``anteil`` der Zahlenspanne 200 ist."""
    d = anteil * 200 / 0.8
    werte = [0, 50, 100 + d, 150, 200]
    anker = [(f"{v:.4f}".replace(".", ","), (X0, Y0 - SY * 50 * i)) for i, v in enumerate(werte)]
    if gilt:
        assert ablesen.achse_aus_ankern(anker).wert((X0, Y0 - SY * 200)) == pytest.approx(200 + d / 5)
    else:
        with pytest.raises(ablesen.AchseUnklar, match="krumm"):
            ablesen.achse_aus_ankern(anker)


def test_reihe_mit_nur_senkrechter_achse():
    auftrag = _auftrag(achse_x=None, toleranz={"y": 3})
    del auftrag["reihen"][0]["achse_x"]
    ergebnis = _ab(_antwort(), _antwort(), auftrag)
    assert _ausgaenge(ergebnis) == [("uebernommen", None)] * 5
    assert list(ergebnis["stellen"][0]["achsen"]) == ["y"]


@pytest.mark.parametrize(
    ("y_name", "grund"),
    [("Temperatur [°C]", "kennwort_keine_achse"), ("Druck-Drehzahl", "kennwort_mehrere_achsen")],
)
def test_kennwort_trifft_keine_oder_zwei_achsen(y_name, grund):
    a = {"achsen": _achsen(y_name=y_name), "punkte": _punkte()}
    if grund == "kennwort_mehrere_achsen":
        a["achsen"][0]["name"] = "Druck-Drehzahl"  # beide Achsen tragen nun beide Kennwoerter
    ergebnis = _ab(a, _antwort())
    assert _ausgaenge(ergebnis) == [("klaerliste", "achse_unklar")] * 5
    assert ergebnis["reihen"][0]["achsen"]["a"]["y"] == grund
    assert ergebnis["reihen"][0]["achsen"]["b"] == {"y": "ok", "x": "ok"}


def test_kennwort_am_anfang_entscheidet_zwischen_mehreren_achsen():
    def mit_relativer_achse():
        antwort = {"achsen": _achsen(x_name="Last (N)"), "punkte": _punkte()}
        relativ = _achsen(x_name="rel. Last (%)")[0]
        antwort["achsen"].append(relativ)
        return antwort

    auftrag = _auftrag(achse_x="last")
    ergebnis = _ab(mit_relativer_achse(), mit_relativer_achse(), auftrag)
    assert ergebnis["reihen"][0]["achsen"]["a"] == {"y": "ok", "x": "ok"}
    assert _ausgaenge(ergebnis) == [("uebernommen", None)] * 5
    zwei_am_anfang = mit_relativer_achse()
    zwei_am_anfang["achsen"][2]["name"] = "Last relativ (%)"
    ergebnis = _ab(zwei_am_anfang, mit_relativer_achse(), auftrag)
    assert ergebnis["reihen"][0]["achsen"]["a"]["x"] == "kennwort_mehrere_achsen"


# --- Abgleich: Anzahl, Lage, Stimmen -------------------------------------------------------------------------------


def test_verschiedene_anzahl_setzt_die_ganze_reihe_auf_die_klaerliste():
    ergebnis = _ab(_antwort(), _antwort(werte=WERTE[:4]))
    assert ergebnis["stellen"] == []
    reihe = ergebnis["reihen"][0]
    assert (reihe["ausgang"], reihe["grund"], reihe["anzahl"]) == (
        "klaerliste",
        "anzahl_uneins",
        {"a": 5, "b": 4, "erwartet": None},
    )


def test_anzahl_gegen_den_auftrag():
    ergebnis = _ab(_antwort(), _antwort(), _auftrag(anzahl=6))
    assert (ergebnis["reihen"][0]["grund"], ergebnis["stellen"]) == ("anzahl_passt_nicht", [])


def test_restrisiko_gemeinsam_ausgelassener_marker_bleibt_ohne_anzahl_unentdeckt():
    """Beide Leser sehen dasselbe Bild: lassen beide denselben Marker aus, stimmen sie ueberein.

    Ohne ``anzahl`` faellt das nicht auf — die vier uebrigen Stellen sind uebernommen und die fehlende fehlt still.
    Erst die vom Fach erwartete Anzahl (etwa aus einer Tabelle) setzt die Reihe auf die Klaerliste.
    """
    ohne_dritten = WERTE[:2] + WERTE[3:]
    ergebnis = _ab(_antwort(werte=ohne_dritten), _antwort(werte=ohne_dritten))
    assert _ausgaenge(ergebnis) == [("uebernommen", None)] * 4
    assert ergebnis["reihen"][0]["ausgang"] == "abgeglichen"
    mit_anzahl = _ab(_antwort(werte=ohne_dritten), _antwort(werte=ohne_dritten), _auftrag(anzahl=5))
    assert (mit_anzahl["reihen"][0]["ausgang"], mit_anzahl["reihen"][0]["grund"]) == (
        "klaerliste",
        "anzahl_passt_nicht",
    )


def test_lagen_eines_paars_zu_weit_auseinander():
    # 1,5 % der laengeren Kante (3000) sind 45 Bildpunkte; 60 sind zu viel, 30 nicht
    ergebnis = _ab(_antwort(), _antwort(versatz=(0, 60)))
    assert _ausgaenge(ergebnis) == [("klaerliste", "lage_uneins")] * 5
    ergebnis = _ab(_antwort(), _antwort(versatz=(30, 0)))
    assert {s["grund"] for s in ergebnis["stellen"]} != {"lage_uneins"}


def test_stimmen_uneins_und_wert_fehlt():
    abgelesen = [(vx, vy) for vx, vy in WERTE]
    abgelesen[1] = (30, 92)  # 7 ueber dem Wert der Lage: Spanne groesser als 3
    abgelesen[2] = (50, "etwa 110")
    ergebnis = _ab(_antwort(), _antwort(abgelesen=abgelesen))
    assert _ausgaenge(ergebnis) == [
        ("uebernommen", None),
        ("klaerliste", "stimmen_uneins"),
        ("klaerliste", "wert_fehlt"),
        ("uebernommen", None),
        ("uebernommen", None),
    ]
    zweite = ergebnis["stellen"][1]["achsen"]["y"]
    assert zweite["wert"] is None and zweite["spanne"][1] == 92 and zweite["stimmen"]["b_abgelesen"] == 92


def test_paarung_ueber_marken_und_reihenfolge_entlang_der_waagrechten():
    marken = ["S1", "S2", "S3", "S4", "S5"]
    a = _antwort(marken=marken)
    b = _antwort(marken=[m.lower() for m in marken])
    b["punkte"].reverse()  # andere Reihenfolge in der Antwort, gleiche Marken
    ergebnis = _ab(a, b)
    assert _ausgaenge(ergebnis) == [("uebernommen", None)] * 5
    assert [s["marke"] for s in ergebnis["stellen"]] == marken
    ohne = _antwort()
    ohne["punkte"].reverse()
    assert _ausgaenge(_ab(_antwort(), ohne)) == [("uebernommen", None)] * 5  # sortiert entlang der Achse
    assert [s["achsen"]["x"]["wert"] for s in _ab(_antwort(), ohne)["stellen"]] == [10, 30, 50, 70, 90]


def test_ungleiche_marken_setzen_die_reihe_auf_die_klaerliste():
    ergebnis = _ab(_antwort(marken=["S1", "S2", "S3", "S4", "S5"]), _antwort(marken=["S1", "S2", "S3", "S4", "S6"]))
    assert (ergebnis["reihen"][0]["grund"], ergebnis["stellen"]) == ("marke_uneins", [])


@pytest.mark.parametrize(
    "marken_der_leser",
    [["S1", "S2", "S3", "S4", "S9"], None],
    ids=["andere_marke", "keine_marke"],
)
def test_benannte_marken_des_auftrags_muessen_genau_gelesen_sein(marken_der_leser):
    auftrag = _auftrag(marken=["S1", "S2", "S3", "S4", "S5"])
    ergebnis = _ab(_antwort(marken=marken_der_leser), _antwort(marken=marken_der_leser), auftrag)
    assert (ergebnis["reihen"][0]["grund"], ergebnis["stellen"]) == ("marke_uneins", [])
    gut = _ab(_antwort(marken=["s1", "S2", "S3", "S4", "S5"]), _antwort(marken=["S1", "S2", "S3", "S4", "S5"]), auftrag)
    assert _ausgaenge(gut) == [("uebernommen", None)] * 5


def test_lage_ist_die_mitte_beider_leser_und_fremde_reihen_werden_gezaehlt():
    a = _antwort()
    a["punkte"].append(_punkte(werte=[(20, 20)], reihe="Temperatur")[0])
    ergebnis = _ab(a, _antwort(versatz=(20, 0)))
    erste = ergebnis["stellen"][0]
    assert erste["lage"] == pytest.approx([(Y0 - SY * 60) / H * 1000, (X0 + SX * 10 + 10) / B * 1000], abs=0.6)
    assert ergebnis["ohne_reihe"] == {"a": 1, "b": 0}


# --- Auftrag und Antwortform ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kaputt",
    [
        lambda a: a.update(seite=0),
        lambda a: a.update(diagramm=" "),
        lambda a: a.update(reihen=[]),
        lambda a: a["reihen"][0].pop("toleranz"),  # ohne Toleranz keine Uebernahme
        lambda a: a["reihen"][0].update(toleranz={"y": 3}),  # Toleranz fuer achse_x fehlt
        lambda a: a["reihen"][0].update(toleranz={"y": 0, "x": 3}),
        lambda a: a["reihen"][0].update(toleranz={"y": "drei", "x": 3}),
        lambda a: a["reihen"][0].update(achse_y=""),
        lambda a: a["reihen"][0].update(anzahl=-1),
        lambda a: a["reihen"][0].update(anzahl=True),
        lambda a: a["reihen"][0].update(anzhal=5),  # Tippfehler faellt auf, statt still zu fehlen
        lambda a: a["reihen"][0].update(marken=["S1", ""]),
        lambda a: a["reihen"].append(dict(a["reihen"][0])),  # zweimal dieselbe Reihe
        lambda a: a.update(extra=1),
    ],
)
def test_kaputter_auftrag_wird_abgewiesen(kaputt):
    auftrag = _auftrag()
    kaputt(auftrag)
    with pytest.raises(ablesen.AuftragUngueltig):
        ablesen.pruefe_auftrag(auftrag)


def test_auftragstext_nennt_diagramm_reihen_und_kennwoerter_aber_nie_anzahl_oder_toleranz():
    auftrag = ablesen.pruefe_auftrag(_auftrag(anzahl=7, marken=None))
    text = ablesen.auftrag(auftrag)
    assert "EIN Diagramm" in text and "„Kennlinie“" in text and "gedreht" in text
    assert "„Druck“" in text and "„druck“" in text and "„drehzahl“" in text
    assert "markierte Messpunkt" in text and "nicht die Kurve" in text
    assert "7" not in text and "Toleranz" not in text
    json.loads(text[text.index("{") :])
    mit_marken = ablesen.auftrag(ablesen.pruefe_auftrag(_auftrag(marken=["S1", "S2"])))
    assert "„S1“, „S2“" in mit_marken


@pytest.mark.parametrize(
    "kaputt",
    [
        [],
        {"achsen": []},
        {"achsen": {}, "punkte": []},
        {"achsen": [{"name": "x", "anker": [{"zahl": 5, "lage": [1, 2]}]}], "punkte": []},  # Zahl statt Text
        {"achsen": [{"name": "x", "anker": [{"zahl": "5", "lage": [1]}]}], "punkte": []},
        {"achsen": [{"name": "x", "anker": [{"zahl": "5", "lage": [1, 1001]}]}], "punkte": []},
        {"achsen": [], "punkte": [{"reihe": "R", "marke": "", "lage": [1, 2], "x_wert": 5, "y_wert": "1"}]},
        {"achsen": [], "punkte": [{"reihe": 1, "marke": "", "lage": [1, 2], "x_wert": "5", "y_wert": "1"}]},
        {"achsen": [], "punkte": [{"reihe": "R", "lage": [True, 2]}]},
    ],
)
def test_falsche_antwortform_bricht_laut(kaputt):
    with pytest.raises(AntwortUngueltig):
        ablesen.pruefe_antwort(kaputt)


def test_gueltige_antwort_mit_fehlenden_nebenfeldern():
    geprueft = ablesen.pruefe_antwort(
        {"achsen": [{"name": "Druck", "anker": []}], "punkte": [{"reihe": "R", "lage": [10, 20.5], "y_wert": "3"}]}
    )
    assert geprueft["punkte"] == [{"reihe": "R", "marke": "", "lage": [10, 20.5], "x_wert": "", "y_wert": "3"}]


# --- Lauf ----------------------------------------------------------------------------------------------------------


def test_lauf_legt_ablesung_json_mit_herkunft_ab_und_liest_aus_der_mitschrift(tmp_path):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf", seiten=2)
    auftrag = _auftrag(anzahl=5) | {"seite": 2}
    # die Lagen sind in Tausendsteln, also unabhaengig von der Groesse des gerenderten Bildes
    a, b = ScheinLeser("a", [_antwort()]), ScheinLeser("b", [_antwort()])
    ergebnis = ablesen.lies_ablesung(pdf, tmp_path / "aus", a, b, auftrag)
    assert (ergebnis["funktion"], ergebnis["herkunft"], ergebnis["seite"]) == ("ablesen", "abgelesen", 2)
    assert ergebnis["auftrag"]["reihen"][0]["anzahl"] == 5 and ergebnis["leser"] == {"a": "a", "b": "b"}
    assert len(ergebnis["quelle"]["sha256"]) == 64 and ergebnis["bild"]["hoehe"] > ergebnis["bild"]["breite"]
    assert a.aufrufe[0].name == "seite-002.png"
    assert ablesen.zaehle(ergebnis) == {"uebernommen": 5}
    datei = tmp_path / "aus" / ablesen.ERGEBNIS
    assert json.loads(datei.read_text()) == ergebnis and stat.S_IMODE(datei.stat().st_mode) == 0o600
    a2, b2 = ScheinLeser("a", []), ScheinLeser("b", [])
    assert ablesen.lies_ablesung(pdf, tmp_path / "aus", a2, b2, auftrag) == ergebnis
    assert a2.aufrufe == [] and b2.aufrufe == []


def test_zaehle_nennt_reihen_auf_der_klaerliste():
    ergebnis = {"stellen": [], "reihen": [{"ausgang": "klaerliste", "grund": "anzahl_uneins"}]}
    assert ablesen.zaehle(ergebnis) == {"reihe_anzahl_uneins": 1}


def test_lauf_bricht_bei_fremder_seite_kaputtem_auftrag_oder_leserfehler(tmp_path):
    pdf = schreibe_pdf(tmp_path / "beleg.pdf")
    with pytest.raises(ablesen.AuftragUngueltig, match="Seite 3"):
        ablesen.lies_ablesung(
            pdf, tmp_path / "aus", ScheinLeser("a", []), ScheinLeser("b", []), _auftrag() | {"seite": 3}
        )
    with pytest.raises(ablesen.AuftragUngueltig):
        ablesen.lies_ablesung(pdf, tmp_path / "aus", ScheinLeser("a", []), ScheinLeser("b", []), {"seite": 1})
    with pytest.raises(LeserFehler):
        ablesen.lies_ablesung(
            pdf, tmp_path / "aus", ScheinLeser("a", [LeserFehler("aus")]), ScheinLeser("b", []), _auftrag()
        )
    with pytest.raises(AntwortUngueltig):
        ablesen.lies_ablesung(
            pdf, tmp_path / "aus", ScheinLeser("a", [_antwort()]), ScheinLeser("b", [{"x": 1}]), _auftrag()
        )
    assert not (tmp_path / "aus" / ablesen.ERGEBNIS).exists()


def test_anzahl_muss_zur_zahl_der_marken_passen():
    """Ein Auftrag mit Marken und abweichender anzahl kann nie aufgehen: er faellt beim Pruefen auf, nicht je Lauf."""
    with pytest.raises(ablesen.AuftragUngueltig, match="anzahl passt nicht"):
        ablesen.pruefe_auftrag(
            {
                "seite": 1,
                "diagramm": "Probe",
                "reihen": [{"name": "R", "achse_y": "wert", "toleranz": {"y": 1}, "marken": ["A", "B"], "anzahl": 3}],
            }
        )
