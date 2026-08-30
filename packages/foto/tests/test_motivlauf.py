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
