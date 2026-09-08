import shutil
import questionary
from rich.panel import Panel
from rich.table import Table
from rich import box
from .styles import console, clear_screen, WIZARD_STYLE, BLUE, DIM, FG, GREEN

_MAX_FILES = 8
_MAX_LANGS = 8


def _resumir(langs: list[str]) -> str:
    """Lista de idiomas legible: con muchos, se dice cuantos quedan fuera."""
    if len(langs) <= _MAX_LANGS:
        return "  ".join(langs)
    return "  ".join(langs[:_MAX_LANGS]) + f"  +{len(langs) - _MAX_LANGS}"


def show_confirmation(config: dict) -> bool:
    clear_screen()
    console.print()
    console.print()

    # Con key=14 y value min_width=20 mas el padding, en un terminal estrecho rich
    # estrujaba la columna de valores hasta hacerla desaparecer: se veian las
    # etiquetas sin un solo dato al lado. Y lo que sobrevivia se cortaba a mitad de
    # palabra sin puntos suspensivos, con pinta de texto corrupto.
    table = Table(show_header=False, show_edge=False, box=None, padding=(0, 2))
    table.add_column("key",   style=DIM,  width=10, no_wrap=True)
    # no_wrap: sin el, catorce idiomas se convertian en catorce lineas. Los saltos
    # de linea explicitos de la lista de ficheros se siguen respetando.
    table.add_column("value", style=FG,   overflow="ellipsis", no_wrap=True)

    files = config.get("files") or []
    if len(files) > 1:
        # Con muchas fuentes la lista entera desbordaba el panel a lo alto.
        visibles = files[:_MAX_FILES]
        listado  = "\n".join(visibles)
        if len(files) > _MAX_FILES:
            listado += f"\n… y {len(files) - _MAX_FILES} más"
        table.add_row(f"Files ({len(files)})", listado)
    else:
        table.add_row("File", files[0] if files else config["source"])
    table.add_row("Provider",  config["provider"])
    table.add_row("Languages", _resumir(config["languages"]))
    table.add_row("Output",    config["output"])
    if config.get("format_raw"):
        table.add_row("Raw text", "format with Gemini")

    # El suelo de 40 hacia que el panel se saliera en terminales mas estrechos que eso.
    terminal_width = shutil.get_terminal_size().columns
    panel_width = max(24, min(60, terminal_width - 2))

    console.print(Panel(
        table,
        title=f"[bold {BLUE}]Configuration[/bold {BLUE}]",
        title_align="left",
        border_style=DIM,
        box=box.ROUNDED,
        padding=(1, 2),
        width=panel_width,
    ))

    try:
        proceed = questionary.select(
            "Proceed?",
            choices=["Yes", "No"],
            style=WIZARD_STYLE,
            erase_when_done=True,
        ).ask()
    except KeyboardInterrupt:
        return False

    if proceed == "Yes":
        console.print(f"[{FG}]Proceed?[/{FG}]")
        console.print(f"  [bold {GREEN}]❯ Yes[/bold {GREEN}]")
        console.print(f"  [{DIM}]  No[/{DIM}]\n")
        return True

    return False