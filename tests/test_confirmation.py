"""La pantalla de confirmación: qué se ve cuando no cabe todo, y cómo se sale de ella."""

import io

import pytest
from rich.console import Console

from cli import confirmation as conf

LANGS = ["EN", "FR", "DE", "IT", "PT", "RU", "JA", "KO", "ZH", "AR", "FA", "HE", "UR", "PL"]


@pytest.fixture
def pantalla(monkeypatch):
    """Pinta la confirmación a un ancho dado y devuelve sus líneas."""
    def _mostrar(config, ancho, respuesta="no"):
        c = Console(file=io.StringIO(), width=ancho, force_terminal=False, no_color=True)
        monkeypatch.setattr(conf, "console", c)
        monkeypatch.setattr(conf, "clear_screen", lambda: None)
        monkeypatch.setattr(conf, "ask_select", lambda *a, **k: respuesta)
        conf.show_confirmation(config)
        return c.file.getvalue().splitlines()
    return _mostrar


def _config(**extra):
    base = {"source": "apuntes.md", "provider": "auto", "provider_label": "Auto (fallback)",
            "output": "Local + Google Drive", "languages": ["EN", "FR"],
            "files": ["apuntes.md"], "format_raw": True}
    base.update(extra)
    return base


@pytest.mark.parametrize("ancho", [30, 45, 60, 80, 120])
def test_nada_se_sale_del_ancho(pantalla, ancho):
    lineas = pantalla(_config(languages=LANGS, files=[f"t{i}.md" for i in range(12)]), ancho)
    assert all(len(l.rstrip()) <= ancho for l in lineas)


@pytest.mark.parametrize("ancho", [30, 45, 80])
def test_los_valores_no_desaparecen(pantalla, ancho):
    # Rich estrujaba la columna de valores hasta dejar solo las etiquetas.
    texto = "\n".join(pantalla(_config(provider_label="DeepL API"), ancho))
    assert "DeepL" in texto or "De…" in texto


def test_muchos_idiomas_no_se_convierten_en_muchas_lineas(pantalla):
    lineas = pantalla(_config(languages=LANGS), 60)
    assert sum(1 for l in lineas if any(x in l for x in ("EN", "+6"))) <= 2


def test_muchos_idiomas_dicen_cuantos_quedan_fuera(pantalla):
    assert "+6" in "\n".join(pantalla(_config(languages=LANGS), 60))


def test_pocos_idiomas_se_muestran_todos(pantalla):
    lineas = pantalla(_config(languages=["EN", "FR", "AR"], output="Local only"), 80)
    fila = next(l for l in lineas if "Languages" in l)
    assert "EN" in fila and "FR" in fila and "AR" in fila
    assert "+" not in fila


def test_muchos_ficheros_se_recortan(pantalla):
    # La lista entera desbordaba la pantalla a lo alto.
    texto = "\n".join(pantalla(_config(files=[f"tema{i:02d}.md" for i in range(20)]), 80))
    assert "… and 12 more" in texto
    assert "tema19.md" not in texto


def test_un_solo_fichero_se_muestra_entero(pantalla):
    texto = "\n".join(pantalla(_config(files=["apuntes.md"]), 80))
    assert "apuntes.md" in texto and "Files" not in texto


def test_dice_cuanto_trabajo_va_a_hacer(pantalla):
    # Cuatro ficheros por tres idiomas son doce documentos: mejor verlo antes de arrancar.
    texto = "\n".join(pantalla(_config(files=[f"t{i}.md" for i in range(4)],
                                       languages=["EN", "FR", "AR"]), 80))
    assert "4" in texto and "3" in texto and "×" in texto


def test_resumir_no_toca_lo_que_cabe():
    assert conf._resumir(["EN", "FR"]) == "EN  FR"


def test_resumir_cuenta_lo_que_oculta():
    assert conf._resumir(LANGS).endswith("+6")


# ── las tres salidas ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("respuesta", ["yes", "no", "back"])
def test_devuelve_lo_que_se_elige(pantalla, respuesta, monkeypatch):
    c = Console(file=io.StringIO(), width=80, force_terminal=False, no_color=True)
    monkeypatch.setattr(conf, "console", c)
    monkeypatch.setattr(conf, "clear_screen", lambda: None)
    monkeypatch.setattr(conf, "ask_select", lambda *a, **k: respuesta)
    assert conf.show_confirmation(_config()) == respuesta


def test_un_ctrl_c_no_arranca_nada(monkeypatch):
    c = Console(file=io.StringIO(), width=80, force_terminal=False, no_color=True)
    monkeypatch.setattr(conf, "console", c)
    monkeypatch.setattr(conf, "clear_screen", lambda: None)
    monkeypatch.setattr(conf, "ask_select", lambda *a, **k: None)
    assert conf.show_confirmation(_config()) == "no"
