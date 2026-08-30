"""KT-1s handschriftliche Antworten als dritte Ortsquelle.

Was das Werkzeug nicht belegen konnte, hat ein Mensch beantwortet — 18 von 20
offenen Sessions. Diese Antworten sind die belastbarste Quelle im ganzen System
und waeren sonst Wegwerfarbeit: beim naechsten Lauf stuenden dieselben 20 Ordner
wieder da.

Drei Dinge, an denen dieses Modul haengt:

1. **Beide Abschnitte lesen.** Die Vorlage bietet `## Ort` und `## Gehoert
   zusammen mit`. KT-1 hat ueberwiegend unter der ZWEITEN geschrieben. Ein
   Leser, der nur `## Ort` kennt, findet fast nichts — und meldet das als
   "keine Notizen" statt als eigenen Fehler. Firsthand passiert.
2. **Der Ortsname ist der Schluessel, nicht der Text.** Die Notizen sind
   Fliesstext ("Tag 1 - erster spot - Montag ... / Lenggries im findpinguines").
   Verwertbar wird er, weil die FindPenguins-Footprints Namen UND Koordinaten
   tragen: der Name im Text findet den Footprint.
3. **Kein Treffer heisst kein Anker.** "Spontan auf einer wiese" und "irgendwo
   im nirgendwo" sind ehrliche Antworten ohne Ort. Sie duerfen keine Koordinate
   erfinden — der Text wandert trotzdem mit, als Beschreibung.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from mkn_foto import notizen
from mkn_foto.modell import Anker

FOOTPRINTS = [
    Anker(zeit=datetime(2026, 8, 24, 7, 23), lat=47.6800, lon=11.5700, name="Lenggries"),
    Anker(zeit=datetime(2026, 8, 24, 17, 28), lat=47.5134, lon=11.4440, name="Vomp"),
    Anker(zeit=datetime(2026, 8, 25, 13, 6), lat=47.6500, lon=11.3700, name="Kochel am See"),
]


def _notiz(wurzel: Path, ordner: str, *, ort: str = "", zusammen: str = "") -> Path:
    p = wurzel / ordner
    p.mkdir(parents=True, exist_ok=True)
    (p / "ort.md").write_text(
        f"# {ordner}\n\n- 43 Aufnahmen\n\n"
        f"## Ort\n\n{ort}\n\n"
        f"## Gehoert zusammen mit\n\n{zusammen}\n",
        encoding="utf-8",
    )
    return p


def test_text_unter_der_zweiten_ueberschrift_wird_gefunden(tmp_path):
    """Der Fall, der real vorkommt: KT-1 hat fast alles dort hingeschrieben."""
    _notiz(
        tmp_path,
        "2026-08-24_0619-0716",
        zusammen="Tag 1 - erster spot - Lenggries im findpinguines",
    )

    gelesen = notizen.lies(tmp_path)

    assert len(gelesen) == 1, f"nichts gefunden: {gelesen}"
    assert "Lenggries" in gelesen[0].text


def test_beide_ueberschriften_werden_zusammengefasst(tmp_path):
    _notiz(tmp_path, "2026-08-25_1535-1612", ort="Scheibum", zusammen="auch Altenau beschriftet")

    gelesen = notizen.lies(tmp_path)

    assert "Scheibum" in gelesen[0].text
    assert "Altenau" in gelesen[0].text


def test_leere_notiz_zaehlt_nicht(tmp_path):
    """Untergrenze: ohne diese Zusicherung bestuende der Leser auch dann, wenn er
    jede Vorlage als beantwortet meldete — und 20 leere Ordner saehen aus wie
    20 Antworten."""
    _notiz(tmp_path, "2026-08-24_1612-1613")

    assert notizen.lies(tmp_path) == []


def test_ortsname_findet_seinen_footprint(tmp_path):
    _notiz(tmp_path, "2026-08-24_0619-0716", zusammen="erster spot - Lenggries im findpinguines")

    zugeordnet = notizen.zu_ankern(notizen.lies(tmp_path), FOOTPRINTS)

    assert len(zugeordnet) == 1
    a = zugeordnet[0]
    assert (a.lat, a.lon) == (47.6800, 11.5700)
    assert a.name == "Lenggries"
    # Die Zeit kommt aus dem ORDNER, nicht aus dem Footprint: der Anker muss in
    # der Session liegen, die er beantwortet.
    assert datetime(2026, 8, 24, 6, 19) <= a.zeit <= datetime(2026, 8, 24, 7, 16)


def test_ohne_erkennbaren_ort_entsteht_kein_anker(tmp_path):
    """ "Spontan auf einer wiese" ist eine ehrliche Antwort ohne Ort. Wer daraus
    eine Koordinate erfindet, verletzt die oberste Regel."""
    _notiz(tmp_path, "2026-08-25_2023-2029", zusammen="ganz spontan ... irgendwo im nirgendwo")

    gelesen = notizen.lies(tmp_path)
    assert len(gelesen) == 1, "der Text soll erhalten bleiben"
    assert notizen.zu_ankern(gelesen, FOOTPRINTS) == []


def test_ein_name_der_in_einem_laengeren_steckt_ist_kein_zweiter_treffer(tmp_path):
    """Sonst waere jeder Text mit dem laengeren Namen mehrdeutig und fiele durch.

    "Kochel" steckt in "Kochel am See" — das sind nicht zwei Orte zur Auswahl,
    sondern derselbe, einmal genauer benannt. Nur echte Alternativen sind
    Mehrdeutigkeit.
    """
    mit_kurzform = [
        *FOOTPRINTS,
        Anker(zeit=datetime(2026, 8, 25, 13, 0), lat=47.65, lon=11.37, name="Kochel"),
    ]
    _notiz(
        tmp_path,
        "2026-08-25_1258-1259",
        zusammen="1. spot - Kochel am See - da gibt es einen footprint",
    )

    zugeordnet = notizen.zu_ankern(notizen.lies(tmp_path), mit_kurzform)

    assert len(zugeordnet) == 1, f"faelschlich als mehrdeutig verworfen: {zugeordnet}"
    assert zugeordnet[0].name == "Kochel am See", "der genauere Name muss gewinnen"


def test_ein_name_ohne_footprint_bezug_ist_keine_zuordnung(tmp_path):
    """Der teuerste Fehler dieses Moduls, firsthand an KT-1s Notizen gemessen.

    Drei seiner Antworten nennen einen Ortsnamen und sagen dabei das GEGENTEIL:
    *"auf der Rueckfahrt VON Grainau"*, *"wahrscheinlich irgendwie bei
    Mehrwald"*, *"von Grainau unten Eibsee denke ich"*. Eine reine Namenssuche
    macht daraus drei Orte — erfundene Orte, genau was die oberste Regel
    verbietet.
    """
    _notiz(tmp_path, "2026-08-25_2023-2029", zusammen="ganz spontan, auf der Rueckfahrt von Vomp")

    assert notizen.zu_ankern(notizen.lies(tmp_path), FOOTPRINTS) == []


def test_mehrdeutiger_text_erzeugt_keinen_anker(tmp_path):
    """Zwei Footprint-Namen in einer Notiz: welcher gilt? Mehrdeutigkeit ist ein
    Grund zu fragen, nicht zu raten."""
    _notiz(
        tmp_path,
        "2026-08-24_1644-1742",
        zusammen="footprint - erst Lenggries, dann Vomp - weiss nicht genau",
    )

    assert notizen.zu_ankern(notizen.lies(tmp_path), FOOTPRINTS) == []


def test_verschobene_ordner_werden_gefunden(tmp_path):
    """KT-1 schiebt beantwortete Ordner in einen Unterordner (`erl/`), sobald er
    sie abgearbeitet hat. Wer nur eine Ebene tief sucht, findet ausgerechnet die
    BEANTWORTETEN nicht — also genau die, um die es geht.

    Firsthand: 18 der 20 Notizen lagen unter `erl/`.
    """
    _notiz(tmp_path / "erl", "2026-08-24_0619-0716", zusammen="Lenggries im findpinguines")
    _notiz(tmp_path, "2026-08-24_1612-1613", zusammen="noch offen, aber beantwortet")

    gelesen = notizen.lies(tmp_path)

    ordner = sorted(n.ordner for n in gelesen)
    assert ordner == ["2026-08-24_0619-0716", "2026-08-24_1612-1613"], (
        f"der verschobene Ordner fehlt: {ordner}"
    )


def test_derselbe_ortsname_zweimal_ist_nicht_mehrdeutig(tmp_path):
    """Zwei Wegpunkte mit demselben Namen sind derselbe Ort.

    Ohne die Entdopplung machte sich ein Ort SELBST mehrdeutig: der aus einer
    Notiz erzeugte Anker traegt denselben Namen wie sein Footprint, und beide
    zusammen liessen die Zuordnung durchfallen. Firsthand beim Verdrahten der
    Pipeline gesehen — die Notiz war korrekt gelesen, korrekt zugeordnet, und
    kam am Ende trotzdem nicht an.
    """
    doppelt = [
        *FOOTPRINTS,
        Anker(zeit=datetime(2026, 8, 24, 6, 47), lat=47.68, lon=11.57, name="Lenggries"),
    ]
    _notiz(tmp_path, "2026-08-24_0619-0716", zusammen="Lenggries im findpinguines")

    zugeordnet = notizen.zu_ankern(notizen.lies(tmp_path), doppelt)

    assert len(zugeordnet) == 1, f"der Ort machte sich selbst mehrdeutig: {zugeordnet}"
    assert zugeordnet[0].name == "Lenggries"


def _n(ordner: str, text: str) -> notizen.Notiz:
    from datetime import datetime

    tag, fenster = ordner.split("_")
    von, bis = fenster.split("-")
    return notizen.Notiz(
        von=datetime.strptime(f"{tag} {von}", "%Y-%m-%d %H%M"),
        bis=datetime.strptime(f"{tag} {bis}", "%Y-%m-%d %H%M"),
        text=text,
        ordner=ordner,
    )


def test_ein_urteil_ersetzt_die_wortsuche() -> None:
    """ "Schon Zugspitze ganz oben" -- kein `footprint` im Text, und trotzdem
    eine klare Zuordnung. Die Wortsuche warf sie weg; ein gelesenes Urteil
    nicht."""
    from mkn_foto.notizurteil import Urteil

    fp = [Anker(zeit=datetime(2026, 8, 26, 15, 0), lat=47.42, lon=10.98, name="Zugspitze")]
    n = _n("2026-08-26_1541-1542", "Schon Zugspitze ganz oben ... erste Bilder")

    anker = notizen.zu_ankern(
        [n], fp, urteile={n.ordner: Urteil(sicher=True, ort="Zugspitze", art="zuordnung")}
    )

    assert len(anker) == 1
    assert anker[0].name == "Zugspitze"


def test_ein_bezug_erbt_den_ort_der_nachbarsession() -> None:
    """ "Gehoert ebenfalls dazu - vorheriger Ordner" ist eine vollstaendige
    Auskunft. Bisher verfiel sie: die Wortsuche fand keinen Namen, weil keiner
    dasteht -- er steht nebenan."""
    from mkn_foto.notizurteil import Urteil

    fp = [Anker(zeit=datetime(2026, 8, 22, 12, 0), lat=49.45, lon=11.08, name="Lenggries")]
    erste = _n("2026-08-22_1210-1212", "Lenggries im findpinguines")
    zweite = _n("2026-08-22_1841-1841", "Gehört ebenfalls dazu - vorheriger Ordner")

    anker = notizen.zu_ankern(
        [erste, zweite],
        fp,
        urteile={
            erste.ordner: Urteil(sicher=True, ort="Lenggries", art="zuordnung"),
            zweite.ordner: Urteil(sicher=True, art="bezug", bezug="vorheriger"),
        },
    )

    assert len(anker) == 2, "der Bezug muss einen eigenen Anker ergeben"
    assert {a.name for a in anker} == {"Lenggries"}
    # Jeder Anker liegt in SEINER Session -- sonst beantwortet er die falsche.
    assert anker[1].zeit.hour == 18


def test_eine_vermutung_wird_nicht_zum_anker() -> None:
    """Regel A: "von Grainau unten Eibsee DENKE ICH" wird vorgelegt, nicht
    geschrieben."""
    from mkn_foto.notizurteil import Urteil

    fp = [Anker(zeit=datetime(2026, 8, 25, 19, 0), lat=47.47, lon=11.02, name="Grainau")]
    n = _n("2026-08-25_1914-1958", "von Grainau unten Eibsee denke ich")

    anker = notizen.zu_ankern(
        [n], fp, urteile={n.ordner: Urteil(sicher=False, ort="Grainau", art="vermutung")}
    )

    assert anker == []


def test_eine_unsichere_zuordnung_wird_nicht_geschrieben() -> None:
    """Regel A trennt SICHER von der Art, nicht die Art allein.

    Aufgefallen durch eine hohle Mutation: der Vermutungs-Test wurde von der
    Art-Pruefung gefangen, nicht von der Sicherheitspruefung. Haette jemand die
    Sicherheitspruefung entfernt, waere alles gruen geblieben -- und ein Ort,
    den das Modell selbst anzweifelt, waere in KT-1s Bilder gewandert.
    """
    from mkn_foto.notizurteil import Urteil

    fp = [Anker(zeit=datetime(2026, 8, 25, 19, 0), lat=47.47, lon=11.02, name="Grainau")]
    n = _n("2026-08-25_1914-1958", "irgendwas mit Grainau")

    anker = notizen.zu_ankern(
        [n],
        fp,
        # Als ZUORDNUNG gelesen, aber das Modell traut sich nicht.
        urteile={n.ordner: Urteil(sicher=False, ort="Grainau", art="zuordnung")},
    )

    assert anker == []
