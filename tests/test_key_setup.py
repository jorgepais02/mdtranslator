"""Alta de una clave: la ficha de cada proveedor, .env y el orden de fallback.

Cada test es un fallo que se puede tener de verdad: reescribir .env encima de lo que
el usuario tenía a mano, dejar dos asignaciones de la misma variable, preguntar dos
veces por GEMINI_API_KEY, o guardar una clave que luego nadie usa porque el proveedor
no está en ai.fallback_order.
"""

import json

import pytest

from cli import key_setup
from cli.key_setup import _citar, anadir_al_orden, check_key, providers, save_key


# ── las fichas ────────────────────────────────────────────────────────────────

def test_cada_proveedor_dice_donde_saca_su_clave():
    for f in providers():
        assert f["key_env"], f["id"]
        assert f["signup"].startswith("https://"), f["id"]
        assert f["free"], f["id"]


def test_gemini_no_se_pregunta_dos_veces():
    """Sirve para traducir y para refinar, pero es una sola clave."""
    fichas = providers()
    claves = [f["key_env"] for f in fichas]
    assert len(claves) == len(set(claves))

    gemini = next(f for f in fichas if f["id"] == "gemini")
    assert gemini["usos"] == ["translate", "refine"]
    # La comprobación que gana es la del modelo: un GET al listado, sin gastar cuota.
    assert gemini["modelo"] is True


def test_azure_pide_tambien_la_region():
    azure = next(f for f in providers() if f["id"] == "azure")
    assert [n for n, _, _ in azure["extra_env"]] == ["AZURE_TRANSLATOR_REGION"]


def test_un_proveedor_que_no_existe_no_se_comprueba():
    assert "unknown provider" in check_key("mistral", "x")


# ── .env ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("valor, escrito", [
    ("gsk_abc123", "gsk_abc123"),
    ("1234:fx", "1234:fx"),
    ("con espacio", '"con espacio"'),
    ("con#almohadilla", '"con#almohadilla"'),
])
def test_solo_se_cita_lo_que_lo_necesita(valor, escrito):
    assert _citar(valor) == escrito


def test_escribir_una_clave_conserva_el_resto_del_fichero(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# mis claves\nDEEPL_API_KEY=vieja:fx\n\n# no tocar\nOTRA_COSA=1\n")
    monkeypatch.setattr(key_setup, "ENV_PATH", env)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    save_key({"GROQ_API_KEY": "gsk_nueva"})
    lineas = env.read_text().splitlines()

    assert "# mis claves" in lineas and "# no tocar" in lineas
    assert "DEEPL_API_KEY=vieja:fx" in lineas
    assert "OTRA_COSA=1" in lineas
    assert lineas[-1] == "GROQ_API_KEY=gsk_nueva"


def test_una_clave_que_ya_estaba_se_sustituye_en_su_sitio(tmp_path, monkeypatch):
    """Dos asignaciones de la misma variable y el valor depende de cuál gane."""
    env = tmp_path / ".env"
    env.write_text("AZURE_TRANSLATOR_KEY=vieja\nAZURE_TRANSLATOR_REGION=global\n")
    monkeypatch.setattr(key_setup, "ENV_PATH", env)

    save_key({"AZURE_TRANSLATOR_KEY": "nueva", "AZURE_TRANSLATOR_REGION": "francecentral"})
    lineas = env.read_text().splitlines()

    assert lineas == ["AZURE_TRANSLATOR_KEY=nueva",
                      "AZURE_TRANSLATOR_REGION=francecentral"]


def test_tambien_sustituye_una_linea_con_export(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("export DEEPL_API_KEY=vieja:fx\n")
    monkeypatch.setattr(key_setup, "ENV_PATH", env)

    save_key({"DEEPL_API_KEY": "nueva:fx"})

    assert env.read_text() == "DEEPL_API_KEY=nueva:fx\n"


def test_el_env_que_creamos_no_nace_legible_para_todos(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    monkeypatch.setattr(key_setup, "ENV_PATH", env)

    save_key({"GROQ_API_KEY": "gsk_x"})

    assert env.stat().st_mode & 0o077 == 0


def test_la_clave_guardada_vale_para_esta_ejecucion(tmp_path, monkeypatch):
    """Sin esto habría que salir y volver a entrar para que el proveedor apareciera."""
    monkeypatch.setattr(key_setup, "ENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)

    save_key({"CEREBRAS_API_KEY": "csk_x"})

    import os
    assert os.environ["CEREBRAS_API_KEY"] == "csk_x"


# ── el orden de fallback ──────────────────────────────────────────────────────

def _config(tmp_path, contenido: dict):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(contenido, indent=4) + "\n", encoding="utf-8")
    return path


def test_una_clave_nueva_entra_en_el_orden(tmp_path, monkeypatch):
    """El que no está en la lista no se intenta nunca, y eso no se ve en ninguna parte."""
    cfg = _config(tmp_path, {"drive": {"folder_id": "x"},
                             "ai": {"fallback_order": ["gemini:gemini-2.5-flash"]}})
    monkeypatch.setattr(key_setup, "PROJECT_ROOT", tmp_path)

    assert anadir_al_orden("groq") == cfg
    guardado = json.loads(cfg.read_text())
    assert guardado["ai"]["fallback_order"] == ["gemini:gemini-2.5-flash", "groq"]
    # Y lo que no es de esta sección sigue donde estaba.
    assert guardado["drive"]["folder_id"] == "x"


def test_no_se_anade_dos_veces(tmp_path, monkeypatch):
    cfg = _config(tmp_path, {"ai": {"fallback_order": ["groq:llama-3.3-70b"]}})
    monkeypatch.setattr(key_setup, "PROJECT_ROOT", tmp_path)

    assert anadir_al_orden("groq") is None
    assert json.loads(cfg.read_text())["ai"]["fallback_order"] == ["groq:llama-3.3-70b"]


def test_sin_seccion_ai_se_parte_del_orden_de_fabrica(tmp_path, monkeypatch):
    """Escribir la sección no puede dejar el orden en un solo modelo."""
    from ai.registry import ORDEN_DE_FABRICA

    cfg = _config(tmp_path, {"drive": {"folder_id": "x"}})
    monkeypatch.setattr(key_setup, "PROJECT_ROOT", tmp_path)

    anadir_al_orden("mistral")
    orden = json.loads(cfg.read_text())["ai"]["fallback_order"]

    assert orden[:len(ORDEN_DE_FABRICA)] == ORDEN_DE_FABRICA
    assert orden[-1] == "mistral"
