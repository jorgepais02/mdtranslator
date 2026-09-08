"""Proveedores: límites de request y mapeo de códigos, sin llamar a ninguna API."""

import pytest

from translators.azure import AzureTranslator
from translators.deepl import DeepLTranslator
from translators.base import TranslationError, chunk_texts

# Topes reales documentados por cada API.
AZURE_MAX_CHARS = 50_000
AZURE_MAX_ITEMS = 1_000
DEEPL_MAX_BYTES = 128 * 1024


@pytest.fixture
def azure():
    return AzureTranslator(api_key="fake", region="westeurope")


@pytest.fixture
def deepl():
    return DeepLTranslator(api_key="fake:fx")


def test_los_limites_de_azure_dejan_margen(azure):
    assert azure.max_batch_chars < AZURE_MAX_CHARS
    assert azure.max_batch_size <= AZURE_MAX_ITEMS


def test_los_limites_de_deepl_dejan_margen(deepl):
    # Margen para la cabecera JSON y el escapado de caracteres.
    assert deepl.max_batch_chars < DEEPL_MAX_BYTES


def test_ningun_request_de_azure_supera_su_tope(azure):
    textos = ["párrafo largo. " * 200] * 40
    for chunk in chunk_texts(textos, azure.max_batch_size, azure.max_batch_chars):
        assert sum(len(t) for t in chunk) <= AZURE_MAX_CHARS


def test_la_clave_free_de_deepl_apunta_al_endpoint_free():
    assert "api-free" in DeepLTranslator(api_key="abc:fx").base_url


def test_la_clave_pro_de_deepl_apunta_al_endpoint_pro():
    assert "api-free" not in DeepLTranslator(api_key="abc").base_url


def test_sin_clave_el_proveedor_no_se_construye(monkeypatch):
    monkeypatch.delenv("DEEPL_API_KEY", raising=False)
    with pytest.raises(TranslationError):
        DeepLTranslator(api_key="")


@pytest.mark.parametrize("entrada,esperado", [
    ("ZH", "zh-Hans"),      # Azure no entiende "zh" a secas
    ("EN-GB", "en-GB"),
    ("FR", "fr"),
    ("ar", "ar"),
])
def test_azure_mapea_los_codigos_especiales(azure, entrada, esperado):
    assert azure._map_lang_code(entrada) == esperado


def test_traducir_una_lista_vacia_no_llama_a_la_api(azure, deepl):
    assert azure.translate([], "EN") == []
    assert deepl.translate([], "EN") == []
