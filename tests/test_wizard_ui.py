"""Wizard y selector de carpetas: lo que se le pasa a questionary y lo que queda en pantalla."""

import io
from pathlib import Path

import pytest
import questionary
from rich.console import Console

from cli import folder_picker, wizard
from cli.prompts import BACK
from cli.styles import elide

LARGO = "transcripcion-clase-magistral-seguridad-informatica-2026-tema-4.md"


@pytest.fixture
def a_ancho(monkeypatch):
    def _set(ancho, modulo=wizard):
        c = Console(file=io.StringIO(), width=ancho, force_terminal=False, no_color=True)
        monkeypatch.setattr(modulo, "console", c)
        return c
    return _set


# ── opciones que se le pasan a questionary ────────────────────────────────────

def test_los_nombres_cortos_van_tal_cual(a_ancho):
    a_ancho(80)
    assert wizard._opciones(["apuntes.md", "tema02.txt"]) == ["apuntes.md", "tema02.txt"]


def test_los_nombres_largos_se_recortan(a_ancho):
    a_ancho(40)
    opcion = wizard._opciones([LARGO])[0]
    assert opcion.title.endswith("…")
    assert len(opcion.title) <= 40 - 6


def test_el_valor_de_la_opcion_es_el_nombre_real(a_ancho):
    # Si se recortara el valor, collect_sources no encontraría el fichero.
    a_ancho(40)
    assert wizard._opciones([LARGO])[0].value == LARGO


def test_lo_que_cabe_no_se_recorta_aunque_sea_largo(a_ancho):
    a_ancho(120)
    assert wizard._opciones([LARGO]) == [LARGO]


# ── las migas de lo ya contestado ─────────────────────────────────────────────

def _estado(**extra):
    base = {"source": "apuntes.md", "provider": "Auto (fallback)",
            "output": "Local only", "languages": ["EN", "FR", "AR"],
            "files": ["apuntes.md"]}
    base.update(extra)
    return base


@pytest.mark.parametrize("ancho", [40, 60, 80, 120])
def test_las_migas_caben(a_ancho, ancho):
    c = a_ancho(ancho)
    c.print(wizard._migas(_estado(source=LARGO, files=[LARGO])))
    assert all(len(l.rstrip()) <= ancho for l in c.file.getvalue().splitlines())


def test_las_migas_son_una_sola_linea(a_ancho):
    # Antes cada pregunta dejaba sus opciones enteras en pantalla; luego fue una
    # rejilla de una fila por respuesta. Cinco filas encima de la pregunta viva pesan
    # tanto como ella: el contexto va en un renglón.
    c = a_ancho(80)
    c.print(wizard._migas(_estado()))
    assert len([l for l in c.file.getvalue().splitlines() if l.strip()]) == 1


def test_sin_nada_contestado_no_hay_migas():
    assert wizard._migas({}) is None


def test_las_migas_solo_ensenan_lo_ya_contestado(a_ancho):
    c = a_ancho(80)
    c.print(wizard._migas({"source": "apuntes.md", "files": ["apuntes.md"]}))
    texto = c.file.getvalue()
    assert "apuntes.md" in texto and "Auto" not in texto


def test_las_migas_van_en_los_dos_tonos_del_contexto():
    # Un color, un rol: el dato en CONTEXT y los signos que lo separan en META. El
    # cian de "esto es un idioma" no entra — está a dos pasos del azul de la marca y
    # en la misma pantalla los dos dejaban de significar cosas distintas.
    from cli.styles import CONTEXT, META
    assert {s.style for s in wizard._migas(_estado()).spans} == {CONTEXT, META}


def test_el_verde_ya_no_marca_la_respuesta():
    # El verde significaba a la vez "elegido" y "salió bien": en cuanto la pantalla
    # se llenaba de verde, el ✓ del final dejaba de destacar.
    from cli.styles import GREEN
    assert all(s.style != GREEN for s in wizard._migas(_estado()).spans)


def test_con_todos_los_ficheros_se_dice_cuantos_son(a_ancho):
    from core.sources import ALL_FILES
    c = a_ancho(80)
    c.print(wizard._migas(_estado(source=ALL_FILES, files=["a.md", "b.md"])))
    assert "all 2 files" in c.file.getvalue()


# ── la cabecera y la lista de una pregunta ────────────────────────────────────

def test_el_aire_entre_opciones_es_una_linea_vacia_de_verdad():
    # Separator("") devuelve "---------------": `line or default` y la cadena vacía
    # es falsa. Las tres listas cortas del wizard habrían salido con una fila de
    # guiones entre cada opción.
    from cli import prompts
    huecos = [c for c in prompts._desplegar(["a", "b", "c"])[0]
              if isinstance(c, questionary.Separator)]
    assert huecos and all(not h.title.strip() for h in huecos)


def test_una_lista_larga_va_apretada():
    # Dieciocho idiomas con una línea en blanco entre cada uno son treinta y seis
    # renglones: no cabe en ninguna ventana.
    from cli import prompts
    largo = [f"op{i}" for i in range(18)]
    assert len(prompts._desplegar(largo)[0]) == len(largo)


def test_el_subtitulo_lo_pintamos_nosotros():
    # questionary sabe enseñar `description`, pero al pie de la lista, con un
    # "Description:" delante y encendido siempre. Se le quita y se guarda aparte.
    from cli import prompts
    op = questionary.Choice(title="Auto (fallback)", value="auto",
                            description="use whichever is configured")
    opciones, subtitulos, _ = prompts._desplegar([op, "DeepL API"])
    assert op.description is None
    assert subtitulos == {0: "use whichever is configured"}


def test_el_subtitulo_no_reserva_sitio_en_la_lista():
    # En estado normal la separación entre opciones es siempre la misma; el subtítulo
    # se inserta al señalar su opción y se quita al salir. Si reservara un hueco fijo,
    # una lista apretada tendría un renglón vacío inexplicable debajo de esa opción.
    from cli import prompts
    largo = [f"op{i}" for i in range(18)]
    largo[3] = questionary.Choice(title="op3", value="op3", description="algo")
    opciones, subtitulos, aire = prompts._desplegar(largo)
    assert len(opciones) == len(largo) and not aire
    assert subtitulos == {3: "algo"}


@pytest.mark.parametrize("ancho", [40, 60, 80, 200])
def test_el_filete_nunca_desborda(a_ancho, ancho):
    from cli import prompts
    a_ancho(ancho, modulo=prompts)
    assert len(prompts._regla()) <= max(ancho, 32) - 2


def test_el_filete_tiene_tope(a_ancho):
    # Una raya de doscientas columnas sobre una lista de cuatro palabras ya no cierra
    # la pregunta: subraya la pantalla entera.
    from cli import prompts
    a_ancho(200, modulo=prompts)
    assert len(prompts._regla()) == prompts._REGLA_MAX


def test_la_pista_se_cae_antes_que_empujar_al_titulo(a_ancho):
    from cli import prompts
    c = a_ancho(34, modulo=prompts)
    prompts._cabecera("Choose translation provider", "space toggle · ⌫ back")
    assert "space toggle" not in c.file.getvalue()


# ── la nota de cobertura de la multiselección ─────────────────────────────────

def test_sin_problema_de_cobertura_no_se_dice_nada():
    # Los dieciocho códigos están cubiertos por DeepL y por Azure: la lista va limpia.
    assert wizard._nota_cobertura("EN", ["deepl", "azure"]) == ""


def test_si_solo_uno_lo_traduce_se_dice_cual(monkeypatch):
    from translators import registry
    monkeypatch.setattr(registry.AVAILABLE_TRANSLATORS["deepl"][1], "supported", frozenset({"EN"}))
    nota = wizard._nota_cobertura("AR", ["deepl", "azure"])
    assert nota.startswith("· only") and "Azure" in nota


def test_si_no_lo_traduce_nadie_se_avisa(monkeypatch):
    from translators import registry
    for pid in ("deepl", "azure"):
        monkeypatch.setattr(registry.AVAILABLE_TRANSLATORS[pid][1], "supported", frozenset({"EN"}))
    assert "no configured provider" in wizard._nota_cobertura("AR", ["deepl", "azure"])


# ── la máquina de pasos ───────────────────────────────────────────────────────

@pytest.fixture
def wizard_falso(monkeypatch, a_ancho):
    """Sustituye las preguntas por un guion, para poder comprobar el ir y venir."""
    a_ancho(80)
    monkeypatch.setattr(wizard, "clear_screen", lambda: None)
    monkeypatch.setattr(wizard, "collect_sources", lambda *a, **k: [Path("apuntes.md")])
    monkeypatch.setattr(wizard, "needs_formatting", lambda p: False)

    def _correr(guion):
        preguntas = []

        def _siguiente(etiqueta):
            preguntas.append(etiqueta)
            return guion.pop(0)

        monkeypatch.setattr(wizard, "ask_select",
                            lambda label, *a, **k: _siguiente(label))
        monkeypatch.setattr(wizard, "ask_checkbox",
                            lambda label, *a, **k: _siguiente(label))
        monkeypatch.setattr(wizard, "ask_confirm",
                            lambda label, *a, **k: _siguiente(label))
        return wizard.run_wizard("apuntes.md"), preguntas
    return _correr


def test_un_recorrido_recto_devuelve_la_config(wizard_falso):
    config, preguntas = wizard_falso(["auto", "Local only", ["EN", "FR"]])
    assert config["provider"] == "auto"
    assert config["languages"] == ["EN", "FR"]
    assert len(preguntas) == 3


def test_el_retroceso_vuelve_a_preguntar_la_anterior(wizard_falso):
    # ⌫ en "Output" tiene que devolverte a "Provider", no cancelar el wizard.
    config, preguntas = wizard_falso(
        ["auto", BACK, "deepl", "Local only", ["EN"]])
    assert preguntas[1].startswith("Output")
    assert preguntas[2].startswith("Choose translation provider")
    assert config["provider"] == "deepl"


def test_retroceder_en_la_primera_pregunta_no_cancela(wizard_falso):
    # No hay nada detrás: se vuelve a preguntar lo mismo en vez de salir.
    config, _ = wizard_falso([BACK, "auto", "Local only", ["EN"]])
    assert config is not None


def test_un_ctrl_c_cancela(wizard_falso):
    config, _ = wizard_falso(["auto", None])
    assert config is None


def test_lo_ya_contestado_vuelve_puesto(monkeypatch, a_ancho):
    # Al volver desde la confirmación, confirmar cada pregunta debe ser un Enter.
    a_ancho(80)
    monkeypatch.setattr(wizard, "clear_screen", lambda: None)
    monkeypatch.setattr(wizard, "collect_sources", lambda *a, **k: [Path("apuntes.md")])
    monkeypatch.setattr(wizard, "needs_formatting", lambda p: False)
    defaults = []
    guion = ["deepl", "Local only", ["EN"]]
    monkeypatch.setattr(wizard, "ask_select",
                        lambda label, choices, default=None, **k:
                        defaults.append(default) or guion.pop(0))
    monkeypatch.setattr(wizard, "ask_checkbox", lambda *a, **k: guion.pop(0))
    wizard.run_wizard("apuntes.md", previo={"provider": "azure", "output": "Google Drive",
                                            "languages": ["FR"], "source": "apuntes.md"})
    assert defaults[0] == "azure" and defaults[1] == "Google Drive"


# ── la carpeta de Drive ───────────────────────────────────────────────────────

@pytest.fixture
def drive_falso(monkeypatch):
    """La carpeta guardada es M18, y nadie habla con Drive. Devuelve lo que se crea."""
    monkeypatch.setattr(wizard, "configured_folder", lambda: ("id18", "M18"))
    monkeypatch.setattr(wizard, "pick_drive_folder", lambda: ("id-otra", "Otra carpeta"))
    creadas = []

    def _crear(nombre, hermana_de):
        creadas.append((nombre, hermana_de))
        return f"id-{nombre}", nombre

    monkeypatch.setattr(wizard, "create_folder_next_to", _crear)
    return creadas


def test_sin_drive_no_se_pregunta_la_carpeta(wizard_falso, drive_falso):
    # Es una pregunta sobre el destino: sin destino en Drive no tiene sentido.
    config, preguntas = wizard_falso(["auto", "Local only", ["EN"]])
    assert not any(p.startswith("Drive folder") for p in preguntas)
    assert config["drive_folder_id"] == ""


def test_con_drive_se_pregunta_la_carpeta(wizard_falso, drive_falso):
    config, preguntas = wizard_falso(["auto", "Google Drive", wizard._MISMA, ["EN"]])
    assert preguntas[1].startswith("Output") and preguntas[2].startswith("Drive folder")
    assert (config["drive_folder_id"], config["drive_folder_name"]) == ("id18", "M18")


def test_la_de_siempre_es_lo_primero_y_viene_puesta(monkeypatch, a_ancho, drive_falso):
    # Lo normal es seguir en la misma carpeta: confirmar tiene que ser un Enter.
    a_ancho(80)
    monkeypatch.setattr(wizard, "clear_screen", lambda: None)
    estado = {"output": "Google Drive"}
    visto = {}
    monkeypatch.setattr(wizard, "ask_select",
                        lambda label, choices, default=None, **k:
                        visto.update(default=default, titulo=choices[0].title) or default)

    wizard._paso_drive(estado, volver=True)

    assert visto["default"] == wizard._MISMA
    assert visto["titulo"].startswith("M18")
    assert estado["drive_folder"] == "M18"


def test_crear_una_carpeta_la_pone_al_lado_de_la_anterior(monkeypatch, wizard_falso, drive_falso):
    # M19 va donde esta M18, no dentro: dentro de M18 estan las carpetas de idioma.
    monkeypatch.setattr(wizard, "ask_text", lambda label, **k: "M19")
    config, _ = wizard_falso(["auto", "Google Drive", wizard._NUEVA, ["EN"]])
    assert drive_falso == [("M19", "id18")]
    assert (config["drive_folder_id"], config["drive_folder_name"]) == ("id-M19", "M19")


def test_el_nombre_nuevo_viene_propuesto(monkeypatch, wizard_falso, drive_falso):
    propuestos = []

    def _texto(label, default="", **k):
        propuestos.append(default)
        return "M19"

    monkeypatch.setattr(wizard, "ask_text", _texto)
    wizard_falso(["auto", "Google Drive", wizard._NUEVA, ["EN"]])
    assert propuestos == ["M19"]


def test_cancelar_el_selector_no_cancela_el_wizard(monkeypatch, wizard_falso, drive_falso):
    # Volver del selector con las manos vacias devuelve a la pregunta, no a la terminal.
    monkeypatch.setattr(wizard, "pick_drive_folder", lambda: None)
    config, preguntas = wizard_falso(
        ["auto", "Google Drive", wizard._ELEGIR, wizard._MISMA, ["EN"]])
    assert config is not None and config["drive_folder_id"] == "id18"
    assert sum(1 for p in preguntas if p.startswith("Drive folder")) == 2


def test_la_carpeta_sale_en_las_migas(a_ancho):
    a_ancho(80)
    migas = wizard._migas(_estado(output="Google Drive", drive_folder="M19"))
    assert "Google Drive · M19" in migas.plain


# ── selector de carpetas ──────────────────────────────────────────────────────

def test_extraer_el_id_sigue_funcionando_con_nombres_largos():
    assert folder_picker.extract_folder_id("1AbCdEfGhIjKlMnOpQrStUvWxYz012345") is not None


def test_el_selector_no_usa_emoji():
    # 📁 ocupa dos celdas y ✓ una: los nombres nunca quedaban alineados entre sí.
    fuente = Path(folder_picker.__file__).read_text(encoding="utf-8")
    linea_opciones = [l for l in fuente.splitlines() if l.startswith("_USE") or l.startswith("_PASTE")]
    assert linea_opciones and not any("📁" in l or "🔗" in l for l in linea_opciones)


@pytest.mark.parametrize("n,esperado", [(0, "0 subcarpetas"), (1, "1 subcarpeta"), (4, "4 subcarpetas")])
def test_los_plurales_estan_bien(n, esperado):
    assert folder_picker._plural(n, "subcarpeta", "subcarpetas") == esperado


def test_elide_es_el_mismo_helper_en_todas_las_vistas():
    from cli import pipeline
    assert pipeline._elide is elide


@pytest.mark.parametrize("ancho,cabe", [(40, 32), (80, 72), (120, 112)])
def test_el_recorte_respeta_el_ancho(ancho, cabe):
    assert len(elide("x" * 200, cabe)) == cabe
