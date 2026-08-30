import pytest


@pytest.fixture(autouse=True)
def _keine_fremde_konfiguration(tmp_path_factory, monkeypatch):
    """Kein Test liest die Konfiguration des Menschen, der ihn laufen laesst.

    **Firsthand gefunden, 2026-08-30.** Kaum las die Pipeline `konfig.lade()`,
    schlug `test_ohne_modell_laeuft_der_rest_weiter` fehl -- nicht wegen des
    Codes, sondern weil auf DIESEM Rechner eine `~/.config/mkn-foto/konfig.json`
    mit einem Modell liegt. Ohne diesen Riegel bewiese die Suite auf meiner
    Maschine etwas anderes als auf einer fremden, und beides saehe gruen aus.

    Die Bedingung wird HERGESTELLT, nicht vorausgesetzt: die Variable zeigt auf
    einen Pfad, der garantiert nicht existiert.
    """
    monkeypatch.setenv(
        "MKN_FOTO_KONFIG", str(tmp_path_factory.mktemp("ohne-konfig") / "gibtsnicht.json")
    )
