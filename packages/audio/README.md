# mkn-audio

Werkzeuge der Domaene **Audio**: Dokumente hoerbar machen. Das erste Werkzeug ist die
**MP4-Konvertierung** (Befehl `mkn-mp4`); weitere Werkzeuge derselben Domaene teilen sich die
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
uv pip install -e .            # aus dem Quellordner; legt den Befehl `mkn-mp4` an
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
arbeiter_python = "~/mkn-mp4/arbeiter/bin/python"
# optional:
arbeitsort = "~/.cache/mkn-mp4"     # Zwischenergebnisse, Vorgabe wie hier
whisper_modell = "small"            # fuer die Rueckpruefung
```

Relative Pfade gelten relativ zur Konfigurationsdatei. Fehlt die Datei, bricht der Aufruf
mit dem Ort ab, an dem er gesucht hat.

## Stimmen

Eine Stimme ist ein Buendel aus Vorlage, Reglern, Tempo und Klang, das zusammen gehoert und
zusammen gemessen wurde. Sie steht als eine Zeile in einer Tabelle (`stimmen.toml`);
`beispiel/stimmen.toml` zeigt das Format. Eigene Stimmen und ihre Vorlagen gehoeren in eine
eigene Tabelle ausserhalb dieses Pakets.

```toml
standard = "deutsch-maennlich"

[stimmen.deutsch-maennlich]
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
```

Der Name folgt `<sprache>-<art>[-<merkmal>]` in Kleinbuchstaben ohne Umlaute. Weitere Felder
(alle mit Vorgabe): `pause_stueck` 0,25 s, `pause_absatz` 0,6 s, `pause_titel` 1,5 s,
`pause_kapitel` 2,0 s, `pausen_kuerzen`, `tempo_angleich` 0,10, `tonhoehe_ht` 0 und
`ansage_stimme`: der Name einer anderen Stimme der Tabelle (oder der eigenen), die Vorspann,
Ueberleitungen und Abspann der Regie spricht; ohne Eintrag spricht die Hauptstimme.
`mkn-mp4 stimmen` zeigt die Tabelle; der Bericht nennt Stimme, Fassung und den Stand der
Tabelle, mit der das Hoerstueck entstand.

Eine Vorlage schneidet `mkn-mp4 vorlage <aufnahme> --ziel <wav>` aus einer laengeren Aufnahme:
das Fenster mit der lebendigsten Betonung, normiert.

## Bedienung

```sh
mkn-mp4 buch.epub                                  # Standard-Stimme, Ergebnis neben der Quelle
mkn-mp4 artikel.jpg --stimme deutsch-weiblich --ziel ~/Hoerstuecke
mkn-mp4 buch.epub --auswahl 1-3                    # nur Kapitel 1 bis 3 (Zaehlung ab 1)
mkn-mp4 buch.epub --format mp3                     # eine MP3 je Kapitel
mkn-mp4 artikel.pdf --regie aus                    # alles vorlesen, keine Regie
mkn-mp4 stimmen
```

Ergebnis: `JJJJ-MM-TT <Titel>_v01.m4b` und `JJJJ-MM-TT <Titel> Bericht_v01.md`. Gibt es den
Namen schon, wird `_v02` angelegt; nichts wird ueberschrieben. MP3-Dateien heissen
`JJJJ-MM-TT <Titel> – NN <Kapiteltitel>_v01.mp3`. Der Titel steht in NFC-Schreibung, auch wenn
die Quelle (etwa vom NAS) in NFD benannt ist.

stdout traegt nur die entstandenen Dateien, Fortschritt und Hinweise gehen nach stderr.
Exit-Code 0 gut, 1 Fehler (unbrauchbare Quelle, defekte Umgebung), 2 Bedienfehler.

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

## Grenzen

- **Sprache:** Regeln und Pruefung des Hoertexts gelten fuer Deutsch. Eine Quelle in anderer
  Sprache wird mit der Stimme gesprochen, aber nicht aufbereitet, und der Bericht warnt.
- **Beiwerk:** Impressum, Inhaltsverzeichnis, Anmerkungen und Fussnoten eines EPUB, Kopf- und
  Fusszeilen, Seitenzahlen und Webadressen werden nicht vorgelesen; der Bericht zaehlt sie.
- **Fussnoten-Verweise und Initialen:** hochgestellte Ziffern eines EPUB gelten als Verweis und
  fallen weg, ausser nach einer Ziffer oder Laengeneinheit (`10⁶`, `m²`) -- Formeln wie `a²`
  verlieren so ihre Hochzahl. Ein einzelner Grossbuchstabe mit Punkt (`C. G. Jung`) beendet nie
  einen Satz; "Vitamin C. Danach" bleibt darum ein Stueck.
- **Tabellen und Bildlayout:** nur so gut, wie das Bildmodell sie liest; ohne Modell liest
  tesseract Zeilen und kennt keine Spalten.
- **Gescannte Buecher:** ueber 20 Seiten liest nur tesseract; die Gliederung ist dann grob.
- **Stimme:** die Synthese ist zufaellig. Ein misslungenes Stueck wird einmal neu gesprochen;
  bleibt es auffaellig, steht es mit Zeitstempel im Bericht. Die Zeitstempel sind aus den
  Stueckdauern auf die fertige Laenge umgerechnet, also auf wenige Sekunden genau.
- **Rechenzeit:** die Stimm-Software laeuft auf der CPU deutlich langsamer als in Echtzeit;
  ein Buch dauert Stunden bis Tage.
- **Pruefung:** Whisper hoert nur bei akustischem Verdacht und bei 5 % Stichprobe zu, nicht
  jedes Stueck.

## Tests

```sh
uv run --extra dev pytest -q
uv run --extra dev ruff check . && uv run --extra dev ruff format --check .
```

Kein Test braucht Netz, Schluessel, Chatterbox oder ein Sprachmodell; ffmpeg und ffprobe
muessen installiert sein.

## Lizenz

AGPL-3.0-or-later.
