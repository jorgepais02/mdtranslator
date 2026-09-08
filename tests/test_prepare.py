"""Fase 0 del pipeline: leer, formatear y parsear las fuentes en paralelo."""

import threading
import time

import pytest

from cli import pipeline
from cli.pipeline import SourceDoc, _prepare_docs


@pytest.fixture
def fuentes(tmp_path):
    rutas = []
    for i in range(4):
        p = tmp_path / f"doc{i}.md"
        p.write_text(f"# Tema {i}\n\nLa seguridad informática protege los sistemas "
                     f"de información frente a accesos no autorizados.\n", encoding="utf-8")
        rutas.append(p)
    return rutas


def test_el_orden_de_salida_es_el_de_entrada(fuentes, monkeypatch):
    # ex.map devuelve en orden, pero terminan desordenadas: el documento más lento
    # es el primero de la lista.
    original = pipeline.load_markdown
    retardos = {"doc0.md": 0.15, "doc1.md": 0.01, "doc2.md": 0.01, "doc3.md": 0.01}

    def lento(path, allow_format=True):
        time.sleep(retardos.get(path.name, 0))
        return original(path, allow_format=allow_format)

    monkeypatch.setattr(pipeline, "load_markdown", lento)
    docs, fallos = _prepare_docs(fuentes, format_raw=False, max_workers=4)

    assert fallos == []
    assert [d.path.name for d in docs] == [p.name for p in fuentes]


def test_se_preparan_en_paralelo(fuentes, monkeypatch):
    original = pipeline.load_markdown

    def lento(path, allow_format=True):
        time.sleep(0.15)
        return original(path, allow_format=allow_format)

    monkeypatch.setattr(pipeline, "load_markdown", lento)

    t = time.monotonic()
    _prepare_docs(fuentes, format_raw=False, max_workers=4)
    assert time.monotonic() - t < 0.15 * 4 * 0.6


def test_un_fichero_ilegible_no_arrastra_a_los_demas(fuentes, tmp_path):
    roto = tmp_path / "vacio.md"
    roto.write_text("   \n", encoding="utf-8")

    docs, fallos = _prepare_docs([*fuentes, roto], format_raw=False, max_workers=4)

    assert len(docs) == 4
    assert len(fallos) == 1
    assert fallos[0]["source"] == "vacio.md"
    assert fallos[0]["ok"] is False


def test_todos_los_resultados_son_documentos_o_fallos(fuentes, tmp_path):
    roto = tmp_path / "vacio.md"
    roto.write_text("", encoding="utf-8")
    docs, fallos = _prepare_docs([*fuentes, roto], format_raw=False, max_workers=4)
    assert all(isinstance(d, SourceDoc) for d in docs)
    assert len(docs) + len(fallos) == 5


def test_el_formateo_con_gemini_respeta_el_presupuesto(fuentes, monkeypatch):
    # El formateo y el refinamiento van contra la misma cuota: si el semáforo no los
    # limita, --all sobre varias transcripciones dispara un 429.
    vivos, maximo, lock = 0, 0, threading.Lock()

    def formatea(path, allow_format=True):
        nonlocal vivos, maximo
        with lock:
            vivos += 1
            maximo = max(maximo, vivos)
        time.sleep(0.05)
        with lock:
            vivos -= 1
        return "# T\n\nLa seguridad informática protege los sistemas de información.\n", None

    monkeypatch.setattr(pipeline, "needs_formatting", lambda p: True)
    monkeypatch.setattr(pipeline, "load_markdown", formatea)

    _prepare_docs(fuentes, format_raw=True, max_workers=4,
                  gemini_sem=threading.Semaphore(1))
    assert maximo == 1


def test_el_presupuesto_de_gemini_es_configurable(fuentes, monkeypatch):
    vivos, maximo, lock = 0, 0, threading.Lock()

    def formatea(path, allow_format=True):
        nonlocal vivos, maximo
        with lock:
            vivos += 1
            maximo = max(maximo, vivos)
        time.sleep(0.05)
        with lock:
            vivos -= 1
        return "# T\n\nLa seguridad informática protege los sistemas de información.\n", None

    monkeypatch.setattr(pipeline, "needs_formatting", lambda p: True)
    monkeypatch.setattr(pipeline, "load_markdown", formatea)

    _prepare_docs(fuentes, format_raw=True, max_workers=4,
                  gemini_sem=threading.Semaphore(2))
    assert maximo == 2


def test_source_lang_forzado_salta_la_deteccion(fuentes, monkeypatch):
    def no_llamar(_textos):  # pragma: no cover
        raise AssertionError("no debería detectarse nada")

    monkeypatch.setattr(pipeline, "detect_source_language", no_llamar)
    docs, _ = _prepare_docs(fuentes, format_raw=False, forced_lang="ES", max_workers=4)
    assert {d.src_lang for d in docs} == {"es"}


def test_sin_ficheros_no_revienta():
    assert _prepare_docs([], format_raw=False, max_workers=4) == ([], [])
