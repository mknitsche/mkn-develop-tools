# Changelog

## [0.3.1](https://github.com/mknitsche/mkn-develop-tools/compare/audio-v0.3.0...audio-v0.3.1) (2026-10-31)


### Bug Fixes

* **audio:** M4B und MP3 bleiben nach der Kodierung unter 0 dBTP, Bericht misst den Fliesstext, Trace je Quelle ([#48](https://github.com/mknitsche/mkn-develop-tools/issues/48)) ([af49a5c](https://github.com/mknitsche/mkn-develop-tools/commit/af49a5c4645c1e9901883b4a1f5bb0d25e1c7d3e))

## [0.3.0](https://github.com/mknitsche/mkn-develop-tools/compare/audio-v0.2.0...audio-v0.3.0) (2026-10-31)


### ⚠ BREAKING CHANGES

* **audio:** Befehl mkn-mp4 entfaellt ohne Alias (mkn-mp4-local, mkn-mp4-gemini); Stimmen-Tabelle Schema 2, Schema 1 wird mit Hinweis gelesen und entfaellt mit 0.4.0

### Features

* **audio:** zweiter Vorlese-Weg mkn-mp4-gemini, Befehl mkn-mp4-local, Stimmen-Tabelle Schema 2 ([#46](https://github.com/mknitsche/mkn-develop-tools/issues/46)) ([59f6979](https://github.com/mknitsche/mkn-develop-tools/commit/59f6979680aa10ca85d4b3616b237582a7c0620c))

## [0.2.0](https://github.com/mknitsche/mkn-develop-tools/compare/audio-v0.1.0...audio-v0.2.0) (2026-10-24)


### Features

* **audio:** die gesprochene Einleitung spricht ganze Saetze ([bf4b099](https://github.com/mknitsche/mkn-develop-tools/commit/bf4b0996e655aac39b9d508b4a4619d80bd1c120))


### Bug Fixes

* **audio:** gleicher Inhalt unter neuem Namen bekommt den neuen Titel ([76dc893](https://github.com/mknitsche/mkn-develop-tools/commit/76dc8932757c261997afa0414a40ea70030e75f0))

## 0.1.0 (2026-10-24)

### Features

* Quellen lesen: EPUB (Lesefolge, Beiwerk weggelassen), PDF (Kopf-/Fusszeilen, Seitenzahlen,
  Webadressen entfernt), Text/Markdown, Fotos und Screenshots (Bildmodell oder tesseract).
* Hoertext: Zahlen, Daten, Abkuerzungen nach Regeln, danach optional ein Sprachmodell mit
  Pruefung in beide Richtungen und Rueckfall auf den Regeltext.
* Sprechen ueber einen Arbeiter-Prozess (Chatterbox, eigene Python-3.11-Umgebung), drei
  Versuche bei zu kurzem Ergebnis; Stimmen aus einer Tabelle.
* Pruefen: akustischer Verdacht plus Stichprobe, Rueckpruefung mit Whisper, einmal neu sprechen.
* Mastern (Tempo-Angleich, Pausen, Lautheit -16 LUFS) und Verpacken als M4B mit Kapitelmarken
  oder MP3 je Kapitel; Bericht neben der Datei.
* Lauf mit Arbeitsverzeichnis und Fingerabdruck je Stufe: Fortsetzen nach Abbruch ohne
  Doppelrechnung, Stimmwechsel rechnet nur ab dem Sprechen neu; ein laufendes Buch kann an
  einer Stueckgrenze weichen.
* Kommandozeile `mkn-mp4` (Lauf, `vorlage`, `stimmen`).
* Regie: ein Sprachmodell bestimmt je Absatz die Rolle (Haupttext, Bildunterschrift,
  Kaufknopf ...), weggelassen wird gezaehlt im Bericht, dazu Vorspann, Ueberleitungen und
  Abspann in eigenen Worten; Ansagen duerfen keine fremde Zahl nennen (Ordnungszahlen bis zur
  Kapitelzahl ausgenommen). Optional spricht eine zweite Stimme (`ansage_stimme`) die Ansagen.
  Der Vorspann ist eine gesprochene Kopfseite aus fester Vorlage (Was, Woher, Worum, Umfang
  und Gliederung, Uebergang); das Modell liefert nur geprueftes Feldwerk. Im M4B heisst sie
  Kapitel "Einleitung". Ueberschriften ohne folgenden Text und die doppelte Titelzeile fallen
  weg; Ordnungszahlen, deren Zahl die Quelle nennt, sind in Ansagen erlaubt.
* `lies` entfernt private und unsichtbare Unicode-Zeichen (`Co`, `Cf`) aus allen Texten.
* Hoertext liest auch, was Sachbuecher setzen: Fussnoten-Verweise fallen weg (EPUB), Versalien
  werden zu Woertern, wenn das Dokument sie normal kennt (Kuerzel wie WHO bleiben),
  Ordnungszahlen hinter Artikeln ("im achten Haus"), Ziffern im Wort (CO2, 5G, 1970er, 3fache,
  m2), Bibelstellen, Versionen, Telefonnummern, Herrschernamen hinter einem Titelwort
  ("Papst Pius dem Neunten"), "v. Chr.", Initialen und Auslassungszeichen.
* Fingerabdruck der Textstufen haengt am Code der Stufe: ein Fix wirkt beim naechsten Lauf,
  gesprochene Stuecke mit gleichem Text bleiben erhalten.
* Gemischte Kapitel (Ueberleitung der Ansage-Stimme im Text) werden je Stimme gemastert.
