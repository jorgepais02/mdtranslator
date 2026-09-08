"""chunk_texts — el troceado que evita los 400 de Azure por request demasiado grande."""

from translators.base import chunk_texts


def _flat(chunks):
    return [t for c in chunks for t in c]


def test_respeta_el_limite_de_elementos():
    chunks = chunk_texts(["a"] * 250, max_items=100, max_chars=10**9)
    assert [len(c) for c in chunks] == [100, 100, 50]


def test_respeta_el_limite_de_caracteres():
    # 60 textos de 1.000 caracteres: por elementos cabrían en un solo request de
    # 60.000 caracteres, que es justo lo que Azure rechazaba con un 400.
    chunks = chunk_texts(["x" * 1000] * 60, max_items=100, max_chars=45_000)
    assert all(sum(len(t) for t in c) <= 45_000 for c in chunks)
    assert len(chunks) > 1


def test_un_texto_gigante_viaja_solo_sin_partirse():
    # Partirlo rompería la correspondencia 1:1 entre entrada y salida.
    grande = "x" * 60_000
    chunks = chunk_texts(["hola", grande, "adios"], max_items=100, max_chars=45_000)
    assert [grande] in chunks
    assert _flat(chunks) == ["hola", grande, "adios"]


def test_nunca_pierde_ni_reordena_textos():
    textos = [f"linea {i}" * (i % 7 + 1) for i in range(500)]
    assert _flat(chunk_texts(textos, 50, 1000)) == textos


def test_lista_vacia():
    assert chunk_texts([], 100, 45_000) == []
