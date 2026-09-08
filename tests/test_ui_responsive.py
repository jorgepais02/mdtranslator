"""Las vistas se adaptan al ancho del terminal en vez de partirse."""

import io

import pytest
from rich.console import Console
from rich.table import Table

from cli import pipeline
from cli.pipeline import MultiFileView, PipelineView, _bar, _cabecera, _elide

IDIOMAS_4  = ["EN", "FR", "AR", "ZH"]
IDIOMAS_14 = ["EN", "FR", "DE", "IT", "PT", "RU", "JA", "KO",
              "ZH", "AR", "FA", "HE", "UR", "PL"]


@pytest.fixture
def a_ancho(monkeypatch):
    """Renderiza una vista al ancho pedido y devuelve sus líneas."""
    def _render(vista, ancho):
        c = Console(file=io.StringIO(), width=ancho, force_terminal=False, no_color=True)
        monkeypatch.setattr(pipeline, "console", c)
        c.print(vista.render())
        return c.file.getvalue().splitlines()
    return _render


# ── helpers ───────────────────────────────────────────────────────────────────

def test_elide_recorta_y_marca():
    assert _elide("abcdefghij", 5) == "abcd…"


def test_elide_no_toca_lo_que_cabe():
    assert _elide("abc", 10) == "abc"


@pytest.mark.parametrize("ancho", [12, 20, 40])
def test_la_barra_mide_lo_que_se_le_pide(ancho):
    # Estaba fija a 40 caracteres y en un terminal estrecho caía a la línea siguiente.
    texto = _bar(50, ancho, "white").plain
    assert len(texto) == ancho + 1          # +1 por la sangría


def test_la_barra_refleja_el_porcentaje():
    assert _bar(25, 40, "white").plain.count("█") == 10
    assert _bar(0, 40, "white").plain.count("█") == 0
    assert _bar(100, 40, "white").plain.count("░") == 0


def test_la_cabecera_recorta_los_idiomas_antes_que_envolver():
    linea = _cabecera("apuntes.md", IDIOMAS_14, 40).plain
    assert len(linea) <= 40
    assert "+" in linea                      # dice cuántos ha ocultado


def test_la_cabecera_los_muestra_todos_si_caben():
    linea = _cabecera("apuntes.md", IDIOMAS_4, 120).plain
    assert all(l in linea for l in IDIOMAS_4)
    assert "+" not in linea


# ── ninguna línea se sale ─────────────────────────────────────────────────────

@pytest.mark.parametrize("ancho", [40, 60, 80, 100, 120])
def test_pipeline_view_cabe(a_ancho, ancho):
    v = PipelineView(IDIOMAS_14, "transcripcion-clase-magistral-seguridad-2026.md")
    v.set_source_done(1.2)
    v.set_progress(60)
    assert all(len(l.rstrip()) <= ancho for l in a_ancho(v, ancho))


@pytest.mark.parametrize("ancho", [40, 60, 80, 100, 120])
@pytest.mark.parametrize("idiomas", [IDIOMAS_4, IDIOMAS_14])
def test_multi_file_view_cabe(a_ancho, ancho, idiomas):
    m = MultiFileView(idiomas, ["transcripcion-clase-magistral-larguisima", "b", "c"], 30)
    assert all(len(l.rstrip()) <= ancho for l in a_ancho(m, ancho))


# ── la rejilla nunca pierde columnas ──────────────────────────────────────────

def test_con_sitio_se_usa_la_rejilla(a_ancho):
    m = MultiFileView(IDIOMAS_4, ["tema01", "tema02"], 10)
    lineas = a_ancho(m, 100)
    assert any("FILE" in l and "SRC" in l for l in lineas)


def test_la_rejilla_muestra_todos_los_idiomas_o_ninguno(a_ancho):
    # Lo que no puede pasar es enseñar la tabla con las cabeceras convertidas en "…".
    m = MultiFileView(IDIOMAS_14, ["tema01"], 15)
    for ancho in (40, 60, 80, 100, 120):
        lineas = a_ancho(m, ancho)
        cabecera = next((l for l in lineas if "FILE" in l), None)
        if cabecera is not None:
            assert all(lang in cabecera for lang in IDIOMAS_14)


def test_sin_sitio_cae_al_modo_compacto(a_ancho):
    # Un glifo por idioma es mejor que una tabla que se queda sin columnas.
    m = MultiFileView(IDIOMAS_14, ["tema01"], 15)
    m.set_status("tema01", "EN", "✓ generated")
    lineas = a_ancho(m, 50)
    assert not any("FILE" in l for l in lineas)
    assert any("✓" in l and "·" in l for l in lineas)


def test_el_modo_compacto_pinta_un_glifo_por_idioma(a_ancho):
    m = MultiFileView(IDIOMAS_14, ["tema01"], 15)
    m.set_status("tema01", "EN", "✓ generated")
    m.set_status("tema01", "FR", "✗ failed")
    m.set_status("tema01", "AR", "translating…")
    fila = m._fila_compacta("tema01", 10)
    glifos = fila.plain.strip().split()[-1]
    assert len(glifos) == len(IDIOMAS_14)
    assert glifos.startswith("✓✗")


def test_la_regla_de_medir_no_recorta():
    # console.measure() viene limitado al ancho de la consola: siempre decía que sí.
    ancha = Table.grid()
    ancha.add_column(width=500)
    ancha.add_row("x")
    assert pipeline._RULER.measure(ancha).maximum >= 500
