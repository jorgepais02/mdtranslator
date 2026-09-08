"""Descubrimiento de fuentes: qué fichero entra y cuál gana cuando hay duplicados."""

import pytest

from core.sources import ALL_FILES, collect_sources, needs_formatting


@pytest.fixture
def carpeta(tmp_path):
    (tmp_path / "apuntes.md").write_text("# Título\n\nTexto.\n", encoding="utf-8")
    (tmp_path / "apuntes.txt").write_text("transcripcion en crudo\n", encoding="utf-8")
    (tmp_path / "tema2.md").write_text("# Tema 2\n", encoding="utf-8")
    (tmp_path / "notas.txt").write_text("otra transcripcion\n", encoding="utf-8")
    (tmp_path / "imagen.png").write_bytes(b"\x89PNG")
    return tmp_path


def test_all_files_ignora_extensiones_no_soportadas(carpeta):
    nombres = [p.name for p in collect_sources(ALL_FILES, carpeta)]
    assert "imagen.png" not in nombres


def test_el_md_gana_sobre_el_txt_del_mismo_nombre(carpeta):
    # Si compitieran, apuntes.md y apuntes.txt escribirían el mismo fichero de salida.
    nombres = [p.name for p in collect_sources(ALL_FILES, carpeta)]
    assert "apuntes.md" in nombres
    assert "apuntes.txt" not in nombres


def test_all_files_devuelve_orden_estable(carpeta):
    nombres = [p.name for p in collect_sources(ALL_FILES, carpeta)]
    assert nombres == sorted(nombres, key=str.lower)
    assert nombres == ["apuntes.md", "notas.txt", "tema2.md"]


def test_nombre_suelto(carpeta):
    assert [p.name for p in collect_sources("tema2.md", carpeta)] == ["tema2.md"]


def test_ruta_absoluta(carpeta):
    ruta = carpeta / "tema2.md"
    assert collect_sources(str(ruta), carpeta) == [ruta]


def test_fichero_inexistente_devuelve_lista_vacia(carpeta):
    assert collect_sources("no-existe.md", carpeta) == []


def test_carpeta_inexistente_no_revienta(tmp_path):
    assert collect_sources(ALL_FILES, tmp_path / "nope") == []


def test_todo_txt_necesita_formateo(carpeta):
    assert needs_formatting(carpeta / "notas.txt")


def test_un_md_con_headings_no_necesita_formateo(carpeta):
    assert not needs_formatting(carpeta / "apuntes.md")


def test_un_md_sin_headings_es_una_transcripcion(tmp_path):
    crudo = tmp_path / "crudo.md"
    crudo.write_text("esto es una transcripcion sin estructura ninguna\n", encoding="utf-8")
    assert needs_formatting(crudo)


def test_almohadilla_sin_espacio_no_es_heading(tmp_path):
    falso = tmp_path / "falso.md"
    falso.write_text("#hashtag y ya\n", encoding="utf-8")
    assert needs_formatting(falso)
