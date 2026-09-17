"""Modelos de IA: fallback, lectura del 429 y decir con qué modelo se refinó.

Cada caso viene del módulo 19: se quedó 16 tareas sin refinar con el 429 de
`gemini-2.5-flash` mientras cinco modelos de la misma cuenta contestaban sin
problema, porque el id del modelo estaba escrito a mano en tres sitios. Lo que se
prueba aquí es que eso ya no puede volver a bloquear un lote, y que el corte por
cuota del pipeline sigue significando lo mismo.
"""

import io

import pytest
from rich.console import Console

from ai.base import (MAX_ESPERA, AIError, AIModel, AIQuotaError, cambio_de_modelo,
                     es_cuota, espera_pedida, FallbackModel, sin_pistas_de_cuota)
from ai import registry
from cli import results as results_mod
from document import refiner


class Fijo(AIModel):
    """Un modelo que contesta lo mismo siempre, o siempre falla."""

    def __init__(self, nombre="uno", modelo="m1", respuesta="ok", error=None):
        super().__init__(model=modelo, name=nombre)
        self.respuesta = respuesta
        self.error = error
        self.llamadas = 0

    def complete(self, prompt, system="", temperature=0.2):
        self.llamadas += 1
        if self.error is not None:
            raise self.error
        return self.respuesta


# ── lo que pide un 429 ────────────────────────────────────────────────────────

def test_del_429_se_saca_la_espera_que_pide():
    e = Exception("429 RESOURCE_EXHAUSTED {'retryDelay': '34s'}")
    # Un segundo de mas: esperar justo lo que dice la API vuelve a chocar con la ventana.
    assert espera_pedida(e) == 35


def test_un_429_sin_espera_cae_en_el_tope():
    assert espera_pedida(Exception("429 RESOURCE_EXHAUSTED")) == MAX_ESPERA


def test_una_espera_enorme_se_recorta_al_tope():
    assert espera_pedida(Exception("429 {'retryDelay': '3600s'}")) == MAX_ESPERA


@pytest.mark.parametrize("mensaje", ["503 unavailable", "400 invalid api key", ""])
def test_lo_que_no_es_cuota_no_se_reintenta(mensaje):
    assert espera_pedida(Exception(mensaje)) is None


def test_la_cabecera_retry_after_tambien_vale():
    # Los compatibles con OpenAI no mandan el retryDelay de Gemini: lo dicen en la
    # cabecera, y Groq ademas en la frase del cuerpo.
    assert espera_pedida(AIQuotaError("429 rate limit", retry_after=7.5)) == 9
    assert espera_pedida(Exception("429: please try again in 4.2s")) == 6


def test_un_rate_limit_sin_numero_cuenta_como_cuota():
    assert es_cuota(Exception("Too Many Requests"))
    assert not es_cuota(Exception("503 service unavailable"))


# ── el fallback ───────────────────────────────────────────────────────────────

@pytest.fixture
def sin_dormir(monkeypatch):
    dormido = []
    monkeypatch.setattr(refiner.time, "sleep", lambda s: dormido.append(s))
    return dormido


def test_el_siguiente_modelo_contesta_sin_esperar(sin_dormir):
    # El caso del modulo 19: el preferido sin cuota y el de al lado libre. Pagar la
    # espera del primero antes de probar el segundo eran hasta 120s por lote.
    sin_cuota = Fijo("gemini", "gemini-2.5-flash",
                     error=AIQuotaError("429 RESOURCE_EXHAUSTED {'retryDelay': '59s'}"))
    libre = Fijo("gemini", "gemini-3.5-flash", respuesta="refinado")
    cadena = FallbackModel([sin_cuota, libre])

    assert cadena.complete("x") == "refinado"
    assert sin_dormir == []
    assert cadena.usado is libre
    assert cadena.ref == "gemini:gemini-3.5-flash"


def test_si_ninguno_tiene_cuota_el_aviso_conserva_el_429():
    cadena = FallbackModel([
        Fijo("gemini", "a", error=AIQuotaError("429 {'retryDelay': '40s'}")),
        Fijo("groq", "b", error=AIQuotaError("429 rate limit", retry_after=5)),
    ])
    with pytest.raises(AIQuotaError) as exc:
        cadena.complete("x")
    # El pipeline corta el refinamiento del resto de la ejecucion leyendo el aviso:
    # sin el 429 dentro, cada documento volveria a pagar sus reintentos.
    assert refiner.es_aviso_de_cuota(str(exc.value))
    assert espera_pedida(exc.value) == 6      # la espera mas corta de las dos


def test_un_503_entre_medias_no_apaga_el_refinado_de_los_demas():
    # Al reves, un 503 de un modelo encenderia sin_cuota en el pipeline y el resto de
    # los documentos se saltaria el refinado teniendo cuota de sobra.
    cadena = FallbackModel([
        Fijo("gemini", "a", error=AIQuotaError("429 RESOURCE_EXHAUSTED")),
        Fijo("groq", "b", error=AIError("503 service unavailable, retry after 429 ms")),
    ])
    with pytest.raises(AIError) as exc:
        cadena.complete("x")
    assert not isinstance(exc.value, AIQuotaError)
    assert not refiner.es_aviso_de_cuota(str(exc.value))
    assert "503" in str(exc.value)            # pero sigue diciendo que paso


def test_el_error_de_un_adaptador_roto_no_corta_la_lista():
    cadena = FallbackModel([Fijo("x", "a", error=RuntimeError("boom")),
                            Fijo("y", "b", respuesta="ok")])
    assert cadena.complete("x") == "ok"


def test_la_espera_solo_llega_cuando_se_agota_la_lista(sin_dormir):
    # Dos modelos sin cuota la primera vez y con cuota la segunda: una sola espera
    # para los dos, no una por modelo.
    class Intermitente(Fijo):
        def complete(self, prompt, system="", temperature=0.2):
            self.llamadas += 1
            if self.llamadas == 1:
                raise AIQuotaError("429 {'retryDelay': '2s'}")
            return "1. refinado uno"

    cadena = FallbackModel([Intermitente("a", "a"), Intermitente("b", "b")])
    salida, aviso = refiner._llamar_modelo(["uno"], "ar", cadena)
    assert aviso is None and salida == ["refinado uno"]
    assert len(sin_dormir) > 0 and sum(sin_dormir) <= 3 * refiner._PASO_ESPERA


def test_las_pistas_de_cuota_se_apagan_sin_perder_el_mensaje():
    limpio = sin_pistas_de_cuota("503 unavailable (429 RESOURCE_EXHAUSTED inside)")
    assert "503 unavailable" in limpio
    assert not refiner.es_aviso_de_cuota(limpio)


# ── el registro ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ref, esperado", [
    ("gemini:gemini-3.5-flash", ("gemini", "gemini-3.5-flash")),
    ("groq",                    ("groq", None)),
    ("GEMINI",                  ("gemini", None)),
    (" groq : abc ",            ("groq", "abc")),
])
def test_una_ref_se_parte_en_proveedor_y_modelo(ref, esperado):
    assert registry.parse_ref(ref) == esperado


def test_los_proveedores_sin_clave_se_caen_de_la_cadena(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    modelo = registry.get_model(["groq", "gemini:gemini-3.5-flash"])
    # Es un orden de preferencia, no una eleccion para esta ejecucion: quedarse sin
    # refinar porque la primera opcion no tiene clave no ayuda a nadie.
    assert modelo.ref == "gemini:gemini-3.5-flash"


def test_sin_ninguna_clave_se_dice_cual_falta(monkeypatch):
    for var in ("GEMINI_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(AIError) as exc:
        registry.get_model(["gemini", "groq"])
    assert "GEMINI_API_KEY" in str(exc.value)


def test_una_lista_con_varios_da_un_fallback(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    modelo = registry.get_model(["gemini:gemini-2.5-flash", "gemini:gemini-3.5-flash"])
    assert isinstance(modelo, FallbackModel)
    assert [m.model for m in modelo.modelos] == ["gemini-2.5-flash", "gemini-3.5-flash"]


def test_un_modelo_repetido_no_se_intenta_dos_veces(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    modelo = registry.get_model(["gemini", "gemini:gemini-2.5-flash"])
    assert not isinstance(modelo, FallbackModel)     # es el mismo modelo dos veces


def test_el_traductor_gemini_usa_el_modelo_del_orden(monkeypatch):
    monkeypatch.setattr(registry, "orden_por_defecto",
                        lambda: ["groq", "gemini:gemini-3.5-flash"])
    assert registry.modelo_de("gemini") == "gemini-3.5-flash"
    assert registry.modelo_de("groq") == AVAILABLE_GROQ


AVAILABLE_GROQ = registry.AVAILABLE_MODELS["groq"]["default_model"]


# ── decir con que modelo se refino ────────────────────────────────────────────

def test_del_modelo_preferido_no_se_dice_nada():
    cadena = FallbackModel([Fijo("gemini", "a"), Fijo("groq", "b")])
    cadena.complete("x")
    assert cambio_de_modelo(cadena) is None
    assert cambio_de_modelo(Fijo("gemini", "a")) is None


def test_del_mismo_proveedor_basta_el_nombre_del_modelo():
    cadena = FallbackModel([
        Fijo("gemini", "gemini-2.5-flash", error=AIQuotaError("429")),
        Fijo("gemini", "gemini-3.5-flash"),
    ])
    cadena.complete("x")
    assert cambio_de_modelo(cadena) == {"used": "gemini-3.5-flash",
                                        "instead_of": "gemini-2.5-flash",
                                        "reason": "no quota"}


def test_de_otro_proveedor_se_dice_de_quien_es():
    cadena = FallbackModel([Fijo("gemini", "gemini-2.5-flash", error=AIError("503")),
                            Fijo("groq", "llama-3.3-70b")])
    cadena.complete("x")
    assert cambio_de_modelo(cadena) == {"used": "groq:llama-3.3-70b",
                                        "instead_of": "gemini:gemini-2.5-flash",
                                        "reason": "failed"}


def test_el_refinado_dice_con_que_modelo_salio(monkeypatch):
    cadena = FallbackModel([
        Fijo("gemini", "gemini-2.5-flash", error=AIQuotaError("429 RESOURCE_EXHAUSTED")),
        Fijo("gemini", "gemini-3.5-flash", respuesta="1. refinado"),
    ])
    monkeypatch.setattr(refiner, "get_model", lambda *a, **k: cadena)
    lineas, aviso, cambio = refiner.refine_markdown(["un parrafo"], "ar")
    assert aviso is None and lineas == ["refinado"]
    assert cambio["used"] == "gemini-3.5-flash"


def test_sin_ningun_modelo_el_refinado_avisa_y_no_toca_el_texto(monkeypatch):
    def sin_claves(*a, **k):
        raise AIError("no AI model configured (GEMINI_API_KEY not set)")
    monkeypatch.setattr(refiner, "get_model", sin_claves)
    lineas, aviso, cambio = refiner.refine_markdown(["un parrafo"], "ar")
    assert lineas == ["un parrafo"] and cambio is None
    assert results_mod._short_warning(aviso) == \
        "No AI model configured — add a key to .env (e.g. GEMINI_API_KEY)"


def test_la_pantalla_final_nombra_el_modelo_que_contesto():
    salida = io.StringIO()
    console = Console(file=salida, width=100, force_terminal=False, legacy_windows=False)
    resultados = [{"lang": "AR", "source": "tema.md", "file": "tema.ar.docx", "ok": True,
                   "time": 3.0, "gdocs_url": None, "warning": None, "incomplete": False,
                   "refine_model": {"used": "gemini-3.5-flash",
                                    "instead_of": "gemini-2.5-flash",
                                    "reason": "no quota"}}]
    import cli.results as r
    console_original = r.console
    r.console = console
    try:
        r.show_results(resultados, 3.0)
    finally:
        r.console = console_original
    texto = salida.getvalue()
    assert "refined with gemini-3.5-flash" in texto
    assert "gemini-2.5-flash had no quota" in texto


def test_sin_cambio_de_modelo_no_hay_bloque_de_avisos():
    salida = io.StringIO()
    console = Console(file=salida, width=100, force_terminal=False, legacy_windows=False)
    resultados = [{"lang": "AR", "source": "tema.md", "file": "tema.ar.docx", "ok": True,
                   "time": 3.0, "gdocs_url": None, "warning": None, "incomplete": False,
                   "refine_model": None}]
    import cli.results as r
    console_original = r.console
    r.console = console
    try:
        r.show_results(resultados, 3.0)
    finally:
        r.console = console_original
    assert "Warnings" not in salida.getvalue()


def test_dieciseis_documentos_del_mismo_modelo_son_una_linea():
    # Eran dieciseis filas identicas debajo de la tabla: la linea que de verdad se lee
    # es cuantos documentos salieron de otro modelo, no cual de ellos.
    cambio = {"used": "gemini-3.5-flash", "instead_of": "gemini-2.5-flash",
              "reason": "no quota"}
    resultados = [{"lang": l, "source": f"tema{i}.md", "file": "x.docx", "ok": True,
                   "time": 1.0, "gdocs_url": None, "warning": None,
                   "incomplete": False, "refine_model": dict(cambio)}
                  for i in range(8) for l in ("AR", "ZH")]
    assert results_mod._por_modelo(resultados) == {
        ("gemini-3.5-flash", "gemini-2.5-flash", "no quota"): 16}

    salida = io.StringIO()
    import cli.results as r
    console_original = r.console
    r.console = Console(file=salida, width=100, force_terminal=False)
    try:
        r.show_results(resultados, 10.0)
    finally:
        r.console = console_original
    texto = salida.getvalue()
    assert texto.count("refined with gemini-3.5-flash") == 1
    assert "16 documents refined with gemini-3.5-flash" in texto
