"""Fallback de traducción: qué pasa cuando un proveedor se queda sin cuota o sin ritmo.

Las dos causas del módulo 21: DeepL sin cupo mensual y Azure con un 429 de ritmo que se
reintentaba a los 7 s, desde cuatro hilos a la vez, y Gemini sin sus 20 diarias en un
único modelo. Ninguna toca la red.
"""

import pytest

from translators import base
from translators.base import (FallbackTranslator, BaseTranslator, TranslationError,
                              TranslationQuotaError, en_pausa)


@pytest.fixture(autouse=True)
def sin_pausas_ni_sueño(monkeypatch):
    base.reiniciar_pausas()
    dormidos = []
    monkeypatch.setattr(base, "dormir", dormidos.append)
    yield dormidos
    base.reiniciar_pausas()


class Falso(BaseTranslator):
    def __init__(self, name, respuestas):
        self.name = name
        self.respuestas = list(respuestas)   # excepciones o textos
        self.llamadas = 0

    def translate(self, texts, target_lang, source_lang=None, context=None):
        self.llamadas += 1
        r = self.respuestas.pop(0) if len(self.respuestas) > 1 else self.respuestas[0]
        if isinstance(r, Exception):
            raise r
        return [r for _ in texts]


def test_sin_cuota_mensual_no_se_vuelve_a_preguntar(sin_pausas_ni_sueño):
    deepl = Falso("deepl", [TranslationQuotaError("DeepL quota exceeded.")])
    azure = Falso("azure", ["ok"])
    f = FallbackTranslator([deepl, azure])
    assert f.translate(["a"], "EN") == ["ok"]
    assert f.translate(["b"], "EN") == ["ok"]
    # Sin fecha de vuelta, DeepL se queda fuera: una sola petición en toda la ejecución.
    assert deepl.llamadas == 1
    assert azure.llamadas == 2


def test_un_429_de_ritmo_espera_y_reintenta_en_vez_de_fallar(sin_pausas_ni_sueño, monkeypatch):
    azure = Falso("azure", [TranslationQuotaError("429", retry_after=10), "ok"])
    f = FallbackTranslator([azure])
    # El tiempo no corre porque dormir está sustituido: la pausa se da por cumplida.
    monkeypatch.setattr(base, "en_pausa",
                        lambda n: 10.0 if azure.llamadas == 1 and not sin_pausas_ni_sueño else 0.0)
    assert f.translate(["a"], "EN") == ["ok"]
    assert azure.llamadas == 2
    assert sin_pausas_ni_sueño and sin_pausas_ni_sueño[0] >= 11


def test_si_vuelve_en_mas_de_lo_que_merece_esperar_falla_sin_dormir(sin_pausas_ni_sueño):
    gemini = Falso("gemini", [TranslationQuotaError("429", retry_after=1492)])
    f = FallbackTranslator([gemini])
    with pytest.raises(TranslationError, match="All translation providers failed"):
        f.translate(["a"], "EN")
    assert sin_pausas_ni_sueño == []
    assert gemini.llamadas == 1


def test_un_fallo_que_no_es_de_cuota_no_deja_al_proveedor_en_pausa():
    raro = Falso("deepl", [TranslationError("DeepL API request failed: 400"), "ok"])
    otro = Falso("azure", ["de azure"])
    f = FallbackTranslator([raro, otro])
    assert f.translate(["a"], "EN") == ["de azure"]
    assert en_pausa("deepl") == 0
    assert f.translate(["b"], "EN") == ["ok"]


def test_el_error_final_dice_por_que_cada_proveedor_no_pudo():
    a = Falso("deepl", [TranslationQuotaError("DeepL quota exceeded.")])
    b = Falso("azure", [TranslationError("Azure API request failed: 401")])
    with pytest.raises(TranslationError) as e:
        FallbackTranslator([a, b]).translate(["x"], "EN")
    assert "DeepL quota exceeded" in str(e.value) and "401" in str(e.value)
    # La cuota se sigue leyendo como cuota en main._retry_provider.
    assert "quota" in str(e.value).lower()


class _Resp:
    def __init__(self, status, headers=None, text=""):
        self.status_code, self.headers, self.text = status, headers or {}, text


def test_azure_429_deja_pausa_para_los_demas_hilos(monkeypatch):
    from translators.azure import AzureTranslator
    az = AzureTranslator(api_key="fake", region="global")
    respuestas = [_Resp(429), _Resp(429), _Resp(429), _Resp(429)]
    monkeypatch.setattr("translators.azure.requests.post",
                        lambda *a, **k: respuestas.pop(0))
    # azure importa dormir por nombre: parchear base.dormir no le llega y el test
    # dormiría de verdad 35 s.
    monkeypatch.setattr("translators.azure.dormir", lambda s: None)
    with pytest.raises(TranslationQuotaError) as e:
        az._post_with_retry({}, [{"text": "a"}], {})
    # 5, 10, 20 y 40 s, con la pausa puesta para toda la ejecución.
    assert e.value.retry_after == 40
    assert en_pausa("azure") > 0


def test_azure_respeta_el_retry_after_del_servidor(monkeypatch):
    from translators.azure import AzureTranslator
    az = AzureTranslator(api_key="fake", region="global")
    respuestas = [_Resp(429, {"Retry-After": "7"})]
    ok = _Resp(200)
    ok.raise_for_status = lambda: None
    ok.json = lambda: [{"translations": [{"text": "hola"}]}]
    respuestas.append(ok)
    monkeypatch.setattr("translators.azure.requests.post", lambda *a, **k: respuestas.pop(0))
    dormidos = []
    monkeypatch.setattr("translators.azure.dormir", dormidos.append)
    assert az._post_with_retry({}, [{"text": "a"}], {}) == ["hola"]
    assert 7 in dormidos


def test_un_retry_after_con_fecha_no_rompe_el_reintento():
    r = _Resp(429, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    assert base.espera_ante_429("x", r, 0) == 5


def test_deepl_456_es_cuota_sin_fecha(monkeypatch):
    from translators.deepl import DeepLTranslator
    d = DeepLTranslator(api_key="fake:fx")
    monkeypatch.setattr("translators.deepl.requests.post", lambda *a, **k: _Resp(456))
    with pytest.raises(TranslationQuotaError) as e:
        d._post_with_retry({}, {})
    assert e.value.retry_after is None


class _Gemini:
    """Cliente que contesta 429 en los modelos que se le dicen y 'ok' en el resto."""
    def __init__(self, sin_cuota):
        self.sin_cuota, self.vistos = sin_cuota, []
        self.models = self

    def generate_content(self, model, contents, config=None):
        self.vistos.append(model)
        if model in self.sin_cuota:
            raise RuntimeError("429 RESOURCE_EXHAUSTED 'retryDelay': '1492s'")
        class R: text = "1. hola"
        return R()


def _gemini(sin_cuota, modelos):
    from translators.gemini import GeminiTranslator
    g = GeminiTranslator.__new__(GeminiTranslator)
    g._client = _Gemini(sin_cuota)
    class T:
        class GenerateContentConfig:
            def __init__(self, **k): pass
        class AutomaticFunctionCallingConfig:
            def __init__(self, **k): pass
    g._types = T
    g._models = modelos
    return g


def test_gemini_sin_cuota_en_un_modelo_pasa_al_siguiente():
    g = _gemini({"a"}, ["a", "b", "c"])
    assert g.translate(["x"], "EN") == ["hola"]
    assert g._client.vistos == ["a", "b"]
    # Y no vuelve a preguntarle al que ya dijo que no.
    g.translate(["y"], "EN")
    assert g._client.vistos == ["a", "b", "b"]


def test_gemini_sin_cuota_en_todos_es_error_de_cuota():
    g = _gemini({"a", "b"}, ["a", "b"])
    with pytest.raises(TranslationQuotaError) as e:
        g.translate(["x"], "EN")
    assert "429" in str(e.value)
    assert e.value.retry_after > base.MAX_ESPERA


def test_modelos_de_respeta_el_orden_y_no_repite(monkeypatch):
    from ai import registry
    monkeypatch.setattr(registry, "orden_por_defecto",
                        lambda: ["gemini:m1", "groq", "gemini:m2", "gemini:m1", "gemini"])
    assert registry.modelos_de("gemini") == ["m1", "m2", registry.AVAILABLE_MODELS["gemini"]["default_model"]]


# ── Aviso de lo traducido sin contexto y del cupo de DeepL ─────────────────────────────

def test_el_registro_dice_que_proveedor_sin_contexto_contesto():
    from translators.wrappers import CachingTranslator

    class Cache:
        def get(self, *a): return None
        def set_many(self, *a): pass

    class Sin(Falso):
        usa_contexto = False

    base.empezar_registro()
    CachingTranslator(Falso("deepl", ["x"]), Cache()).translate(["a"], "EN")
    assert base.quien_respondio_sin_contexto() == []
    CachingTranslator(Sin("azure", ["x"]), Cache()).translate(["a"], "EN")
    assert base.quien_respondio_sin_contexto() == ["azure"]


def test_un_proveedor_que_falla_no_cuenta_como_que_contesto():
    from translators.wrappers import CachingTranslator

    class Cache:
        def get(self, *a): return None
        def set_many(self, *a): pass

    class Sin(Falso):
        usa_contexto = False

    base.empezar_registro()
    roto = Sin("azure", [TranslationError("500")])
    with pytest.raises(TranslationError):
        CachingTranslator(roto, Cache()).translate(["a"], "EN")
    assert base.quien_respondio_sin_contexto() == []


class _RespuestaUso:
    def __init__(self, cuerpo): self._cuerpo = cuerpo
    def raise_for_status(self): pass
    def json(self): return self._cuerpo


@pytest.mark.parametrize("cuerpo, esperado", [
    ({"character_count": 120, "character_limit": 500_000}, (120, 500_000)),
    (None, None),
    ([], None),
    ({"otra": 1}, None),
])
def test_usage_de_deepl_con_respuestas_raras(monkeypatch, cuerpo, esperado):
    from translators.deepl import DeepLTranslator
    monkeypatch.setattr("translators.deepl.requests.get", lambda *a, **k: _RespuestaUso(cuerpo))
    assert DeepLTranslator(api_key="k:fx").usage() == esperado


def test_el_aviso_de_cupo_solo_salta_si_no_alcanza(monkeypatch):
    from cli import pipeline

    class Doc:
        src_lang = "es"
        texts = ["hola mundo", "hola mundo", "adiós"]

    class Cache:
        def get(self, t, lang, prov): return "ya" if t == "adiós" else None

    class DL:
        def __init__(self, uso): self._uso = uso
        def usage(self): return self._uso

    dichos = []
    monkeypatch.setattr(pipeline, "TranslationCache", Cache)
    monkeypatch.setattr(pipeline.console, "print", lambda m, *a, **k: dichos.append(m))
    monkeypatch.setattr(pipeline, "DeepLTranslator", lambda: DL((499_995, 500_000)))
    pipeline._avisar_si_no_alcanza_deepl([Doc()], ["EN"], "auto")
    assert len(dichos) == 1 and "5 of 500,000" in dichos[0] and "needs about 10" in dichos[0]

    dichos.clear()
    monkeypatch.setattr(pipeline, "DeepLTranslator", lambda: DL((0, 500_000)))
    pipeline._avisar_si_no_alcanza_deepl([Doc()], ["EN"], "auto")
    pipeline._avisar_si_no_alcanza_deepl([Doc()], ["EN"], "azure")
    assert dichos == []


def test_el_aviso_de_cupo_entiende_una_lista_de_proveedores_y_un_plan_sin_tope(monkeypatch):
    from cli import pipeline

    class Doc:
        src_lang = "es"
        texts = ["una frase"]

    class Cache:
        def get(self, *a): return None

    class DL:
        def __init__(self, uso): self._uso = uso
        def usage(self): return self._uso

    dichos = []
    monkeypatch.setattr(pipeline, "TranslationCache", Cache)
    monkeypatch.setattr(pipeline.console, "print", lambda m, *a, **k: dichos.append(m))
    monkeypatch.setattr(pipeline, "DeepLTranslator", lambda: DL((499_999, 500_000)))
    pipeline._avisar_si_no_alcanza_deepl([Doc()], ["EN"], ["deepl", "azure"])
    assert len(dichos) == 1
    dichos.clear()
    monkeypatch.setattr(pipeline, "DeepLTranslator", lambda: DL((10, 0)))
    pipeline._avisar_si_no_alcanza_deepl([Doc()], ["EN"], "auto")
    assert dichos == []


def test_sin_cupo_de_deepl_en_automatico_la_ejecucion_para_salvo_que_se_acepte(monkeypatch):
    from cli import pipeline
    from cli.errors import CLIError

    class Doc:
        src_lang = "es"
        texts = ["una frase de cierto largo"]

    class Cache:
        def get(self, *a): return None

    class DL:
        def __init__(self, uso): self._uso = uso
        def usage(self): return self._uso

    dichos = []
    monkeypatch.setattr(pipeline, "TranslationCache", Cache)
    monkeypatch.setattr(pipeline.console, "print", lambda m, *a, **k: dichos.append(m))
    monkeypatch.setattr(pipeline, "DeepLTranslator", lambda: DL((499_999, 500_000)))

    with pytest.raises(CLIError, match="--accept-fallback"):
        pipeline._avisar_si_no_alcanza_deepl([Doc()], ["EN"], "auto", parar=True)
    assert dichos == []

    # Aceptado, a mano o con cupo de sobra: sigue como antes, avisando
    pipeline._avisar_si_no_alcanza_deepl([Doc()], ["EN"], "auto", parar=False)
    assert len(dichos) == 1
    dichos.clear()
    pipeline._avisar_si_no_alcanza_deepl([Doc()], ["EN"], "deepl", parar=True)
    assert len(dichos) == 1
    dichos.clear()
    monkeypatch.setattr(pipeline, "DeepLTranslator", lambda: DL((0, 500_000)))
    pipeline._avisar_si_no_alcanza_deepl([Doc()], ["EN"], "auto", parar=True)
    assert dichos == []
