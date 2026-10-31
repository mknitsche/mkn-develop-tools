# mkn-audio

Werkzeuge der Domaene **Audio**: Dokumente hoerbar machen. Das erste Werkzeug ist die
**MP4-Konvertierung** (Befehle `mkn-mp4-local` und `mkn-mp4-gemini`); weitere Werkzeuge derselben Domaene teilen sich die
Bausteine des Pakets (Lesen, Hoertext, Gliedern, Sprechen, Pruefen, Mastern, Verpacken).

## MP4-Konvertierung

Verwandelt eine Quelle (EPUB, PDF, Text, Foto oder Screenshot) ohne Durchsicht in eine
Hoerdatei mit Kapiteln, gesprochen in einer waehlbaren Stimme: eine `.m4b` je Quelle mit
Kapitelmarken, Titel, Autor und Cover (Apple Books, BookPlayer), oder auf Wunsch eine MP3
je Kapitel. Neben der Datei liegt ein Bericht, der sagt, was nicht gelesen, weggelassen
oder nicht sauber gesprochen wurde.

Das Paket kennt keinen Anbieter und kein Sprachmodell: das Modell, das den Hoertext glaettet
und Bilder liest, kommt aus der Umgebung.

## Installation

Das Paket (Python 3.12 oder neuer) braucht nur leichte Abhaengigkeiten:

```sh
uv pip install -e .            # aus dem Quellordner; legt `mkn-mp4-local` und `mkn-mp4-gemini` an
```

Die Stimm-Software ist schwer und verlangt eine eigene **Python-3.11-Umgebung**, den
*Arbeiter*. Das Paket startet ihn als Kindprozess und spricht ueber JSON-Zeilen mit ihm:

```sh
uv venv --python 3.11 ~/mkn-mp4/arbeiter
uv pip install --python ~/mkn-mp4/arbeiter/bin/python \
    chatterbox-tts==0.1.7 faster-whisper librosa soundfile "setuptools<81"
```

`setuptools<81` ist kein Versehen: das Wasserzeichen-Modul von Chatterbox braucht
`pkg_resources`, das ab setuptools 81 fehlt. Fehlt es, scheitert schon die Startprobe des
Arbeiters (`'NoneType' object is not callable`).

Ausserdem muessen im `PATH` stehen:

| Programm | wofuer |
|---|---|
| `ffmpeg`, `ffprobe` | Tempo, Pausen, Lautheit, M4B und MP3 |
| `rubberband` | Tonhoehe (nur Stimmen mit `tonhoehe_ht`) |
| `tesseract` mit Sprachdaten `deu` | Bilder ohne Sprachmodell, gescannte PDFs ueber 20 Seiten |
| `heif-convert` (Linux: Paket `libheif-examples`) | HEIC-Fotos; auf macOS genuegt `sips`, das ffmpeg eines Linux-Servers liest iPhone-HEIC nicht |

## Konfiguration

`~/.config/mkn-mp4/konfig.toml` (oder der Pfad aus `MKN_MP4_KONFIG`):

```toml
stimmen_tabelle = "~/mkn-mp4/stimmen.toml"
# optional:
arbeiter_python = "~/mkn-mp4/arbeiter/bin/python"   # Pflicht fuer local; bei gemini nur fuer die
                                                    # Abschrift-Stichprobe (Whisper)
arbeitsort = "~/.cache/mkn-mp4"     # Zwischenergebnisse, Vorgabe wie hier
whisper_modell = "small"            # fuer die Rueckpruefung
```

Relative Pfade gelten relativ zur Konfigurationsdatei. Fehlt die Datei, bricht der Aufruf
mit dem Ort ab, an dem er gesucht hat.

## Stimmen

Eine Stimme ist ein Buendel, das zusammen gehoert und zusammen gemessen wurde: bei Chatterbox
(`local`) Vorlage, Regler, Tempo und Klang, bei Gemini (`gemini`) der Name einer Google-Stimme.
Sie steht als eine Zeile in einer Tabelle (`stimmen.toml`); `beispiel/stimmen.toml` zeigt das
Format. Eigene Stimmen und ihre Vorlagen gehoeren in eine eigene Tabelle ausserhalb dieses Pakets.

### Stimmen-Tabelle Schema 2

Eine Zeile ist die Stimme EINES Wegs in einer Sprache. `[wege.<weg>]` nennt das Modell des Wegs,
`[standard.<weg>.<sprache>]` bindet die Rollen: `text` (Fliesstext) und `ansage` (Titel,
Zwischenueberschriften, Vorspann, Ueberleitungen, Abspann); beide muessen Zeilen desselben Wegs
und derselben Sprache sein, derselbe Name fuer beide ist erlaubt.

```toml
schema = 2

[wege.local]                       # optional; Vorgabe chatterbox-multilingual
modell = "chatterbox-multilingual"

[wege.gemini]                      # Pflicht, sobald eine Gemini-Zeile existiert
modell = "gemini-2.5-pro-preview-tts"
parallel = 3                       # gleichzeitige Anfragen (Vorgabe)
block_zeichen = 1100               # Blockgroesse (Vorgabe)
zeitgrenze_s = 300                 # je Anfrage (Vorgabe)

[standard.local.de]
text = "deutsch-maennlich"
ansage = "deutsch-maennlich"

[standard.gemini.de]
text = "deutsch-gemini-charon"
ansage = "deutsch-gemini-sulafat"       # Kore (`deutsch-gemini-kore`) bleibt waehlbar

[stimmen.deutsch-maennlich]        # Chatterbox-Zeile; `weg` entfaellt (Vorgabe local)
beschreibung = "..."
vorlage = "vorlagen/vorlage.wav"   # ca. 24 s Sprache, mono, 24 kHz; relativ zur Tabelle
version = 1                        # neue Fassung: version + 1
sprache = "de"
exaggeration = 0.45
cfg_weight = 0.45
temperature = 0.75
tempo = 0.90
klang = ["highpass=f=80"]          # ffmpeg-Filter, nur wenn die Stimme sie braucht
stand = "standard"                 # standard | freigegeben | probe

[stimmen.deutsch-gemini-charon]
weg = "gemini"
stimme = "Charon"                  # Name bei Google
stil = ""                          # optional; geht als Stilvorgabe mit, nie in den Text
beschreibung = "..."
sprache = "de"
stand = "probe"
```

Der Name folgt `<sprache>-<art>[-<merkmal>]` in Kleinbuchstaben ohne Umlaute. Pflicht an jeder
Zeile sind `beschreibung`, `sprache` und `stand`; dazu nur bei `local` `vorlage`, `exaggeration`,
`cfg_weight`, `temperature` (und `pausen_kuerzen`), nur bei `gemini` `stimme` (und `stil`). Ein
Feld des anderen Wegs, ein `modell` an der Zeile (es gehoert dem Weg) und die alte
`ansage_stimme` (die Rolle bindet `[standard]`) brechen mit Ort und Feldnamen. Weitere Felder
fuer beide Wege, alle mit Vorgabe: `tempo`, `tempo_angleich`, `tonhoehe_ht`, `klang`, `version`
und die Pausen `pause_stueck`, `pause_absatz`, `pause_titel`, `pause_kapitel`,
`pause_vor_ueberschrift`, `pause_nach_ueberschrift` -- bei `local` 0,25 / 0,6 / 1,5 / 2,0 / 1,0 /
0,7 s und Angleich 0,10, bei `gemini` 0,35 / 0,35 / 0,7 / 1,8 / 1,0 / 0,7 s und Angleich 0.
Fehlt die Sprache des Dokuments unter `[standard.<weg>]`, spricht `[standard.<weg>.de]` -- mit
Warnung im Bericht.

Eine Tabelle ohne `schema` (Schema 1: `standard = "name"`, `modell` und `ansage_stimme` an der
Zeile) wird weiter gelesen und auf `local` abgebildet; der Bericht meldet den alten Aufbau. Sie
entfaellt mit Fassung 0.4.0.

`mkn-mp4-local stimmen` (ebenso `mkn-mp4-gemini stimmen`) zeigt die Tabelle; der Bericht nennt Stimme, Fassung und den Stand der
Tabelle, mit der das Hoerstueck entstand.

Eine Vorlage schneidet `mkn-mp4-local vorlage <aufnahme> --ziel <wav>` aus einer laengeren Aufnahme:
das Fenster mit der lebendigsten Betonung, normiert.

## Bedienung

Zwei Befehle, ein Kern: `mkn-mp4-local` spricht mit Chatterbox auf dem eigenen Rechner,
`mkn-mp4-gemini` mit Googles Gemini-TTS ueber das Netz (naechster Abschnitt). Die Optionen
sind dieselben; `mkn-mp4` allein gibt es nicht mehr.

```sh
mkn-mp4-local buch.epub                            # Standard-Stimme, Ergebnis neben der Quelle
mkn-mp4-local artikel.jpg --stimme deutsch-weiblich --ziel ~/Hoerstuecke
mkn-mp4-local buch.epub --stimme a --ansage b      # Fliesstext in a, Titel und Ueberschriften in b
mkn-mp4-local buch.epub --auswahl 1-3              # nur Kapitel 1 bis 3 (Zaehlung ab 1)
mkn-mp4-local buch.epub --format mp3               # eine MP3 je Kapitel
mkn-mp4-local artikel.pdf --regie aus              # alles vorlesen, keine Regie
mkn-mp4-local stimmen                              # die Tabelle, Standards des Wegs mit *
mkn-mp4-gemini buch.epub --cloud-ok                # siehe unten
```

Ergebnis: `JJJJ-MM-TT <Titel>_v01.m4b` und `JJJJ-MM-TT <Titel> Bericht_v01.md`. Gibt es den
Namen schon, wird `_v02` angelegt; nichts wird ueberschrieben. MP3-Dateien heissen
`JJJJ-MM-TT <Titel> – NN <Kapiteltitel>_v01.mp3`. Der Titel steht in NFC-Schreibung, auch wenn
die Quelle (etwa vom NAS) in NFD benannt ist.

stdout traegt nur die entstandenen Dateien, Fortschritt und Hinweise gehen nach stderr.
Exit-Code 0 gut, 1 Fehler (unbrauchbare Quelle, defekte Umgebung), 2 Bedienfehler, 3 Rueckfrage
noetig (nur gemini, siehe Datenschutz).

### Der Weg gemini

`mkn-mp4-gemini <quelle>` spricht ueber die Interactions API von Google (Modell aus
`[wege.gemini].modell` der Tabelle, fuer einen Lauf mit `--modell ID` ueberschreibbar). Die
Stimmen sind Zeilen der Tabelle mit `weg = "gemini"` und dem Google-Namen in `stimme`.

- **Schluessel:** `GEMINI_API_KEY`, oder `MKN_LLM_SCHLUESSEL_DATEI` zeigt auf eine JSON-Datei mit
  `gemini` oder `api_key`. Das gilt unabhaengig vom Sprachmodell (`MKN_LLM_ANBIETER`). Fehlt er,
  bricht der Aufruf vor der Arbeit mit Exit 1 ab und nennt die Variable.
- **Datenschutz:** der Text geht an Google. Vor der ersten Anfrage prueft das Paket den Lesetext
  nach der Regie auf Kontaktdaten (E-Mail, Telefon, IBAN), Kennziffern mit Vorwort (Steuernummer,
  Aktenzeichen ...), Lebensdaten (nur in kurzen Dokumenten, nicht in Buechern), Briefform und die
  Dokumentart (Brief, Rechnung, Befund ...). Namen werden nicht erkannt: die Erkennung ist eine
  Untergrenze. Gibt es Hinweise, stehen sie maskiert auf stderr; am Terminal fragt der Befehl
  "Trotzdem an Google senden? [j/N]", sonst bricht er mit Exit 3 ab, bevor etwas gesendet wird.
  `--cloud-ok` gibt vorab frei (fuer Skripte). Der Bericht nennt die Hinweise.
- **Fehler:** eine Sperre durch Google wird einmal wiederholt, dann an Satzgrenzen in 2 und 4
  Teile geteilt (immer dasselbe Modell); bleibt auch ein Einzelsatz gesperrt, bricht der Lauf
  laut mit Kapitel, Block und den ersten Woertern ab. Ein erschoepftes Limit (429) heisst
  warten (15, 45, 120, 240, 300 s), ohne neue Anfragen; nach drei 429 laufen nur noch halb so
  viele Anfragen gleichzeitig. Eine Fehlerantwort wird bis zu viermal wiederholt, dann steht an
  der Stelle Stille und ein Befund im Bericht. Ein Block, dessen Sprechrate ausserhalb 0,75 bis
  1,3 des Medians seiner Stimme liegt, wird einmal neu gesprochen und bricht den Lauf ab, wenn
  er wieder ausserhalb liegt.
- **Kosten:** vor dem Sprechen steht eine Schaetzung auf stderr, nach dem Lauf im Bericht Modell,
  Token (Text/Audio) und USD. Die Preise stehen in `[wege.gemini]` der Tabelle
  (`preis_usd_je_1m_text_token`, `preis_usd_je_1m_audio_token`, `preisstand`); ohne sie steht
  "Preise nicht konfiguriert", nie eine erfundene Zahl. Meldet Google keine Token, steht "Token
  nicht gemeldet". Die Kommandozeile bucht nichts.
- **Abschrift-Stichprobe:** nur mit `arbeiter_python` (Whisper); ohne ihn steht im Bericht
  "Abschrift: nicht geprueft (kein Arbeiter)". Eine Stilvorgabe der Zeile (`stil`) geht als
  Metadatum mit, nie als Text; steht ein Inhaltswort der Vorgabe (ohne Stoppwoerter, wortgenau)
  in der Abschrift eines gehoerten Blocks, den der Text selbst nicht enthaelt, steht
  "Stilvorgabe mitgesprochen" als Befund im Bericht (kein Neusprechen). Ohne Arbeiter steht
  "Stilvorgabe: ungeprueft (kein Arbeiter)".

### Sprachmodell (optional)

Mit `MKN_LLM_ANBIETER` (`anthropic`, `gemini`, `moonshot`, `ollama`) und `MKN_LLM_MODELL`
plus dem Schluessel des Anbieters (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MOONSHOT_API_KEY`,
oder `MKN_LLM_SCHLUESSEL_DATEI`) glaettet es den Hoertext und liest Fotos, Screenshots und
kurze gescannte PDFs. Ohne sie wird nur nach Regeln aufbereitet und Bilder liest tesseract;
das steht im Bericht. Eine unvollstaendige Angabe bricht vor der Arbeit ab. Das Modell darf
nichts hinzufuegen oder weglassen: weicht seine Fassung eines Absatzes zu stark vom
regelbasierten Text ab (Woerter fehlen oder kommen hinzu, eine Zahl aendert sich), wird
dieser Absatz mit dem Regeltext gesprochen und im Bericht genannt.

### Regie

Mit Sprachmodell erkennt die Regie, was ein Zuhoerer nicht hoeren will (Bildunterschriften,
Seitenzahlen, Kaufknoepfe, Bewertungen ...), und sagt eine kurze Kopfseite an: was das ist,
woher, worum es geht, wie lang und wie gegliedert. Jede Angabe der Kopfseite, der
Ueberleitungen und des Abspanns muss in der Quelle belegt sein, sonst entfaellt sie und der
Bericht nennt es. `--regie` waehlt, wie weit sie eingreift:

- `voll`: nur Haupttext und Ueberschriften werden gesprochen (Vorgabe, ausser bei einem EPUB).
- `buch`: nur Bildunterschriften, Seitenzahlen, Fussnoten und Bedienelemente entfallen, alles
  andere bleibt Wortlaut; keine Ueberleitungen (Vorgabe bei einem EPUB).
- `aus`: keine Regie, die Quelle wird unveraendert gelesen.

### Bereichs-Manifest

Jeder Lauf legt neben seinen Zwischenergebnissen eine `manifest.json` ab: das Gelesene, nach
Rollen geordnet, damit andere Werkzeuge dieselbe Quelle erschliessen koennen. Aufbau:

- `quelle`: `pfad` (nur der Dateiname), `sha256`, `dokumentart`, `titel`, `autor`, `datum`,
  `sprache`, `seiten_gesamt`. Was das Paket nicht weiss, ist leer oder `null`, nie geraten.
- `abschnitte`: je Kapitel `nr`, `titel`, `seite_von`, `seite_bis` und `bereiche`.
- `bereiche`: je Absatz `nr`, `reihenfolge` (Lesereihenfolge im ganzen Dokument), `art`, `titel`,
  `seite`, `text` (Zeichen fuer Zeichen wie gelesen), `handschrift`, `herkunft`, `lage`, `leser`.
- `art`: `fliesstext`, `ueberschrift`, `kopf`, `uebersicht`, `bildunterschrift`,
  `zitatkasten`, `bedienelement`, `fussnote`, `wert_tabelle`, `seitenzahl`. Das Manifest zeigt
  ALLES mit seiner Art; was gesprochen wird, entscheidet der Abnehmer.
- `herkunft`: `textschicht`, `ocr` oder `bildmodell`, je nachdem, wie der Text entstand.
- `text_bilanz`: `woerter_gesamt`, `woerter_zugeordnet` und `rest` (je Eintrag `grund`, `woerter`:
  Text, den der Leser schon vor der Rollenvergabe entfernt hat). Ein nicht leerer `rest` heisst: die
  Erschliessung ist nicht vollstaendig, und das soll sichtbar sein.

### Aussprache

Eine Datei `aussprache.json` neben der Quelle ersetzt Woerter vor dem Sprechen:
`{"Xylophon": "Ksuelofon"}`.

### Fortsetzen

Jeder Lauf legt seine Zwischenergebnisse im Arbeitsort ab (ein Ordner je Quelle, benannt
nach dem Inhalt der Datei). Bricht er ab, setzt derselbe Aufruf fort und spricht nur, was
noch fehlt. Wechselt die Stimme, wird nur ab dem Sprechen neu gerechnet, nicht der Text.
Aufnahmen werden nicht von selbst geloescht: der Ordner einer fertigen Quelle kann von Hand
weg.

## Umstieg von 0.2

- **Befehl:** `mkn-mp4` entfaellt ohne Alias. Was bisher `mkn-mp4 <quelle>` hiess, ist
  `mkn-mp4-local <quelle>` (gleiche Optionen, gleiches Ergebnis); `mkn-mp4-gemini` ist neu.
  Nach dem Update `uv pip install -e .` neu ausfuehren, sonst bleibt der alte Befehl stehen,
  der auf nichts mehr zeigt. Skripte und Shell-Verlaeufe auf den neuen Namen umstellen.
- **Konfiguration:** unveraendert (`~/.config/mkn-mp4/konfig.toml`, `MKN_MP4_KONFIG`, Arbeitsort).
  Bereits gesprochene Stuecke bleiben gueltig: der Schluessel der lokalen Aufnahmen aendert sich nicht.
- **Stimmen-Tabelle:** eine Tabelle im alten Aufbau (Schema 1) wird weiter gelesen und auf
  `local` abgebildet; der Bericht meldet den alten Aufbau. Sie entfaellt mit Fassung 0.4.0.
  Umstellen: `schema = 2` setzen, `modell` und `ansage_stimme` von den Zeilen nach
  `[wege.local]` und `[standard.local.<sprache>]` verschieben (Abschnitt "Stimmen-Tabelle
  Schema 2"), Gemini-Zeilen mit `weg = "gemini"` ergaenzen.
- **Neu fuer Titel:** Kapiteltitel und Zwischenueberschriften spricht jetzt die Ansage-Stimme
  (`[standard.<weg>.<sprache>].ansage`), nicht mehr die Text-Stimme.

## Grenzen

- **Sprache:** Regeln und Pruefung des Hoertexts gelten fuer Deutsch. Eine Quelle in anderer
  Sprache wird mit der Stimme gesprochen, aber nicht aufbereitet, und der Bericht warnt.
- **Beiwerk:** Impressum, Inhaltsverzeichnis, Anmerkungen und Fussnoten eines EPUB, Kopf- und
  Fusszeilen, Seitenzahlen und Webadressen werden nicht vorgelesen; der Bericht zaehlt sie.
- **Quellenangaben, Literatur, Quellvermerke:** nicht vorgelesen werden Quellenangaben in
  Klammern nach der Zitat-Syntax (`(Mustermann 2004)`, `(vgl. Muster und Beispiel 2001, S. 12 f.)`:
  Name, Jahr, optional Seite; mehrere Angaben mit `;` oder `,` getrennt, `et al` mit oder ohne
  Punkt, Vorwort wie `vgl.` oder `Übersicht in:`, `???` fuer ein unbekanntes Jahr nur neben
  einer echten Jahreszahl). Ein Name ist ein Wort mit grossem Anfangsbuchstaben -- kein Monat
  und keines der Woerter `Stand`, `Sommer`, `Auflage`, `Version` und aehnlicher (`(Stand 2020)`
  bleibt Text) -- oder ein Kuerzel einer festen Liste herausgebender Organisationen (`WHO`,
  `OECD`, `UNICEF`, `UNESCO`, `UN`, `UNO`, `IPCC`, `IARC`, `CDC`, `NIH`, `RKI`, `BZgA`, `DGE`).
  Zitate mit einem anderen Kuerzel (`(DDR 1989)`) werden gesprochen, ebenso eine Jahreszahl allein
  und eine Voll-Literaturangabe mit Titel und Zeitschrift in Klammern -- auch die Regie mit
  Sprachmodell entfernt sie nicht, denn sie uebernimmt den Fliesstext woertlich. Umgekehrt gilt
  ein Wort mit grossem Anfangsbuchstaben vor einer Jahreszahl immer als Name: `(Berlin 1989)` und
  `(Gründung 1949, Neugründung 1990)` werden weggelassen und im Bericht gezaehlt.
  Weiter nicht vorgelesen: ein Abschnitt ab einer Ueberschrift, die GANZ `Literatur`, `Quellen`,
  `Zum Weiterlesen` o. ae. heisst (bis zur naechsten Ueberschrift; EPUB und reiner Text
  kennen keine Zwischenueberschriften, dort reicht er bis zum Kapitelende), und ein Quellvermerk
  `Aus: ... Seiten 25-34` am Kapitelende. Der Bericht zaehlt jede Regel.
- **Fussnoten-Verweise und Initialen:** hochgestellte Ziffern eines EPUB gelten als Verweis und
  fallen weg, ausser nach einer Ziffer oder Laengeneinheit (`10⁶`, `m²`) -- Formeln wie `a²`
  verlieren so ihre Hochzahl. Ein einzelner Grossbuchstabe mit Punkt (`C. G. Jung`) beendet nie
  einen Satz; "Vitamin C. Danach" bleibt darum ein Stueck.
- **Gliederung eines PDF:** Lesezeichen gliedern. Ohne Lesezeichen wird in einem zweispaltigen
  PDF ein Block oben auf der Seite, der beide Spalten ueberspannt, zum Kapiteltitel; ein breiter
  Absatz am Seitenanfang gilt dort ebenfalls als Titel. Zwischenueberschriften erkennt nur eine
  Zeile ganz in Versalien am Blockanfang (Schriftgroesse und Fettdruck zaehlen nicht); sie wird
  in Satzschreibung gesetzt, gemischt geschriebene Titel bleiben unveraendert.
- **Tabellen und Bildlayout:** nur so gut, wie das Bildmodell sie liest; ohne Modell liest
  tesseract Zeilen und kennt keine Spalten.
- **Gescannte Buecher:** ueber 20 Seiten liest nur tesseract; die Gliederung ist dann grob.
- **Stimme:** die Synthese ist zufaellig. Ein misslungenes Stueck wird einmal neu gesprochen;
  bleibt es auffaellig, steht es mit Zeitstempel im Bericht. Die Zeitstempel sind aus den
  Stueckdauern auf die fertige Laenge umgerechnet, also auf wenige Sekunden genau.
- **Rechenzeit:** die Stimm-Software laeuft auf der CPU deutlich langsamer als in Echtzeit;
  ein Buch dauert Stunden bis Tage.
- **Pruefung:** Whisper hoert nur bei akustischem Verdacht und bei 5 % Stichprobe zu, nicht
  jedes Stueck. Kann der Weg nicht hoeren (kein Arbeiter), steht "Abschrift: nicht geprueft
  (kein Arbeiter)" im Bericht und jeder verdaechtige Block als Befund. Nach dem Verpacken liest
  der Lauf die Kapitelmarken aus der fertigen M4B (ffprobe) und prueft, dass jede in einer Pause
  liegt; eine Marke daneben steht als Hinweis im Bericht. Ein Format ohne Kapitel (MP3) oder eine
  M4B, deren Marken nicht gelesen werden koennen, steht als "Kapitelmarken: ungeprueft" da.

## Tests

```sh
uv run --extra dev pytest -q
uv run --extra dev ruff check . && uv run --extra dev ruff format --check .
```

Kein Test braucht Netz, Schluessel, Chatterbox oder ein Sprachmodell; ffmpeg und ffprobe
muessen installiert sein.

## Lizenz

AGPL-3.0-or-later.
