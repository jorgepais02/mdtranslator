import questionary
from rich.panel import Panel
from rich.table import Table
from .styles import console, WIZARD_STYLE

def show_confirmation(config: dict) -> bool:
    # Config table (no borders, key-value)
    table = Table(show_header=False, show_edge=False, box=None, padding=(0, 2))
    table.add_column("key", style="dim", width=12)
    table.add_column("value", style="white")

    table.add_row("File", config["source"])
    table.add_row("Provider", config["provider"])
    table.add_row("Languages", "  ".join(config["languages"]))
    table.add_row("Output", config["output"])

    panel = Panel(
        table,
        title="[bold blue]Configuration[/bold blue]",
        title_align="left",
        border_style="dim",
        padding=(1, 2),
    )
    console.print(panel)

    proceed = questionary.select(
        "Proceed?",
        choices=["Yes", "No"],
        style=WIZARD_STYLE,
    ).ask()

    return proceed == "Yes"
