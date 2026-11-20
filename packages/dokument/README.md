# mkn-dokument

Liest Dokumente — PDF mit oder ohne Textschicht, Scan, Foto — und übernimmt nur, was zwei unabhängige Leser gleich
gelesen haben. Drei Funktionen nach demselben Muster:

| Befehl | liest | Ergebnis |
|---|---|---|
| `lesen` | gedruckte Angaben mit Wert (Tabellen, Kopfangaben, beschriftete Zahlen) | `ergebnis.json` |
| `seiten` | je Seite Kopf (Seitenart, Aussteller, Datum, Inhaltsart), Fließtexte, Verzeichnis der Diagramme | `seiten.json` |
| `ablesen` | markierte Stellen eines Diagramms ohne gedruckte Zahlen, nach einem Ableseauftrag | `ablesung.json` |

## Wozu

Ein einzelnes Modell liest eine Seite fast immer richtig. „Fast“ reicht nicht, wenn die Werte in eine Datenbank gehen
und niemand jede Zahl nachprüft. `mkn-dokument` lässt deshalb jede Seite von **zwei Modellen verschiedener Anbieter**
unabhängig vom Bild lesen. Ein Programm ohne Modell gleicht die beiden Lesungen ab:

- gleicher Wert unter demselben Namen: **übernommen**,
- nur ein Leser hat die Angabe, beide lesen an derselben Stelle Verschiedenes, oder sie nennen zum gleichen Wert
  verschiedene Größen: **Klärliste**, mit Grund.

Verglichen werden die Zeichen des Werts und sein Ort, nie abgeschriebener Text. Wie ein Modell Klammern, Einheiten oder
Bereiche formatiert, spielt keine Rolle.

## `lesen`: was es liest — und was nicht

Es liest **gedruckte Angaben mit einem Wert**: Tabellenzeilen, Kopfangaben, beschriftete Zahlen an Balken und in
Diagrammen, Verlaufs- und Zielwerte. Je Angabe: Abschnitt, Bezeichnung, Zusatz, Art, Wert, Vergleichszeichen, Einheit,
Bereich, Kennzeichen und die Lage auf der Seite.

Es liest **keinen Fließtext** (das tut `seiten`) und liest **keine Werte an Kurven oder Achsen ab**, die nicht als Zahl
dastehen (das tut `ablesen`, und nur auf Auftrag).

## Benutzen

```bash
export ANTHROPIC_API_KEY=…  GEMINI_API_KEY=…
mkn-dokument lesen befund.pdf --aus arbeit/befund \
    --leser-a gemini:<modell> --leser-b anthropic:<modell> \
    --dokumentart "eines medizinischen Belegs"
```

Die zwei Leser wählt der Anwender (`anbieter:modell`, auch über `MKN_DOKUMENT_LESER_A` / `MKN_DOKUMENT_LESER_B`). Es
gibt keine Vorgabe, und zwei Leser desselben Anbieters weist der Befehl ab: Modelle derselben Herkunft irren gemeinsam.

Im Arbeitsordner entstehen `seiten/` (Seitenbilder), `mitschrift/` (jede Modellantwort, je Seite und Leser) und
`ergebnis.json`. Alles ist nur für den Besitzer lesbar; der Ordner ist so vertraulich wie das Dokument und gehört nicht
in ein Repository. Ein zweiter Lauf mit gleicher Eingabe liest die Mitschrift und kostet nichts.

Als Bibliothek, mit eigenen Lesern (eigene Anbindung, Abrechnung, Protokoll):

```python
from mkn_dokument import lesen

ergebnis = lesen.lies_dokument(pfad, ordner, leser_a, leser_b, dokumentart="einer Rechnung")
```

Ein Leser ist jedes Objekt mit `kennung` und `lies(auftrag, bild) -> dict` (`mkn_dokument.leser.Leser`).

## Ergebnis

```json
{"seite": 1, "bezeichnung": "…", "wert": "6,25", "einheit": "kg", "bereich": "5,50~7,00",
 "ausgang": "uebernommen", "grund": "zwei_leser", "offen": [], "lage": [118, 190, 127, 222], "leser": {"a": {}, "b": {}}}
```

- `ausgang`: `uebernommen` oder `klaerliste`; `grund`: `zwei_leser`, `nur_leser_a`, `nur_leser_b`, `leser_uneins`,
  `vergleich_uneins`, `name_uneins` (gleicher Wert, aber die Leser nennen verschiedene Größen oder einer hat die Größe mit
  einem anderen Wert gelesen).
- `offen`: Nebenfelder (Einheit, Bereich, Kennzeichen, Art), in denen die Leser uneins sind. Sie sind dann leer; der
  Wert bleibt. Ob ein Wert ohne geklärte Einheit verwendbar ist, entscheidet die Anwendung.
- `unsicher`: einer der Leser hat die Zahl als schwer lesbar markiert.

## Grenzen

- Zwei Leser können dieselbe Zahl auslassen; sie fehlt dann still. Zwei Leser können sich gleich irren; der Wert gilt
  dann als übernommen. Beides ist selten, aber nicht ausgeschlossen — eine Anwendung mit hohem Anspruch prüft die
  übernommenen Werte zusätzlich fachlich (Wertebereich, Verlauf, zweite Quelle).
- Jede Seite wird für sich gelesen. Eine Tabelle, deren Spaltenköpfe nur auf der Vorseite stehen, verliert sie.
- Die Qualität hängt an den gewählten Modellen. Gemessen ist das Verfahren mit je einem aktuellen Bildmodell zweier
  Anbieter; mit anderen Modellen ist neu zu messen.

## `seiten`: Seitenkopf, Texte, Diagramm-Verzeichnis

```bash
mkn-dokument seiten befund.pdf --aus arbeit/befund --leser-a … --leser-b … \
    --dokumentart "eines medizinischen Belegs" --seitenarten "leer,deckblatt,befund,brief,formular,sonstiges" \
    --inhaltsarten "…" --textarten "…" --datum-hinweis "der Tag der Untersuchung, genau wie gedruckt"
```

**Liest** je Seite: Seitenart, Aussteller (wie im Briefkopf, ohne Adresse), das maßgebliche Datum mit seiner gedruckten
Beschriftung, Inhaltsart; jeden zusammenhängenden Fließtext wörtlich mit Überschrift und Art; jedes Diagramm mit Titel,
Typ, Achsen, Reihen und ob seine Werte gedruckt sind. **Liest nicht:** Tabellenwerte, Adressen, Fußzeilen,
Grußformeln — und keine Werte aus den Diagrammen.

Das Fach setzt nur Wörter ein: die Dokumentart, die erlaubten Wörter für Seitenart, Inhaltsart und Textart und einen
Satz, welches Datum gilt. Ohne Angabe gelten allgemeine Vorgaben (Seitenart `leer, deckblatt, inhalt, brief,
formular, sonstiges`; Inhaltsart und Textart frei; Datum: das, auf das sich der Inhalt bezieht).

Abgleich: ein Kopf-Feld gilt nur, wenn beide Leser es gleich lesen — das Datum nur, wenn beide genau einen und
denselben Kalendertag nennen (eindeutige Schreibweisen; `01/02/2020` wird nie gelesen), der Aussteller, wenn er gleich
ist oder einer im anderen steht, die Wörter, wenn sie gleich sind. Sonst steht das Feld in `uneins` und ist leer. Ein
Text von Leser a ist `uebernommen`, wenn jeder seiner Sätze auch bei Leser b auf der Seite steht; alles andere steht
mit seinem Leser auf der Klärliste. Diagramme gelten als dieselben, wenn beide gleich viele nennen und sie der Reihe
nach im Typ und im Titel oder in den Achsen zusammenpassen. `seiten.json` enthält je Seite das Ergebnis und die rohen
Antworten beider Leser.

## `ablesen`: Stellen eines Diagramms gezielt ablesen

```bash
mkn-dokument ablesen befund.pdf --aus arbeit/befund --auftrag kurve.json --leser-a … --leser-b …
```

```json
{"seite": 2, "diagramm": "Kennlinie",
 "reihen": [{"name": "Druck", "achse_y": "druck", "achse_x": "drehzahl", "toleranz": {"y": 3, "x": 10}, "anzahl": 7}]}
```

Der Aufrufer sagt, was er braucht: ein Auftrag ist **ein** Diagramm; je Reihe der Name, die Stellen (ohne Angabe jeder
markierte Messpunkt, mit `marken` benannte Marken), die Achsen als Kennwort, das im gedruckten Achsennamen vorkommt
(`achse_x` darf fehlen), die **Toleranz** je Achse in deren Einheit und wahlweise die erwartete **Anzahl** der Stellen.
Ohne Toleranz nimmt das Programm den Auftrag nicht an. Welche Achse zu einer Reihe gehört, entscheidet allein der
Auftrag: das Kennwort muss genau eine Achse eines Lesers treffen; enthalten es mehrere Achsennamen („Last (N)“ und
„rel. Last (%)“), gilt die eine, deren Name mit dem Kennwort beginnt — sonst ist die Achse unklar. Nennt der Auftrag
`marken`, muss jeder Leser genau diese Marken lesen, sonst steht die Reihe mit `marke_uneins` auf der Klärliste.

**Liest** markierte Punkte, benannte Marken und Balkenenden in Diagrammen mit linearen Zahlenachsen. **Liest nicht:**
ganze Kurven, logarithmische Achsen (sie fallen in der Regel als krumm auf, geraten wird nie), Kreis- und
Ringdiagramme, gewölbte oder perspektivisch verzerrte Fotos. Es erkennt selbst keine Achsen oder Marker in den
Bildpunkten — das tun die zwei Leser.

So entsteht ein Wert: jeder Leser nennt je Achse die beschrifteten Teilstriche mit Zahl und Lage und je Stelle die
Lage des Markers und den selbst abgelesenen Wert. Das Programm legt durch die Teilstriche jedes Lesers eine Gerade
(Richtung aus den Teilstrichen selbst, so dass ein gedrehter oder leicht schräger Scan nichts ausmacht) und rechnet die
Lage des Markers in einen Wert um. Als Zahl gilt nur Eindeutiges: ein Trenner mit genau drei Ziffern dahinter vor
einem Ganzzahlteil ungleich 0 („2.500“, „12,500“) kann ein Tausender- oder ein Dezimaltrenner sein und zählt nicht
(der Teilstrich fehlt, die Stimme fehlt); „0,500“ ist eine Zahl. Eine Achse gilt nur mit mindestens drei verschiedenen Zahlen, wenn alle Teilstriche
auf 1 % genau auf der Geraden liegen, keiner quer daneben liegt und zwei Achsen einer Reihe rechtwinklig stehen
(sonst ist das Bild geschert). Je Wert gibt es so vier Stimmen — gerechnet und abgelesen, je Leser. Übernommen wird ein
Wert, wenn alle vier da sind, die Lagen beider Leser beieinander liegen und die Spanne der Stimmen höchstens die
Toleranz ist. Ergebnis ist der Median, gerundet auf die Stellen der Toleranz, mit seiner Spanne.

**Gemessene Genauigkeit** (Linien-Diagramme mit Markern eines Ausstellers, Wahrheit eine gedruckte Tabelle derselben
Dokumente, Toleranz 3 bzw. 0,3 Einheiten der jeweiligen Achse): in der Entwicklungsgruppe (5 Diagramme, 68 Tabellenpunkte)
wurden 57 Werte übernommen (84 %), keiner über der Toleranz; in einer zurückgehaltenen Gruppe (6 Diagramme, 70
Punkte) 52 (74 %), keiner über der Toleranz, größter Fehler 1,0 bzw. 0,09. Nicht übernommen wurde wegen einer krummen
Achse bei einem Leser, uneiniger Lagen und uneiniger Anzahl: das Werkzeug ist vorsichtig, die angestrebte Übernahme
von 80 % hat die zurückgehaltene Gruppe nicht erreicht. Gemessen ist nur dieser eine Diagrammtyp — Balken, Punkte ohne
Marker, Skalen mit nur einer Achse sind ungemessen.

**Konsistenzprüfung, keine Fehlerschranke.** Beide Leser sehen dasselbe Bild. Was beide gleich falsch sehen — ein
schräg gedrucktes Diagramm, ein von beiden ausgelassener Marker, eine von beiden verlesene Achsenzahl —, bleibt
unentdeckt; auf dem schrägen Scan der Messung wichen alle Wege in dieselbe Richtung ab. Ein gemeinsam ausgelassener
Marker fällt nur über die `anzahl` des Auftrags auf; wer sie kennt (etwa aus einer Tabelle), gibt sie mit.

**Abgelesen ist nie gedruckt.** `ablesung.json` trägt `herkunft: "abgelesen"`; jede Stelle nennt je Achse `wert`,
`spanne` und die vier `stimmen`. Eine Anwendung stellt einen abgelesenen Wert nie über einen gedruckten derselben
Größe und zeigt ihn mit seiner Spanne.

Ausgänge je Stelle: `uebernommen` oder Klärliste mit `lage_uneins`, `achse_unklar`, `wert_fehlt`, `stimmen_uneins`; je
Reihe `anzahl_uneins` (die Leser nennen verschieden viele Stellen), `anzahl_passt_nicht` (nicht die erwartete Anzahl)
oder `marke_uneins`. Ein technischer Fehler (Anbieter, ungültige Antwort, kaputter Auftrag) bricht den Lauf laut ab.
Kosten: je Auftrag zwei Aufrufe mit dem ganzen Seitenbild; mehrere Diagramme einer Seite sind mehrere Aufträge.
