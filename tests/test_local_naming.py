"""Nombres de salida local y consistencia con la configuración."""

import json
from pathlib import Path

import pytest

from cli import pipeline


@pytest.fixture
def patron(monkeypatch):
    def _set(valor):
        cfg = dict(pipeline.CONFIG)
        cfg["local"] = {"naming_pattern": valor} if valor else {}
        monkeypatch.setattr(pipeline, "CONFIG", cfg)
    return _set


def test_patron_por_defecto(patron):
    patron(None)
    assert pipeline._local_stem("apuntes", "en") == "apuntes.en"


def test_patron_personalizado(patron):
    patron("{lang}_{title}")
    assert pipeline._local_stem("apuntes", "fr") == "fr_apuntes"


def test_el_idioma_distingue_las_salidas(patron):
    patron(None)
    stems = {pipeline._local_stem("apuntes", l) for l in ("en", "fr", "ar", "zh")}
    assert len(stems) == 4


def test_dos_documentos_distintos_no_colisionan(patron):
    patron(None)
    assert pipeline._local_stem("tema1", "en") != pipeline._local_stem("tema2", "en")


def test_el_config_de_ejemplo_es_json_valido_y_completo():
    ejemplo = json.loads((Path(__file__).resolve().parent.parent / "config.example.json")
                         .read_text(encoding="utf-8"))
    assert set(ejemplo) >= {"drive", "local", "pipeline", "document"}
    assert "{n}" in ejemplo["drive"]["sequential_naming_pattern"]
    assert ejemplo["pipeline"]["max_workers"] >= 1


def test_el_config_de_ejemplo_conserva_su_indentacion():
    # Reformatearlo con json.dumps (4 espacios) ya ha pasado dos veces.
    texto = (Path(__file__).resolve().parent.parent / "config.example.json").read_text()
    assert '\n  "drive"' in texto


def test_en_y_en_gb_son_salidas_distintas(patron):
    # Colapsar la variante regional hacía que las dos tareas escribieran el mismo
    # fichero a la vez, y el DOCX resultante era el de quien terminara el último.
    patron(None)
    assert pipeline._local_stem("apuntes", "en") != pipeline._local_stem("apuntes", "en-gb")
