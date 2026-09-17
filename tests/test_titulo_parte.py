"""El (I)/(II)/(III) del nombre del fichero, en el título del documento.

Pasó con el módulo 19: las tres partes de "Técnica de extracciones de dispositivos
móviles" llegaron a Drive tituladas como tres temas sin relación, y en los cinco
idiomas —lo que no está en el origen no aparece en ninguna traducción—.
"""

import pytest

from core.parser import conserva_la_parte, parte_de, quita_la_parte


@pytest.mark.parametrize("nombre, esperado", [
    ("3. Técnica de extracciones (III)", "(III)"),
    ("Análisis forense sobre vehículos (I)", "(I)"),
    ("Clonado de dispositivos (II) ", "(II)"),
    ("Tema largo (XIV)", "(XIV)"),
    ("Tema con arábigo (2)", "(2)"),
])
def test_reconoce_la_parte(nombre, esperado):
    assert parte_de(nombre) == esperado


@pytest.mark.parametrize("nombre", [
    "Jaulas de Faraday en investigaciones forenses DFIR",
    "Extracción de información de ECUs (ECU)",
    "Un título con paréntesis (resumen)",
    "Proyecto (I+D)",
    "(I) al principio no es una parte",
])
def test_lo_que_no_es_una_parte_se_deja_en_paz(nombre):
    """Un título que acaba en "(DFIR)" no es la parte de nada: colgársela al
    encabezado sería inventar una serie que no existe."""
    assert parte_de(nombre) == ""


def test_la_parte_se_pega_al_titulo():
    md = "# Técnicas de Extracción Invasivas\n\n## JTAG\n\nTexto.\n"
    out = conserva_la_parte(md, "3. Técnica de extracciones (III)")
    assert out.splitlines()[0] == "# Técnicas de Extracción Invasivas (III)"
    assert out.splitlines()[2] == "## JTAG"


def test_sin_parte_en_el_fichero_el_titulo_no_se_toca():
    md = "# Clonado de Dispositivos\n\nTexto.\n"
    assert conserva_la_parte(md, "8. Clonado de dispositivos") == md


def test_manda_la_del_fichero_sobre_la_que_invente_el_modelo():
    """O convivirían dos convenciones —"(2)" y "(II)"— en la misma carpeta."""
    md = "# Extracción Física (2)\n\nTexto.\n"
    out = conserva_la_parte(md, "2. Técnica de extracciones (II)")
    assert out.splitlines()[0] == "# Extracción Física (II)"


def test_solo_el_primer_h1():
    """Un "## Fase (I)" del cuerpo es una sección, no la parte del documento."""
    md = "# Título\n\n## Fase de arranque\n\n# Otro h1 raro\n"
    out = conserva_la_parte(md, "1. Tema (I)")
    assert out.splitlines()[0] == "# Título (I)"
    assert out.splitlines()[4] == "# Otro h1 raro"


def test_sin_encabezado_no_revienta():
    md = "Un texto sin ningún heading.\n"
    assert conserva_la_parte(md, "1. Tema (I)") == md


def test_generate_markdown_pasa_el_nombre_y_no_el_numero(monkeypatch):
    """El número es la posición en el módulo, no parte del título."""
    from integrations import generate_md

    visto = {}

    class Modelo:
        def complete(self, prompt, system="", temperature=0.2):
            visto["prompt"] = prompt
            return "# Técnicas de Extracción Invasivas\n\nTexto."

    monkeypatch.setattr(generate_md, "get_model", lambda: Modelo())
    out = generate_md.generate_markdown("habla en crudo",
                                        title="3. Técnica de extracciones (III)")
    assert "Técnica de extracciones (III)" in visto["prompt"]
    assert "3. Técnica" not in visto["prompt"]
    assert out.splitlines()[0] == "# Técnicas de Extracción Invasivas (III)"


def test_generate_markdown_sigue_valiendo_con_dos_argumentos(monkeypatch):
    """La firma gana un tercer argumento opcional, como translate()."""
    from integrations import generate_md

    class Modelo:
        def complete(self, prompt, system="", temperature=0.2):
            return "# Título\n\nTexto."

    monkeypatch.setattr(generate_md, "get_model", lambda: Modelo())
    assert generate_md.generate_markdown("crudo", "es").startswith("# Título")


def test_el_indicador_no_viaja_al_traductor():
    """Quitarlo antes de traducir es lo que mantiene la serie legible.

    Mandándoselo, el árabe lo convertía en "(الجزء الأول)" y el chino en "（一）"
    mientras su hermano decía "（II）": tres convenciones en la misma carpeta.
    """
    md = "# Técnicas de Extracción Invasivas (III)\n\n## JTAG\n\nTexto.\n"
    assert quita_la_parte(md).splitlines()[0] == "# Técnicas de Extracción Invasivas"
    assert quita_la_parte(md).splitlines()[2] == "## JTAG"


def test_quitar_y_volver_a_poner_deja_el_documento_igual():
    md = "# Extracción Física (II)\n\nUn párrafo.\n"
    assert conserva_la_parte(quita_la_parte(md), "2. Tema (II)") == md


def test_quitar_no_toca_un_titulo_que_no_lleva_parte():
    md = "# Jaulas de Faraday en investigaciones forenses DFIR\n\nTexto.\n"
    assert quita_la_parte(md) == md
