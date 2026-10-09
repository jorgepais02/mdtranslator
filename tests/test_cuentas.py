"""«Seis bloques» y cinco viñetas: el error es de la charla y viaja a los cinco idiomas."""
import pytest

from core.parser import cuentas_que_no_cuadran


@pytest.mark.parametrize("md, esperado", [
    # M21, documento 1: anunció seis bloques y dio cinco
    ("La ponencia tiene seis bloques principales.\n\n- a\n- b\n- c\n- d\n- e\n",
     ['says "seis bloques" and lists 5']),
    # M21, documento 4: nueve categorías anunciadas, ocho en la lista
    ("El anexo agrupa 38 controles en nueve categorías:\n\n" + "".join(f"- c{i}\n" for i in range(8)),
     ['says "nueve categorías" and lists 8']),
    ("Hay tres fases:\n1. uno\n2. dos\n3. tres\n", []),
    ("Hay tres fases:\n\n- uno\n  - sub\n  - sub\n- dos\n- tres\n", []),
    ("Son cuatro pasos y se explican en el texto.\n\nOtro párrafo.\n- suelto\n", []),
    ("Tiene 38 controles agrupados.\n\n- a\n- b\n", []),
])
def test_avisa_solo_cuando_la_lista_no_tiene_los_elementos_anunciados(md, esperado):
    assert cuentas_que_no_cuadran(md) == esperado
