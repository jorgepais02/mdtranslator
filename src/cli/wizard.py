import questionary
from pathlib import Path
from rich.text import Text
from .styles import console, WIZARD_STYLE, LANGUAGES, GREEN, BLUE, DIM, FG, BRIGHT

from core.sources import ALL_FILES, VALID_EXTS, collect_sources, needs_formatting

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
    source_choices = [ALL_FILES]
    if sources_dir.exists():
        source_choices.extend(sorted(
            f.name for f in sources_dir.iterdir()
            if f.is_file() and f.suffix.lower() in VALID_EXTS
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

    # ── Raw text → Markdown ───────────────────────────────────────────
    # The wizard only asks; the pipeline does the formatting.
    selected = collect_sources(source, sources_dir)
    if not selected:
        console.print(f"[red]✗ No source files found for: {source}[/red]")
        return None

    if source == ALL_FILES:
        listing = Text()
        listing.append(f"  {len(selected)} file(s):  ", style=DIM)
        listing.append("  ".join(p.name for p in selected), style=BRIGHT)
        console.print(listing)
        console.print()

    raw = [p for p in selected if needs_formatting(p)]
    format_raw = False
    if raw:
        names = ", ".join(p.name for p in raw[:3]) + ("…" if len(raw) > 3 else "")
        label = (f"Format {names} into Markdown with Gemini AI?" if len(raw) == 1
                 else f"Format {len(raw)} raw files ({names}) into Markdown with Gemini AI?")
        answer = _ask(lambda: questionary.confirm(
            label,
            default=True,
            style=WIZARD_STYLE,
            erase_when_done=True,
        ).ask())
        if answer is None:
            return None
        format_raw = answer
        console.print(f"[{FG}]{label}[/{FG}]")
        console.print(f"  [bold {GREEN}]❯ {'Yes' if format_raw else 'No'}[/bold {GREEN}]\n")

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

    return {
        "source":     source,
        "provider":   provider,
        "output":     output,
        "languages":  langs,
        "format_raw": format_raw,
        "files":      [p.name for p in selected],
    }