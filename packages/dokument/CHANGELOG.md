# Changelog

## 0.2.0 (2026-11-16)

### Features

* **dokument:** Befehl `mkn-dokument seiten` (`mkn_dokument.seitenlesung`) — je Seite Kopf (Seitenart, Aussteller,
  Datum, Inhaltsart), Fließtexte wörtlich und Verzeichnis der Diagramme, von zwei Lesern abgeglichen; das Fach setzt
  die Wörter ein. Ergebnis `seiten.json`.
* **dokument:** Befehl `mkn-dokument ablesen` (`mkn_dokument.ablesen`) — markierte Stellen eines Diagramms nach einem
  Ableseauftrag (Reihen, Achsen-Kennwort, Toleranz, wahlweise Anzahl); Achse je Leser aus den Teilstrichen, vier
  Stimmen je Wert, Median mit Spanne. Ergebnis `ablesung.json` mit `herkunft: "abgelesen"`.

### Intern

* `lesen` teilt seine Bausteine (`schreibe`, `gemerkt`, `bereite_vor`) mit den neuen Funktionen.

## 0.1.0 (2026-11-15)

### Features

* **dokument:** Befehl `mkn-dokument lesen` — jede Seite (PDF, Scan, Foto) wird von zwei Lesern verschiedener Anbieter
  vom Bild gelesen; ein Abgleich über Wert und Lage übernimmt nur Übereinstimmung, alles andere steht mit Grund auf der
  Klärliste. Mitschrift je Seite und Leser, Ergebnis als JSON.
