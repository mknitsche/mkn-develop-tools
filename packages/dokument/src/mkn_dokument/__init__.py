"""mkn-dokument: Dokumente lesen, ohne einem einzelnen Modell zu glauben.

Jede Seite wird als Bild von zwei Lesern unabhaengig gelesen. Ein Programm ohne
Modell gleicht beide Lesungen ab und uebernimmt nur, worin sie uebereinstimmen;
alles andere steht mit Grund auf der Klaerliste.

Drei Funktionen nach diesem Muster: ``lesen`` (gedruckte Angaben mit Wert),
``seitenlesung`` (Seitenkopf, Fliesstexte, Diagramm-Verzeichnis) und ``ablesen``
(markierte Stellen eines Diagramms nach einem Ableseauftrag).

Dazu ohne Modell: ``epub`` (Text, Metadaten, ISBN und Kapitel eines EPUB, verlinkte Anmerkungen an ihrer
Fundstelle; Kopierschutz wird abgewiesen).
"""

__version__ = "0.4.0"  # x-release-please-version
