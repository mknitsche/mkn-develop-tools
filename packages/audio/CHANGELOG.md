# Changelog

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
