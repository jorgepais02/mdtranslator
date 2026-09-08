"""La vista del pipeline: qué filas se muestran cuando no caben todas a lo alto."""

import pytest

from cli.pipeline import ProgressView


def _vista(n_ficheros, idiomas=("EN", "FR")):
    filas = {f"tema{i:02d}": len(idiomas) for i in range(n_ficheros)}
    return ProgressView(f"{n_ficheros} files", list(idiomas), filas, show_langs=True)


def test_si_caben_se_muestran_todas():
    v = _vista(5)
    filas, ocultas = v.visible_tracks(alto=40)
    assert len(filas) == 5 and ocultas == 0


def test_si_no_caben_se_recortan():
    v = _vista(50)
    filas, ocultas = v.visible_tracks(alto=24)
    assert len(filas) + ocultas == 50
    assert len(filas) < 50


def test_lo_que_esta_en_marcha_tiene_prioridad():
    # Lo terminado cede el sitio: para eso está la tabla de resultados del final.
    v = _vista(30)
    for clave in list(v.tracks)[:25]:
        for _ in range(2):
            v.complete(clave)
    filas, _ = v.visible_tracks(alto=24)
    vivas = set(list(v.tracks)[25:])
    assert vivas <= {t.key for t in filas}


def test_las_filas_no_bailan_de_sitio():
    # Si el orden cambiara en cada refresco, la vista sería ilegible.
    v = _vista(30)
    filas, _ = v.visible_tracks(alto=24)
    orden = {k: i for i, k in enumerate(v.tracks)}
    claves = [t.key for t in filas]
    assert claves == sorted(claves, key=orden.get)


def test_un_terminal_diminuto_deja_al_menos_unas_pocas():
    filas, ocultas = _vista(30).visible_tracks(alto=5)
    assert len(filas) >= 3
    assert ocultas == 30 - len(filas)


def test_el_recorte_no_afecta_al_porcentaje():
    v = _vista(50)
    for _ in range(50):
        v.complete("tema00")
    assert v.pct == 50


# ── la barra de cada fila ─────────────────────────────────────────────────────

def test_una_fila_en_cola_esta_a_cero():
    v = _vista(1)
    assert v.tracks["tema00"].pct == 0.0


def test_la_fila_avanza_con_las_tareas_terminadas():
    v = _vista(1, idiomas=("EN", "FR", "AR", "ZH"))
    v.complete("tema00")
    assert v.tracks["tema00"].pct == 25.0


def test_la_fase_en_curso_mueve_la_barra_sin_esperar_a_terminar():
    # Traducir, refinar y subir son tres momentos distintos: la barra los distingue.
    v = _vista(1, idiomas=("EN",))
    v.update("tema00", "translating…")
    a = v.tracks["tema00"].pct
    v.update("tema00", "uploading…")
    assert 0 < a < v.tracks["tema00"].pct < 100


def test_una_fila_terminada_llega_al_cien():
    v = _vista(1, idiomas=("EN",))
    v.complete("tema00")
    assert v.tracks["tema00"].pct == 100.0


def test_el_cronometro_para_al_terminar():
    v = _vista(1, idiomas=("EN",))
    v.update("tema00", "translating…")
    v.complete("tema00")
    t = v.tracks["tema00"]
    assert t.elapsed(t.finished + 10) == pytest.approx(t.finished - t.started)


def test_el_cronometro_sigue_corriendo_mientras_la_fila_vive():
    v = _vista(1, idiomas=("EN",))
    v.update("tema00", "translating…")
    t = v.tracks["tema00"]
    assert t.elapsed(t.started + 5) == pytest.approx(5)


def test_una_fila_sin_empezar_no_tiene_cronometro():
    assert _vista(1).tracks["tema00"].elapsed(0.0) is None


# ── la etiqueta de estado ─────────────────────────────────────────────────────

def test_la_etiqueta_no_repite_el_glifo():
    # El color ya dice si fue bien; el ✓ solo gastaba una columna.
    v = _vista(1)
    v.update("tema00", "✓ generated")
    assert v.tracks["tema00"].etiqueta() == "generated"


def test_la_etiqueta_dice_en_que_idioma_va():
    v = _vista(1)
    v.update("tema00", "uploading…", "ZH")
    assert v.tracks["tema00"].etiqueta() == "uploading ZH"


@pytest.mark.parametrize("n", [1, 3, 10, 100])
def test_render_no_revienta_con_cualquier_numero_de_ficheros(n):
    v = _vista(n)
    v.update("tema00", "translating…", "EN")
    assert v.render() is not None


def test_una_fila_terminada_no_se_queda_con_el_ultimo_idioma():
    # Se quedaba diciendo "generated FR" cuando ya habia hecho los cuatro.
    v = _vista(1, idiomas=("EN", "FR"))
    v.update("tema00", "uploading…", "EN")
    v.complete("tema00")
    v.update("tema00", "✓ generated", "FR")
    v.complete("tema00")
    assert v.tracks["tema00"].etiqueta() == "generated"
