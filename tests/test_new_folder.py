"""--new-folder: la carpeta del módulo nuevo sin contestar preguntas en pantalla."""

import pytest

from cli import main as m


@pytest.fixture
def guardada(monkeypatch):
    monkeypatch.setattr(m, "configured_folder", lambda: ("ID-M20", "M20"))
    monkeypatch.setattr(m, "configured_lote", lambda: "modulo-20")
    monkeypatch.setattr(m, "_lote_de_config", lambda c: c.get("lote", "modulo-21"))


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
    monkeypatch.setattr(m, "configured_lote", lambda: "")
    monkeypatch.setattr(m, "_lote_de_config", lambda c: "")
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


def test_relanzar_el_mismo_modulo_reutiliza_la_carpeta_en_vez_de_crear_la_siguiente(guardada, monkeypatch):
    llamadas = _crea(monkeypatch)
    config = {"output": "Google Drive", "lote": "modulo-20"}
    m._apply_new_folder(config, "")
    assert llamadas == []
    assert (config["drive_folder_id"], config["drive_folder_name"]) == ("ID-M20", "M20")


def test_con_nombre_explicito_crea_aunque_sea_el_mismo_lote(guardada, monkeypatch):
    llamadas = _crea(monkeypatch, ("ID-X", "Otra"))
    m._apply_new_folder({"output": "Google Drive", "lote": "modulo-20"}, "Otra")
    assert llamadas == [("Otra", "ID-M20")]


def test_el_lote_se_guarda_y_se_borra_al_cambiar_de_carpeta(tmp_path, monkeypatch):
    from cli import folder_picker as fp
    monkeypatch.setattr(fp, "PROJECT_ROOT", tmp_path)
    fp.save_folder_id("ID-M21", "M21", "modulo-21")
    assert fp.configured_lote() == "modulo-21"
    fp.save_folder_id("ID-M21", "M21")            # misma carpeta: el lote se conserva
    assert fp.configured_lote() == "modulo-21"
    fp.save_folder_id("ID-OTRA", "Otra")          # --set-folder a otra: ya no es de ese lote
    assert fp.configured_lote() == ""


def test_el_lote_sale_de_la_carpeta_de_sources(tmp_path, monkeypatch):
    from core import sources
    (tmp_path / "modulo-21").mkdir()
    dentro = tmp_path / "modulo-21" / "a.md"
    suelto = tmp_path / "b.md"
    monkeypatch.setattr(m, "lote_de", lambda p: sources.lote_de(p, tmp_path))
    monkeypatch.setattr(m, "collect_sources", lambda s: [dentro])
    assert m._lote_de_config({"source": "x"}) == "modulo-21"
    monkeypatch.setattr(m, "collect_sources", lambda s: [dentro, suelto])
    assert m._lote_de_config({"source": "x"}) == ""
