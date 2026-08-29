"""Schneidet den Bilderstrom in Foto-Sessions — die Einheit der Ortsbestimmung.

Eine Session ist zusammenhaengende fotografische Arbeit an einem Ort. Der
Rhythmus dahinter: zum Spot kommen (auch fahrend), ankommen und ueberlegen,
fotografieren und sich dabei bewegen, wahrnehmen und zurueckgehen. Zwischen
zwei Aufnahmen koennen dabei zwoelf Minuten liegen, ohne dass jemand den Ort
gewechselt haette.

Die Schwelle ist GEMESSEN, nicht gewaehlt. An 1286 Abstaenden einer
Fotowoche:

    50. Perzentil      6 s
    90. Perzentil    2,3 min
    95. Perzentil    3,8 min
    97. Perzentil    7,3 min
    99. Perzentil     56 min

Der Sprung zwischen dem 97. und dem 99. Perzentil ist die Trennlinie: fast
alles Zusammenhaengende liegt unter vier Minuten, und was deutlich darueber
hinausgeht, ist meist ein Ortswechsel. Bei 15 Minuten ergeben sich 31
Sessions in sieben Tagen — vier bis fuenf am Tag.

Anwender sind `ort` und die Pipeline.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from mkn_foto.modell import Aufnahme, Spot

PAUSE_S = 900.0
"""Ab wann eine Pause als Ortswechsel gilt. Oeffentlich, weil ein anderer
Arbeitsstil eine andere Schwelle braucht — wer ruhiger arbeitet, macht
laengere Pausen am selben Fleck."""


def schneide(aufnahmen: Sequence[Aufnahme], *, pause_s: float = PAUSE_S) -> list[Spot]:
    """Zerlegt die Aufnahmen in Sessions, getrennt an Pausen ueber `pause_s`.

    Getrennt wird NUR an der Zeit — nicht an der Kamera. Ein Spot ist ein Ort
    und eine Zeitspanne; in den meisten Sessions waren beide Gehaeuse im
    Einsatz, und eine Trennung nach Kamera zerlegte sie alle.

    Die Grenze ist offen: genau `pause_s` gehoert noch zur selben Session.
    """
    if not aufnahmen:
        return []

    geordnet = sorted(aufnahmen, key=lambda a: (a.zeitpunkt, a.stamm))
    gruppen: list[list[Aufnahme]] = [[geordnet[0]]]
    for vorher, aktuell in pairwise(geordnet):
        if (aktuell.zeitpunkt - vorher.zeitpunkt).total_seconds() > pause_s:
            gruppen.append([])
        gruppen[-1].append(aktuell)

    return [Spot(aufnahmen=tuple(g)) for g in gruppen]
