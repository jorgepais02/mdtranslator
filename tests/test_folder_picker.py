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


# ── navegar: la raiz tiene alias y tiene id ───────────────────────────────────

class _DriveFalso:
    """Lo justo de GoogleDocsManager para navegar: Mi unidad con una subcarpeta."""

    RAIZ = "id-real-de-mi-unidad"

    def __init__(self):
        self.arbol = {
            folder_picker.ROOT: [{"id": "id-usal", "name": "USAL"}],
            self.RAIZ:          [{"id": "id-usal", "name": "USAL"}],
            "id-usal":          [],
        }
        self.info = {
            folder_picker.ROOT: {"id": self.RAIZ, "name": "My Drive", "parents": []},
            self.RAIZ:          {"id": self.RAIZ, "name": "My Drive", "parents": []},
            "id-usal":          {"id": "id-usal", "name": "USAL", "parents": [self.RAIZ]},
        }

    def list_subfolders(self, fid):
        return self.arbol[fid]

    def get_folder_info(self, fid):
        return self.info[fid]


def test_al_volver_a_la_raiz_no_se_ofrece_subir_mas(monkeypatch):
    # El padre de una carpeta de primer nivel es "Mi unidad" con su id real, no el
    # alias "root": al subir, la raíz dejaba de parecer la raíz y "Up one level"
    # seguía en la lista sin nada a donde subir.
    listas = []
    guion = iter(["USAL/", folder_picker._UP, folder_picker._CANCEL])

    def ask_select_falso(label, choices, **kw):
        listas.append([str(c) for c in choices])
        return next(guion)

    monkeypatch.setattr(folder_picker, "ask_select", ask_select_falso)
    monkeypatch.setattr(folder_picker, "_pintar", lambda *a, **k: None)

    assert folder_picker.pick_drive_folder(manager=_DriveFalso()) is None
    assert folder_picker._UP not in listas[0]
    assert folder_picker._UP in listas[1]
    assert folder_picker._UP not in listas[2]


def test_el_selector_no_apila_una_cabecera_por_nivel(monkeypatch):
    # Cada nivel dejaba su cabecera y su filete en pantalla: bajar tres carpetas eran
    # tres preguntas iguales apiladas y la lista viva quedaba al final de la columna.
    pintadas = []
    guion = iter(["USAL/", folder_picker._CANCEL])
    monkeypatch.setattr(folder_picker, "ask_select", lambda *a, **k: next(guion))
    monkeypatch.setattr(folder_picker, "clear_screen", lambda: pintadas.append("limpia"))
    monkeypatch.setattr(folder_picker.console, "print", lambda *a, **k: None)

    folder_picker.pick_drive_folder(manager=_DriveFalso())

    assert pintadas.count("limpia") == 2      # una pantalla por nivel, no dos encima
