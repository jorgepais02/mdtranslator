from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.console import Group
from rich import box
from .styles import console

def show_results(results: list[dict], total_time: float, version: str = "2.1.0"):
    parts = []

    # Results table
    parts.append(Text("Results", style="bold blue"))

    file_table = Table(show_edge=True, border_style="dim", padding=(0, 1), box=box.ROUNDED)
    file_table.add_column("Lang", style="cyan", width=6)
    file_table.add_column("File", style="white")
    file_table.add_column("Status", width=8)
    file_table.add_column("Time", style="dim", justify="right", width=8)

    for r in results:
        status = Text("✓", style="green") if r["ok"] else Text("✗", style="red")
        file_table.add_row(r["lang"], r["file"], status, f"{r['time']:.1f}s")

    parts.append(file_table)
    parts.append(Text())  # spacer

    # Google Docs table (if applies)
    if any(r.get("gdocs_url") for r in results):
        parts.append(Text("Google Docs", style="bold blue"))

        gdocs_table = Table(show_edge=True, border_style="dim", padding=(0, 1), box=box.ROUNDED)
        gdocs_table.add_column("Lang", style="cyan", width=6)
        gdocs_table.add_column("URL", style="blue underline")

        for r in results:
            if r.get("gdocs_url"):
                gdocs_table.add_row(r["lang"], r["gdocs_url"])

        parts.append(gdocs_table)
        parts.append(Text())  # spacer

    # Footer
    footer = Text()
    failed = any(not r["ok"] for r in results)
    
    if failed:
        success_count = sum(1 for r in results if r["ok"])
        total = len(results)
        footer.append(f"⚠ Completed with errors ({success_count}/{total} succeeded) in {total_time:.1f}s", style="bold yellow")
    else:
        footer.append(f"✓ Completed in {total_time:.1f}s", style="bold green")
    
    parts.append(footer)

    version_text = Text(f"mdtranslator v{version}", style="dim", justify="right")
    parts.append(version_text)

    console.print(Group(*parts))
