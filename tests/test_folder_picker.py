"""Selector de carpeta de Drive: extracción del ID y guardado en config.json."""

import json

import pytest

from cli import folder_picker
from cli.folder_picker import extract_folder_id, save_folder_id

ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"


@pytest.mark.parametrize("entrada", [
    f"https://drive.google.com/drive/folders/{ID}",
    f"https://drive.google.com/drive/folders/{ID}?usp=sharing",
    f"https://drive.google.com/drive/u/0/folders/{ID}",
    f"https://drive.google.com/open?id={ID}",
    ID,
    f"  {ID}  ",
])
def test_reconoce_las_formas_habituales(entrada):
    assert extract_folder_id(entrada) == ID


@pytest.mark.parametrize("basura", ["", "   ", None, "no es una url", "https://google.com"])
def test_rechaza_lo_que_no_es_una_carpeta(basura):
    assert extract_folder_id(basura) is None


def test_guardar_conserva_el_resto_de_la_configuracion(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "drive": {"folder_id": "viejo", "sequential_naming": True},
        "document": {"default_languages": ["EN", "FR"]},
    }), encoding="utf-8")
    monkeypatch.setattr(folder_picker, "PROJECT_ROOT", tmp_path)

    save_folder_id(ID)
    guardado = json.loads(cfg.read_text(encoding="utf-8"))

    assert guardado["drive"]["folder_id"] == ID
    assert guardado["drive"]["sequential_naming"] is True
    assert guardado["document"]["default_languages"] == ["EN", "FR"]


def test_sin_config_json_se_parte_del_ejemplo(tmp_path, monkeypatch):
    (tmp_path / "config.example.json").write_text(
        json.dumps({"drive": {"folder_id": ""}, "pipeline": {"max_workers": 4}}), encoding="utf-8")
    monkeypatch.setattr(folder_picker, "PROJECT_ROOT", tmp_path)

    save_folder_id(ID)
    guardado = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))

    assert guardado["drive"]["folder_id"] == ID
    assert guardado["pipeline"]["max_workers"] == 4


def test_guardar_sobre_un_config_sin_seccion_drive(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text(json.dumps({"document": {}}), encoding="utf-8")
    monkeypatch.setattr(folder_picker, "PROJECT_ROOT", tmp_path)

    save_folder_id(ID)
    guardado = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert guardado["drive"]["folder_id"] == ID
