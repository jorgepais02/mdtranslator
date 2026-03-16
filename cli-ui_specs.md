# mdtranslator CLI — Especificación Técnica de UI/UX

> Spec para implementar con Python + Rich + Questionary.  
> Última actualización: 2026-03-12

---

## Dependencias

```toml
[project.dependencies]
rich = ">=13.7"
questionary = ">=2.0"
```

Componentes Rich utilizados:
- `Console`, `Live`, `Panel`, `Table`, `Text`, `Progress`, `Columns`, `Group`

---

## Arquitectura de la UI

```
┌─────────────────────────────────────────┐
│            InteractiveWizard            │  ← questionary prompts
├─────────────────────────────────────────┤
│          ConfirmationSummary            │  ← Rich Panel + questionary confirm
├─────────────────────────────────────────┤
│           PipelineView                  │  ← Rich Live (zero-scroll)
├─────────────────────────────────────────┤
│            ResultsView                  │  ← Rich Table + Panel
└─────────────────────────────────────────┘
```

Flujo secuencial. Cada etapa reemplaza a la anterior en la terminal.
NO es un dashboard full-screen. Es output secuencial compacto.

---

## Stage 1 — Interactive Wizard

### Comportamiento
Prompts secuenciales con `questionary`. Cada pregunta aparece después de responder la anterior.

### Implementación

```python
import questionary
from rich.console import Console

console = Console()

def run_wizard() -> dict:
    console.print("[bold]mdtranslator[/bold] [dim]v2.1.0[/dim]\n")

    # 1. Source file
    source = questionary.select(
        "Select source file",
        choices=["Process ALL files", "apuntes.md", "resumen.md"],
        style=questionary.Style([
            ("selected", "fg:green bold"),
            ("pointer", "fg:green bold"),
            ("highlighted", "fg:green"),
            ("question", "fg:white bold"),
        ]),
    ).ask()

    # 2. Provider
    provider = questionary.select(
        "Choose translation provider",
        choices=["Azure AI Translator", "DeepL API", "Auto (fallback)"],
    ).ask()

    # 3. Output destination
    output = questionary.select(
        "Output destination",
        choices=["Google Drive", "Local only", "Local + Google Drive"],
    ).ask()

    # 4. Target languages
    langs_raw = questionary.text(
        "Target languages",
        instruction="(examples: EN FR AR ZH JA KO)",
    ).ask()

    langs = langs_raw.upper().split()

    return {
        "source": source,
        "provider": provider,
        "output": output,
        "languages": langs,
    }
```

### Estilo visual esperado
```
$ mdtranslator translate

mdtranslator v2.1.0

Select source file
    Process ALL files
  ❯ apuntes.md
    resumen.md

Choose translation provider
  ❯ Azure AI Translator
    DeepL API
    Auto (fallback)

Output destination
  ❯ Google Drive
    Local only
    Local + Google Drive

Target languages
  > ZH AR
    (examples: EN FR AR ZH JA KO)
```

### Questionary Style Config
```python
WIZARD_STYLE = questionary.Style([
    ("qmark", "fg:blue bold"),
    ("question", "fg:white bold"),
    ("answer", "fg:green bold"),
    ("pointer", "fg:green bold"),         # ❯
    ("highlighted", "fg:green"),           # opción seleccionada
    ("selected", "fg:green bold"),
    ("instruction", "fg:#666666 italic"),  # hints dim
])
```

---

## Stage 2 — Confirmation Summary

### Comportamiento
Panel con la configuración seleccionada + prompt Yes/No.

### Implementación

```python
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

def show_confirmation(config: dict) -> bool:
    # Config table (sin bordes, key-value)
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
```

### Output esperado
```
╭─ Configuration ─────────────────────────╮
│                                         │
│   File        sources/apuntes.md        │
│   Provider    Azure AI Translator       │
│   Languages   ZH  AR                    │
│   Output      Google Drive              │
│                                         │
╰─────────────────────────────────────────╯

Proceed?
  ❯ Yes
    No
```

---

## Stage 3 — Pipeline View (Rich Live)

### Comportamiento
- Usa `Rich Live` para actualizar in-place (zero-scroll)
- Muestra: lectura del source, traducción por idioma, progreso global
- Cada idioma tiene su propio estado y tiempo

### Estados por idioma
| Estado | Color | Texto |
|--------|-------|-------|
| waiting | `dim` | `waiting` |
| translating | `yellow` | `translating…` |
| refining | `yellow` | `refining…` |
| done | `green` | `✓ generated` |
| error | `red` | `✗ failed` |

### Implementación

```python
from rich.live import Live
from rich.table import Table
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn
from rich.console import Group
from rich.text import Text
from rich.panel import Panel
import time

class PipelineView:
    def __init__(self, languages: list[str]):
        self.languages = languages
        self.lang_status: dict[str, dict] = {
            lang: {"status": "waiting", "time": None} for lang in languages
        }
        self.source_done = False
        self.source_time = None
        self.overall_progress = 0

    def set_source_done(self, elapsed: float):
        self.source_done = True
        self.source_time = elapsed

    def set_lang_status(self, lang: str, status: str, elapsed: float | None = None):
        self.lang_status[lang] = {"status": status, "time": elapsed}

    def set_progress(self, pct: int):
        self.overall_progress = pct

    def render(self) -> Group:
        parts = []

        # Command echo
        parts.append(Text(
            f"$ mdtranslator translate apuntes.md --lang {' '.join(self.languages)}",
            style="dim",
        ))
        parts.append(Text())  # spacer

        # Section: Pipeline
        parts.append(Text("Pipeline", style="bold blue"))

        # Source reading
        if self.source_done:
            bar_text = "█" * 40 + " ✓"
            style = "green"
        else:
            bar_text = "█" * 15 + "░" * 25
            style = "green"

        source_line = Text()
        source_line.append("Reading source ", style="white")
        if self.source_time:
            source_line.append(f"{self.source_time:.1f}s", style="dim")
        parts.append(source_line)
        parts.append(Text(bar_text, style=style))
        parts.append(Text())  # spacer

        # Translation status
        parts.append(Text("Translating", style="white"))

        # Overall bar
        filled = int((self.overall_progress / 100) * 40)
        bar = "█" * filled + "░" * (40 - filled)
        parts.append(Text(bar, style="blue"))

        # Per-language status
        for lang, info in self.lang_status.items():
            line = Text("  ")
            line.append(f"{lang:>3} ", style="cyan")

            status = info["status"]
            if status.startswith("✓"):
                line.append(status, style="green")
            elif status in ("translating…", "refining…"):
                line.append(status, style="yellow")
            elif status.startswith("✗"):
                line.append(status, style="red")
            else:
                line.append(status, style="dim")

            if info["time"]:
                line.append(f"  {info['time']:.1f}s", style="dim")

            parts.append(line)

        parts.append(Text())  # spacer

        # Progress summary
        progress_line = Text()
        progress_line.append("Progress ", style="white")
        prog_filled = self.overall_progress // 10
        progress_line.append("██" * prog_filled, style="blue")
        progress_line.append("░░" * (10 - prog_filled), style="dim")
        progress_line.append(f" {self.overall_progress}%", style="bold white")
        parts.append(progress_line)

        return Group(*parts)
```

### Uso con Rich Live

```python
def run_pipeline(config: dict):
    languages = config["languages"]
    view = PipelineView(languages)

    with Live(view.render(), console=console, refresh_per_second=8) as live:
        # Step 1: Read source
        time.sleep(0.3)
        view.set_source_done(0.3)
        view.set_progress(20)
        live.update(view.render())

        # Step 2: Translate each language
        total = len(languages)
        for i, lang in enumerate(languages):
            view.set_lang_status(lang, "translating…")
            view.set_progress(20 + int((i / total) * 60))
            live.update(view.render())

            # ... actual translation call ...
            elapsed = translate(config["source"], lang, config["provider"])

            # Optional: refinement for AR, ZH, JA, KO
            if lang in ("AR", "ZH", "JA", "KO"):
                view.set_lang_status(lang, "refining…")
                live.update(view.render())
                elapsed += refine(lang)

            view.set_lang_status(lang, "✓ generated", elapsed)
            view.set_progress(20 + int(((i + 1) / total) * 60))
            live.update(view.render())

        # Step 3: Generate files
        view.set_progress(90)
        live.update(view.render())
        # ... generate DOCX ...

        # Step 4: Upload (optional)
        view.set_progress(100)
        live.update(view.render())

    return results
```

### Output esperado (in-place, no scroll)
```
$ mdtranslator translate apuntes.md --lang ZH AR

Pipeline

Reading source 0.3s
█████████████████████████████████████████ ✓

Translating
████████████████████████░░░░░░░░░░░░░░░░ 

   ZH ✓ generated  1.4s
   AR translating…

Progress ████████████████░░░░ 65%
```

---

## Stage 4 — Results View

### Comportamiento
Dos tablas Rich: resultados de archivos + links de Google Docs.
Footer con tiempo total y versión.

### Implementación

```python
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.console import Group

def show_results(results: list[dict], total_time: float, version: str = "2.1.0"):
    parts = []

    # Results table
    parts.append(Text("Results", style="bold blue"))

    file_table = Table(show_edge=True, border_style="dim", padding=(0, 1))
    file_table.add_column("Lang", style="cyan", width=6)
    file_table.add_column("File", style="white")
    file_table.add_column("Status", width=8)
    file_table.add_column("Time", style="dim", justify="right", width=8)

    for r in results:
        status = Text("✓", style="green") if r["ok"] else Text("✗", style="red")
        file_table.add_row(r["lang"], r["file"], status, f"{r['time']:.1f}s")

    parts.append(file_table)
    parts.append(Text())  # spacer

    # Google Docs table (si aplica)
    if any(r.get("gdocs_url") for r in results):
        parts.append(Text("Google Docs", style="bold blue"))

        gdocs_table = Table(show_edge=True, border_style="dim", padding=(0, 1))
        gdocs_table.add_column("Lang", style="cyan", width=6)
        gdocs_table.add_column("URL", style="blue underline")

        for r in results:
            if r.get("gdocs_url"):
                gdocs_table.add_row(r["lang"], r["gdocs_url"])

        parts.append(gdocs_table)
        parts.append(Text())  # spacer

    # Footer
    footer = Text()
    footer.append(f"✓ Completed in {total_time:.1f}s", style="bold green")
    parts.append(footer)

    version_text = Text(f"mdtranslator v{version}", style="dim", justify="right")
    parts.append(version_text)

    console.print(Group(*parts))
```

### Output esperado
```
Results
┌──────┬─────────┬────────┬────────┐
│ Lang │ File    │ Status │   Time │
├──────┼─────────┼────────┼────────┤
│ ZH   │ zh.docx │ ✓      │  1.4s  │
│ AR   │ ar.docx │ ✓      │  2.1s  │
└──────┴─────────┴────────┴────────┘

Google Docs
┌──────┬──────────────────────────────┐
│ Lang │ URL                          │
├──────┼──────────────────────────────┤
│ ZH   │ docs.google.com/d/1a2b3c...  │
│ AR   │ docs.google.com/d/4d5e6f...  │
└──────┴──────────────────────────────┘

✓ Completed in 4.2s
                          mdtranslator v2.1.0
```

---

## Stage 5 — Error States

### Tipos de error

| Error | Comportamiento |
|-------|---------------|
| File not found | Abort con `console.print("[red]✗ File not found: {path}[/red]")` + exit code 2 |
| API timeout | Marcar idioma como `✗ timeout`, continuar con los demás |
| API auth error | Abort: `"✗ Authentication failed for {provider}"` + exit code 2 |
| Partial failure | Mostrar resultados parciales + exit code 1 |
| Upload failed | Warning amarillo, archivos locales disponibles |

### Implementación de error por idioma

```python
try:
    elapsed = translate(source, lang, provider)
    view.set_lang_status(lang, "✓ generated", elapsed)
except TimeoutError:
    view.set_lang_status(lang, "✗ timeout")
except APIError as e:
    view.set_lang_status(lang, f"✗ {e.short_msg}")
```

### Output de error parcial
```
Results
┌──────┬─────────┬──────────┬────────┐
│ Lang │ File    │ Status   │   Time │
├──────┼─────────┼──────────┼────────┤
│ ZH   │ zh.docx │ ✓        │  1.4s  │
│ AR   │ —       │ ✗ timeout│  —     │
└──────┴─────────┴──────────┴────────┘

⚠ Completed with errors (1/2 succeeded) in 6.8s
```

---

## CLI Flags

```
mdtranslator translate [OPTIONS] [FILE]

Options:
  --lang TEXT        Target language codes (space-separated)
  --provider TEXT    Translation provider: azure|deepl|auto
  --output TEXT      Output: local|gdrive|both
  --yes, -y          Skip confirmation prompt
  --json             Machine-readable JSON output
  --verbose, -v      Show debug logs
  --version          Show version
```

### --yes flag
```python
if not args.yes:
    if not show_confirmation(config):
        console.print("[dim]Aborted.[/dim]")
        sys.exit(0)
```

### --json flag
```python
if args.json:
    import json
    print(json.dumps({
        "status": "success",
        "files": [{"lang": "ZH", "path": "zh.docx", "time": 1.4}],
        "total_time": 4.2,
    }))
    sys.exit(0)
```

---

## Exit Codes

| Code | Significado |
|------|-------------|
| 0 | Éxito total |
| 1 | Éxito parcial (algunos idiomas fallaron) |
| 2 | Error fatal (auth, file not found, config inválida) |

---

## Paleta de Colores (Rich styles)

| Uso | Rich Style | Hex aprox |
|-----|-----------|-----------|
| Texto normal | `white` | #d9d9d9 |
| Dim/secundario | `dim` | #666666 |
| Éxito | `green` | #50c878 |
| Warning/progreso | `yellow` | #e6a817 |
| Info/headers | `bold blue` | #4da6ff |
| Idiomas | `cyan` | #40bfbf |
| Error | `red` | #cc4444 |
| Bright/énfasis | `bold white` | #ebebeb |
| Links | `blue underline` | #4da6ff |

---

## Estructura de Archivos Sugerida

```
src/
├── cli/
│   ├── __init__.py
│   ├── main.py              # Entry point, argparse/click
│   ├── wizard.py            # Stage 1: questionary prompts
│   ├── confirmation.py      # Stage 2: Rich Panel summary
│   ├── pipeline.py          # Stage 3: Rich Live pipeline
│   ├── results.py           # Stage 4: Rich Tables output
│   ├── errors.py            # Stage 5: error handling
│   └── styles.py            # questionary Style + Rich theme
```

---

## Flujo Principal

```python
# main.py
def main():
    args = parse_args()
    console.print(f"[dim]$ mdtranslator translate[/dim]\n")

    # Stage 1
    config = run_wizard() if not args.lang else build_config_from_args(args)

    # Stage 2
    if not args.yes:
        if not show_confirmation(config):
            console.print("[dim]Aborted.[/dim]")
            sys.exit(0)

    # Stage 3
    start = time.monotonic()
    results = run_pipeline(config)
    total_time = time.monotonic() - start

    # Stage 4
    if args.json:
        print_json_results(results, total_time)
    else:
        show_results(results, total_time)

    # Exit code
    failed = sum(1 for r in results if not r["ok"])
    sys.exit(0 if failed == 0 else 1)
```

---

## Notas de Implementación

1. **Rich Live refresh**: `refresh_per_second=8` es suficiente. Más alto no aporta.
2. **Questionary style**: Aplicar el mismo `Style` a todos los prompts para consistencia.
3. **time.monotonic()**: Usar siempre para medir tiempos (no `time.time()`).
4. **Panel border**: `border_style="dim"` para que no compita con el contenido.
5. **Table box**: `box=rich.box.ROUNDED` para las tablas de resultados, `box=None` para el config summary.
6. **Encoding**: `console = Console(force_terminal=True)` si hay problemas con Unicode en Windows.
