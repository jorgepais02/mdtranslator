"""Numeración y resolución de nombres en Drive, sin tocar la red.

FakeDrive sustituye las dos únicas llamadas de red que usa la lógica de nombres.
"""

import threading

import pytest

from integrations.drive import GoogleDocsManager


class FakeDrive(GoogleDocsManager):
    """GoogleDocsManager sin autenticar: la carpeta es una lista en memoria."""

    def __init__(self, files=None, delay=0.0):
        self._files = [dict(f) for f in (files or [])]
        self._delay = delay
        self.listados = 0

    def _list_files(self, folder_id):
        self.listados += 1
        if self._delay:
            import time
            time.sleep(self._delay)
        return [dict(f) for f in self._files]

    def _list_file_names(self, folder_id):
        return [f["name"] for f in self._list_files(folder_id)]


@pytest.fixture(autouse=True)
def _estado_limpio():
    # El estado de reservas es de clase: sin limpiarlo un test contamina al siguiente.
    GoogleDocsManager._reserved.clear()
    GoogleDocsManager._folder_cache.clear()
    yield
    GoogleDocsManager._reserved.clear()
    GoogleDocsManager._folder_cache.clear()


def _nombres(n):
    return [{"id": f"id{i}", "name": str(i)} for i in range(1, n + 1)]


# ── numeración ────────────────────────────────────────────────────────────────

def test_carpeta_vacia_empieza_en_uno():
    assert FakeDrive([])._find_next_number("F", "{n}. {title}") == 1


def test_continua_despues_del_ultimo():
    g = FakeDrive(_nombres(10))
    assert g._find_next_number("F", "{n}. {title}") == 11


def test_la_numeracion_sobrevive_a_un_cambio_de_patron():
    # Los documentos 1..10 se subieron con el patrón "{n}" pelado. Al pasar a
    # "{n}. {title}" dejaban de casar y la numeración se reiniciaba en 1,
    # sobrescribiendo la serie entera.
    g = FakeDrive(_nombres(10))
    assert g._find_next_number("F", "{n}. {title}") == 11


def test_rellena_el_primer_hueco_libre():
    g = FakeDrive([{"id": "a", "name": "1"}, {"id": "b", "name": "3"}])
    assert g._find_next_number("F", "{n}. {title}") == 2


def test_los_nombres_reservados_cuentan_como_ocupados():
    # Drive todavía no conoce lo que otro hilo está subiendo en este instante.
    g = FakeDrive(_nombres(3))
    assert g._find_next_number("F", "{n}. {title}", extra_used={"4. otro"}) == 5


def test_ignora_nombres_que_no_empiezan_por_numero():
    g = FakeDrive([{"id": "a", "name": "apuntes finales"}])
    assert g._find_next_number("F", "{n}. {title}") == 1


# ── patrón → regex ────────────────────────────────────────────────────────────

def test_el_patron_con_titulo_solo_casa_ese_documento():
    rx = GoogleDocsManager._pattern_to_regex("{n}. {title}", title="apuntes", lang="en")
    assert rx.match("12. apuntes")
    assert not rx.match("12. otro documento")


def test_el_patron_escapa_los_metacaracteres_del_titulo():
    rx = GoogleDocsManager._pattern_to_regex("{n}. {title}", title="a.b(c)")
    assert rx.match("3. a.b(c)")
    assert not rx.match("3. axbXcX")


def test_el_patron_admite_lang():
    rx = GoogleDocsManager._pattern_to_regex("{n}. {title} ({lang})", title="apuntes", lang="fr")
    assert rx.match("7. apuntes (FR)")
    assert not rx.match("7. apuntes (EN)")


# ── resolve_target ────────────────────────────────────────────────────────────

def test_sin_numeracion_el_nombre_es_el_titulo():
    g = FakeDrive([])
    assert g.resolve_target("apuntes", "F", "en") == ("apuntes", None)


def test_aplica_el_patron_completo():
    g = FakeDrive(_nombres(11))
    name, prev = g.resolve_target("apuntes", "F", "en", sequential_naming=True,
                                  sequential_naming_pattern="{n}. {title}")
    assert (name, prev) == ("12. apuntes", None)


def test_replace_existing_devuelve_el_id_a_actualizar():
    # Actualizar en sitio conserva enlace, comentarios e historial de versiones.
    g = FakeDrive([{"id": "docX", "name": "4. apuntes"}])
    name, prev = g.resolve_target("apuntes", "F", "en", sequential_naming=True,
                                  sequential_naming_pattern="{n}. {title}",
                                  replace_existing=True)
    assert (name, prev) == ("4. apuntes", "docX")


def test_replace_existing_crea_cuando_no_hay_nada_que_reemplazar():
    # No hay ningún "{n}. apuntes": se crea uno nuevo en el primer hueco libre.
    g = FakeDrive([{"id": "docX", "name": "4. otro"}])
    name, prev = g.resolve_target("apuntes", "F", "en", sequential_naming=True,
                                  sequential_naming_pattern="{n}. {title}",
                                  replace_existing=True)
    assert (name, prev) == ("1. apuntes", None)


def test_hilos_simultaneos_no_resuelven_el_mismo_numero():
    # El fallo original: tres subidas a la vez leían la carpeta antes de que ninguna
    # hubiera escrito, y las tres se llamaban "12".
    g = FakeDrive(_nombres(11), delay=0.01)
    salida, lock = [], threading.Lock()

    def worker(i):
        name, _ = g.resolve_target(f"doc{i}", "F", "en", sequential_naming=True,
                                   sequential_naming_pattern="{n}. {title}")
        with lock:
            salida.append(name)

    hilos = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for h in hilos: h.start()
    for h in hilos: h.join()

    numeros = sorted(int(n.split(".")[0]) for n in salida)
    assert numeros == [12, 13, 14]


@pytest.mark.xfail(reason="defecto conocido: con organize_by_language=false los idiomas "
                          "comparten carpeta y el patrón por defecto no lleva {lang}, "
                          "así que los cuatro resuelven al mismo documento",
                   strict=True)
def test_idiomas_distintos_no_deben_compartir_documento_en_carpeta_comun():
    g = FakeDrive([{"id": "docA", "name": "1. apuntes"}])
    ids = set()
    for lang in ("EN", "FR", "AR", "ZH"):
        _, prev = g.resolve_target("apuntes", "F", lang, sequential_naming=True,
                                   sequential_naming_pattern="{n}. {title}",
                                   replace_existing=True)
        ids.add(prev)
    assert len(ids) == 4, "cada idioma debería tener su propio documento"
