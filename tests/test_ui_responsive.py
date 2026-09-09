"""Las vistas se adaptan al ancho del terminal en vez de partirse."""

import io

import pytest
from rich.console import Console

from cli import pipeline
from cli.pipeline import ProgressView, Track, _bar, _cabecera, _elide
from cli.styles import BAR_RAIL, BAR_TINT

IDIOMAS_4  = ["EN", "FR", "AR", "ZH"]
IDIOMAS_14 = ["EN", "FR", "DE", "IT", "PT", "RU", "JA", "KO",
              "ZH", "AR", "FA", "HE", "UR", "PL"]

LARGO = "transcripcion-clase-magistral-seguridad-informatica-2026"


@pytest.fixture
def a_ancho(monkeypatch):
    """Renderiza una vista al ancho pedido y devuelve sus líneas."""
    def _render(vista, ancho):
        c = Console(file=io.StringIO(), width=ancho, force_terminal=False, no_color=True)
        monkeypatch.setattr(pipeline, "console", c)
        c.print(vista.render())
        return c.file.getvalue().splitlines()
    return _render


def _un_fichero(idiomas=IDIOMAS_4, nombre="apuntes.md"):
    return ProgressView(nombre, idiomas, {l: 1 for l in idiomas},
                        show_langs=False, prepare_time=1.2)


def _varios(idiomas=IDIOMAS_4, stems=("tema00", "tema01", LARGO)):
    return ProgressView(f"{len(stems)} files", idiomas,
                        {s: len(idiomas) for s in stems}, show_langs=True)


# ── helpers ───────────────────────────────────────────────────────────────────

def test_elide_recorta_y_marca():
    assert _elide("abcdefghij", 5) == "abcd…"


def test_elide_no_toca_lo_que_cabe():
    assert _elide("abc", 10) == "abc"


# La barra ya no dibuja glifos: son celdas en blanco con color de fondo, así que lo
# que hay que mirar es el color de cada celda y no qué carácter lleva.
RAIL = BAR_RAIL                      # lo que queda es un filete, no un fondo
CABEZA = f"on {BAR_TINT}"


def _celdas(barra):
    """Color de fondo de cada celda, saltando la sangría inicial."""
    fondos = []
    for i in range(1, len(barra.plain)):
        estilo = ""
        for span in barra.spans:
            if span.start <= i < span.end:
                estilo = str(span.style)
        fondos.append(estilo)
    return fondos


@pytest.mark.parametrize("ancho", [12, 20, 40])
def test_la_barra_mide_lo_que_se_le_pide(ancho):
    # Estaba fija a 40 caracteres y en un terminal estrecho caía a la línea siguiente.
    assert len(_bar(50, ancho).plain) == ancho + 1               # +1 por la sangría
    assert len(_celdas(_bar(50, ancho))) == ancho


def test_la_barra_refleja_el_porcentaje():
    assert sum(c != RAIL for c in _celdas(_bar(25, 40))) == 10
    assert sum(c != RAIL for c in _celdas(_bar(0, 40))) == 0
    assert sum(c == RAIL for c in _celdas(_bar(100, 40))) == 0


def test_una_barra_casi_llena_no_se_pinta_llena():
    # Una fila que sigue subiendo con la barra al 100% se lee como terminada.
    assert _celdas(_bar(99.9, 20))[-1] != CABEZA
    assert _celdas(_bar(100, 20))[-1] == CABEZA


def test_una_fila_terminada_llega_a_pintarse_llena():
    # La persecución exponencial es asintótica y nunca llega. Sin banda muerta la
    # fila se quedaba en 99,9%, la barra pintaba a falta de una celda y contradecía
    # al ✓ que tiene al lado.
    t = Track("EN", total=1, hechas=1)
    for _ in range(40):                       # dos segundos a veinte fotogramas
        t.avanzar(0.05)
    assert t.pintada == 100.0
    assert _celdas(_bar(t.pintada, 20))[-1] == CABEZA


def test_la_barra_no_salta_de_golpe_al_valor_nuevo():
    # V1: lo que se dibuja persigue a pct, así que un salto de fase se recorre.
    t = Track("EN", total=1, hechas=1)
    t.avanzar(0.05)
    assert 0 < t.pintada < 100


def test_una_fila_terminada_apaga_la_barra():
    # Cinco barras llenas de color al acabar son media pantalla repitiendo lo que ya
    # dice el ✓. Al terminar, la fila devuelve la barra al raíl.
    assert set(_celdas(_bar(100, 20, apagada=True))) == {RAIL}


def test_el_rail_no_pinta_fondo():
    # Pintado de fondo, los raíles de las cinco filas se funden en un rectángulo:
    # entre renglones de un terminal no hay separación que los corte.
    assert all("on " not in c for c in _celdas(_bar(0, 20)))


def test_el_latido_solo_toca_la_celda_de_cabeza():
    apagado = _celdas(_bar(50, 20, pulso=0.0))
    encendido = _celdas(_bar(50, 20, pulso=1.0))
    assert sum(a != b for a, b in zip(apagado, encendido)) == 1


def test_la_cabecera_recorta_los_idiomas_antes_que_envolver():
    linea = _cabecera("apuntes.md", IDIOMAS_14, 40).plain
    assert len(linea) <= 40
    assert "+" in linea                      # dice cuántos ha ocultado


def test_la_cabecera_los_muestra_todos_si_caben():
    linea = _cabecera("apuntes.md", IDIOMAS_4, 120).plain
    assert all(l in linea for l in IDIOMAS_4)
    assert "+" not in linea


# ── ninguna línea se sale ─────────────────────────────────────────────────────

@pytest.mark.parametrize("ancho", [32, 40, 60, 80, 100, 120])
def test_la_vista_de_un_fichero_cabe(a_ancho, ancho):
    v = _un_fichero(IDIOMAS_14, LARGO + ".md")
    v.update("EN", "translating…")
    assert all(len(l.rstrip()) <= ancho for l in a_ancho(v, ancho))


@pytest.mark.parametrize("ancho", [32, 40, 60, 80, 100, 120])
@pytest.mark.parametrize("idiomas", [IDIOMAS_4, IDIOMAS_14])
def test_la_vista_de_varios_cabe(a_ancho, ancho, idiomas):
    v = _varios(idiomas)
    v.update(LARGO, "uploading…", "ZH")
    assert all(len(l.rstrip()) <= ancho for l in a_ancho(v, ancho))


def test_la_barra_nunca_baja_de_su_minimo(a_ancho):
    # Una barra de tres caracteres no dice nada; antes de eso se cae el texto.
    v = _varios()
    for ancho in (32, 40, 60):
        _n, barra, _e, _b = v._medidas(ancho)
        assert barra >= pipeline._MIN_BAR


def test_en_un_terminal_estrecho_desaparece_el_estado_entero(a_ancho):
    # "ge…", "up…" no son palabras: mejor ninguna y que hable el color.
    v = _varios()
    _n, _b, estado, _bl = v._medidas(32)
    assert estado == 0 or estado >= 6


def test_la_barra_no_se_estira_sin_limite():
    # A 200 columnas una barra de 190 deja de leerse como barra.
    v = _varios()
    _n, barra, _e, _b = v._medidas(200)
    assert barra <= pipeline._MAX_BAR


def test_el_total_se_alinea_con_la_columna_de_tiempos(a_ancho):
    v = _un_fichero()
    v.complete("EN")
    lineas = [l for l in a_ancho(v, 100) if l.strip()]
    fila  = next(l for l in lineas if l.strip().startswith("EN"))
    total = next(l for l in lineas if "total" in l)
    assert len(fila.rstrip()) == len(total.rstrip())


def test_el_resumen_no_se_parte_en_dos_lineas(a_ancho):
    # Una segunda línea de resumen empuja las filas y la vista baila en cada refresco.
    v = _varios(IDIOMAS_14)
    lineas = a_ancho(v, 40)
    assert lineas[1].strip().startswith(("0 of", "parsed"))
    assert lineas[2].strip() == ""
