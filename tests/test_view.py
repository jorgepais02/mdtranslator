"""La rejilla de --all: qué filas se muestran cuando no caben todas."""

import pytest

from cli.pipeline import MultiFileView


def _vista(n_ficheros, idiomas=("EN", "FR")):
    stems = [f"tema{i:02d}" for i in range(n_ficheros)]
    return MultiFileView(list(idiomas), stems, n_ficheros * (len(idiomas) + 1))


def test_si_caben_se_muestran_todas():
    v = _vista(5)
    stems, ocultas = v.visible_stems(alto=40)
    assert stems == v.stems and ocultas == 0


def test_si_no_caben_se_recortan():
    v = _vista(50)
    stems, ocultas = v.visible_stems(alto=24)
    assert len(stems) + ocultas == 50
    assert len(stems) < 50


def test_lo_que_esta_en_marcha_tiene_prioridad():
    # Lo terminado cede el sitio: para eso está la tabla de resultados del final.
    v = _vista(30)
    for stem in v.stems[:25]:
        for col in v.cells[stem]:
            v.set_status(stem, col, "✓ generated")
    stems, _ = v.visible_stems(alto=24)
    assert set(v.stems[25:]) <= set(stems)


def test_las_filas_no_bailan_de_sitio():
    # Si el orden cambiara en cada refresco, la tabla sería ilegible.
    v = _vista(30)
    stems, _ = v.visible_stems(alto=24)
    orden = {s: i for i, s in enumerate(v.stems)}
    assert stems == sorted(stems, key=orden.get)


def test_un_terminal_diminuto_deja_al_menos_unas_pocas():
    stems, ocultas = _vista(30).visible_stems(alto=5)
    assert len(stems) >= 3
    assert ocultas == 30 - len(stems)


def test_el_recorte_no_afecta_al_porcentaje():
    v = _vista(50)
    for _ in range(75):
        v.mark_completed()
    assert v.pct == 50


@pytest.mark.parametrize("n", [1, 3, 10, 100])
def test_render_no_revienta_con_cualquier_numero_de_ficheros(n):
    v = _vista(n)
    v.set_source_lang(v.stems[0], "es")
    v.set_status(v.stems[0], "EN", "translating…")
    assert v.render() is not None
