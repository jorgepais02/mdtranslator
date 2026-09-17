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


# ── el nombre del modulo siguiente ────────────────────────────────────────────

@pytest.mark.parametrize("actual, siguiente", [
    ("M18", "M19"),
    ("M9", "M10"),
    ("Modulo 8", "Modulo 9"),
    ("M08", "M09"),                        # el relleno se conserva o deja de ordenar
    ("2026-tema-4", "2026-tema-5"),        # el numero que cuenta es el ultimo
    ("M18 (copia)", "M19 (copia)"),
])
def test_propone_el_siguiente_de_la_serie(actual, siguiente):
    assert folder_picker.next_folder_name(actual) == siguiente


@pytest.mark.parametrize("sin_serie", ["Apuntes", "", None, "   "])
def test_sin_numero_no_propone_nada(sin_serie):
    # No hay serie que continuar: proponer algo seria inventarselo.
    assert folder_picker.next_folder_name(sin_serie) is None


# ── la carpeta guardada, con su nombre ────────────────────────────────────────

def test_guardar_recuerda_el_nombre(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_picker, "PROJECT_ROOT", tmp_path)
    (tmp_path / "config.json").write_text('{"drive": {"folder_id": "viejo"}}', encoding="utf-8")

    folder_picker.save_folder_id("nuevo", "M19")

    assert folder_picker.configured_folder() == ("nuevo", "M19")


def test_guardar_sin_nombre_no_borra_el_que_habia(tmp_path, monkeypatch):
    # El id cambia y el nombre no se sabe: mejor una etiqueta vieja que ninguna.
    monkeypatch.setattr(folder_picker, "PROJECT_ROOT", tmp_path)
    folder_picker.save_folder_id("id1", "M18")

    folder_picker.save_folder_id("id2")

    assert folder_picker.configured_folder() == ("id2", "M18")


def test_sin_config_no_hay_carpeta_guardada(tmp_path, monkeypatch):
    monkeypatch.setattr(folder_picker, "PROJECT_ROOT", tmp_path)
    assert folder_picker.configured_folder() == ("", "")


def test_un_config_roto_no_revienta_la_pregunta(tmp_path, monkeypatch):
    # Se pinta la pregunta sin carpeta que ofrecer, en vez de abortar el wizard.
    monkeypatch.setattr(folder_picker, "PROJECT_ROOT", tmp_path)
    (tmp_path / "config.json").write_text("{esto no es json", encoding="utf-8")
    assert folder_picker.configured_folder() == ("", "")
