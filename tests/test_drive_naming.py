"""Numeración y resolución de nombres en Drive, sin tocar la red.

FakeDrive sustituye las dos únicas llamadas de red que usa la lógica de nombres.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

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


@pytest.fixture(autouse=True)
def _estado_limpio():
    # Reservas, locks y listados cacheados son de clase: sin limpiarlos un test
    # contamina al siguiente, igual que una ejecución contaminaría a la siguiente.
    GoogleDocsManager.reset_run_state()
    yield
    GoogleDocsManager.reset_run_state()


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


# ── carpeta compartida entre idiomas ──────────────────────────────────────────

def test_en_carpeta_comun_cada_idioma_tiene_su_documento():
    # Sin desambiguar, los cuatro idiomas resolvían al mismo id y se sobrescribían:
    # cuatro traducciones y un solo documento en Drive, ganando el último hilo.
    g = FakeDrive([{"id": "docA", "name": "1. apuntes (EN)"}])
    nombres = []
    for lang in ("EN", "FR", "AR", "ZH"):
        name, _ = g.resolve_target("apuntes", "F", lang, sequential_naming=True,
                                   sequential_naming_pattern="{n}. {title}",
                                   replace_existing=True, disambiguate_lang=True)
        nombres.append(name)
    assert len(set(nombres)) == 4
    assert nombres[0] == "1. apuntes (EN)"          # el que ya existía se reemplaza
    assert all(l in n for n, l in zip(nombres, ("EN", "FR", "AR", "ZH")))


def test_con_carpeta_por_idioma_el_nombre_no_cambia():
    # organize_by_language=true: cada idioma ya está aislado, nada que desambiguar.
    g = FakeDrive(_nombres(11))
    name, _ = g.resolve_target("apuntes", "F", "fr", sequential_naming=True,
                               sequential_naming_pattern="{n}. {title}",
                               disambiguate_lang=False)
    assert name == "12. apuntes"


def test_un_patron_que_ya_lleva_lang_no_se_toca():
    assert GoogleDocsManager._effective_pattern("{n}. {title} [{lang}]", True) == \
        "{n}. {title} [{lang}]"


def test_sin_numeracion_el_idioma_tambien_desambigua():
    g = FakeDrive([])
    assert g.resolve_target("apuntes", "F", "fr", disambiguate_lang=True) == \
        ("apuntes (FR)", None)


def test_en_carpeta_comun_los_numeros_no_se_repiten():
    g = FakeDrive([])
    nombres = [g.resolve_target("apuntes", "F", l, sequential_naming=True,
                                sequential_naming_pattern="{n}. {title}",
                                disambiguate_lang=True)[0]
               for l in ("EN", "FR", "AR")]
    assert [n.split(".")[0] for n in nombres] == ["1", "2", "3"]


# ── un listado por carpeta y por ejecución ────────────────────────────────────

def test_la_carpeta_se_lista_una_sola_vez():
    # Eran dos llamadas de red por documento: una para buscar el que se reemplaza y
    # otra para calcular el número.
    g = FakeDrive(_nombres(5))
    for i in range(10):
        g.resolve_target(f"doc{i}", "F", "en", sequential_naming=True,
                         sequential_naming_pattern="{n}. {title}",
                         replace_existing=True)
    assert g.listados == 1


def test_cada_carpeta_se_lista_por_separado():
    g = FakeDrive(_nombres(5))
    for carpeta in ("F1", "F2", "F3"):
        g.resolve_target("apuntes", carpeta, "en", sequential_naming=True,
                         sequential_naming_pattern="{n}. {title}")
    assert g.listados == 3


def test_el_cache_no_sobrevive_a_la_ejecucion():
    g = FakeDrive(_nombres(5))
    g.resolve_target("a", "F", "en", sequential_naming=True,
                     sequential_naming_pattern="{n}. {title}")
    GoogleDocsManager.reset_run_state()
    g.resolve_target("b", "F", "en", sequential_naming=True,
                     sequential_naming_pattern="{n}. {title}")
    assert g.listados == 2


def test_carpetas_distintas_no_se_bloquean_entre_si():
    # Con un lock global, resolver en cuatro carpetas costaba cuatro latencias en fila.
    g = FakeDrive(_nombres(3), delay=0.20)
    t = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(lambda i: g.resolve_target(f"doc{i}", f"F{i}", "en",
                                               sequential_naming=True,
                                               sequential_naming_pattern="{n}. {title}"),
                    range(4)))
    assert time.monotonic() - t < 0.20 * 4 * 0.75


def test_el_documento_reemplazado_es_siempre_el_mismo_con_titulos_duplicados():
    # Drive no garantiza el orden del listado: sin ordenar, cada pasada podía
    # reemplazar un documento distinto.
    carpeta = [{"id": "b", "name": "7. apuntes"}, {"id": "a", "name": "3. apuntes"}]
    elegidos = set()
    for _ in range(3):
        GoogleDocsManager.reset_run_state()
        carpeta.reverse()
        _, prev = FakeDrive(carpeta).resolve_target(
            "apuntes", "F", "en", sequential_naming=True,
            sequential_naming_pattern="{n}. {title}", replace_existing=True)
        elegidos.add(prev)
    assert elegidos == {"a"}


# ── credenciales compartidas entre hilos ──────────────────────────────────────

class CredsFalsas:
    def __init__(self, restante_segundos, refresh_token="rt"):
        import datetime
        self.expiry = datetime.datetime.utcnow() + datetime.timedelta(seconds=restante_segundos)
        self.refresh_token = refresh_token
        self.refrescos = 0

    def refresh(self, request):
        self.refrescos += 1


class DriveConCreds(FakeDrive):
    def __init__(self, creds, token_path):
        super().__init__([])
        self.creds = creds
        self.token_path = str(token_path)


def test_un_token_con_margen_no_se_toca(tmp_path):
    creds = CredsFalsas(restante_segundos=3600)
    assert DriveConCreds(creds, tmp_path / "t.json").ensure_fresh_credentials() is False
    assert creds.refrescos == 0


def test_un_token_a_punto_de_caducar_se_renueva_antes_del_pool(tmp_path):
    # Si caduca a mitad, los cuatro hilos lo refrescan a la vez sobre el mismo objeto.
    creds = CredsFalsas(restante_segundos=60)
    token = tmp_path / "t.json"
    assert DriveConCreds(creds, token).ensure_fresh_credentials() is True
    assert creds.refrescos == 1
    assert token.exists()


def test_sin_refresh_token_no_se_intenta(tmp_path):
    creds = CredsFalsas(restante_segundos=10, refresh_token=None)
    assert DriveConCreds(creds, tmp_path / "t.json").ensure_fresh_credentials() is False
    assert creds.refrescos == 0


def test_dos_tareas_no_reemplazan_el_mismo_documento():
    # EN y EN-GB caen en la misma carpeta con el mismo título: si las dos reclaman el
    # mismo id, la segunda sobrescribe a la primera y una traducción se pierde.
    g = FakeDrive([{"id": "docA", "name": "1. apuntes"}])
    resultados = [
        g.resolve_target("apuntes", "F", lang, sequential_naming=True,
                         sequential_naming_pattern="{n}. {title}", replace_existing=True)
        for lang in ("en", "en-gb")
    ]
    assert resultados[0] == ("1. apuntes", "docA")
    assert resultados[1][1] is None            # la segunda crea uno nuevo
    assert resultados[1][0] == "2. apuntes"


def test_lo_reclamado_se_olvida_entre_ejecuciones():
    carpeta = [{"id": "docA", "name": "1. apuntes"}]
    for _ in range(3):
        GoogleDocsManager.reset_run_state()
        _, prev = FakeDrive(carpeta).resolve_target(
            "apuntes", "F", "en", sequential_naming=True,
            sequential_naming_pattern="{n}. {title}", replace_existing=True)
        assert prev == "docA"
