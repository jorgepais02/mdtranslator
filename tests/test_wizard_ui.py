"""Wizard y selector de carpetas: lo que se le pasa a questionary y lo que queda en pantalla."""

import io
from pathlib import Path

import pytest
from rich.console import Console

from cli import folder_picker, wizard
from cli.prompts import BACK
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


# ── el resumen de lo ya contestado ────────────────────────────────────────────

def _estado(**extra):
    base = {"source": "apuntes.md", "provider": "Auto (fallback)",
            "output": "Local only", "languages": ["EN", "FR", "AR"],
            "files": ["apuntes.md"]}
    base.update(extra)
    return base


@pytest.mark.parametrize("ancho", [40, 60, 80, 120])
def test_el_resumen_cabe(a_ancho, ancho):
    c = a_ancho(ancho)
    c.print(wizard._resumen(_estado(source=LARGO, files=[LARGO])))
    assert all(len(l.rstrip()) <= ancho for l in c.file.getvalue().splitlines())


def test_el_resumen_es_una_linea_por_pregunta(a_ancho):
    # Antes cada pregunta dejaba sus opciones enteras en pantalla: veinte líneas
    # de opciones descartadas que ya no significaban nada.
    c = a_ancho(80)
    c.print(wizard._resumen(_estado()))
    lineas = [l for l in c.file.getvalue().splitlines() if l.strip()]
    assert len(lineas) == 4


def test_el_resumen_solo_ensena_lo_ya_contestado(a_ancho):
    c = a_ancho(80)
    c.print(wizard._resumen({"source": "apuntes.md", "files": ["apuntes.md"]}))
    texto = c.file.getvalue()
    assert "apuntes.md" in texto and "Provider" not in texto


def test_los_idiomas_van_en_cian_y_el_resto_un_escalon_por_debajo():
    # Lo ya contestado no compite con la pregunta viva: el resumen baja a MUTED y el
    # blanco se queda para lo que responde a la pregunta que está en pantalla.
    from cli.styles import BRIGHT, CYAN, MUTED
    assert wizard._valor("languages", _estado()).style == CYAN
    assert wizard._valor("output", _estado()).style == MUTED
    assert MUTED != BRIGHT


def test_el_verde_ya_no_marca_la_respuesta(a_ancho):
    # El verde significaba a la vez "elegido" y "salió bien": en cuanto la pantalla
    # se llenaba de verde, el ✓ del final dejaba de destacar.
    from cli.styles import GREEN
    for clave in ("source", "provider", "output", "languages"):
        assert wizard._valor(clave, _estado()).style != GREEN


def test_con_todos_los_ficheros_se_dice_cuantos_son(a_ancho):
    from core.sources import ALL_FILES
    c = a_ancho(80)
    c.print(wizard._resumen(_estado(source=ALL_FILES, files=["a.md", "b.md"])))
    assert "all 2 files" in c.file.getvalue()


# ── la nota de cobertura de la multiselección ─────────────────────────────────

def test_sin_problema_de_cobertura_no_se_dice_nada():
    # Los dieciocho códigos están cubiertos por DeepL y por Azure: la lista va limpia.
    assert wizard._nota_cobertura("EN", ["deepl", "azure"]) == ""


def test_si_solo_uno_lo_traduce_se_dice_cual(monkeypatch):
    from translators import registry
    monkeypatch.setattr(registry.AVAILABLE_TRANSLATORS["deepl"][1], "supported", frozenset({"EN"}))
    nota = wizard._nota_cobertura("AR", ["deepl", "azure"])
    assert nota.startswith("· only") and "Azure" in nota


def test_si_no_lo_traduce_nadie_se_avisa(monkeypatch):
    from translators import registry
    for pid in ("deepl", "azure"):
        monkeypatch.setattr(registry.AVAILABLE_TRANSLATORS[pid][1], "supported", frozenset({"EN"}))
    assert "no configured provider" in wizard._nota_cobertura("AR", ["deepl", "azure"])


# ── la máquina de pasos ───────────────────────────────────────────────────────

@pytest.fixture
def wizard_falso(monkeypatch, a_ancho):
    """Sustituye las preguntas por un guion, para poder comprobar el ir y venir."""
    a_ancho(80)
    monkeypatch.setattr(wizard, "clear_screen", lambda: None)
    monkeypatch.setattr(wizard, "collect_sources", lambda *a, **k: [Path("apuntes.md")])
    monkeypatch.setattr(wizard, "needs_formatting", lambda p: False)

    def _correr(guion):
        preguntas = []

        def _siguiente(etiqueta):
            preguntas.append(etiqueta)
            return guion.pop(0)

        monkeypatch.setattr(wizard, "ask_select",
                            lambda label, *a, **k: _siguiente(label))
        monkeypatch.setattr(wizard, "ask_checkbox",
                            lambda label, *a, **k: _siguiente(label))
        monkeypatch.setattr(wizard, "ask_confirm",
                            lambda label, *a, **k: _siguiente(label))
        return wizard.run_wizard("apuntes.md"), preguntas
    return _correr


def test_un_recorrido_recto_devuelve_la_config(wizard_falso):
    config, preguntas = wizard_falso(["auto", "Local only", ["EN", "FR"]])
    assert config["provider"] == "auto"
    assert config["languages"] == ["EN", "FR"]
    assert len(preguntas) == 3


def test_el_retroceso_vuelve_a_preguntar_la_anterior(wizard_falso):
    # ⌫ en "Output" tiene que devolverte a "Provider", no cancelar el wizard.
    config, preguntas = wizard_falso(
        ["auto", BACK, "deepl", "Local only", ["EN"]])
    assert preguntas[1].startswith("Output")
    assert preguntas[2].startswith("Choose translation provider")
    assert config["provider"] == "deepl"


def test_retroceder_en_la_primera_pregunta_no_cancela(wizard_falso):
    # No hay nada detrás: se vuelve a preguntar lo mismo en vez de salir.
    config, _ = wizard_falso([BACK, "auto", "Local only", ["EN"]])
    assert config is not None


def test_un_ctrl_c_cancela(wizard_falso):
    config, _ = wizard_falso(["auto", None])
    assert config is None


def test_lo_ya_contestado_vuelve_puesto(monkeypatch, a_ancho):
    # Al volver desde la confirmación, confirmar cada pregunta debe ser un Enter.
    a_ancho(80)
    monkeypatch.setattr(wizard, "clear_screen", lambda: None)
    monkeypatch.setattr(wizard, "collect_sources", lambda *a, **k: [Path("apuntes.md")])
    monkeypatch.setattr(wizard, "needs_formatting", lambda p: False)
    defaults = []
    guion = ["deepl", "Local only", ["EN"]]
    monkeypatch.setattr(wizard, "ask_select",
                        lambda label, choices, default=None, **k:
                        defaults.append(default) or guion.pop(0))
    monkeypatch.setattr(wizard, "ask_checkbox", lambda *a, **k: guion.pop(0))
    wizard.run_wizard("apuntes.md", previo={"provider": "azure", "output": "Google Drive",
                                            "languages": ["FR"], "source": "apuntes.md"})
    assert defaults[0] == "azure" and defaults[1] == "Google Drive"


# ── selector de carpetas ──────────────────────────────────────────────────────

def test_extraer_el_id_sigue_funcionando_con_nombres_largos():
    assert folder_picker.extract_folder_id("1AbCdEfGhIjKlMnOpQrStUvWxYz012345") is not None


def test_el_selector_no_usa_emoji():
    # 📁 ocupa dos celdas y ✓ una: los nombres nunca quedaban alineados entre sí.
    fuente = Path(folder_picker.__file__).read_text(encoding="utf-8")
    linea_opciones = [l for l in fuente.splitlines() if l.startswith("_USE") or l.startswith("_PASTE")]
    assert linea_opciones and not any("📁" in l or "🔗" in l for l in linea_opciones)


@pytest.mark.parametrize("n,esperado", [(0, "0 subcarpetas"), (1, "1 subcarpeta"), (4, "4 subcarpetas")])
def test_los_plurales_estan_bien(n, esperado):
    assert folder_picker._plural(n, "subcarpeta", "subcarpetas") == esperado


def test_elide_es_el_mismo_helper_en_todas_las_vistas():
    from cli import pipeline
    assert pipeline._elide is elide


@pytest.mark.parametrize("ancho,cabe", [(40, 32), (80, 72), (120, 112)])
def test_el_recorte_respeta_el_ancho(ancho, cabe):
    assert len(elide("x" * 200, cabe)) == cabe
