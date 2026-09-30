"""parse_markdown_lines / rebuild: la correspondencia 1:1 entre líneas y traducciones."""

from core.parser import (contexto_del_documento, espaciado_cjk, parse_markdown_lines,
                         rebuild_markdown_from_translations, sin_envoltorio)

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


# ── listas con letra ─────────────────────────────────────────────────────────
# La letra es estructura: mandándola al traductor, el árabe devolvía "أ)" y el chino
# "A）", Pandoc dejaba de ver la lista y la solución "C" no apuntaba a ninguna opción.

OPCIONES = ["A) Superior a 60 dB", "", "b) Superior a 30 dB", "", "  c. Superior a 45 dB"]


def test_la_letra_de_una_opcion_no_viaja_al_traductor():
    assert _textos(parse_markdown_lines(OPCIONES)) == [
        "Superior a 60 dB", "Superior a 30 dB", "Superior a 45 dB"]


def test_la_letra_vuelve_a_su_sitio_con_la_traduccion():
    parsed = parse_markdown_lines(OPCIONES)
    salida = rebuild_markdown_from_translations(parsed, ["أكثر من 60", "أكثر من 30", "أكثر من 45"])
    assert salida == ["A) أكثر من 60", "", "b) أكثر من 30", "", "  c. أكثر من 45"]


def test_una_inicial_con_punto_es_prosa_y_no_una_lista():
    """Igual que para Pandoc: "B. Russell…" con un solo espacio no es el punto B."""
    assert parse_markdown_lines(["B. Russell fue un filósofo."]) == [
        ("body", "", "B. Russell fue un filósofo.")]


def test_las_opciones_no_son_contexto():
    md = "# Test\n\nRepaso de las jaulas de Faraday.\n\nA) Superior a 60 dB\n"
    assert contexto_del_documento(md) == "Test Repaso de las jaulas de Faraday."


# ── énfasis que envuelve la línea ────────────────────────────────────────────
# La opción correcta de un test es la única en negrita, y con los asteriscos hacía otro
# camino: en el módulo 20 DeepL devolvió en árabe los tres distractores con «؟» y la
# negrita sin él. La negrita delataba la respuesta.

def test_la_negrita_que_envuelve_la_linea_se_separa():
    assert sin_envoltorio("**Los hallazgos de la investigación**") == (
        "Los hallazgos de la investigación", "**")
    assert sin_envoltorio("**Respuesta: [C]{.notranslate}**") == ("Respuesta: [C]{.notranslate}", "**")
    assert sin_envoltorio("***x***") == ("x", "***")
    assert sin_envoltorio("_nota_") == ("nota", "_")


def test_lo_que_no_envuelve_la_linea_entera_se_queda():
    for texto in ["**A** y **B**", "Un **hallazgo** clave", "**mal cerrada*", "** con hueco**",
                  "**`snake_case`**", "sin énfasis"]:
        assert sin_envoltorio(texto) == (texto, "")


def test_el_espaciado_entre_chino_y_latino_es_uno_solo():
    """En el test chino del módulo 20 la opción correcta era la única con «低于 5%»: el
    refinador metía el espacio en unas líneas y no en otras, y el espaciado la delataba."""
    assert espaciado_cjk("低于 5%", "zh") == "低于5%"
    assert espaciado_cjk("20% 至 40%", "zh") == "20%至40%"
    assert espaciado_cjk("MITRE 严重性等级及 CMDB 中资产", "zh") == "MITRE严重性等级及CMDB中资产"
    assert espaciado_cjk("一个看似 7 GB 的文件", "zh-hant") == "一个看似7 GB的文件"
    assert espaciado_cjk("Python を使う", "ja") == "Pythonを使う"


def test_el_espaciado_solo_cambia_en_chino_y_japones():
    assert espaciado_cjk("低于 5%", "ko") == "低于 5%"
    assert espaciado_cjk("Menos del 5 %", "fr") == "Menos del 5 %"
    # los ⟦n⟧ del código inline y la puntuación de ancho completo se quedan como estaban
    assert espaciado_cjk("访问文件 ⟦0⟧ 意味着", "zh") == "访问文件 ⟦0⟧ 意味着"
    assert espaciado_cjk("数据采集， SIEM", "zh") == "数据采集， SIEM"
