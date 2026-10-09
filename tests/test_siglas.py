import pytest

from translators.base import BaseTranslator, ProtectedTranslator


class EnMinusculas(BaseTranslator):
    """Traductor de mentira: pasa a minúsculas, así que lo que sale en mayúsculas no viajó."""
    name = "minusculas"

    def translate(self, texts, target_lang, source_lang=None):
        return [t.lower() for t in texts]


def traducir(texto):
    return ProtectedTranslator(EnMinusculas()).translate([texto], "en")[0]


@pytest.mark.parametrize("texto, esperado", [
    # M21: el árabe tradujo (AEPD) por «la Policía»
    ("la Agencia Española (AEPD) actúa", "la agencia española (AEPD) actúa"),
    ("la Declaración (SoA) se firma", "la declaración (SoA) se firma"),
])
def test_la_sigla_entre_parentesis_llega_intacta(texto, esperado):
    assert traducir(texto) == esperado


@pytest.mark.parametrize("texto", [
    "la fase de planificación (Plan)",
    "la capital (Madrid)",
    "el Reglamento (RGPD)",
    "la Unión (UE)",
    "la inteligencia artificial (IA)",
    "una sigla suelta ENS",
])
def test_lo_que_no_es_una_sigla_se_traduce(texto):
    assert traducir(texto) == texto.lower()


@pytest.mark.parametrize("texto", ["Tema 3 (II)", "Parte (IV) del curso"])
def test_los_romanos_son_parte_de_una_serie_y_no_se_protegen(texto):
    assert traducir(texto) == texto.lower()


@pytest.mark.parametrize("texto", [
    "`print(ID)` y (AB)",
    "$f(AB)$ y más",
    "mira http://x.com/a(AB) hoy",
])
def test_una_sigla_dentro_de_codigo_formula_o_url_no_deja_marcadores(texto):
    # Regresión de la primera versión: el marcador de la sigla quedaba dentro del token
    # del código y la restauración dejaba "⟦0⟧" en el documento.
    assert "⟦" not in traducir(texto)
