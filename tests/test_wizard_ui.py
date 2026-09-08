"""Wizard y selector de carpetas: lo que se le pasa a questionary y lo que queda en pantalla."""

import io

import pytest
from rich.console import Console

from cli import folder_picker, wizard
from cli.styles import elide

LARGO = "transcripcion-clase-magistral-seguridad-informatica-2026-tema-4.md"


@pytest.fixture
def a_ancho(monkeypatch):
    def _set(ancho, modulo=wizard):
        c = Console(file=io.StringIO(), width=ancho, force_terminal=False, no_color=True)
        monkeypatch.setattr(modulo, "console", c)
        return c
    return _set


# ── opciones que se le pasan a questionary ────────────────────────────────────

def test_los_nombres_cortos_van_tal_cual(a_ancho):
    a_ancho(80)
    assert wizard._opciones(["apuntes.md", "tema02.txt"]) == ["apuntes.md", "tema02.txt"]


def test_los_nombres_largos_se_recortan(a_ancho):
    a_ancho(40)
    opcion = wizard._opciones([LARGO])[0]
    assert opcion.title.endswith("…")
    assert len(opcion.title) <= 40 - 6


def test_el_valor_de_la_opcion_es_el_nombre_real(a_ancho):
    # Si se recortara el valor, collect_sources no encontraría el fichero.
    a_ancho(40)
    assert wizard._opciones([LARGO])[0].value == LARGO


def test_lo_que_cabe_no_se_recorta_aunque_sea_largo(a_ancho):
    a_ancho(120)
    assert wizard._opciones([LARGO]) == [LARGO]


# ── ecos que quedan en pantalla ───────────────────────────────────────────────

@pytest.mark.parametrize("ancho", [40, 60, 80, 120])
def test_el_eco_del_select_cabe(a_ancho, ancho):
    c = a_ancho(ancho)
    wizard._print_select("Select source file", ["Process ALL files", LARGO], LARGO)
    assert all(len(l.rstrip()) <= ancho for l in c.file.getvalue().splitlines())


@pytest.mark.parametrize("ancho", [40, 60, 80, 120])
def test_el_eco_del_texto_cabe(a_ancho, ancho):
    c = a_ancho(ancho)
    wizard._print_text("Target languages", "", "EN FR DE IT PT RU JA KO ZH AR FA HE UR PL")
    assert all(len(l.rstrip()) <= ancho for l in c.file.getvalue().splitlines())


def test_la_flecha_sigue_pegada_a_su_valor(a_ancho):
    # Al envolverse, la segunda línea empezaba en la columna 0 y el ❯ no señalaba nada.
    c = a_ancho(40)
    wizard._print_select("Select source file", [LARGO], LARGO)
    lineas = [l for l in c.file.getvalue().splitlines() if l.strip()]
    marcada = next(l for l in lineas if "❯" in l)
    assert marcada.strip().startswith("❯ transcripcion")
    assert not any(l.startswith("transcripcion") for l in lineas)


# ── selector de carpetas ──────────────────────────────────────────────────────

def test_extraer_el_id_sigue_funcionando_con_nombres_largos():
    assert folder_picker.extract_folder_id("1AbCdEfGhIjKlMnOpQrStUvWxYz012345") is not None


def test_elide_es_el_mismo_helper_en_todas_las_vistas():
    from cli import pipeline
    assert pipeline._elide is elide


@pytest.mark.parametrize("ancho,cabe", [(40, 32), (80, 72), (120, 112)])
def test_el_recorte_respeta_el_ancho(ancho, cabe):
    assert len(elide("x" * 200, cabe)) == cabe
