"""Ultima pantalla antes de arrancar: lo mismo que el resumen del wizard, y una salida.

API:
    show_confirmation(config) -> "yes" | "no" | "back"
"""

from rich.text import Text

from .prompts import ask_select
from .styles import (console, clear_screen, summary_grid, BRIGHT, CYAN, DIM, FG)

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
        filas.append((f"Files ({len(files)})", Text(listado, style=BRIGHT)))
    else:
        filas.append(("File", Text(files[0] if files else config["source"], style=BRIGHT)))

    filas.append(("Provider", Text(config.get("provider_label") or config["provider"],
                                   style=BRIGHT)))
    filas.append(("Languages", Text(_resumir(config["languages"]), style=CYAN)))
    filas.append(("Output", Text(config["output"], style=BRIGHT)))
    if config.get("format_raw"):
        filas.append(("Raw text", Text("format with Gemini", style=BRIGHT)))

    total = Text()
    total.append(f"{len(files) or 1}", style=BRIGHT)
    total.append(" × ", style=DIM)
    total.append(f"{len(config['languages'])}", style=BRIGHT)
    total.append("  files × languages", style=DIM)
    filas.append(("Work", total))
    return filas


def show_confirmation(config: dict) -> str:
    """Ensena la configuracion y pregunta. API: 'yes' | 'no' | 'back'."""
    clear_screen()
    console.print()
    console.print(f"[{FG}]Ready to run[/{FG}]")
    console.print()
    console.print(summary_grid(_filas(config)))
    console.print()

    respuesta = ask_select("Proceed?",
                           [{"name": n, "value": v} for n, v in _OPCIONES])
    if respuesta is None:
        return _NO
    return respuesta
