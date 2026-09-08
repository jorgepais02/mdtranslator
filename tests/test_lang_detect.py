"""Detección del idioma origen: no acertar a medias."""

from cli.pipeline import detect_source_language, MIN_LANG_CONFIDENCE

ES = ("La seguridad informática protege los sistemas de información frente a "
      "accesos no autorizados, alteraciones y destrucción de los datos que "
      "custodian las organizaciones y las administraciones públicas.")

EN = ("Information security protects computer systems against unauthorised "
      "access, alteration and destruction of the data that organisations and "
      "public administrations are responsible for keeping safe.")


def test_detecta_espanol():
    lang, warning = detect_source_language([ES])
    assert (lang, warning) == ("es", None)


def test_detecta_ingles():
    lang, warning = detect_source_language([EN])
    assert (lang, warning) == ("en", None)


def test_texto_demasiado_corto_no_inventa_idioma():
    # "A) Josep Albors" no es una muestra: langdetect devolvía 'pt' con total aplomo
    # y el pipeline creaba translated/pt/ con contenido español.
    lang, warning = detect_source_language(["A) Josep Albors", "B) Carlos"])
    assert lang is None
    assert "too short" in warning


def test_lista_vacia_no_revienta():
    lang, warning = detect_source_language([])
    assert lang is None and warning


def test_el_aviso_explica_como_forzarlo():
    _, warning = detect_source_language(["hola", "mundo", "adios"])
    assert warning is not None


def test_solo_se_analiza_el_texto_traducible():
    # El pipeline pasa los textos ya extraídos por el parser, no el markdown crudo:
    # almohadillas, tuberías de tabla y URLs desviaban la detección.
    lang, _ = detect_source_language(ES.split(". "))
    assert lang == "es"


def test_el_umbral_es_exigente():
    assert MIN_LANG_CONFIDENCE >= 0.90
