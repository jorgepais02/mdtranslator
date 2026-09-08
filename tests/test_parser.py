"""parse_markdown_lines / rebuild: la correspondencia 1:1 entre líneas y traducciones."""

from core.parser import parse_markdown_lines, rebuild_markdown_from_translations

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
