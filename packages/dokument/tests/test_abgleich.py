"""Der Abgleich uebernimmt nur Uebereinstimmung — und nie ueber Formatierung hinweg das Falsche."""

from mkn_dokument import abgleich


def angabe(wert, lage=(100, 100, 110, 140), bezeichnung="Messgroesse", **mehr):
    return {
        "abschnitt": "",
        "bezeichnung": bezeichnung,
        "zusatz": "",
        "art": "messwert",
        "wert": wert,
        "vergleich": "",
        "einheit": "",
        "bereich": "",
        "kennzeichen": "",
        "lage": list(lage),
        "unsicher": False,
    } | mehr


def test_gleicher_wert_an_gleicher_stelle_wird_uebernommen():
    e = abgleich.gleiche_ab([angabe("6,25")], [angabe("6,25")])
    assert [(x["ausgang"], x["grund"], x["wert"]) for x in e] == [("uebernommen", "zwei_leser", "6,25")]


def test_komma_und_punkt_sind_verschiedene_werte():
    e = abgleich.gleiche_ab([angabe("1,234")], [angabe("1.234")])
    assert [(x["ausgang"], x["grund"], x["wert"]) for x in e] == [("klaerliste", "leser_uneins", None)]


def test_klammern_und_ordnungspunkt_aendern_den_wert_nicht():
    assert abgleich.wert_schluessel("(6,0)") == abgleich.wert_schluessel(" 6,0 ")
    assert abgleich.wert_schluessel("60.") == abgleich.wert_schluessel("60")
    assert abgleich.wert_schluessel("6,20") != abgleich.wert_schluessel("6,2")


def test_verschiedene_werte_an_derselben_stelle_sind_ein_widerspruch_ohne_wert():
    e = abgleich.gleiche_ab([angabe("41")], [angabe("47")])
    assert [(x["ausgang"], x["grund"], x["wert"]) for x in e] == [("klaerliste", "leser_uneins", None)]


def test_nur_ein_leser_heisst_klaerliste():
    e = abgleich.gleiche_ab([angabe("13")], [])
    assert [(x["ausgang"], x["grund"]) for x in e] == [("klaerliste", "nur_leser_a")]
    e = abgleich.gleiche_ab([], [angabe("13")])
    assert [(x["ausgang"], x["grund"]) for x in e] == [("klaerliste", "nur_leser_b")]


def test_gleicher_wert_an_fremder_stelle_mit_fremdem_namen_ist_kein_paar():
    a = [angabe("85", lage=(100, 100, 110, 140), bezeichnung="Niederschlag")]
    b = [angabe("85", lage=(700, 600, 710, 640), bezeichnung="Windgeschwindigkeit")]
    e = abgleich.gleiche_ab(a, b)
    assert sorted(x["grund"] for x in e) == ["nur_leser_a", "nur_leser_b"]


def test_gleicher_wert_mit_gleichem_namen_paart_auch_bei_ungenauer_lage():
    a = [angabe("85", lage=(100, 100, 110, 140), bezeichnung="Max. Höhe")]
    b = [angabe("85", lage=(160, 180, 170, 220), bezeichnung="Max. Hoehe")]
    assert abgleich.gleiche_ab(a, b)[0]["ausgang"] == "uebernommen"


def test_doppelter_wert_wird_nach_lage_richtig_gepaart():
    a = [
        angabe("0,415", lage=(100, 500, 110, 540), bezeichnung="Rechter Turm"),
        angabe("0,415", lage=(130, 500, 140, 540), bezeichnung="Linker Turm"),
    ]
    b = [
        angabe("0,415", lage=(131, 501, 141, 541), bezeichnung="Linker Turm"),
        angabe("0,415", lage=(101, 501, 111, 541), bezeichnung="Rechter Turm"),
    ]
    e = abgleich.gleiche_ab(a, b)
    assert [x["ausgang"] for x in e] == ["uebernommen", "uebernommen"]
    assert [(x["leser"]["a"]["bezeichnung"], x["leser"]["b"]["bezeichnung"]) for x in e] == [
        ("Rechter Turm", "Rechter Turm"),
        ("Linker Turm", "Linker Turm"),
    ]


def test_einheit_uneins_laesst_den_wert_stehen_und_das_feld_offen():
    e = abgleich.gleiche_ab([angabe("12,6", einheit="L")], [angabe("12,6", einheit="")])
    assert e[0]["ausgang"] == "uebernommen"
    assert e[0]["einheit"] is None
    assert e[0]["offen"] == ["einheit"]


def test_einheit_und_bereich_gelten_ueber_formatierung_hinweg():
    a = [angabe("8,0", einheit="(kg)", bereich="(6,5-9,5)")]
    b = [angabe("8,0", einheit="Kg", bereich="6,5~9,5")]
    e = abgleich.gleiche_ab(a, b)
    assert e[0]["offen"] == []
    assert e[0]["einheit"] == "(kg)"


def test_vergleichszeichen_uneins_ist_keine_uebernahme():
    e = abgleich.gleiche_ab([angabe("5", vergleich="<")], [angabe("5")])
    assert [(x["ausgang"], x["grund"]) for x in e] == [("klaerliste", "vergleich_uneins")]


def test_kleiner_und_groesser_sind_ein_widerspruch():
    e = abgleich.gleiche_ab([angabe("5", vergleich="<")], [angabe("5", vergleich=">")])
    assert [(x["ausgang"], x["grund"]) for x in e] == [("klaerliste", "vergleich_uneins")]


def test_reihenfolge_der_leser_aendert_keinen_ausgang():
    a = [angabe("6,25", einheit="kg"), angabe("41", lage=(300, 100, 310, 140)), angabe("7", lage=(500, 1, 510, 9))]
    b = [angabe("6,25", einheit="(Kg)"), angabe("47", lage=(301, 101, 311, 141))]
    hin = sorted((x["ausgang"], x["grund"].replace("_a", "").replace("_b", "")) for x in abgleich.gleiche_ab(a, b))
    her = sorted((x["ausgang"], x["grund"].replace("_a", "").replace("_b", "")) for x in abgleich.gleiche_ab(b, a))
    assert hin == her == [("klaerliste", "leser_uneins"), ("klaerliste", "nur_leser"), ("uebernommen", "zwei_leser")]


def test_gleicher_wert_an_naher_stelle_mit_fremdem_namen_ist_keine_uebernahme():
    # Leser a ist in der Zeile verrutscht und schreibt den Wert der Nachbarzeile unter seinen Namen.
    a = [angabe("5", lage=(130, 100, 140, 140), bezeichnung="Heizung")]
    b = [
        angabe("6", lage=(100, 100, 110, 140), bezeichnung="Heizung"),
        angabe("5", lage=(130, 100, 140, 140), bezeichnung="Abwasser"),
    ]
    e = abgleich.gleiche_ab(a, b)
    assert [(x["ausgang"], x["grund"]) for x in e] == [("klaerliste", "name_uneins"), ("klaerliste", "nur_leser_b")]


def test_gemeinsamer_abschnitt_macht_verschiedene_groessen_nicht_aehnlich():
    a = [angabe("5", bezeichnung="Heizung", abschnitt="Nebenkosten")]
    b = [angabe("5", bezeichnung="Abwasser", abschnitt="Nebenkosten")]
    assert abgleich.gleiche_ab(a, b)[0]["grund"] == "name_uneins"


def test_aehnlicher_name_reicht_nicht_wenn_der_andere_leser_die_groesse_anders_gelesen_hat():
    # Leser a schreibt den Wert der Kalt-Miete unter „Miete“; Leser b hat die Miete mit 180 gelesen.
    a = [angabe("52", lage=(130, 100, 140, 140), bezeichnung="Miete")]
    b = [
        angabe("180", lage=(100, 100, 110, 140), bezeichnung="Miete"),
        angabe("52", lage=(130, 100, 140, 140), bezeichnung="Kalt-Miete"),
    ]
    for hin, her in ((a, b), (b, a)):
        e = abgleich.gleiche_ab(hin, her)
        assert [x["ausgang"] for x in e].count("uebernommen") == 0
        assert "name_uneins" in [x["grund"] for x in e]


def test_weggelassene_spalte_macht_vorwert_nicht_zum_aktuellen_wert():
    # Leser a verliest den aktuellen Wert zu dem des Vorjahres; Leser b hat beide Spalten richtig.
    a = [angabe("135,5", lage=(100, 300, 110, 340), bezeichnung="Stand", zusatz="aktuell")]
    b = [
        angabe("141,0", lage=(100, 300, 110, 340), bezeichnung="Stand", zusatz="aktuell"),
        angabe("135,5", lage=(100, 600, 110, 640), bezeichnung="Stand", zusatz="Vorjahr"),
    ]
    assert [x["ausgang"] for x in abgleich.gleiche_ab(a, b)].count("uebernommen") == 0
    assert [x["ausgang"] for x in abgleich.gleiche_ab(b, a)].count("uebernommen") == 0


def test_aehnlich_klingende_groessen_ohne_lage_sind_kein_paar_wenn_der_andere_sie_anders_las():
    a = [angabe("4,2", lage=(0, 0, 0, 0), bezeichnung="Kaltwasser")]
    b = [
        angabe("4,2", lage=(0, 0, 0, 0), bezeichnung="Warmwasser"),
        angabe("4,7", lage=(0, 0, 0, 0), bezeichnung="Kaltwasser"),
    ]
    assert [x["ausgang"] for x in abgleich.gleiche_ab(a, b)].count("uebernommen") == 0


def test_zwei_gleichnamige_zeilen_mit_einheit_im_zusatz_des_einen_lesers():
    # Leser a nennt beide Zeilen „Rechter Turm“, Leser b unterscheidet sie im Zusatz.
    a = [
        angabe("3,75", lage=(100, 300, 110, 340), bezeichnung="Rechter Turm"),
        angabe("86,4", lage=(120, 300, 130, 340), bezeichnung="Rechter Turm"),
    ]
    b = [
        angabe("3,75", lage=(101, 301, 111, 341), bezeichnung="Rechter Turm", zusatz="kg"),
        angabe("86,4", lage=(121, 301, 131, 341), bezeichnung="Rechter Turm", zusatz="%"),
    ]
    assert [x["ausgang"] for x in abgleich.gleiche_ab(a, b)] == ["uebernommen", "uebernommen"]


def test_gleicher_name_mit_mehreren_werten_ist_kein_widerspruch():
    # Verlaufstabelle: achtmal „Zaehlerstand“, die Leser nennen kein Datum.
    a = [angabe(str(80 + n), lage=(100, 100 + 60 * n, 110, 140 + 60 * n), bezeichnung="Zaehlerstand") for n in range(8)]
    b = [angabe(str(80 + n), lage=(101, 101 + 60 * n, 111, 141 + 60 * n), bezeichnung="Zaehlerstand") for n in range(8)]
    assert [x["ausgang"] for x in abgleich.gleiche_ab(a, b)] == ["uebernommen"] * 8


def test_langform_und_kurzform_sind_derselbe_name():
    a = [angabe("41,8", bezeichnung="USt Umsatzsteuer")]
    b = [
        angabe("41,8", bezeichnung="USt"),
        angabe("39,9", lage=(300, 100, 310, 140), bezeichnung="USt", zusatz="12.03."),
    ]
    assert abgleich.gleiche_ab(a, b)[0]["ausgang"] == "uebernommen"


def test_name_gilt_auch_wenn_die_leser_ihn_verschieden_aufteilen():
    a = [angabe("136", bezeichnung="Kosten", zusatz="Anteil % Plan", abschnitt="Uebersicht")]
    b = [angabe("136", bezeichnung="Anteil % Plan", zusatz="Kosten", abschnitt="")]
    assert abgleich.gleiche_ab(a, b)[0]["ausgang"] == "uebernommen"


def test_vorlage_lage_aus_dem_auftrag_ist_keine_lage():
    a = [angabe("4,2", lage=(0, 0, 0, 0), bezeichnung="Kaltwasser")]
    b = [angabe("4,2", lage=(0, 0, 0, 0), bezeichnung="Warmwasser gesamt im Altbau")]
    assert sorted(x["grund"] for x in abgleich.gleiche_ab(a, b)) == ["nur_leser_a", "nur_leser_b"]


def test_vorzeichen_gehoert_zum_wert():
    assert abgleich.wert_schluessel("-5") != abgleich.wert_schluessel("5")
    assert abgleich.wert_schluessel("\u22125") == abgleich.wert_schluessel("-5")
    assert abgleich.gleiche_ab([angabe("-10,5")], [angabe("10,5")])[0]["grund"] == "leser_uneins"


def test_kennzeichen_stern_gegen_leer_ist_uneins_in_beiden_reihenfolgen():
    a, b = [angabe("7", kennzeichen="*")], [angabe("7")]
    assert abgleich.gleiche_ab(a, b)[0]["offen"] == ["kennzeichen"]
    assert abgleich.gleiche_ab(b, a)[0]["offen"] == ["kennzeichen"]


def test_unsicher_eines_lesers_bleibt_sichtbar():
    assert abgleich.gleiche_ab([angabe("7")], [angabe("7", unsicher=True)])[0]["unsicher"] is True
    assert abgleich.gleiche_ab([angabe("7")], [angabe("7")])[0]["unsicher"] is False


def test_angaben_ohne_wert_werden_nicht_gefuehrt():
    assert abgleich.gleiche_ab([angabe("")], [angabe(None)]) == []


def test_ungueltige_lage_paart_nur_ueber_den_namen():
    a = [angabe("7", lage=(0, 0, 0), bezeichnung="Druck")]
    b = [angabe("7", bezeichnung="Druck")]
    assert abgleich.gleiche_ab(a, b)[0]["ausgang"] == "uebernommen"
    c = [angabe("7", bezeichnung="Etwas ganz anderes")]
    assert abgleich.gleiche_ab(a, c)[0]["ausgang"] == "klaerliste"


def test_gleiche_eingabe_gleiches_ergebnis():
    a = [angabe(str(n), lage=(n, 10, n + 8, 40)) for n in range(10, 200, 10)]
    b = list(reversed([angabe(str(n), lage=(n + 1, 11, n + 9, 41)) for n in range(10, 200, 10)]))
    assert abgleich.gleiche_ab(a, b) == abgleich.gleiche_ab(a, b)
    assert all(x["ausgang"] == "uebernommen" for x in abgleich.gleiche_ab(a, b))
