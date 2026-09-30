"""La garantía de compatibilidad de translate() y las capas que lo envuelven."""

import pytest

from translators.base import (BaseTranslator, FallbackTranslator, ProtectedTranslator,
                              TranslationError, call_translate)
from translators.cache import TranslationCache
from translators.wrappers import CachingTranslator


class Antiguo(BaseTranslator):
    """Proveedor escrito contra la interfaz original de dos argumentos."""
    name = "antiguo"

    def translate(self, texts, target_lang):
        return [f"[{target_lang}] {t}" for t in texts]


class Nuevo(BaseTranslator):
    name = "nuevo"

    def translate(self, texts, target_lang, source_lang=None):
        marca = f"{target_lang}<{source_lang}>" if source_lang else target_lang
        return [f"[{marca}] {t}" for t in texts]


class Roto(BaseTranslator):
    name = "roto"

    def __init__(self, salida=None, error=None):
        self.salida, self.error = salida, error

    def translate(self, texts, target_lang, source_lang=None):
        if self.error:
            raise TranslationError(self.error)
        return self.salida


# ── call_translate ────────────────────────────────────────────────────────────

def test_un_proveedor_de_la_firma_antigua_sigue_funcionando():
    # CLAUDE.md: nunca romper translate(texts, target_lang).
    assert call_translate(Antiguo(), ["hola"], "EN", "es") == ["[EN] hola"]


def test_un_proveedor_nuevo_recibe_el_idioma_origen():
    assert call_translate(Nuevo(), ["hola"], "EN", "es") == ["[EN<es>] hola"]


def test_sin_idioma_origen_el_comportamiento_es_el_de_siempre():
    assert call_translate(Nuevo(), ["hola"], "EN") == ["[EN] hola"]


def test_un_proveedor_con_kwargs_se_considera_compatible():
    class ConKwargs(BaseTranslator):
        name = "kwargs"
        def translate(self, texts, target_lang, **kw):
            return [f"[{kw.get('source_lang')}] {t}" for t in texts]

    assert call_translate(ConKwargs(), ["hola"], "EN", "es") == ["[es] hola"]


# ── ProtectedTranslator ───────────────────────────────────────────────────────

@pytest.mark.parametrize("fragmento", ["`ls -la`", "$E = mc^2$", "https://ejemplo.com/x?a=1",
                                       "[C]{.notranslate}"])
def test_el_contenido_protegido_sobrevive_a_la_traduccion(fragmento):
    class Mayusculas(BaseTranslator):
        name = "up"
        def translate(self, texts, target_lang, source_lang=None):
            return [t.upper() for t in texts]

    salida = ProtectedTranslator(Mayusculas()).translate([f"usa {fragmento} aqui"], "EN")
    assert fragmento in salida[0]


def test_la_negrita_de_la_linea_entera_no_llega_al_traductor():
    """La opción correcta de un test es la única en negrita, y con los asteriscos DeepL
    la devolvía distinta: en árabe, los tres distractores con «؟» y ella sin él."""
    recibido = []

    class Eco(BaseTranslator):
        name = "eco"
        def translate(self, texts, target_lang, source_lang=None):
            recibido.extend(texts)
            return [f" {t.upper()} " for t in texts]

    salida = ProtectedTranslator(Eco()).translate(
        ["**los hallazgos**", "**Respuesta: [C]{.notranslate}**", "**A** y **B**"], "EN")
    assert recibido == ["los hallazgos", "Respuesta: ⟦0⟧", "**A** y **B**"]
    assert salida == ["**LOS HALLAZGOS**", "**RESPUESTA: [C]{.notranslate}**", " **A** Y **B** "]


@pytest.mark.parametrize("origen, traducido, esperado", [
    ("Todos los sistemas se aíslan", "Tous les systèmes sont isolés.", "Tous les systèmes sont isolés"),
    ("**Responde toda la organización**", "Toute l'organisation répond.", "**Toute l'organisation répond**"),
    ("Menos del 5%", "少于5%。", "少于5%"),
    ("Una frase entera.", "A whole sentence.", "A whole sentence."),
    ("Qué hash tiene", "What is the hash?", "What is the hash?"),
    ("Discos, memorias, etc", "Disks, memory, etc...", "Disks, memory, etc..."),
])
def test_la_traduccion_no_gana_un_punto_que_el_origen_no_tenia(origen, traducido, esperado):
    """DeepL pone punto a lo que le parece una frase: en el test francés del módulo 20
    la opción correcta de una pregunta fue la única que lo llevaba."""
    class Fijo(BaseTranslator):
        name = "fijo"
        def translate(self, texts, target_lang, source_lang=None):
            return [traducido for _ in texts]

    assert ProtectedTranslator(Fijo()).translate([origen], "FR") == [esperado]


def test_el_chino_sale_sin_espacio_junto_al_latino_salvo_en_el_codigo():
    """DeepL escribe «利用 RClone» en una opción y «MITRE严重性» en la de al lado."""
    class Fijo(BaseTranslator):
        name = "fijo"
        def translate(self, texts, target_lang, source_lang=None):
            return ["利用 RClone 访问文件 ⟦0⟧ 意味着" for _ in texts]

    origen = ["Con RClone, acceder a `ntds.dit` supone"]
    assert ProtectedTranslator(Fijo()).translate(origen, "ZH") == ["利用RClone访问文件 `ntds.dit` 意味着"]
    assert ProtectedTranslator(Fijo()).translate(origen, "EN") == ["利用 RClone 访问文件 `ntds.dit` 意味着"]


def test_protected_detecta_que_el_proveedor_devuelve_de_menos():
    with pytest.raises(TranslationError, match="1 translations"):
        ProtectedTranslator(Roto(salida=["solo una"])).translate(["a", "b"], "EN")


# ── FallbackTranslator ────────────────────────────────────────────────────────

def test_el_fallback_pasa_al_siguiente_proveedor():
    f = FallbackTranslator([Roto(error="sin cuota"), Nuevo()])
    assert f.translate(["hola"], "EN") == ["[EN] hola"]


def test_el_fallback_propaga_el_idioma_origen():
    f = FallbackTranslator([Roto(error="sin cuota"), Nuevo()])
    assert f.translate(["hola"], "EN", "es") == ["[EN<es>] hola"]


def test_si_fallan_todos_el_error_los_nombra():
    f = FallbackTranslator([Roto(error="uno"), Roto(error="dos")])
    with pytest.raises(TranslationError) as e:
        f.translate(["hola"], "EN")
    assert "uno" in str(e.value) and "dos" in str(e.value)


def test_el_fallback_necesita_al_menos_un_proveedor():
    with pytest.raises(ValueError):
        FallbackTranslator([])


# ── CachingTranslator ─────────────────────────────────────────────────────────

@pytest.fixture
def cache(tmp_path):
    return TranslationCache(tmp_path / "cache" / "test.db")


class Contador(BaseTranslator):
    name = "contador"

    def __init__(self):
        self.llamadas, self.recibidos = 0, []

    def translate(self, texts, target_lang, source_lang=None):
        self.llamadas += 1
        self.recibidos.extend(texts)
        return [t.upper() for t in texts]


def test_la_segunda_pasada_no_llama_al_proveedor(cache):
    p = Contador()
    c = CachingTranslator(p, cache)
    assert c.translate(["hola", "mundo"], "EN") == ["HOLA", "MUNDO"]
    assert c.translate(["hola", "mundo"], "EN") == ["HOLA", "MUNDO"]
    assert p.llamadas == 1


def test_solo_se_piden_los_textos_que_faltan(cache):
    p = Contador()
    c = CachingTranslator(p, cache)
    c.translate(["hola"], "EN")
    c.translate(["hola", "nuevo"], "EN")
    assert p.recibidos == ["hola", "nuevo"]


def test_el_orden_se_respeta_mezclando_aciertos_y_fallos(cache):
    p = Contador()
    c = CachingTranslator(p, cache)
    c.translate(["b"], "EN")
    assert c.translate(["a", "b", "c"], "EN") == ["A", "B", "C"]


def test_el_idioma_origen_no_invalida_la_cache(cache):
    # La clave excluye source_lang a propósito: si lo incluyera, añadir la detección
    # habría tirado las 13.788 entradas ya guardadas.
    p = Contador()
    c = CachingTranslator(p, cache)
    c.translate(["hola"], "EN")
    c.translate(["hola"], "EN", "es")
    assert p.llamadas == 1


def test_cada_idioma_destino_tiene_su_entrada(cache):
    p = Contador()
    c = CachingTranslator(p, cache)
    c.translate(["hola"], "EN")
    c.translate(["hola"], "FR")
    assert p.llamadas == 2


def test_una_respuesta_corta_no_deja_huecos_none(cache):
    # Un None colado llegaba al DOCX como el texto literal "None".
    with pytest.raises(TranslationError):
        CachingTranslator(Roto(salida=["una"]), cache).translate(["a", "b"], "EN")


def test_una_respuesta_no_textual_se_rechaza(cache):
    with pytest.raises(TranslationError):
        CachingTranslator(Roto(salida=[None, None]), cache).translate(["a", "b"], "EN")


def test_nada_se_cachea_si_la_llamada_falla(cache):
    with pytest.raises(TranslationError):
        CachingTranslator(Roto(salida=["una"]), cache).translate(["a", "b"], "EN")
    assert cache.get("a", "EN", "roto") is None


def test_la_cache_soporta_varios_hilos(cache):
    # Conexión por hilo + WAL: con una conexión compartida esto daba
    # "SQLite objects created in a thread can only be used in that same thread".
    import threading
    p, errores = Contador(), []
    c = CachingTranslator(p, cache)

    def worker(i):
        try:
            c.translate([f"texto {i}"], "EN")
        except Exception as e:  # pragma: no cover
            errores.append(e)

    hilos = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for h in hilos: h.start()
    for h in hilos: h.join()
    assert errores == []
    assert cache.get("texto 3", "EN", "contador") == "TEXTO 3"


def test_un_proveedor_con_source_lang_solo_por_nombre():
    class SoloKeyword(BaseTranslator):
        name = "kw-only"
        def translate(self, texts, target_lang, *, source_lang=None):
            return [f"[{source_lang}] {t}" for t in texts]

    assert call_translate(SoloKeyword(), ["hola"], "EN", "es") == ["[es] hola"]


def test_un_proveedor_con_args_variables_lo_recibe_por_posicion():
    class ConArgs(BaseTranslator):
        name = "args"
        def translate(self, texts, target_lang, *args):
            return [f"[{args[0] if args else None}] {t}" for t in texts]

    assert call_translate(ConArgs(), ["hola"], "EN", "es") == ["[es] hola"]


# ── context ───────────────────────────────────────────────────────────────────
# De qué van los apuntes, para que el proveedor elija la acepción del módulo. Cada línea
# viaja sola y "forense" en español es a la vez el médico del juzgado y la disciplina
# informática: sin contexto, "Análisis Forense" salía en chino como "法医分析" —el de las
# autopsias— y "Selección del Origen" como "产地选择", la procedencia de un producto.


class ConContexto(BaseTranslator):
    name = "con-contexto"

    def __init__(self):
        self.visto = "sin pasar"

    def translate(self, texts, target_lang, source_lang=None, context=None):
        self.visto = context
        return [f"[{context}] {t}" for t in texts]


def test_un_proveedor_que_lo_declara_recibe_el_contexto():
    p = ConContexto()
    assert call_translate(p, ["hola"], "EN", "es", "apuntes de forense digital") == \
        ["[apuntes de forense digital] hola"]
    assert p.visto == "apuntes de forense digital"


def test_un_proveedor_que_no_lo_declara_no_se_entera():
    # Es el caso de Azure: su API no tiene nada equivalente, y pasárselo reventaría.
    assert call_translate(Nuevo(), ["hola"], "EN", "es", "apuntes de forense") == \
        ["[EN<es>] hola"]
    assert call_translate(Antiguo(), ["hola"], "EN", None, "apuntes de forense") == \
        ["[EN] hola"]


def test_con_args_variables_el_contexto_no_se_cuela_por_posicion():
    """Su sitio depende de que source_lang venga puesto: por posición llegaría descolocado."""
    class ConArgs(BaseTranslator):
        name = "args"
        def translate(self, texts, target_lang, *args):
            return [f"[{len(args)}] {t}" for t in texts]

    assert call_translate(ConArgs(), ["hola"], "EN", "es", "contexto") == ["[1] hola"]
    assert call_translate(ConArgs(), ["hola"], "EN", None, "contexto") == ["[0] hola"]


def test_el_contexto_atraviesa_las_tres_capas(cache):
    p = ConContexto()
    envuelto = ProtectedTranslator(FallbackTranslator([CachingTranslator(p, cache)]))
    envuelto.translate(["hola"], "EN", "es", context="apuntes de vehículos")
    assert p.visto == "apuntes de vehículos"


def test_el_contexto_no_entra_en_la_clave_de_la_cache(cache):
    """Meterlo invalidaría las 16.000 traducciones que ya hay para reescribir lo mismo."""
    p = Contador()
    envuelto = CachingTranslator(p, cache)

    envuelto.translate(["hola"], "EN", context="apuntes de vehículos")
    assert p.llamadas == 1
    # Otro módulo, otro contexto: sigue siendo un acierto de caché y no se paga.
    assert envuelto.translate(["hola"], "EN", context="apuntes de jaulas de Faraday") == \
        ["HOLA"]
    assert p.llamadas == 1
