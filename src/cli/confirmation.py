"""Ultima pantalla antes de arrancar: lo que va a pasar, y una salida.

API:
    show_confirmation(config) -> "yes" | "no" | "back"
"""

from rich.padding import Padding
from rich.text import Text

from .folder_picker import configured_folder
from .prompts import ask_select
from .styles import (console, clear_screen, marca, summary_grid, aire_superior,
                     CONTEXT, MARGEN, META)

_MAX_FILES = 8
_MAX_LANGS = 8

_SI     = "yes"
_NO     = "no"
_VOLVER = "back"

_OPCIONES = [
    ("Yes, start",       _SI),
    ("Change something…", _VOLVER),
    ("Cancel",           _NO),
]


def _resumir(langs: list[str]) -> str:
    """Lista de idiomas legible: con muchos, se dice cuantos quedan fuera."""
    if len(langs) <= _MAX_LANGS:
        return "  ".join(langs)
    return "  ".join(langs[:_MAX_LANGS]) + f"  +{len(langs) - _MAX_LANGS}"


def _filas(config: dict) -> list[tuple[str, Text]]:
    filas: list[tuple[str, Text]] = []
    files = config.get("files") or []

    if len(files) > 1:
        # Con muchas fuentes la lista entera se comia la pantalla.
        visibles = files[:_MAX_FILES]
        listado = "\n".join(visibles)
        if len(files) > _MAX_FILES:
            listado += f"\n… and {len(files) - _MAX_FILES} more"
        filas.append((f"Files ({len(files)})", Text(listado, style=CONTEXT)))
    else:
        filas.append(("File", Text(files[0] if files else config["source"], style=CONTEXT)))

    filas.append(("Provider", Text(config.get("provider_label") or config["provider"],
                                   style=CONTEXT)))
    filas.append(("Languages", Text(_resumir(config["languages"]), style=CONTEXT)))
    filas.append(("Output", Text(config["output"], style=CONTEXT)))
    # Subir a Drive sin decir adonde era la mitad de la frase: la carpeta es parte del
    # destino, y es justo lo que cambia entre un modulo y el siguiente.
    if "Google Drive" in config["output"]:
        guardada_id, guardada_nombre = configured_folder()
        carpeta = (config.get("drive_folder_name") or guardada_nombre
                   or config.get("drive_folder_id") or guardada_id)
        if carpeta:
            filas.append(("Drive folder", Text(carpeta, style=CONTEXT)))
    if config.get("format_raw"):
        filas.append(("Raw text", Text("format with Gemini", style=CONTEXT)))

    total = Text()
    total.append(f"{len(files) or 1}", style=CONTEXT)
    total.append(" × ", style=META)
    total.append(f"{len(config['languages'])}", style=CONTEXT)
    total.append("  files × languages", style=META)
    filas.append(("Work", total))
    return filas


def show_confirmation(config: dict) -> str:
    """Ensena la configuracion y pregunta. API: 'yes' | 'no' | 'back'."""
    # Un titulo por pantalla: el resumen es el contexto —lo que en el wizard son las
    # migas— y la pregunta es "Ready to run?". Con "Ready to run" arriba y "Proceed?"
    # abajo habia dos titulos discutiendose cual es la pregunta de la pantalla.
    clear_screen()
    for _ in range(aire_superior()):
        console.print()
    console.print(marca())
    console.print()
    console.print(Padding(summary_grid(_filas(config)), (0, 0, 0, len(MARGEN) + 2)))
    console.print()

    respuesta = ask_select("Ready to run?",
                           [{"name": n, "value": v} for n, v in _OPCIONES])
    if respuesta is None:
        return _NO
    return respuesta
