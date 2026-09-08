"""Conversión a PDF: agrupación por carpeta y atribución de fallos."""

from pathlib import Path

import pytest

from core import docgen


class Registro(list):
    """Lista de invocaciones con el conjunto de ficheros que deben fallar."""
    fallar: set


@pytest.fixture
def invocaciones(monkeypatch):
    """Sustituye LibreOffice: registra las llamadas y crea los PDFs pedidos."""
    llamadas = Registro()
    fallar = set()

    def falso(docx_files, outdir, timeout):
        llamadas.append((outdir, list(docx_files)))
        for f in docx_files:
            if f.name not in fallar:
                f.with_suffix(".pdf").write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(docgen, "_soffice_convert", falso)
    llamadas.fallar = fallar
    return llamadas


def _docx(tmp_path, *nombres):
    salida = []
    for n in nombres:
        p = tmp_path / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"PK")
        salida.append(p)
    return salida


def test_una_sola_invocacion_para_la_misma_carpeta(tmp_path, invocaciones):
    # Arrancar LibreOffice cuesta ~1,4s y convertir ~0,2s: el proceso es el gasto.
    ficheros = _docx(tmp_path, "en/a.docx", "en/b.docx", "en/c.docx")
    assert docgen.convert_many_to_pdf(ficheros) == {}
    assert len(invocaciones) == 1


def test_una_invocacion_por_carpeta(tmp_path, invocaciones):
    # --outdir es uno solo, así que no se pueden mezclar carpetas.
    ficheros = _docx(tmp_path, "en/a.docx", "fr/a.docx", "ar/a.docx")
    docgen.convert_many_to_pdf(ficheros)
    assert len(invocaciones) == 3


def test_sin_ficheros_no_se_arranca_libreoffice(invocaciones):
    assert docgen.convert_many_to_pdf([]) == {}
    assert list(invocaciones) == []


def test_el_fallo_se_atribuye_al_fichero_sin_pdf(tmp_path, invocaciones):
    ficheros = _docx(tmp_path, "en/a.docx", "en/roto.docx")
    invocaciones.fallar.add("roto.docx")
    fallos = docgen.convert_many_to_pdf(ficheros)
    assert list(fallos) == [tmp_path / "en" / "roto.docx"]


def test_un_fichero_roto_no_invalida_a_sus_companeros(tmp_path, invocaciones):
    ficheros = _docx(tmp_path, "en/a.docx", "en/roto.docx", "en/c.docx")
    invocaciones.fallar.add("roto.docx")
    docgen.convert_many_to_pdf(ficheros)
    assert (tmp_path / "en" / "a.pdf").exists()
    assert (tmp_path / "en" / "c.pdf").exists()


def test_el_timeout_crece_con_el_numero_de_ficheros(tmp_path, monkeypatch):
    timeouts = []
    monkeypatch.setattr(docgen, "_soffice_convert",
                        lambda f, o, timeout: timeouts.append(timeout))
    docgen.convert_many_to_pdf(_docx(tmp_path, "en/a.docx"))
    docgen.convert_many_to_pdf(_docx(tmp_path, *[f"fr/{i}.docx" for i in range(10)]))
    assert timeouts[1] > timeouts[0]
