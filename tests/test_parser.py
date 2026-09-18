"""parse_markdown_lines / rebuild: la correspondencia 1:1 entre líneas y traducciones."""

from core.parser import (contexto_del_documento, parse_markdown_lines,
                         rebuild_markdown_from_translations)

DOC = """# Título del tema

Un párrafo normal.

- primer punto
- segundo punto

1. paso uno
2. paso dos

> una cita
>
> otra cita

```python
codigo = "no traducir"
```

| Col A | Col B |
|-------|-------|
| uno   | dos   |

---
"""


def _parsed(texto=DOC):
    return parse_markdown_lines(texto.splitlines())


def _textos(parsed):
    return [t for _, _p, t in parsed if t]


def test_el_rebuild_sin_traducir_reproduce_el_original():
    parsed = _parsed()
    assert rebuild_markdown_from_translations(parsed, _textos(parsed)) == DOC.splitlines()


def test_los_bloques_de_codigo_no_son_traducibles():
    assert 'codigo = "no traducir"' not in _textos(_parsed())


def test_el_codigo_sale_intacto():
    parsed = _parsed()
    salida = rebuild_markdown_from_translations(parsed, ["X"] * len(_textos(parsed)))
    assert 'codigo = "no traducir"' in salida


def test_el_separador_de_tabla_no_se_traduce():
    assert not any(set(t) <= set("|-: ") for t in _textos(_parsed()))


def test_una_linea_estructural_vacia_no_consume_traduccion():
    # El '>' suelto entre dos citas: si consumiera un hueco, todas las líneas
    # posteriores se desplazarían una posición.
    parsed = parse_markdown_lines(["> uno", ">", "> dos"])
    salida = rebuild_markdown_from_translations(parsed, ["ONE", "TWO"])
    assert salida == ["> ONE", ">", "> TWO"]


def test_una_respuesta_corta_degrada_al_original_en_vez_de_escribir_none():
    parsed = _parsed()
    salida = rebuild_markdown_from_translations(parsed, ["X"])
    assert "None" not in "\n".join(salida)
    assert "Un párrafo normal." in salida


def test_un_none_del_proveedor_no_llega_al_documento():
    parsed = parse_markdown_lines(["Hola mundo"])
    assert rebuild_markdown_from_translations(parsed, [None]) == ["Hola mundo"]


def test_se_conserva_el_salto_de_linea_forzado():
    parsed = parse_markdown_lines(["linea con salto  "])
    assert rebuild_markdown_from_translations(parsed, ["LINEA"]) == ["LINEA  "]


def test_se_conserva_la_indentacion_de_las_listas():
    parsed = parse_markdown_lines(["  - anidado"])
    assert rebuild_markdown_from_translations(parsed, ["NESTED"]) == ["  - NESTED"]


def test_se_conserva_el_nivel_del_heading():
    parsed = parse_markdown_lines(["### Sub"])
    assert rebuild_markdown_from_translations(parsed, ["SUB"]) == ["### SUB"]


def test_el_numero_de_la_lista_ordenada_no_se_traduce():
    parsed = parse_markdown_lines(["1. primero"])
    assert rebuild_markdown_from_translations(parsed, ["FIRST"]) == ["1. FIRST"]


def test_documento_vacio():
    assert rebuild_markdown_from_translations(parse_markdown_lines([]), []) == []


# ── contexto_del_documento ────────────────────────────────────────────────────
# De qué van los apuntes, sacado del propio documento y no de un glosario a mano: cada
# módulo habla de otra cosa y no se sabe de antemano qué palabras se vuelven ambiguas.


def test_el_contexto_es_el_titulo_y_su_entradilla():
    md = ("# Clonado de Dispositivos a Nivel Forense\n\n"
          "Este módulo aborda el clonado de dispositivos, la cadena de custodia y el uso "
          "de funciones hash.\n\n"
          "## Introducción\n")
    c = contexto_del_documento(md)
    assert c.startswith("Clonado de Dispositivos a Nivel Forense ")
    assert "cadena de custodia" in c


def test_sin_entradilla_el_contexto_baja_al_desarrollo():
    """Sin esto, "Técnicas de Extracción Invasivas" era todo el contexto, y el chino
    tradujo "extracción" como la dental: 侵入性拔牙技术."""
    md = ("# Técnicas de Extracción Invasivas\n\n"
          "## JTAG\n\n"
          "La técnica JTAG implica soldar cables a la placa para leer la memoria flash "
          "del teléfono móvil.\n")
    c = contexto_del_documento(md)
    assert "memoria flash" in c
    assert "JTAG\n" not in c          # el encabezado suelto no, la prosa sí


def test_el_contexto_deja_fuera_lo_que_no_es_prosa():
    md = ("# Formatos de Imagen\n\n"
          "- RAW: sin compresión\n"
          "| a | b |\n"
          "> una cita\n"
          "```\ndd if=/dev/sda\n```\n"
          "Los formatos más usados comprimen la imagen.\n")
    c = contexto_del_documento(md)
    assert c == "Formatos de Imagen Los formatos más usados comprimen la imagen."


def test_sin_encabezado_de_nivel_uno_no_hay_contexto():
    assert contexto_del_documento("## Solo una sección\n\nTexto.\n") == ""
    assert contexto_del_documento("Texto suelto sin título.\n") == ""


def test_el_recorte_no_parte_la_ultima_palabra():
    md = "# Título\n\n" + ("palabra " * 300)
    c = contexto_del_documento(md, tope=50)
    assert len(c) <= 50
    assert not c.endswith("palabr")
    assert c.split()[-1] == "palabra"
