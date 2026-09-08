"""Configuracion interactiva. Solo recoge datos; el pipeline hace el trabajo.

El wizard es una maquina de pasos, no una lista de preguntas seguidas: cada pregunta
puede devolver BACK y entonces se retrocede uno y se vuelve a desplegar con la
respuesta anterior ya puesta. Por eso repinta la pantalla entera en cada paso —lo ya
contestado se colapsa a una linea de resumen— en vez de ir dejando ecos debajo.

API:
    run_wizard(preselected_source=None) -> dict | None
"""

import questionary
from pathlib import Path
from rich.table import Table
from rich.text import Text

from .prompts import BACK, ask_checkbox, ask_confirm, ask_select, ask_text
from .styles import (console, clear_screen, elide, LANGUAGES, BRIGHT, CYAN, DIM,
                     FG, YELLOW)

from core.sources import ALL_FILES, VALID_EXTS, collect_sources, needs_formatting
from translators.registry import AVAILABLE_TRANSLATORS, supported_by

VERSION = "2.1.0"

# El paso no aplica en esta ejecucion (no hay texto crudo, o el fichero venia dado).
SKIP = object()

_AUTO      = "auto"
_AUTO_NAME = "Auto (fallback)"
_OTRO      = "__otro__"


def _ancho() -> int:
    return max(32, console.width)


def _opciones(nombres: list[str]) -> list:
    """Opciones para questionary con el titulo recortado y el valor intacto.

    questionary envuelve las opciones largas en dos lineas y la seleccion deja de
    leerse. Recortando solo el titulo, collect_sources sigue recibiendo el nombre real.
    """
    cabe = _ancho() - 6
    return [nombre if len(nombre) <= cabe
            else questionary.Choice(title=elide(nombre, cabe), value=nombre)
            for nombre in nombres]


# ── el resumen de lo ya contestado ────────────────────────────────────────────

_ETIQUETAS = (("source",    "File"),
              ("format",    "Raw text"),
              ("provider",  "Provider"),
              ("output",    "Output"),
              ("languages", "Languages"))


def _valor(clave: str, estado: dict) -> Text:
    """Como se lee una respuesta ya dada. Blanco el dato, cian solo los idiomas."""
    v = estado[clave]
    if clave == "languages":
        return Text("  ".join(v), style=CYAN)
    if clave == "format":
        return Text("format with Gemini" if v else "leave as is", style=BRIGHT)
    if clave == "source" and v == ALL_FILES:
        ficheros = estado.get("files") or []
        t = Text(f"all {len(ficheros)} files", style=BRIGHT)
        if ficheros:
            t.append("  " + "  ".join(ficheros), style=DIM)
        return t
    return Text(str(v), style=BRIGHT)


def _resumen(estado: dict) -> Table:
    """Una linea por pregunta contestada: etiqueta en gris, respuesta en blanco.

    Antes cada pregunta dejaba en pantalla sus opciones enteras, la elegida en verde
    y las descartadas en gris. Cuatro preguntas eran veinte lineas de opciones que ya
    no significaban nada, y el verde competia con el verde de "salio bien".
    """
    tabla = Table.grid(padding=(0, 2))
    tabla.add_column(style=DIM, width=10, no_wrap=True)
    tabla.add_column(overflow="ellipsis", no_wrap=True)
    for clave, etiqueta in _ETIQUETAS:
        if clave in estado:
            tabla.add_row(etiqueta, _valor(clave, estado))
    return tabla


def _pintar(estado: dict) -> None:
    clear_screen()
    console.print(f"\n[bold white]mdtranslator[/bold white] [{DIM}]v{VERSION}[/{DIM}]\n")
    if any(c in estado for c, _ in _ETIQUETAS):
        console.print(_resumen(estado))
        console.print()


def _aviso(texto: str) -> None:
    console.print(f"[{YELLOW}]⚠ {texto}[/{YELLOW}]")


# ── los pasos ─────────────────────────────────────────────────────────────────

def _paso_source(estado: dict, volver: bool):
    if estado.get("_preselected"):
        estado["source"] = Path(estado["_preselected"]).name
        estado["files"] = [p.name for p in estado["_selected"]]
        return SKIP

    estado.pop("source", None)
    estado.pop("files", None)
    _pintar(estado)

    opciones = [ALL_FILES]
    if estado["_dir"].exists():
        opciones.extend(sorted(f.name for f in estado["_dir"].iterdir()
                               if f.is_file() and f.suffix.lower() in VALID_EXTS))

    r = ask_select("Select source file", _opciones(opciones),
                   default=estado.get("_ultimo_source"), back=volver)
    if r is None or r is BACK:
        return r

    seleccion = collect_sources(r, estado["_dir"])
    if not seleccion:
        _aviso(f"No source files found for: {r}")
        return BACK if volver else SKIP

    estado["source"] = estado["_ultimo_source"] = r
    estado["_selected"] = seleccion
    estado["files"] = [p.name for p in seleccion]
    return True


def _paso_format(estado: dict, volver: bool):
    crudos = [p for p in estado["_selected"] if needs_formatting(p)]
    if not crudos:
        estado.pop("format", None)
        return SKIP

    estado.pop("format", None)
    _pintar(estado)
    if len(crudos) == 1:
        label = f"Format {elide(crudos[0].name, max(16, _ancho() - 40))} with Gemini AI?"
    else:
        label = f"Format {len(crudos)} raw files with Gemini AI?"

    r = ask_confirm(label, default=True, back=volver)
    if r is None or r is BACK:
        return r
    estado["format"] = r
    return True


def _paso_provider(estado: dict, volver: bool):
    estado.pop("provider", None)
    _pintar(estado)

    # La lista sale del registro, no de una constante paralela: anadir un proveedor
    # era tocar tres sitios y olvidarse de uno (Gemini estaba registrado y no
    # aparecia aqui). Los que no tienen clave se ven, en gris y sin poder elegirse:
    # es mas util saber que existen que fingir que no.
    opciones = [questionary.Choice(title=f"{_AUTO_NAME:<22}"
                                        "use whichever is configured", value=_AUTO)]
    for pid, (nombre, cls) in AVAILABLE_TRANSLATORS.items():
        try:
            cls()
            opciones.append(questionary.Choice(title=nombre, value=pid))
        except Exception:
            opciones.append(questionary.Choice(title=nombre, value=pid,
                                               disabled="no API key in .env"))

    r = ask_select("Choose translation provider", opciones,
                   default=estado.get("_ultimo_provider"), back=volver)
    if r is None or r is BACK:
        return r
    estado["_provider_id"] = estado["_ultimo_provider"] = r
    estado["provider"] = _AUTO_NAME if r == _AUTO else AVAILABLE_TRANSLATORS[r][0]
    return True


def _paso_output(estado: dict, volver: bool):
    estado.pop("output", None)
    _pintar(estado)
    opciones = ["Google Drive", "Local only", "Local + Google Drive"]
    r = ask_select("Output destination", opciones,
                   default=estado.get("_ultimo_output"), back=volver)
    if r is None or r is BACK:
        return r
    estado["output"] = estado["_ultimo_output"] = r
    return True


def _nota_cobertura(code: str, proveedores: list[str]) -> str:
    """Que decir al lado de un idioma que no todos los proveedores traducen.

    Se calla cuando no hay nada que decir, que es el caso normal: los dieciocho
    codigos de la lista estan cubiertos por DeepL y por Azure. Solo habla cuando la
    eleccion de proveedor deja ese idioma cojo, para no ensuciar la lista entera con
    una anotacion que siempre dice lo mismo.
    """
    cubren = supported_by(code, proveedores)
    if len(cubren) == len(proveedores):
        return ""
    if not cubren:
        return "· no configured provider translates this"
    return "· only " + ", ".join(AVAILABLE_TRANSLATORS[p][0].split()[0] for p in cubren)


def _paso_languages(estado: dict, volver: bool):
    estado.pop("languages", None)
    _pintar(estado)

    proveedores = ([p for p in AVAILABLE_TRANSLATORS if _configurado(p)]
                   if estado.get("_provider_id", _AUTO) == _AUTO
                   else [estado["_provider_id"]])
    ya = set(estado.get("_ultimo_langs") or [])

    opciones = []
    for code, info in LANGUAGES.items():
        nota = _nota_cobertura(code, proveedores)
        titulo = f"{code:<4}{info['name']:<12}{nota}".rstrip()
        opciones.append(questionary.Choice(title=titulo, value=code, checked=code in ya))
    opciones.append(questionary.Choice(title="Other code…  (EN-GB, PT-BR, …)",
                                       value=_OTRO, checked=False))

    r = ask_checkbox("Target languages", opciones, back=volver)
    if r is None or r is BACK:
        return r

    langs = [c for c in r if c != _OTRO]
    if _OTRO in r:
        extra = ask_text("Extra codes, space separated", back=True)
        if extra is None:
            return None
        if extra is not BACK:
            langs += [c for c in extra.upper().split() if c not in langs]

    if not langs:
        _aviso("Pick at least one language.")
        return _paso_languages(estado, volver)

    estado["languages"] = estado["_ultimo_langs"] = langs
    return True


def _configurado(pid: str) -> bool:
    try:
        AVAILABLE_TRANSLATORS[pid][1]()
        return True
    except Exception:
        return False


_PASOS = (_paso_source, _paso_format, _paso_provider, _paso_output, _paso_languages)


def run_wizard(preselected_source: str = None, previo: dict | None = None) -> dict | None:
    """Recorre los pasos hasta el final. Devuelve la config, o None si se cancela.

    `previo` es la config de una pasada anterior: al volver desde la confirmacion con
    "Change something…" cada pregunta se despliega con lo que ya habias contestado
    puesto, y confirmar es un Enter.
    """
    base_dir = Path(__file__).resolve().parent.parent.parent
    estado: dict = {"_dir": base_dir / "sources", "_preselected": preselected_source}
    if previo:
        estado["_ultimo_source"]   = previo.get("source")
        estado["_ultimo_provider"] = previo.get("provider")
        estado["_ultimo_output"]   = previo.get("output")
        estado["_ultimo_langs"]    = previo.get("languages")

    if preselected_source:
        seleccion = collect_sources(Path(preselected_source).name, estado["_dir"])
        if not seleccion:
            console.print(f"[red]✗ No source files found for: {preselected_source}[/red]")
            return None
        estado["_selected"] = seleccion

    i, direccion = 0, 1
    while i < len(_PASOS):
        r = _PASOS[i](estado, volver=i > 0)
        if r is None:
            return None
        if r is SKIP:
            i += direccion
            if i < 0:
                i, direccion = 0, 1
            continue
        if r is BACK:
            direccion = -1
            i -= 1
            if i < 0:
                i, direccion = 0, 1
            continue
        direccion = 1
        i += 1

    _pintar(estado)
    return {
        "source":      estado["source"],
        "provider":       estado["_provider_id"],
        "provider_label": estado["provider"],
        "output":      estado["output"],
        "languages":   estado["languages"],
        "format_raw":  estado.get("format", False),
        "files":       estado["files"],
    }
