import sys
import questionary
from pathlib import Path
from rich.text import Text
from .styles import console, WIZARD_STYLE, LANGUAGES, GREEN, BLUE, DIM, FG, BRIGHT

VERSION = "2.1.0"

def _ask(fn):
    try:
        return fn()
    except KeyboardInterrupt:
        return None

def _print_select(label: str, choices: list[str], selected: str):
    """Print a completed select block — label + all options, selected in green."""
    console.print(f"[{FG}]{label}[/{FG}]")
    for c in choices:
        if c == selected:
            console.print(f"  [bold {GREEN}]❯ {c}[/bold {GREEN}]")
        else:
            console.print(f"  [{DIM}]  {c}[/{DIM}]")
    console.print()

def _print_text(label: str, instruction: str, value: str):
    """Print a completed text field — label + instruction + value in green."""
    console.print(f"[{FG}]{label}[/{FG}]")
    console.print(f"  [{DIM}]{instruction}[/{DIM}]")
    console.print(f"  [bold {GREEN}]❯ {value}[/bold {GREEN}]")
    console.print()

def run_wizard(preselected_source: str = None) -> dict | None:
    console.print(f"\n[bold white]mdtranslator[/bold white] [dim]v{VERSION}[/dim]\n")

    base_dir    = Path(__file__).resolve().parent.parent.parent
    sources_dir = base_dir / "sources"

    # ── 1. Source file ────────────────────────────────────────────────
    source_choices = ["Process ALL files"]
    if sources_dir.exists():
        valid_exts = {".md", ".txt"}
        source_choices.extend(sorted(
            f.name for f in sources_dir.iterdir()
            if f.is_file() and f.suffix.lower() in valid_exts
        ))

    if preselected_source:
        source = Path(preselected_source).name
    else:
        source = _ask(lambda: questionary.select(
            "Select source file",
            choices=source_choices,
            style=WIZARD_STYLE,
            erase_when_done=True,
        ).ask())
        if source is None:
            return None

    _print_select("Select source file", source_choices, source)

    # ── .txt → markdown ───────────────────────────────────────────────
    if source != "Process ALL files" and source.lower().endswith(".txt"):
        source_path = (sources_dir / Path(source).name).resolve()
        if not source_path.exists():
            console.print(f"[red]✗ File not found: {source_path}[/red]")
            return None

        confirm = _ask(lambda: questionary.confirm(
            f"Format {source_path.name} into Markdown with Gemini AI?",
            default=True,
            style=WIZARD_STYLE,
            erase_when_done=True,
        ).ask())
        if confirm is None:
            return None

        if confirm:
            import subprocess
            console.print(f"[{DIM}]Formatting with Gemini AI…[/{DIM}]")
            result = subprocess.run(
                [sys.executable, "-m", "src.integrations.generate_md", str(source_path)],
                cwd=str(base_dir), capture_output=True, text=True,
            )
            if result.returncode == 0:
                source = source_path.with_suffix(".md").name
                console.print(f"[{GREEN}]✓ Formatted → {source}[/{GREEN}]\n")
            else:
                err = result.stderr.strip() or result.stdout.strip()
                console.print(f"[yellow]✗ Formatting failed: {err}[/yellow]\n")

    # ── 2. Provider ───────────────────────────────────────────────────
    provider_choices = ["Azure AI Translator", "DeepL API", "Auto (fallback)"]
    provider = _ask(lambda: questionary.select(
        "Choose translation provider",
        choices=provider_choices,
        style=WIZARD_STYLE,
        erase_when_done=True,
    ).ask())
    if provider is None:
        return None
    _print_select("Choose translation provider", provider_choices, provider)

    # ── 3. Output destination ─────────────────────────────────────────
    output_choices = ["Google Drive", "Local only", "Local + Google Drive"]
    output = _ask(lambda: questionary.select(
        "Output destination",
        choices=output_choices,
        style=WIZARD_STYLE,
        erase_when_done=True,
    ).ask())
    if output is None:
        return None
    _print_select("Output destination", output_choices, output)

    # ── 4. Target languages ───────────────────────────────────────────
    known_line = Text()
    known_line.append("  Known codes:  ", style=DIM)
    known_line.append("  ".join(["EN", "ES", "FR", "DE", "IT", "PT", "ZH", "JA", "KO", "AR"]), style=BRIGHT)
    console.print(known_line)

    more_line = Text()
    more_line.append("  More codes:   ", style=DIM)
    more_line.append("https://www.deepl.com/docs-api/translate-text", style=f"underline {BLUE}")
    console.print(more_line)
    console.print()

    while True:
        langs_raw = _ask(lambda: questionary.text(
            "Target languages",
            instruction="",
            style=WIZARD_STYLE,
            erase_when_done=True,
            validate=lambda v: True if v.strip() else "Enter at least one language code",
        ).ask())
        if langs_raw is None:
            return None

        langs = langs_raw.upper().split()
        unknown = [l for l in langs if l not in LANGUAGES]

        if not unknown:
            _print_text("Target languages", "", langs_raw.upper())
            break

        console.print(f"[yellow]⚠ Unrecognized: {', '.join(unknown)}[/yellow]")
        console.print(f"[{DIM}]  These may still work if the provider supports them (e.g. EN-GB, PT-BR).[/{DIM}]\n")

        proceed = _ask(lambda: questionary.confirm(
            "Proceed anyway?",
            default=False,
            style=WIZARD_STYLE,
            erase_when_done=True,
        ).ask())
        if proceed is None:
            return None
        if proceed:
            _print_text("Target languages", "", langs_raw.upper())
            break
        console.print()

    return {"source": source, "provider": provider, "output": output, "languages": langs}