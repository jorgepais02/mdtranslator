"""Retomar un lote que murió a la mitad: cuota, caché de refinado y el aviso final.

Cada caso es algo que pasó de verdad con el módulo 19: el refinamiento se rendía al
primer 429 teniendo la cuota a un minuto de distancia, relanzar volvía a pagar lo ya
refinado, y el único sitio donde constaba que dos documentos habían salido sin refinar
era un aviso en una pantalla que se cierra.
"""

import io

import pytest
from rich.console import Console

from cli import main as cli_main
from cli import results as results_mod
from document import refiner


# ── lo que pide un 429 ────────────────────────────────────────────────────────

def test_del_429_se_saca_la_espera_que_pide():
    e = Exception("429 RESOURCE_EXHAUSTED {'retryDelay': '34s'}")
    # Un segundo de mas: esperar justo lo que dice la API vuelve a chocar con la ventana.
    assert refiner._espera_pedida(e) == 35


def test_un_429_sin_espera_cae_en_el_tope():
    assert refiner._espera_pedida(Exception("429 RESOURCE_EXHAUSTED")) == refiner._MAX_ESPERA


def test_una_espera_enorme_se_recorta_al_tope():
    e = Exception("429 RESOURCE_EXHAUSTED {'retryDelay': '3600s'}")
    assert refiner._espera_pedida(e) == refiner._MAX_ESPERA


@pytest.mark.parametrize("mensaje", ["503 unavailable", "400 invalid api key", ""])
def test_lo_que_no_es_cuota_no_se_reintenta(mensaje):
    assert refiner._espera_pedida(Exception(mensaje)) is None


def test_el_aviso_de_cuota_se_distingue_de_los_demas():
    assert refiner.es_aviso_de_cuota("Gemini: 429 RESOURCE_EXHAUSTED")
    assert refiner.es_aviso_de_cuota("resource_exhausted")
    assert not refiner.es_aviso_de_cuota("Gemini returned 3/4 lines")
    assert not refiner.es_aviso_de_cuota(None)


# ── el reintento ──────────────────────────────────────────────────────────────

class ClienteFalso:
    """Un cliente de Gemini que falla las primeras veces y luego contesta."""

    def __init__(self, fallos=0, error="429 RESOURCE_EXHAUSTED {'retryDelay': '2s'}"):
        self.fallos = fallos
        self.error = error
        self.llamadas = 0
        self.models = self

    def generate_content(self, **kw):
        self.llamadas += 1
        if self.llamadas <= self.fallos:
            raise RuntimeError(self.error)
        pedidas = kw["contents"].strip().splitlines()
        lineas = [l for l in pedidas if l[:1].isdigit()]
        texto = "\n".join(f"{i+1}. refinado {l.split('. ', 1)[-1]}"
                          for i, l in enumerate(lineas))
        return type("R", (), {"text": texto})()


@pytest.fixture
def sin_dormir(monkeypatch):
    dormido = []
    monkeypatch.setattr(refiner.time, "sleep", lambda s: dormido.append(s))
    return dormido


def test_el_refinado_reintenta_tras_un_429(sin_dormir):
    c = ClienteFalso(fallos=refiner._MAX_INTENTOS - 1)
    salida, aviso = refiner._call_gemini(["uno", "dos"], "ar", c)
    assert aviso is None
    assert salida == ["refinado uno", "refinado dos"]
    assert c.llamadas == refiner._MAX_INTENTOS
    assert sum(sin_dormir) > 0      # esperó lo que pidió el 429, no de golpe


def test_tras_los_intentos_el_429_se_propaga(sin_dormir):
    c = ClienteFalso(fallos=99)
    with pytest.raises(RuntimeError):
        refiner._call_gemini(["uno"], "ar", c)
    assert c.llamadas == refiner._MAX_INTENTOS


def test_un_error_que_no_es_cuota_no_gasta_intentos(sin_dormir):
    c = ClienteFalso(fallos=99, error="400 invalid argument")
    with pytest.raises(RuntimeError):
        refiner._call_gemini(["uno"], "ar", c)
    assert c.llamadas == 1
    assert sin_dormir == []


def test_cancelar_corta_la_espera(monkeypatch):
    monkeypatch.setattr(refiner.time, "sleep", lambda s: None)
    c = ClienteFalso(fallos=99)
    with pytest.raises(RuntimeError):
        refiner._call_gemini(["uno"], "ar", c, cancelado=lambda: True)
    assert c.llamadas == 1      # no reintenta lo que el usuario acaba de cancelar


# ── la caché del refinado ─────────────────────────────────────────────────────

class CacheFalsa:
    def __init__(self):
        self.datos = {}
    def get(self, texto, lang, provider):
        return self.datos.get((texto, lang, provider))
    def set_many(self, pares, lang, provider):
        for src, tgt in pares:
            self.datos[(src, lang, provider)] = tgt


def test_lo_ya_refinado_no_vuelve_a_gemini():
    cache = CacheFalsa()
    c1 = ClienteFalso()
    salida1, _ = refiner._refinar(["uno", "dos"], "ar", c1, cache, None)
    c2 = ClienteFalso()
    salida2, _ = refiner._refinar(["uno", "dos"], "ar", c2, cache, None)
    assert salida1 == salida2
    assert c1.llamadas == 1 and c2.llamadas == 0


def test_solo_viaja_lo_que_falta():
    cache = CacheFalsa()
    cache.set_many([("uno", "ya estaba")], "ar", refiner.CACHE_PROVIDER)
    c = ClienteFalso()
    salida, _ = refiner._refinar(["uno", "dos"], "ar", c, cache, None)
    assert salida == ["ya estaba", "refinado dos"]
    assert c.llamadas == 1


def test_una_linea_repetida_se_paga_una_vez():
    c = ClienteFalso()
    # "Fuente: INCIBE" sale veinte veces en unos apuntes; mandarla veinte veces era
    # gastar cuota en la misma frase.
    salida, _ = refiner._refinar(["a", "b", "a", "b"], "ar", c, CacheFalsa(), None)
    assert salida == ["refinado a", "refinado b", "refinado a", "refinado b"]
    assert c.llamadas == 1


def test_sin_cache_el_refinado_sigue_funcionando():
    c = ClienteFalso()
    salida, aviso = refiner._refinar(["uno"], "ar", c, None, None)
    assert aviso is None and salida == ["refinado uno"]


# ── el comando que relanza ────────────────────────────────────────────────────

def test_el_comando_reconstruye_un_lote():
    cmd = cli_main._retry_command({
        "source": "sources/modulo-19", "languages": ["ES", "EN", "AR"],
        "output": "Local + Google Drive", "provider": "auto", "source_lang": "ES",
    })
    assert cmd == ("python -m src.cli.main sources/modulo-19 --lang ES EN AR "
                   "--output both --source-lang ES -y")


def test_el_comando_usa_all_cuando_toca():
    from core.sources import ALL_FILES
    cmd = cli_main._retry_command({"source": ALL_FILES, "languages": ["EN"],
                                   "output": "Local only", "provider": "auto"})
    assert "--all" in cmd and ALL_FILES not in cmd


def test_el_comando_entrecomilla_un_nombre_con_espacios():
    cmd = cli_main._retry_command({
        "source": "sources/modulo-19/4. Análisis forense (I).md",
        "languages": ["AR"], "output": "Local only", "provider": "deepl",
    })
    assert "'sources/modulo-19/4. Análisis forense (I).md'" in cmd
    assert "--provider deepl" in cmd


def test_el_proveedor_auto_no_se_escribe():
    cmd = cli_main._retry_command({"source": "x.md", "languages": ["EN"],
                                   "output": "Local only", "provider": "auto"})
    assert "--provider" not in cmd


# ── la pantalla final ─────────────────────────────────────────────────────────

def _pintar(monkeypatch, results, retry_cmd=None, retry_note=None, ancho=100):
    c = Console(file=io.StringIO(), width=ancho, force_terminal=False, no_color=True)
    monkeypatch.setattr(results_mod, "console", c)
    results_mod.show_results(results, 1.0, retry_cmd=retry_cmd, retry_note=retry_note)
    return c.file.getvalue()


def _fila(lang, **extra):
    base = {"lang": lang, "source": "m19.md", "file": f"m19.{lang.lower()}.docx",
            "ok": True, "time": 1.0, "gdocs_url": None, "warning": None}
    base.update(extra)
    return base



def test_lo_que_quedo_a_medias_sale_con_su_comando(monkeypatch):
    salida = _pintar(monkeypatch,
                     [_fila("EN"), _fila("AR", incomplete=True,
                                         warning="Gemini: 429 RESOURCE_EXHAUSTED")],
                     retry_cmd="python -m src.cli.main sources/modulo-19 --lang EN AR -y")
    assert "Unfinished" in salida
    assert "1 of 2" in salida
    assert "python -m src.cli.main sources/modulo-19" in salida


def test_sin_nada_a_medias_no_hay_bloque(monkeypatch):
    salida = _pintar(monkeypatch, [_fila("EN"), _fila("AR")], retry_cmd="cualquier cosa")
    assert "Unfinished" not in salida
    assert "cualquier cosa" not in salida


def test_a_medias_no_es_un_fallo(monkeypatch):
    # El documento está subido y se usa: el pie sigue diciendo que la ejecución fue bien.
    salida = _pintar(monkeypatch, [_fila("AR", incomplete=True)])
    assert "Completed with errors" not in salida
    assert "Unfinished" in salida


def test_el_json_lleva_el_comando(capsys):
    cli_main.print_json_results(
        [_fila("EN"), _fila("AR", incomplete=True)], 2.0, "python -m src.cli.main x -y")
    import json
    datos = json.loads(capsys.readouterr().out)
    assert datos["incomplete"] == 1
    assert datos["retry_command"] == "python -m src.cli.main x -y"
    assert datos["status"] == "success"      # nada falló: solo falta una pasada


def test_el_json_sin_nada_a_medias_no_mete_ruido(capsys):
    cli_main.print_json_results([_fila("EN")], 1.0, "python -m src.cli.main x -y")
    import json
    datos = json.loads(capsys.readouterr().out)
    assert "retry_command" not in datos and "incomplete" not in datos


# ── con qué proveedor relanzar ────────────────────────────────────────────────

def _cargados(monkeypatch, *ids):
    monkeypatch.setattr(cli_main, "get_available_translators",
                        lambda: [{"id": i, "name": i.title()} for i in ids])


def _fallo_cuota(warning="DeepL: Quota exceeded (456)"):
    return {"lang": "EN", "source": "m19.md", "file": "—", "ok": False, "time": 0.0,
            "gdocs_url": None, "warning": warning}


@pytest.mark.parametrize("aviso", ["DeepL: Quota exceeded", "429 Too Many Requests",
                                   "RESOURCE_EXHAUSTED", "azure: rate limit"])
def test_se_reconoce_un_proveedor_agotado(aviso):
    assert cli_main._es_fallo_de_cuota(aviso)


@pytest.mark.parametrize("aviso", ["auth failed", "timeout", None, ""])
def test_lo_que_no_es_cuota_no_cambia_de_proveedor(aviso):
    assert not cli_main._es_fallo_de_cuota(aviso)


def test_un_proveedor_agotado_propone_los_demas(monkeypatch):
    # Elegir proveedor a mano quita el fallback a proposito, asi que el 429 deja el lote
    # sin traducir: lo unico que faltaba era decir que hay otras claves cargadas.
    _cargados(monkeypatch, "deepl", "azure", "gemini")
    provider, nota = cli_main._retry_provider({"provider": "deepl"}, [_fallo_cuota()])
    assert provider == "auto"
    assert "Azure" in nota and "Gemini" in nota


def test_sin_otras_claves_no_se_promete_nada(monkeypatch):
    _cargados(monkeypatch, "deepl")
    assert cli_main._retry_provider({"provider": "deepl"}, [_fallo_cuota()]) == ("deepl", None)


def test_un_fallo_que_no_es_cuota_mantiene_el_proveedor(monkeypatch):
    _cargados(monkeypatch, "deepl", "azure")
    fallo = _fallo_cuota("auth failed")
    assert cli_main._retry_provider({"provider": "deepl"}, [fallo]) == ("deepl", None)


def test_en_auto_no_hay_nada_que_proponer(monkeypatch):
    _cargados(monkeypatch, "deepl", "azure")
    assert cli_main._retry_provider({"provider": "auto"}, [_fallo_cuota()]) == ("auto", None)


def test_el_comando_del_reintento_lleva_el_proveedor_nuevo():
    cmd = cli_main._retry_command({"source": "x.md", "languages": ["EN"],
                                   "output": "Local only", "provider": "deepl"}, "auto")
    # auto no se escribe cuando es lo que ya se pidio, pero aqui es el cambio: el
    # comando tiene que ensenar en que se diferencia del que acaba de fallar.
    assert "--provider auto" in cmd


# ── la pantalla final con fallos ──────────────────────────────────────────────

def test_un_lote_que_fallo_tambien_dice_como_retomarse(monkeypatch):
    salida = _pintar(monkeypatch,
                     [_fila("EN"), _fila("AR", ok=False, file="—",
                                         warning="DeepL: Quota exceeded")],
                     retry_cmd="python -m src.cli.main x -y")
    assert "Unfinished" in salida
    assert "1 of 2 documents did not come out" in salida
    assert "python -m src.cli.main x -y" in salida


def test_la_nota_del_proveedor_se_pinta(monkeypatch):
    fallo = [_fila("AR", ok=False, file="—")]
    assert "ran out of quota" not in _pintar(monkeypatch, fallo, retry_cmd="x")
    salida = _pintar(monkeypatch, fallo, retry_cmd="x",
                     retry_note="DeepL API ran out of quota — switching.")
    assert "ran out of quota" in salida


def test_el_json_de_un_lote_fallido_lleva_el_comando(capsys):
    import json
    cli_main.print_json_results([_fila("EN"), _fila("AR", ok=False, file="—")], 1.0,
                                "python -m src.cli.main x -y")
    datos = json.loads(capsys.readouterr().out)
    assert datos["status"] == "partial_success"
    assert datos["retry_command"] == "python -m src.cli.main x -y"
    assert datos["incomplete"] == 0


# ── relanzar no puede dejarte con menos ───────────────────────────────────────

def test_sin_refinar_no_se_pisa_lo_que_ya_estaba(tmp_path):
    from cli.pipeline import _conserva_lo_refinado
    fuente = tmp_path / "m19.md"; fuente.write_text("origen")
    salida = tmp_path / "m19.ar.md"; salida.write_text("ya refinado")
    assert _conserva_lo_refinado(salida, fuente, refined=False) is True


def test_lo_refinado_de_esta_pasada_si_se_escribe(tmp_path):
    from cli.pipeline import _conserva_lo_refinado
    fuente = tmp_path / "m19.md"; fuente.write_text("origen")
    salida = tmp_path / "m19.ar.md"; salida.write_text("viejo")
    assert _conserva_lo_refinado(salida, fuente, refined=True) is False


def test_una_fuente_mas_nueva_manda_aunque_no_haya_refinado(tmp_path):
    import os, time
    from cli.pipeline import _conserva_lo_refinado
    salida = tmp_path / "m19.ar.md"; salida.write_text("traduccion vieja")
    fuente = tmp_path / "m19.md"; fuente.write_text("el apunte cambio")
    os.utime(fuente, (time.time() + 10, time.time() + 10))
    # El apunte se ha editado: conservar la salida vieja seria servir contenido caducado.
    assert _conserva_lo_refinado(salida, fuente, refined=False) is False


def test_si_no_hay_nada_escrito_se_escribe(tmp_path):
    from cli.pipeline import _conserva_lo_refinado
    fuente = tmp_path / "m19.md"; fuente.write_text("origen")
    assert _conserva_lo_refinado(tmp_path / "no-existe.md", fuente, refined=False) is False
