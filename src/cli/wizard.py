import questionary
from pathlib import Path
from .styles import console, WIZARD_STYLE

def run_wizard(preselected_source: str = None) -> dict:
    console.print("[bold]mdtranslator[/bold] [dim]v2.1.0[/dim]\n")

    base_dir = Path(__file__).resolve().parent.parent.parent
    sources_dir = base_dir / "sources"

    # 1. Source file
    if preselected_source:
        source = preselected_source
        console.print(f"[green]?[/green] [bold]Select source file[/bold] [cyan]»[/cyan] {source}")
    else:
        choices = ["Process ALL files"]
        if sources_dir.exists() and sources_dir.is_dir():
            valid_exts = {".md", ".txt"}
            files = [f.name for f in sources_dir.iterdir() if f.is_file() and f.suffix.lower() in valid_exts]
            choices.extend(sorted(files))

        source = questionary.select(
            "Select source file",
            choices=choices,
            style=WIZARD_STYLE,
        ).ask()

    if source != "Process ALL files" and source.lower().endswith(".txt"):
        # Resolve absolute source path
        if sources_dir.exists():
            source_path = (sources_dir / source).resolve()
            if not source_path.exists():
                # Try just the name in case it's already a partial path
                source_path = (sources_dir / Path(source).name).resolve()
        else:
            source_path = Path(source).resolve()

        if not source_path.exists():
            console.print(f"\n[red]ERROR: Source file not found at {source_path}[/red]")
            return None

        console.print(f"\n[yellow]It looks like you selected a raw text file ({source_path.name}).[/yellow]")
        if questionary.confirm("Would you like to use Gemini AI to format it into clean Markdown automatically?", default=True).ask():
            import subprocess
            import sys
            console.print("[dim]Formatting text with Gemini AI...[/dim]")
            
            # Use absolute path for the script
            gen_md_script = (base_dir / "src" / "generate_markdown.py").resolve()
            
            if not gen_md_script.exists():
                console.print(f"[red]ERROR: Internal script not found at {gen_md_script}[/red]")
                return None

            result = subprocess.run(
                [sys.executable, str(gen_md_script), str(source_path)],
                cwd=str(base_dir),
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                # Update source to the newly created .md file
                source = source_path.with_suffix(".md").name
                console.print(f"[green]✓ Successfully formatted. New source file: {source}[/green]\n")
            else:
                console.print(f"[red]❌ Formatting failed.[/red]")
                if result.stderr:
                    console.print(f"[dim]{result.stderr.strip()}[/dim]")
                console.print("[yellow]Continuing with original file...[/yellow]\n")

    # 2. Provider
    choices = ["Azure AI Translator", "DeepL API", "Auto (fallback)"]
    provider = questionary.select(
        "Choose translation provider",
        choices=choices,
        style=WIZARD_STYLE,
    ).ask()
    if provider is None: return None

    # 3. Output destination
    output = questionary.select(
        "Output destination",
        choices=["Google Drive", "Local only", "Local + Google Drive"],
        style=WIZARD_STYLE,
    ).ask()
    if output is None: return None

    # 4. Target languages
    langs_raw = questionary.text(
        "Target languages",
        instruction="(examples: EN FR AR ZH JA KO)",
        style=WIZARD_STYLE,
    ).ask()
    if langs_raw is None: return None

    langs = langs_raw.upper().split()

    return {
        "source": source,
        "provider": provider,
        "output": output,
        "languages": langs,
    }
