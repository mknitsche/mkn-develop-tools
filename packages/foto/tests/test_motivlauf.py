"""Der Laeufer: Vorschau, Modell, Urteil, Datei — ueber 1.293 Aufnahmen.

**Die Wiederaufnahme laeuft ueber den BAUM selbst, nicht ueber ein Journal.**
Wer schon ein `Motiv |`-Stichwort traegt, wird uebersprungen. Das ist kein
Sparzwang, sondern HC-1: ein Journal waere ein zweiter Zustand neben dem
Ergebnis, und die beiden driften, sobald ein Lauf abbricht — genau in dem
Moment, in dem man sich auf die Wiederaufnahme verlassen muss.

**Ein Abbruch ist der Normalfall, nicht die Ausnahme.** 630 Modellaufrufe dauern
Stunden; dazwischen faellt das Netz aus, das Limit greift, der Deckel geht zu.
Der Lauf muss danach dort weitermachen, wo er war — ohne dass jemand etwas
aufraeumt.

Alle Tests offline: der Transport ist injiziert, kein Netz, kein Schluessel.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from mkn_foto import bildurteil, kontaktbogen, motivlauf, vorschau

from mkn_kern import modelle

pytest.importorskip("PIL")
from PIL import Image

# Ohne exiftool schreibt `_merke` nichts -- und ein Test, der die ABWESENHEIT
# einer Datei behauptet, wird dann vakuum gruen: er besteht, ohne je etwas
# geprueft zu haben (LP-36, Untergrenze). `test_anreichern.py` hatte den Riegel
# von Anfang an, diese Datei nicht.
pytestmark = pytest.mark.skipif(
    shutil.which("exiftool") is None, reason="exiftool nicht verfuegbar"
)


def kontaktbogen_breite_einer_kachel() -> int:
    """Eine Kachel plus Raender — alles darueber ist ein Bogen mit mehreren."""
    return kontaktbogen.KACHEL_PX + 2 * kontaktbogen.RAND_PX


def _wahl() -> modelle.Wahl:
    return modelle.Wahl(anbieter="anthropic", modell="test-modell")


def _antwort(motive, sicher=True, belichtung="gut"):
    nutzlast = {
        "sicher": sicher,
        "motive": list(motive),
        "beschreibung": "Ein Satz.",
        "belichtung": belichtung,
    }
    return 200, json.dumps({"content": [{"text": json.dumps(nutzlast)}]}).encode()


def _bild(ordner: Path, name: str) -> Path:
    ordner.mkdir(parents=True, exist_ok=True)
    p = ordner / name
    Image.new("RGB", (300, 200), (120, 90, 60)).save(p)
    return p


def _serien_antwort(serie, bilder, sicher=True, motive=("x",), belichtung="gut"):
    """Eine Antwort auf die SERIEN-Frage (Design Stufe 3 § 4) -- anders als
    `_antwort` traegt sie `serie` und `bilder`, nicht nur die Motiv-Felder."""
    nutzlast = {
        "serie": serie,
        "bilder": list(bilder),
        "sicher": sicher,
        "motive": list(motive),
        "beschreibung": "Ein Satz.",
        "belichtung": belichtung,
    }
    return 200, json.dumps({"content": [{"text": json.dumps(nutzlast)}]}).encode()


def test_jedes_bild_bekommt_sein_urteil(tmp_path):
    bilder = [_bild(tmp_path, f"b{i}.jpg") for i in range(3)]
    aufrufe = []

    def transport(url, koerper, kopf, zeitgrenze):
        aufrufe.append(url)
        return _antwort(["Wald", "Nebel"])

    ergebnis = motivlauf.fahre(
        [(b, None) for b in bilder], _wahl(), transport=transport, schluessel="x"
    )

    assert len(aufrufe) == 3, f"erwartet drei Aufrufe, gezaehlt {len(aufrufe)}"
    assert len(ergebnis.urteile) == 3
    assert all(u.sicher for u in ergebnis.urteile.values())


def test_eine_serie_kostet_genau_einen_aufruf(tmp_path):
    """Der Grund, warum die Analyse bezahlbar bleibt: eine Serie ist EIN Motiv.
    630 Aufrufe statt 1.293, rund 7 EUR statt 13."""
    mitglieder = [_bild(tmp_path, f"s{i}.jpg") for i in range(5)]
    aufrufe = []

    def transport(url, koerper, kopf, zeitgrenze):
        aufrufe.append(json.loads(koerper))
        return _antwort(["Panorama", "Bergkette"])

    ergebnis = motivlauf.fahre(
        [(mitglieder[0], mitglieder)], _wahl(), transport=transport, schluessel="x"
    )

    assert len(aufrufe) == 1, f"eine Serie kostete {len(aufrufe)} Aufrufe"
    assert len(ergebnis.urteile) == 1
    # Alle Mitglieder erben dasselbe Urteil.
    assert ergebnis.fuer(mitglieder[3]) is ergebnis.fuer(mitglieder[0])

    # Und es muss der KONTAKTBOGEN mitgehen, nicht bloss das erste Bild: sonst
    # urteilt das Modell ueber eine Aufnahme und die Serie erbt es blind. Der
    # Bogen ist breiter als eine Einzelkachel -- daran ist er zu erkennen.
    import base64
    import io

    daten = aufrufe[0]["messages"][0]["content"]
    bildteil = next(x for x in daten if x.get("type") == "image")
    roh = base64.standard_b64decode(bildteil["source"]["data"])
    with Image.open(io.BytesIO(roh)) as gesendet:
        assert gesendet.width > kontaktbogen_breite_einer_kachel(), (
            f"es ging ein Einzelbild mit ({gesendet.width} px breit), kein Kontaktbogen"
        )


def test_ein_zweiter_lauf_macht_keinen_einzigen_aufruf(tmp_path):
    """Die Wiederaufnahme. Ein Abbruch nach 400 von 630 Aufrufen ist normal —
    der zweite Lauf darf die 400 nicht noch einmal bezahlen."""
    bilder = [_bild(tmp_path, f"w{i}.jpg") for i in range(3)]
    aufrufe = []

    def transport(url, koerper, kopf, zeitgrenze):
        aufrufe.append(url)
        return _antwort(["Wald"])

    eintraege = [(b, None) for b in bilder]
    erstes = motivlauf.fahre(eintraege, _wahl(), transport=transport, schluessel="x")
    erste_runde = len(aufrufe)

    # Der Zustand des ersten Laufs geht in den zweiten -- er IST der Zustand,
    # daneben gibt es keinen (HC-1). Die Pipeline baut ihn aus dem Baum.
    motivlauf.fahre(eintraege, _wahl(), transport=transport, schluessel="x", vorhandene=erstes)

    assert erste_runde == 3
    assert len(aufrufe) == 3, (
        f"der zweite Lauf hat {len(aufrufe) - erste_runde} Aufrufe wiederholt — "
        "die Wiederaufnahme greift nicht"
    )


def test_ein_gescheiterter_aufruf_stoppt_den_lauf_nicht(tmp_path):
    """Bei 630 Aufrufen ist ein Fehler normal. Er darf die anderen 629 nicht
    mitnehmen — und er muss im Ergebnis stehen, nicht im Nichts."""
    bilder = [_bild(tmp_path, f"f{i}.jpg") for i in range(3)]
    zaehler = {"n": 0}

    def transport(url, koerper, kopf, zeitgrenze):
        zaehler["n"] += 1
        if zaehler["n"] == 2:
            return 429, b'{"error":{"message":"rate limit"}}'
        return _antwort(["Wald"])

    ergebnis = motivlauf.fahre(
        [(b, None) for b in bilder], _wahl(), transport=transport, schluessel="x"
    )

    assert len(ergebnis.urteile) == 2, "die gesunden Bilder fehlen"
    assert len(ergebnis.fehler) == 1, f"der Fehler steht nirgends: {ergebnis.fehler}"
    assert "rate limit" in ergebnis.fehler[0][1]


def test_ohne_lesbare_vorschau_wird_kein_aufruf_gemacht(tmp_path):
    """Ein Aufruf ohne Bild kostet Geld und liefert eine fluessige, vollstaendig
    erfundene Antwort — das ist schlimmer als kein Aufruf."""
    kaputt = tmp_path / "kaputt.jpg"
    kaputt.write_bytes(b"kein bild")
    aufrufe = []

    def transport(url, koerper, kopf, zeitgrenze):
        aufrufe.append(url)
        return _antwort(["irgendwas"])

    ergebnis = motivlauf.fahre([(kaputt, None)], _wahl(), transport=transport, schluessel="x")

    assert not aufrufe, "es wurde ohne Bild angefragt"
    assert ergebnis.fehler, "der Grund fehlt im Ergebnis"


def test_das_bild_geht_wirklich_mit(tmp_path):
    """Untergrenze: ein stillschweigend weggelassenes Bild ergibt eine fluessige,
    vollstaendig erfundene Antwort — und die sieht man ihr nicht an."""
    bild = _bild(tmp_path, "mit.jpg")
    gesehen = {}

    def transport(url, koerper, kopf, zeitgrenze):
        gesehen["koerper"] = json.loads(koerper)
        return _antwort(["Wald"])

    motivlauf.fahre([(bild, None)], _wahl(), transport=transport, schluessel="x")

    inhalt = gesehen["koerper"]["messages"][0]["content"]
    bildteile = [t for t in inhalt if t.get("type") == "image"]
    assert bildteile, f"kein Bild in der Anfrage: {[t.get('type') for t in inhalt]}"
    assert bildteile[0]["source"]["data"], "das Bild ist leer"


def test_der_zustand_laesst_sich_aus_dem_baum_lesen(tmp_path):
    """Die Wiederaufnahme braucht keinen zweiten Zustand.

    Wer schon ein `Motiv |`-Stichwort in seinem Sidecar traegt, ist beurteilt.
    Ein Journal daneben waere ein zweiter Zustand ueber dieselbe Sache — und die
    beiden driften, sobald ein Lauf abbricht, also genau dann, wenn man sich auf
    die Wiederaufnahme verlassen muss (HC-1).
    """
    fertig = _bild(tmp_path, "fertig.jpg")
    offen = _bild(tmp_path, "offen.jpg")
    (tmp_path / "fertig.xmp").write_text(
        "<x:xmpmeta><lr:hierarchicalSubject>Motiv|Wald</lr:hierarchicalSubject></x:xmpmeta>",
        encoding="utf-8",
    )

    zustand = motivlauf.aus_baum([fertig, offen])

    assert fertig in zustand.urteile, "das fertige Bild wird nicht erkannt"
    assert offen not in zustand.urteile, "das offene Bild gilt faelschlich als fertig"


def test_ein_sidecar_ohne_motiv_gilt_als_offen(tmp_path):
    """Untergrenze zur Baum-Lesung: ein Sidecar ist nicht dasselbe wie ein
    Urteil.

    Nach V1 traegt JEDE Aufnahme einen Sidecar (Ort, Serie, Technik) — aber noch
    kein Motiv. Wer die blosse Anwesenheit der Datei als „erledigt" liest,
    ueberspringt den ganzen Bestand und macht null Aufrufe.
    """
    bild = _bild(tmp_path, "mit-sidecar.jpg")
    (tmp_path / "mit-sidecar.xmp").write_text(
        "<x:xmpmeta><lr:hierarchicalSubject>Technik|Einzelbild"
        "</lr:hierarchicalSubject></x:xmpmeta>",
        encoding="utf-8",
    )

    zustand = motivlauf.aus_baum([bild])

    assert bild not in zustand.urteile, (
        "ein Sidecar ohne Motiv-Stichwort gilt als beurteilt — dann macht der "
        "Lauf ueber den ganzen Bestand keinen einzigen Aufruf"
    )


def test_der_lauf_misst_jeden_aufruf(tmp_path):
    """KT-1s Frage vor dem Start: „nicht dass wir durchlaufen und uns dann
    messwerte token pro aktion, pro bild usw fehlen".

    Die Zahlen liefert die API frei Haus; sie wegzuwerfen und hinterher zu
    schaetzen waere die teuerste Art, an Daten zu kommen, die man schon hatte.
    """
    bilder = [_bild(tmp_path, f"m{i}.jpg") for i in range(2)]

    def transport(url, koerper, kopf, zeitgrenze):
        status, roh = _antwort(["Wald"])
        d = json.loads(roh)
        d["usage"] = {"input_tokens": 2184, "output_tokens": 187}
        return status, json.dumps(d).encode()

    ergebnis = motivlauf.fahre(
        [(b, None) for b in bilder], _wahl(), transport=transport, schluessel="x"
    )

    assert ergebnis.messung.aufrufe == 2
    assert ergebnis.messung.tokens_ein == 2 * 2184, (
        f"Tokens nicht erfasst: {ergebnis.messung.tokens_ein}"
    )
    assert ergebnis.messung.tokens_aus == 2 * 187
    assert ergebnis.messung.dauer_s > 0, "die Dauer wurde nicht gemessen"


def test_auch_ein_gescheiterter_aufruf_wird_gemessen(tmp_path):
    """Gerade der ist interessant: er hat Zeit gekostet. Wer nur die gelungenen
    misst, sieht einen Lauf, der schneller war, als er wirklich war."""
    bild = _bild(tmp_path, "f.jpg")

    def transport(url, koerper, kopf, zeitgrenze):
        return 429, b'{"error":{"message":"rate limit"}}'

    ergebnis = motivlauf.fahre([(bild, None)], _wahl(), transport=transport, schluessel="x")

    assert ergebnis.messung.aufrufe == 1, "der Fehlschlag fehlt in der Messung"
    assert ergebnis.messung.gescheitert == 1


def test_serien_und_einzelbilder_werden_getrennt_gemessen(tmp_path):
    """Sie kosten verschieden viel, und der Unterschied ist der Grund fuer den
    Kontaktbogen. Ohne die Trennung laesst sich nicht pruefen, ob er sich
    gelohnt hat."""
    einzeln = _bild(tmp_path, "e.jpg")
    serie = [_bild(tmp_path, f"s{i}.jpg") for i in range(3)]

    def transport(url, koerper, kopf, zeitgrenze):
        status, roh = _antwort(["Wald"])
        d = json.loads(roh)
        d["usage"] = {"input_tokens": 2000, "output_tokens": 100}
        return status, json.dumps(d).encode()

    ergebnis = motivlauf.fahre(
        [(einzeln, None), (serie[0], serie)], _wahl(), transport=transport, schluessel="x"
    )

    arten = {w.art for w in ergebnis.messung.werte}
    assert arten == {"einzel", "serie"}, f"die Arten werden nicht getrennt: {arten}"


def test_der_lauf_meldet_fortschritt(tmp_path):
    """KT-1 vor dem Start: "zeit auch messen und auch fortschritt".

    969 Aufrufe dauern Stunden. Ein Lauf ohne Zwischenmeldung ist ein blinder
    Fleck, kein Fortschritt — man weiss nicht, ob er arbeitet, wo er steht und
    wann er fertig ist.
    """
    bilder = [_bild(tmp_path, f"p{i}.jpg") for i in range(5)]
    meldungen = []

    def transport(url, koerper, kopf, zeitgrenze):
        status, roh = _antwort(["Wald"])
        d = json.loads(roh)
        d["usage"] = {"input_tokens": 2000, "output_tokens": 100}
        return status, json.dumps(d).encode()

    motivlauf.fahre(
        [(b, None) for b in bilder],
        _wahl(),
        transport=transport,
        schluessel="x",
        melde=meldungen.append,
        melde_alle=2,
    )

    assert meldungen, "keine einzige Fortschrittsmeldung"
    # Jede Meldung nennt, wo der Lauf steht.
    assert any("5" in m for m in meldungen), f"die Gesamtzahl fehlt: {meldungen}"


def test_die_meldung_nennt_verbrauch_und_hochrechnung(tmp_path):
    """Ohne beides ist "Bild 400 von 969" eine Zahl ohne Folge. Mit beidem
    kann KT-1 entscheiden, ob er den Lauf weiterlaufen laesst."""
    bilder = [_bild(tmp_path, f"h{i}.jpg") for i in range(4)]
    meldungen = []

    def transport(url, koerper, kopf, zeitgrenze):
        status, roh = _antwort(["Wald"])
        d = json.loads(roh)
        d["usage"] = {"input_tokens": 2000, "output_tokens": 100}
        return status, json.dumps(d).encode()

    motivlauf.fahre(
        [(b, None) for b in bilder],
        _wahl(),
        transport=transport,
        schluessel="x",
        melde=meldungen.append,
        melde_alle=2,
    )

    letzte = meldungen[-1]
    assert "EUR" in letzte or "€" in letzte, f"kein Verbrauch in der Meldung: {letzte}"
    # Auf die konkrete Form pruefen, nicht auf ein "s": das steckt auch in
    # "Tokens", und die erste Fassung blieb deshalb gruen, als die Zeitangabe
    # ganz entfiel.
    assert "gelaufen" in letzte, f"keine verstrichene Zeit: {letzte}"
    assert "noch ~" in letzte, f"keine Hochrechnung: {letzte}"


def test_ohne_melde_funktion_laeuft_es_trotzdem(tmp_path):
    """Untergrenze: die Meldung ist ein Zusatz, kein Fundament."""
    bild = _bild(tmp_path, "still.jpg")

    def transport(url, koerper, kopf, zeitgrenze):
        return _antwort(["Wald"])

    ergebnis = motivlauf.fahre([(bild, None)], _wahl(), transport=transport, schluessel="x")

    assert len(ergebnis.urteile) == 1


def test_gemini_wird_richtig_adressiert_und_angemeldet(tmp_path, monkeypatch) -> None:
    """Adresse UND Kopf -- zwei Fehler an derselben Naht.

    Gegen die echte API kam `404`, weil die Adresse auf `/models` endete. Und
    haette sie gestimmt, waere der naechste Fehler `401` gefolgt: Google nimmt
    `x-goog-api-key`, kein `Bearer`. Beides konnte ein gefaelschter Transport
    nicht finden -- er waehlt keine Adresse an und meldet sich nirgends an.
    """
    from PIL import Image

    bild = tmp_path / "b.jpg"
    Image.new("RGB", (400, 300), (60, 90, 120)).save(bild)

    gesehen: dict[str, object] = {}

    def transport(url, koerper, kopf, zeitgrenze):
        gesehen["url"] = url
        gesehen["kopf"] = kopf
        return 200, json.dumps(
            {
                "candidates": [{"content": {"parts": [{"text": '{"sicher": false}'}]}}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2},
            }
        ).encode()

    wahl = modelle.Wahl(anbieter="gemini", modell="gemini-2.5-flash")
    motivlauf.fahre([(bild, None)], wahl, schluessel="AIza-test", transport=transport)

    assert gesehen["url"].endswith("/models/gemini-2.5-flash:generateContent")
    assert gesehen["kopf"].get("x-goog-api-key") == "AIza-test"
    assert "authorization" not in gesehen["kopf"]


def test_ein_grosses_jpeg_geht_nicht_in_voller_groesse_hinaus(tmp_path) -> None:
    """Der teuerste Fehler dieser Nacht -- zum ZWEITEN Mal.

    **Gemessen, 2026-08-30.** Eine RAW-Datei bekam laengst eine verkleinerte
    Vorschau; ein JPEG wurde als "ist schon ein Bild" DURCHGEREICHT. Bei einer
    D850 sind das 6192x4128 Pixel = rund 34.000 Tokens statt 2.185 -- das
    **Fuenfzehnfache**, je Bild.

    Im laufenden Archiv sind 136 von 1.363 Aufnahmen reine JPEGs ohne RAW.
    Haette der Lauf sie erreicht, waere er um rund 20 EUR teurer geworden --
    fuer nichts, denn keine Bildbeurteilung braucht 25 Megapixel.

    Es ist derselbe Fehler wie in der Nacht zuvor, nur im anderen Zweig: dort
    gingen die RAW-Vorschauen in Originalgroesse hinaus (60.588 Tokens je
    Bild, 252 EUR statt 16). Der RAW-Zweig wurde repariert, der JPEG-Zweig
    blieb -- weil niemand nach dem zweiten Zweig gefragt hat.

    **Das Original wird dabei NICHT angefasst.** Verkleinert wird eine Kopie
    im Arbeitsraum; die Datei des Anwenders bleibt, wie sie ist.
    """
    from PIL import Image

    gross = tmp_path / "gross.JPG"
    Image.new("RGB", (6192, 4128), (120, 60, 30)).save(gross, quality=60)
    vorher = gross.stat().st_size

    vorlage = motivlauf._bildvorlage(gross, None, tmp_path / "arbeit" / "v.jpg")

    assert vorlage is not None
    breite, hoehe = Image.open(vorlage).size
    assert max(breite, hoehe) <= vorschau.MAX_KANTE_PX, f"{breite}x{hoehe} geht ungekuerzt hinaus"
    # Und das Original ist unberuehrt.
    assert Image.open(gross).size == (6192, 4128), "das Original wurde veraendert"
    assert gross.stat().st_size == vorher


def test_ein_urteil_ueberlebt_den_abbruch(tmp_path, monkeypatch) -> None:
    """**Was zweimal an einem Tag verloren ging.**

    `aus_baum` liest den Stand eines frueheren Laufs aus den Sidecars und
    ueberspringt, was schon beurteilt ist -- ein durchdachter
    Wiederaufnahme-Weg. Er lief nur ins Leere: geschrieben wurde erst GANZ AM
    ENDE, nach allen Aufrufen. Bis dahin lagen die Urteile im Arbeitsspeicher.

    Am 2026-08-30 wurde der Lauf zweimal abgebrochen; beide Male waren die
    bezahlten Urteile weg, und `aus_baum` fand beim Neustart nichts. Beim
    zweiten Mal waren es 3,12 EUR und 200 Aufrufe.

    Der Kommentar an `MOTIV_MARKE` sagt es selbst: *"Der Baum IST der Zustand"*.
    Das stimmt aber erst, wenn waehrend des Laufs in ihn geschrieben wird.
    """
    from PIL import Image

    bild = tmp_path / "b.jpg"
    Image.new("RGB", (400, 300), (60, 90, 120)).save(bild)
    zweites = tmp_path / "c.jpg"
    Image.new("RGB", (400, 300), (90, 60, 120)).save(zweites)

    class Abbruch(RuntimeError):
        pass

    aufrufe = {"n": 0}

    def transport(url, koerper, kopf, zeitgrenze=120.0):
        aufrufe["n"] += 1
        if aufrufe["n"] > 1:
            raise Abbruch("Strom weg")
        return 200, json.dumps(
            {
                "content": [{"text": '{"sicher": true, "motive": ["Wald"]}'}],
                "usage": {"input_tokens": 10, "output_tokens": 2},
            }
        ).encode()

    wahl = modelle.Wahl(anbieter="anthropic", modell="x")
    with pytest.raises(Abbruch):
        motivlauf.fahre([(bild, None), (zweites, None)], wahl, schluessel="k", transport=transport)

    # Das erste Urteil muss im Baum stehen -- sonst ist es bezahlt und weg.
    wieder = motivlauf.aus_baum([bild, zweites])
    assert bild in wieder.urteile, "das bezahlte Urteil ueberlebte den Abbruch nicht"
    assert zweites not in wieder.urteile


def test_ein_unsicheres_urteil_wird_nicht_gemerkt(tmp_path) -> None:
    """Regel A gilt auch fuer die Zwischenspeicherung.

    Wuerde ein unsicheres Urteil in den Baum geschrieben, haette es zwei
    Wirkungen, und beide sind falsch: es stuende als Stichwort in KT-1s Datei,
    obwohl das Modell selbst zweifelt -- und `aus_baum` haelte das Bild beim
    naechsten Lauf fuer erledigt, sodass es NIE eine bessere Antwort bekaeme.

    Aufgefallen durch eine hohle Mutation: der Abbruch-Test benutzt ein
    SICHERES Urteil und konnte den Fall gar nicht sehen.
    """
    from PIL import Image

    bild = tmp_path / "b.jpg"
    Image.new("RGB", (400, 300), (60, 90, 120)).save(bild)

    def transport(url, koerper, kopf, zeitgrenze=120.0):
        return 200, json.dumps(
            {
                "content": [{"text": '{"sicher": false, "motive": ["Wald"]}'}],
                "usage": {"input_tokens": 10, "output_tokens": 2},
            }
        ).encode()

    motivlauf.fahre(
        [(bild, None)],
        modelle.Wahl(anbieter="anthropic", modell="x"),
        schluessel="k",
        transport=transport,
    )

    assert not bild.with_suffix(".xmp").exists(), "ein unsicheres Urteil landete in der Datei"
    assert bild not in motivlauf.aus_baum([bild]).urteile


def test_neben_einem_jpeg_entsteht_kein_sidecar(tmp_path) -> None:
    """**KT-1s 71 ueberzaehlige Dateien -- der Mechanismus.**

    Die Traeger-Regel der Spec Paragraf 10 kennt eine Stelle je Format: RAW
    bekommt einen Sidecar, JPEG traegt seine Angaben eingebettet. `_merke` kannte
    sie nicht und legte seine Marke blind nach `bild.with_suffix('.xmp')` -- auch
    neben ein JPEG, in das `anreichern` unmittelbar danach einbettet.

    Das Ergebnis ist nicht nur Muell. Dieselbe Aussage steht dann an ZWEI Stellen
    (Spec: „zwei Zustaende ueber eine Sache"), und Lightroom bevorzugt bei
    vorhandenem Sidecar diesen -- angezeigt wird moeglicherweise etwas anderes,
    als in der Datei steht.

    Gemessen am 2026-08-30: der Bestand traegt 65 JPEG ohne RAW, KT-1 zaehlte 71
    ueberzaehlige Dateien. Firsthand nachgestellt an drei D850-JPEGs: zwei
    bekamen einen Sidecar, den `anreichern` nie geschrieben hatte (es meldete
    „1 Sidecars, 4 eingebettet" bei vier Aufnahmen).
    """
    from PIL import Image

    bild = tmp_path / "nur.jpg"
    Image.new("RGB", (400, 300), (60, 90, 120)).save(bild)

    def transport(url, koerper, kopf, zeitgrenze=120.0):
        return 200, json.dumps(
            {"content": [{"text": '{"sicher": true, "motive": ["Wald"]}'}]}
        ).encode()

    motivlauf.fahre(
        [(bild, None)],
        modelle.Wahl(anbieter="anthropic", modell="x"),
        schluessel="k",
        transport=transport,
    )

    assert not bild.with_suffix(".xmp").exists(), (
        "neben dem JPEG liegt ein Sidecar -- die Traeger-Regel gilt nur an einer Stelle"
    )
    # Die Untergrenze: ohne sie besteht dieser Test auch dann, wenn gar nichts
    # geschrieben wurde. "Keine Datei daneben" ist ueber dem Nichts trivial wahr
    # -- die Aussage lautet "eingebettet STATT daneben", und die Haelfte davon
    # steht sonst nirgends in diesem Test (LP-36).
    assert bild in motivlauf.aus_baum([bild]).urteile, (
        "die Marke wurde weder daneben noch eingebettet geschrieben -- "
        "der Test ueber die Abwesenheit des Sidecars beweist so gar nichts"
    )


def test_ein_jpeg_urteil_ueberlebt_den_abbruch_ebenfalls(tmp_path) -> None:
    """Die andere Haelfte derselben Aenderung -- und ohne sie waere sie ein Rueckschritt.

    Wird die Marke bei einem JPEG eingebettet statt danebengelegt, muss die
    Wiederaufnahme genau dort nachsehen. Sonst faende `aus_baum` nichts mehr,
    haelte jedes JPEG fuer unbeurteilt und zahlte beim naechsten Lauf ALLE
    Urteile erneut -- teurer als der Fehler, den die Aenderung behebt.

    Der Abbruch-Test daneben benutzt ebenfalls JPEGs und wuerde diesen Fall
    mitnehmen; er steht hier trotzdem eigenstaendig, weil er eine ANDERE
    Zusicherung traegt: dort geht es um das Schreiben waehrend des Laufs, hier
    um das Wiederfinden ueber die Traeger-Regel hinweg.
    """
    from PIL import Image

    bild = tmp_path / "b.jpg"
    Image.new("RGB", (400, 300), (60, 90, 120)).save(bild)

    def transport(url, koerper, kopf, zeitgrenze=120.0):
        return 200, json.dumps(
            {"content": [{"text": '{"sicher": true, "motive": ["Wald"]}'}]}
        ).encode()

    motivlauf.fahre(
        [(bild, None)],
        modelle.Wahl(anbieter="anthropic", modell="x"),
        schluessel="k",
        transport=transport,
    )

    wieder = motivlauf.aus_baum([bild])
    assert bild in wieder.urteile, "das eingebettete Urteil wird beim naechsten Lauf nicht gefunden"


def test_ein_fremdes_stichwort_gilt_nicht_als_urteil(tmp_path) -> None:
    """**Ein Teilstring ist keine Marke.**

    `aus_baum` erkannte ein beurteiltes Bild daran, dass `Motiv|` im Feldtext
    vorkommt. Ein fremdes Stichwort aus Capture One wie `Themen|Motiv|Ideen`
    enthaelt das ebenfalls -- das Bild haette als beurteilt gegolten und **nie**
    ein Urteil bekommen. Das ist die teurere der beiden Fehlrichtungen: ein
    doppelter Aufruf kostet zwei Cent, ein nie gestellter kostet die Aussage.

    Geprueft wird deshalb je EINTRAG auf seinen Anfang, nicht der
    zusammengesetzte Text auf ein Vorkommen. Gefunden vom Cross-Modell-Review.
    """
    from PIL import Image

    bild = tmp_path / "fremd.jpg"
    Image.new("RGB", (400, 300), (60, 90, 120)).save(bild)
    import subprocess as sp

    sp.run(
        [
            "exiftool",
            "-q",
            "-overwrite_original",
            "-XMP-lr:HierarchicalSubject+=Themen|Motiv|Ideen",
            str(bild),
        ],
        capture_output=True,
        check=False,
    )

    zustand = motivlauf.aus_baum([bild])

    assert bild not in zustand.urteile, (
        "ein fremdes Stichwort, das 'Motiv|' nur enthaelt, gilt als Urteil -- "
        "dieses Bild bekaeme nie eines"
    )


def test_ein_fehlgeschlagenes_merken_wird_gemeldet(tmp_path, caplog) -> None:
    """**Ein stiller Schreibfehlschlag kostet nicht einen Aufruf, sondern jeden Lauf.**

    Der Docstring von `_merke` sagt, ein Fehler koste "im schlimmsten Fall EINEN
    doppelten Aufruf". Das gilt fuer einen einmaligen Ausrutscher. Kann ein
    Format grundsaetzlich nicht beschrieben werden -- HEIC braucht exiftool
    >= 12.44 fuer XMP, eine Datei ist schreibgeschuetzt oder defekt --, schlaegt
    es bei JEDEM Bild und in JEDEM Lauf fehl. Ohne Meldung sieht das niemand:
    die Marke fehlt, und `aus_baum` haelt das Bild folgerichtig fuer offen.

    Aus einem doppelten Aufruf wird so ein doppelter LAUF. Gefunden vom
    Cross-Modell-Review; der Rueckgabewert wurde vorher verworfen.
    """
    import logging

    kaputt = tmp_path / "kaputt.jpg"
    kaputt.write_bytes(b"das ist kein JPEG")

    with caplog.at_level(logging.WARNING, logger="mkn_foto.motivlauf"):
        motivlauf._merke(kaputt, bildurteil.Urteil(sicher=True, motive=("Wald",)))

    assert any("nicht gemerkt" in r.getMessage() for r in caplog.records), (
        "ein fehlgeschlagenes Einbetten wurde nicht gemeldet"
    )


# ---------------------------------------------------------------------------
# Die Frage-Art (Design 2026-08-30 Stufe 3 § 4): ein Eintrag traegt kuenftig,
# WELCHE Frage er stellt. `motiv` ist die bestehende Frage (auch fuer
# Wiederholungs-Gruppen); `serie` ist die neue Frage nach Panorama /
# Wiederholung / keine Serie -- sie ERSETZT den Motiv-Aufruf der Gruppe (§ 7).
# ---------------------------------------------------------------------------


def test_die_serien_frage_stellt_den_serien_prompt_statt_des_motiv_prompts(tmp_path):
    mitglieder = [_bild(tmp_path, f"k{i}.jpg") for i in range(3)]
    gesehen = []

    def transport(url, koerper, kopf, zeitgrenze):
        gesehen.append(json.loads(koerper))
        return _serien_antwort("panorama", [1, 2, 3])

    ergebnis = motivlauf.fahre(
        [(mitglieder[0], mitglieder, "serie")], _wahl(), transport=transport, schluessel="x"
    )

    assert len(gesehen) == 1, f"erwartet ein Aufruf, gezaehlt {len(gesehen)}"
    text_teil = next(t for t in gesehen[0]["messages"][0]["content"] if t.get("type") == "text")
    assert text_teil["text"] == bildurteil.serien_prompt(), (
        "der Aufruf stellte nicht den Serien-Prompt"
    )
    urteil = ergebnis.fuer(mitglieder[0])
    assert isinstance(urteil, bildurteil.Serienurteil), f"kein Serienurteil, sondern {urteil!r}"
    assert urteil.serie == "panorama"
    assert urteil.bilder == (1, 2, 3)


def test_ohne_frage_art_wird_weiterhin_nach_dem_motiv_gefragt(tmp_path):
    """Rueckwaertskompatibilitaet: `pipeline.py` baut seine Eintraege heute
    noch als reine 2-Tupel -- ohne diesen Test wuerde die Serien-Verdrahtung
    den bestehenden Aufrufer sofort brechen."""
    bild = _bild(tmp_path, "zwei-tupel.jpg")
    gesehen = []

    def transport(url, koerper, kopf, zeitgrenze):
        gesehen.append(json.loads(koerper))
        return _antwort(["Wald"])

    ergebnis = motivlauf.fahre([(bild, None)], _wahl(), transport=transport, schluessel="x")

    text_teil = next(t for t in gesehen[0]["messages"][0]["content"] if t.get("type") == "text")
    assert text_teil["text"] == bildurteil.prompt(), "ein 2-Tupel fragte nicht nach dem Motiv"
    assert isinstance(ergebnis.fuer(bild), bildurteil.Urteil)


def test_serien_kontaktbogen_bricht_bei_einem_unlesbaren_mitglied_ab(tmp_path):
    """Die Nummern im Prompt und die Bilder im Kontaktbogen muessen dieselbe
    Reihenfolge haben (Design § 4): faellt ein Mitglied beim Bauen durch,
    wuerde `kontaktbogen.baue` die folgenden Kacheln nach vorne ruecken --
    Nummer 3 waere dann Mitglied 4, und die Antwort des Modells wuerde spaeter
    dem FALSCHEN Bild zugeordnet. Besser gar kein Bogen als ein falsch
    nummerierter."""
    gut = [_bild(tmp_path, f"g{i}.jpg") for i in range(2)]
    kaputt = tmp_path / "kaputt.jpg"
    kaputt.write_bytes(b"kein bild")
    gruppe = [gut[0], kaputt, gut[1]]

    vorlage = motivlauf._bildvorlage(gruppe[0], gruppe, tmp_path / "ziel.jpg", frage="serie")

    assert vorlage is None, "trotz Luecke in der Nummerierung entstand ein Kontaktbogen"


def test_motiv_kontaktbogen_uebersteht_ein_unlesbares_mitglied(tmp_path):
    """Untergrenze + Regression: fuer die bestehende Motiv-Frage bleibt das
    grosszuegige Verhalten unveraendert -- dort referenziert keine Antwort
    eine Bildnummer, die Luecke ist unschaedlich."""
    gut = [_bild(tmp_path, f"m{i}.jpg") for i in range(2)]
    kaputt = tmp_path / "kaputt-motiv.jpg"
    kaputt.write_bytes(b"kein bild")
    gruppe = [gut[0], kaputt, gut[1]]

    vorlage = motivlauf._bildvorlage(gruppe[0], gruppe, tmp_path / "ziel-motiv.jpg")

    assert vorlage is not None, "die Motiv-Frage darf bei einer Luecke weiterhin einen Bogen bauen"


def test_serie_keine_markiert_den_vertreter_nicht_als_beurteilt(tmp_path):
    """Regel-A-Sonderfall: `serie == "keine"` vererbt nicht, auch wenn das
    Modell sicher ist (Design § 4). Wuerde der Vertreter trotzdem als
    beurteilt gemerkt, faende `aus_baum` bei seinem spaeteren EIGENEN
    Motiv-Urteil eine Marke aus der Serien-Frage vor -- und er bekaeme NIE ein
    echtes Einzel-Urteil (Design § 4, Motiv-Pfad der Nicht-Erbenden)."""
    mitglieder = [_bild(tmp_path, f"n{i}.jpg") for i in range(3)]

    def transport(url, koerper, kopf, zeitgrenze):
        return _serien_antwort("keine", [1, 2, 3], sicher=True, motive=("Weg",))

    motivlauf.fahre(
        [(mitglieder[0], mitglieder, "serie")], _wahl(), transport=transport, schluessel="x"
    )

    zustand = motivlauf.aus_baum(mitglieder)
    assert mitglieder[0] not in zustand.urteile, (
        "der Vertreter gilt nach 'keine' faelschlich als beurteilt -- er bekaeme nie "
        "ein eigenes Motiv-Urteil"
    )


def test_serie_panorama_markiert_den_vertreter_als_beurteilt(tmp_path):
    """Untergrenze zum Test daneben: ohne diese Gegenprobe waere ein `_merke`,
    das NIE aufgerufen wird, genauso gruen (LP-36)."""
    mitglieder = [_bild(tmp_path, f"p{i}.jpg") for i in range(3)]

    def transport(url, koerper, kopf, zeitgrenze):
        return _serien_antwort("panorama", [1, 2, 3], sicher=True, motive=("Kirche",))

    motivlauf.fahre(
        [(mitglieder[0], mitglieder, "serie")], _wahl(), transport=transport, schluessel="x"
    )

    zustand = motivlauf.aus_baum(mitglieder)
    assert mitglieder[0] in zustand.urteile, (
        "ein sicheres 'panorama'-Urteil wurde nicht gemerkt -- ein Abbruch danach "
        "wuerde den bezahlten Aufruf verlieren"
    )


def test_serie_unsicher_markiert_den_vertreter_ebenfalls_nicht(tmp_path):
    mitglieder = [_bild(tmp_path, f"u{i}.jpg") for i in range(2)]

    def transport(url, koerper, kopf, zeitgrenze):
        return _serien_antwort("panorama", [1, 2], sicher=False, motive=("Berg",))

    motivlauf.fahre(
        [(mitglieder[0], mitglieder, "serie")], _wahl(), transport=transport, schluessel="x"
    )

    assert mitglieder[0] not in motivlauf.aus_baum(mitglieder).urteile, (
        "ein unsicheres Serienurteil wurde trotzdem gemerkt"
    )


def test_serien_frage_wird_bei_wiederaufnahme_nicht_wiederholt(tmp_path):
    mitglieder = [_bild(tmp_path, f"w{i}.jpg") for i in range(3)]
    aufrufe = []

    def transport(url, koerper, kopf, zeitgrenze):
        aufrufe.append(url)
        return _serien_antwort("panorama", [1, 2, 3])

    eintrag = [(mitglieder[0], mitglieder, "serie")]
    erstes = motivlauf.fahre(eintrag, _wahl(), transport=transport, schluessel="x")
    motivlauf.fahre(eintrag, _wahl(), transport=transport, schluessel="x", vorhandene=erstes)

    assert len(aufrufe) == 1, (
        f"der zweite Lauf hat die Serien-Frage erneut gestellt ({len(aufrufe)} Aufrufe)"
    )


def test_ein_fremdes_stichwort_im_sidecar_gilt_nicht_als_urteil(tmp_path) -> None:
    """**Derselbe Fehler wie beim JPEG — im Zweig, der den RAW-Bestand traegt.**

    Der Teilstring-Test wurde im eingebetteten Zweig repariert, im Sidecar-Zweig
    nicht: dort las `aus_baum` weiter den XML-Text der ganzen Datei und suchte
    `Motiv|` als Vorkommen. Ein fremdes Stichwort aus Capture One wie
    `Themen|Motiv|Ideen` traf das ebenso.

    Die Verhaeltnisse machen den Unterschied bitter: das JPEG-Loch betraf 65
    Aufnahmen, dieses hier **1.227 von 1.293**. Und der Sidecar-Weg war sogar
    schwaecher als der alte eingebettete — er traf `Motiv|` an JEDER Stelle der
    Datei, auch in einer Beschreibung oder einem Kommentar.

    Gefunden vom Critic, nachdem die Cross-Modell-Review die JPEG-Haelfte
    gefunden hatte. Zweimal dieselbe Bewegung: eine Regel an einer Stelle
    repariert, die zweite stehengelassen.
    """
    import subprocess as sp

    roh = tmp_path / "r.RAF"
    roh.write_bytes(b"roh")
    sp.run(
        [
            "exiftool",
            "-q",
            "-o",
            str(tmp_path / "r.xmp"),
            "-XMP-lr:HierarchicalSubject+=Themen|Motiv|Ideen",
            str(roh),
        ],
        capture_output=True,
        check=False,
    )
    assert (tmp_path / "r.xmp").exists(), "Vorbedingung nicht hergestellt: kein Sidecar"

    zustand = motivlauf.aus_baum([roh])

    assert roh not in zustand.urteile, (
        "ein fremdes Stichwort im Sidecar gilt als Urteil -- dieses RAW bekaeme nie eines"
    )


def test_ein_beurteiltes_raw_wird_weiterhin_erkannt(tmp_path) -> None:
    """Die Untergrenze zur vorigen Zusicherung.

    Ohne sie koennte `aus_baum` im Sidecar-Zweig gar nichts mehr erkennen und
    saehe trotzdem korrekt aus -- der Test darueber waere gruen, und JEDES
    bezahlte RAW-Urteil wuerde bei der naechsten Wiederaufnahme erneut gekauft.
    """
    import subprocess as sp

    roh = tmp_path / "s.RAF"
    roh.write_bytes(b"roh")
    sp.run(
        [
            "exiftool",
            "-q",
            "-o",
            str(tmp_path / "s.xmp"),
            "-XMP-lr:HierarchicalSubject+=Motiv|Wald",
            str(roh),
        ],
        capture_output=True,
        check=False,
    )

    assert roh in motivlauf.aus_baum([roh]).urteile, (
        "ein echtes Urteil im Sidecar wird nicht mehr erkannt"
    )


def _doppelt(bild: Path) -> int:
    """Wie oft `Motiv|Bruecke` am Traeger dieses Bildes steht."""
    import subprocess as sp

    from mkn_foto import anreichern

    ziel, _ = anreichern.traeger(bild)
    return sp.run(
        ["exiftool", "-s3", "-XMP-lr:HierarchicalSubject", str(ziel)],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.count("Motiv|Bruecke")


def test_ein_doppelt_genanntes_motiv_wird_auch_beim_merken_nur_einmal_geschrieben(
    tmp_path,
) -> None:
    """**Die zweite Haelfte derselben Regel — und hier heilt sie nicht von selbst.**

    `anreichern._argumente` laesst seit heute Nacht keine wiederholte Zuweisung
    mehr hinaus. `_merke` baut seine Argumente aber selbst und lief nicht durch
    dieselbe Behandlung: nennt das Modell ein Motiv zweimal, schreibt die
    Abbruchsicherung es zweimal.

    **Und es bleibt.** Im durchlaufenden Lauf raeumt `anreichern` es spaeter mit
    (`-=` trifft alle Vorkommen). Im WIEDERAUFNAHME-Lauf nicht -- also genau in
    dem Fall, fuer den `_merke` ueberhaupt existiert: `aus_baum` liefert
    `Urteil(sicher=True, fehler="aus dem Baum")` OHNE Motive, `anreichern`
    schreibt fuer diese Aufnahme also nie ein `Motiv|Bruecke`, und das `-=`
    laeuft auf dem Wert nie. Die Dublette steht dauerhaft im Baum, den KT-1
    ansieht. Der Modul-Docstring sagt "Ein Abbruch ist der Normalfall" -- damit
    ist das nicht der Ausnahme-, sondern der Regelfall.

    Gefunden vom Critic, in der Nachpruefung der Behebung seines eigenen
    Befunds.
    """
    from PIL import Image

    bild = tmp_path / "b.jpg"
    Image.new("RGB", (400, 300), (60, 90, 120)).save(bild)

    motivlauf._merke(bild, bildurteil.Urteil(sicher=True, motive=("Bruecke", "Bruecke")))

    assert _doppelt(bild) == 1, f"'Motiv|Bruecke' steht {_doppelt(bild)}x im JPEG"


def test_der_raw_zweig_des_merkens_verdoppelt_ebenfalls_nicht(tmp_path) -> None:
    """Dieselbe Zusicherung fuer den Zweig, der den RAW-Bestand traegt.

    **Und zugleich die erste Testabdeckung dieses Zweigs ueberhaupt.** Bis heute
    ergab `grep -c "RAF\\|NEF"` ueber dieser Datei **0**: ungeprueft war damit
    der `-o`-Pfad, der die Abbruchsicherung von 1.227 der 1.293 Aufnahmen
    traegt. Dass er funktioniert, stand nur im Protokoll eines Pruefers, nicht
    in der Suite.
    """
    roh = tmp_path / "r.RAF"
    roh.write_bytes(b"roh")

    motivlauf._merke(roh, bildurteil.Urteil(sicher=True, motive=("Bruecke", "Bruecke")))

    assert (tmp_path / "r.xmp").exists(), "der Sidecar wurde gar nicht angelegt"
    assert _doppelt(roh) == 1, f"'Motiv|Bruecke' steht {_doppelt(roh)}x im Sidecar"


def test_die_dublette_ueberlebt_die_wiederaufnahme_nicht(tmp_path) -> None:
    """Der Weg, auf dem die Dublette dauerhaft wuerde -- als eigene Zusicherung.

    Sie ist die eigentliche: die beiden Tests darueber pruefen den Schreibakt,
    dieser prueft, dass der Schaden auch nach einem zweiten Lauf nicht dasteht.
    Ohne ihn koennte man den Dedupe an einer Stelle einbauen und uebersehen,
    dass die Wiederaufnahme ihn gar nicht erreicht.
    """
    from PIL import Image

    bild = tmp_path / "w.jpg"
    Image.new("RGB", (400, 300), (60, 90, 120)).save(bild)

    def transport(url, koerper, kopf, zeitgrenze=120.0):
        return 200, json.dumps(
            {"content": [{"text": '{"sicher": true, "motive": ["Bruecke", "Bruecke"]}'}]}
        ).encode()

    wahl = modelle.Wahl(anbieter="anthropic", modell="x")
    motivlauf.fahre([(bild, None)], wahl, schluessel="k", transport=transport)

    # Zweiter Lauf: das Urteil kommt aus dem Baum und traegt KEINE Motive mehr.
    zweiter = motivlauf.fahre(
        [(bild, None)],
        wahl,
        schluessel="k",
        transport=transport,
        vorhandene=motivlauf.aus_baum([bild]),
    )
    assert zweiter.aufrufe == 0, "die Wiederaufnahme hat erneut gefragt"
    assert _doppelt(bild) == 1, f"nach der Wiederaufnahme steht es {_doppelt(bild)}x da"
