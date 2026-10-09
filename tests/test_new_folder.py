"""--new-folder: la carpeta del módulo nuevo sin contestar preguntas en pantalla."""

import pytest

from cli import main as m


@pytest.fixture
def guardada(monkeypatch):
    monkeypatch.setattr(m, "configured_folder", lambda: ("ID-M20", "M20"))


def _crea(monkeypatch, resultado=("ID-M21", "M21")):
    llamadas = []
    monkeypatch.setattr(m, "create_folder_next_to",
                        lambda nombre, hermana, manager=None: llamadas.append((nombre, hermana)) or resultado)
    return llamadas


def test_sin_nombre_propone_el_siguiente_de_la_serie(guardada, monkeypatch):
    llamadas = _crea(monkeypatch)
    config = {"output": "Google Drive"}
    m._apply_new_folder(config, "")
    assert llamadas == [("M21", "ID-M20")]
    assert (config["drive_folder_id"], config["drive_folder_name"]) == ("ID-M21", "M21")


def test_con_nombre_usa_ese(guardada, monkeypatch):
    llamadas = _crea(monkeypatch, ("ID-X", "Curso B"))
    config = {"output": "Local + Google Drive"}
    m._apply_new_folder(config, "Curso B")
    assert llamadas == [("Curso B", "ID-M20")]


def test_solo_local_no_crea_nada(guardada, monkeypatch):
    llamadas = _crea(monkeypatch)
    with pytest.raises(SystemExit) as e:
        m._apply_new_folder({"output": "Local only"}, "")
    assert e.value.code == 2 and llamadas == []


def test_sin_carpeta_guardada_no_hay_hermana_donde_crear(monkeypatch):
    monkeypatch.setattr(m, "configured_folder", lambda: ("", ""))
    llamadas = _crea(monkeypatch)
    with pytest.raises(SystemExit):
        m._apply_new_folder({"output": "Google Drive"}, "")
    assert llamadas == []


def test_un_nombre_sin_numero_pide_que_se_diga(monkeypatch):
    monkeypatch.setattr(m, "configured_folder", lambda: ("ID", "Apuntes"))
    llamadas = _crea(monkeypatch)
    with pytest.raises(SystemExit):
        m._apply_new_folder({"output": "Google Drive"}, "")
    assert llamadas == []


def test_si_drive_falla_no_se_sigue_ni_se_toca_la_config(guardada, monkeypatch):
    _crea(monkeypatch, None)
    config = {"output": "Google Drive"}
    with pytest.raises(SystemExit) as e:
        m._apply_new_folder(config, "")
    assert e.value.code == 2 and "drive_folder_id" not in config
