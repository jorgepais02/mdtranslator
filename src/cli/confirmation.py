import shutil
import questionary
from rich.panel import Panel
from rich.table import Table
from rich import box
from .styles import console, clear_screen, WIZARD_STYLE, BLUE, DIM, FG, GREEN

def show_confirmation(config: dict) -> bool:
    clear_screen()
    console.print()
    console.print()

    table = Table(show_header=False, show_edge=False, box=None, padding=(0, 3))
    table.add_column("key",   style=DIM,  width=14)
    table.add_column("value", style=FG,   min_width=20)

    files = config.get("files") or []
    if len(files) > 1:
        table.add_row(f"Files ({len(files)})", "\n".join(files))
    else:
        table.add_row("File", files[0] if files else config["source"])
    table.add_row("Provider",  config["provider"])
    table.add_row("Languages", "  ".join(config["languages"]))
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