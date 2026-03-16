"""Translate Markdown files to multiple languages via DeepL and generate documents.

Pipeline:
  1. Read .md file(s) from sources/
  2. Translate content to target languages via DeepL API
  3. Copy the original as es.md
  4. Generate DOCX with academic formatting per language
  5. Convert DOCX to PDF via LibreOffice (if available)

Output structure:
  translated/es/es.md + es.docx + es.pdf
  translated/en/en.md + en.docx + en.pdf
  translated/fr/fr.md + fr.docx + fr.pdf
  translated/ar/ar.md + ar.docx + ar.pdf
  translated/zh/zh.md + zh.docx + zh.pdf

Usage:
    python translation_pipeline.py                              # all .md in sources/
    python translation_pipeline.py sources/apuntes.md           # single file
    python translation_pipeline.py sources/apuntes.md --langs EN-GB FR
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from translators import get_translator, TranslationError
from ai_refiner import refine_markdown


from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskID
)

console = Console()

# ═══════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = PROJECT_ROOT / "sources"
TRANSLATED_DIR = PROJECT_ROOT / "translated"
DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()


def load_config() -> dict:
    """Load user config from config.json, falling back to config.example.json."""
    config_path = PROJECT_ROOT / "config.json"
    if not config_path.exists():
        config_path = PROJECT_ROOT / "config.example.json"
    if config_path.exists():
        return json.loads(config_path.read_text(encoding="utf-8"))
    return {"drive": {}, "document": {}}


CONFIG = load_config()

# Default languages if not specified in config
DEFAULT_LANGS = CONFIG.get("document", {}).get("default_languages", ["EN", "FR", "AR", "ZH"])


# ═══════════════════════════════════════════
# Markdown line classification
# ═══════════════════════════════════════════

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
BULLET_RE  = re.compile(r"^(\s*)-\s+(.*\S)\s*$")
NUMBER_RE  = re.compile(r"^(\s*)(\d+)\.\s+(.*\S)\s*$")
HR_RE      = re.compile(r"^\s*---\s*$")

LineInfo = tuple[str, str, str]


def parse_markdown_lines(lines: list[str]) -> list[LineInfo]:
    """Classify each Markdown line and extract translatable text.

    Returns a list of (kind, prefix, text) tuples where:
      - kind:   'blank', 'hr', 'heading', 'bullet', 'number', 'body'
      - prefix: structural prefix (hashes, indentation, number marker)
      - text:   the translatable content (empty for blank/hr)
    """
    parsed: list[LineInfo] = []

    for raw in lines:
        line = raw.rstrip("\n")

        if not line.strip():
            parsed.append(("blank", "", ""))
            continue

        if HR_RE.match(line):
            parsed.append(("hr", "---", ""))
            continue

        m = HEADING_RE.match(line)
        if m:
            parsed.append(("heading", m.group(1), m.group(2)))
            continue

        m = BULLET_RE.match(line)
        if m:
            parsed.append(("bullet", m.group(1), m.group(2)))
            continue

        m = NUMBER_RE.match(line)
        if m:
            prefix = f"{m.group(1)}{m.group(2)}."
            parsed.append(("number", prefix, m.group(3)))
            continue

        parsed.append(("body", "", line.strip()))

    return parsed


def rebuild_markdown_from_translations(
    parsed: list[LineInfo], translated_texts: list[str]
) -> list[str]:
    """Reconstruct the Markdown document using translated texts in order."""
    out: list[str] = []
    t_idx = 0

    for kind, prefix, _original in parsed:
        if kind == "blank":
            out.append("")
        elif kind == "hr":
            out.append("---")
        elif kind == "heading":
            out.append(f"{prefix} {translated_texts[t_idx]}")
            t_idx += 1
        elif kind == "bullet":
            out.append(f"{prefix}- {translated_texts[t_idx]}")
            t_idx += 1
        elif kind == "number":
            out.append(f"{prefix} {translated_texts[t_idx]}")
            t_idx += 1
        elif kind == "body":
            out.append(translated_texts[t_idx])
            t_idx += 1

    return out


# ═══════════════════════════════════════════
# Document generation (DOCX + PDF)
# ═══════════════════════════════════════════

def generate_docx_document(md_file: Path, lang_code: str) -> Path:
    """Generate a DOCX from a translated .md file using document_converter."""
    from document_converter import convert

    docx_file = md_file.with_suffix(".docx")
    
    # We might need to pass header image from config if any
    header_cfg = CONFIG.get("document", {}).get("header_image")
    header_img = Path("public/header.png") if not header_cfg else (PROJECT_ROOT / header_cfg)
    
    convert(md_file, docx_file, lang=lang_code, header=header_img)
    return docx_file


def convert_docx_to_pdf(docx_file: Path) -> None:
    """Convert a DOCX file to PDF using LibreOffice in headless mode.

    If LibreOffice is not installed, prints a warning and skips silently.
    """
    outdir = docx_file.parent

    try:
        result = subprocess.run(
            [
                "soffice",
                "--headless",
                "--convert-to", "pdf",
                "--outdir", str(outdir),
                str(docx_file),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            console.print(f"        [yellow]⚠ PDF conversion failed: {result.stderr.strip()}[/yellow]")
    except FileNotFoundError:
        print(
            "        ⚠ LibreOffice not found — skipping PDF generation. "
            "Install with: brew install --cask libreoffice",
            file=sys.stderr,
        )
    except subprocess.TimeoutExpired:
        print("        ⚠ PDF conversion timed out", file=sys.stderr)


# ═══════════════════════════════════════════
# Pipeline orchestration
# ═══════════════════════════════════════════

def process_source_file(md_path: Path, langs: list[str], translator, use_google: bool = False, no_local: bool = False, folder: str | None = None) -> bool:
    """Translate one .md file and generate DOCX + PDF (local) or upload to Google Docs.

    Output goes to translated/<lang>/<lang>.md, .docx, .pdf
    Returns True if everything succeeded, False if any part failed.
    """
    success = True
    g_manager = None
    if use_google:
        from google_docs_manager import GoogleDocsManager
        try:
            g_manager = GoogleDocsManager()
        except Exception as e:
            print(f"ERROR: Google Docs Auth failed: {e}", file=sys.stderr)
            print("Please ensure credentials.json is present in the project root.", file=sys.stderr)
            sys.exit(1)

    # Resolve Drive destination folder
    folder_id = folder or DRIVE_FOLDER_ID or None

    lines = md_path.read_text(encoding="utf-8").splitlines()
    parsed = parse_markdown_lines(lines)

    # Collect translatable texts
    texts_to_translate = [text for kind, _pfx, text in parsed if text]

    if not texts_to_translate:
        console.print("  [yellow]⚠ No translatable text found.[/yellow]")
        return

    # 1. Handle original Spanish file
    es_folder = TRANSLATED_DIR / "es"
    es_folder.mkdir(parents=True, exist_ok=True)
    es_file = es_folder / "es.md"
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
        transient=False,
    ) as progress:
    
        es_task = progress.add_task(f"[cyan]Processing: {md_path.name} (ES Original)...", total=2 if g_manager else 1)
        
        if not no_local or (no_local and g_manager):
            # We need to process locally to generate DOCX if we have to upload to Drive or if no_local=False
            shutil.copy2(md_path, es_file)
            docx_file = generate_docx_document(es_file, "es")
            if not no_local:
                convert_docx_to_pdf(docx_file)
            progress.update(es_task, advance=1)
        else:
            progress.update(es_task, advance=1)

        if g_manager:
            try:
                target_folder = folder_id
                if CONFIG.get("drive", {}).get("organize_by_language", False):
                    target_folder = g_manager.resolve_language_folder(
                        folder_id, "es", CONFIG.get("drive", {}).get("language_folder_names")
                    )
                
                doc_name = g_manager.resolve_filename(
                    title=md_path.stem, 
                    folder_id=target_folder, 
                    lang="es",
                    sequential_naming=CONFIG.get("drive", {}).get("sequential_naming", False),
                    sequential_naming_pattern=CONFIG.get("drive", {}).get("sequential_naming_pattern")
                )

                # Upload DOCX
                doc_id = g_manager.upload_docx(docx_file, target_folder, filename=doc_name)
                doc_url = g_manager.get_document_url(doc_id)
                if not hasattr(process_source_file, "generated_links"):
                    process_source_file.generated_links = {}
                process_source_file.generated_links["es"] = doc_url
                progress.update(es_task, advance=1, description=f"[green]✓ ES Original uploaded")
            except Exception as e:
                progress.update(es_task, description=f"[red]❌ ES Upload Error: {e}")
                success = False

        # 2. Translate to each target language
        total_langs = len(langs)
        main_task = progress.add_task("[bold magenta]Translating languages...", total=total_langs)

        for idx, lang_code in enumerate(langs, 1):
            short = lang_code.lower().split("-")[0]
            lang_folder_names = CONFIG.get("drive", {}).get("language_folder_names", {})
            lang_display_name = lang_folder_names.get(short.lower(), short).upper()
            
            lang_task = progress.add_task(f"  [cyan]Translating → {lang_display_name} ({short.upper()})", total=3 if g_manager else 2)
            
            try:
                translated = translator.translate(texts_to_translate, lang_code)
                rebuilt = rebuild_markdown_from_translations(parsed, translated)
                progress.update(lang_task, advance=1)
            except Exception as e:
                progress.update(lang_task, description=f"  [red]❌ Translation Error ({short.upper()}): {e}")
                success = False
                continue

        # AI Refinement for specific languages
            needs_refinement = short in ['ar', 'zh', 'ja', 'ko', 'fa', 'he', 'ur']
            if needs_refinement:
                progress.update(lang_task, description=f"  [cyan]Refining {lang_display_name}...")
                try:
                    rebuilt = refine_markdown(rebuilt, lang_code)
                except Exception as e:
                    progress.console.print(f"      [yellow]⚠ Refinement Error: {e} (Using unrefined)[/]")

            # Local output
            lang_folder = TRANSLATED_DIR / short
            lang_folder.mkdir(parents=True, exist_ok=True)
            out_file = lang_folder / f"{short}.md"
            out_file.write_text("\n".join(rebuilt) + "\n", encoding="utf-8")
                    
            if not no_local or (no_local and g_manager):
                try:
                    docx_file = generate_docx_document(out_file, short)
                    if not no_local:
                        convert_docx_to_pdf(docx_file)
                    progress.update(lang_task, advance=1)
                except Exception as e:
                    progress.console.print(f"      [red]❌ Local Export Error ({short}): {e}[/]")
                    success = False
            else:
                progress.update(lang_task, advance=1)

            # Google Docs output
            if g_manager:
                progress.update(lang_task, description=f"  [cyan]☁️ Uploading {lang_display_name}...")
                try:
                    target_folder = folder_id
                    if CONFIG.get("drive", {}).get("organize_by_language", False):
                        target_folder = g_manager.resolve_language_folder(
                            folder_id, short, CONFIG.get("drive", {}).get("language_folder_names")
                        )
                    
                    doc_name = g_manager.resolve_filename(
                        title=md_path.stem, 
                        folder_id=target_folder, 
                        lang=short,
                        sequential_naming=CONFIG.get("drive", {}).get("sequential_naming", False),
                        sequential_naming_pattern=CONFIG.get("drive", {}).get("sequential_naming_pattern")
                    )

                    # Upload DOCX
                    doc_id = g_manager.upload_docx(docx_file, target_folder, filename=doc_name)
                    doc_url = g_manager.get_document_url(doc_id)
                    if not hasattr(process_source_file, "generated_links"):
                        process_source_file.generated_links = {}
                    process_source_file.generated_links[short] = doc_url
                    progress.update(lang_task, advance=1, description=f"  [green]✓ {lang_display_name} completed")
                except Exception as e:
                    progress.update(lang_task, description=f"  [red]❌ Upload Error ({short}): {e}")
                    success = False
            else:
                 progress.update(lang_task, description=f"  [green]✓ {lang_display_name} completed")
            
            # Update main translation total progress
            progress.update(main_task, advance=1)
            
            # Cleanup local files if --cloud-only / no_local is True
            if no_local and lang_folder.exists():
                shutil.rmtree(lang_folder)
                
        # Cleanup for ES original if no_local
        if no_local:
            es_folder = TRANSLATED_DIR / "es"
            if es_folder.exists():
                shutil.rmtree(es_folder)

    return success




# ═══════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Translate Markdown files and generate DOCX + PDF documents."
    )
    ap.add_argument(
        "md",
        type=Path,
        nargs="?",
        default=None,
        help="Markdown source file. If omitted, uses interactive mode.",
    )
    ap.add_argument("-l", "--languages", nargs="+", default=None)
    ap.add_argument("-p", "--provider", default=None)
    ap.add_argument("-d", "--drive", action="store_true", dest="google")
    ap.add_argument("-c", "--cloud-only", action="store_true", dest="no_local")
    ap.add_argument("-v", "--verbose", action="store_true", dest="verbose")
    ap.add_argument("-o", "--output", type=Path, default=None)
    ap.add_argument("-f", "--folder", type=str, default=None)
    args = ap.parse_args()

    import questionary
    from rich.table import Table

    console.print(Panel.fit("[bold cyan]Markdown Translation & Formatting Tool[/bold cyan]", border_style="blue"))

    md_path = args.md
    if not md_path:
        md_files = [f.name for f in SOURCES_DIR.glob("*") if f.suffix in {".md", ".txt"}] + ["* Process ALL files"]
        if not md_files or (len(md_files) == 1 and "*" in md_files[0]):
            console.print("[red]No Markdown or text files found in sources/ directory.[/red]")
            sys.exit(1)
            
        md_choice = questionary.select("Select file to translate:", choices=md_files).ask()
        if not md_choice: sys.exit(0)
        md_path = None if md_choice.startswith("*") else SOURCES_DIR / md_choice

    if md_path and md_path.suffix.lower() == ".txt":
        console.print(f"\n[yellow]It looks like you provided a raw text file ({md_path.name}).[/yellow]")
        if questionary.confirm("Would you like to use Gemini AI to format it into clean Markdown automatically?", default=True).ask():
            import subprocess
            console.print(Panel("Formatting text with Gemini AI...", border_style="blue"))
            result = subprocess.run([sys.executable, str(PROJECT_ROOT / "src/generate_markdown.py"), str(md_path)])
            if result.returncode == 0:
                md_path = md_path.with_suffix(".md")
                console.print(f"[green]✓ Successfully formatted. New source file: {md_path.name}[/green]\n")
            else:
                console.print("[red]❌ Formatting failed. Continuing with original file...[/red]\n")
        else:
            console.print()
    provider = args.provider
    if not provider:
        try:
            from translators import get_available_translators
            avail = get_available_translators()
            choices = [q['name'] for q in avail]
            prov_choice = questionary.select("Choose translation provider (or 'auto'):", choices=choices + ["auto"]).ask()
            if prov_choice and prov_choice != "auto":
                provider = next(q['id'] for q in avail if q['name'] == prov_choice)
            else:
                provider = "auto"
        except Exception:
            provider = "auto"

    provider = provider or "auto"

    # For boolean flags, check if the user explicitly provided them, otherwise ask.
    google = args.google
    no_local = args.no_local
    has_drive_flag = any(f in sys.argv for f in ['-d', '--drive', '-c', '--cloud-only'])
    
    if not has_drive_flag:
        output_choice = questionary.select(
            "Where should the generated documents be stored?",
            choices=["Local Only", "Google Drive Only", "Both Local and Google Drive"],
            default="Both Local and Google Drive"
        ).ask()
        if not output_choice: sys.exit(0)
        google = "Google Drive" in output_choice
        no_local = "Google Drive Only" in output_choice

    langs = args.languages
    if not langs:
        lang_input = questionary.text(
            f"Enter Target Language Codes separated by space (Default: {' '.join(DEFAULT_LANGS)}):"
        ).ask()
        if lang_input is None: sys.exit(0)
        langs = lang_input.strip().split() if lang_input.strip() else DEFAULT_LANGS

    langs = langs or DEFAULT_LANGS

    # Custom output dir
    global TRANSLATED_DIR
    if args.output:
        TRANSLATED_DIR = args.output.expanduser().resolve()

    # Initialize translator
    try:
        translator = get_translator(provider)
    except (TranslationError, ValueError) as e:
        console.print(f"[red]ERROR: {e}[/red]")
        sys.exit(1)

    files = [md_path] if md_path else sorted(SOURCES_DIR.glob("*.md"))

    if not files:
        console.print("[red]No .md files found.[/red]")
        sys.exit(1)

    TRANSLATED_DIR.mkdir(parents=True, exist_ok=True)

    console.print()
    overall_success = True
    
    # Store results for the final summary table
    results_summary = []

    for f_path in files:
        if not f_path.exists():
            console.print(f"[red]ERROR: File not found: {f_path}[/red]")
            overall_success = False
            continue

        if process_source_file(f_path, langs, translator, use_google=google, no_local=no_local, folder=args.folder):
            results_summary.append((f_path.name, langs, "Success"))
        else:
            results_summary.append((f_path.name, langs, "Failed"))
            overall_success = False

    # Summary Table
    console.print()
    table = Table(title="Translation Summary", header_style="bold magenta")
    table.add_column("File", style="cyan")
    table.add_column("Languages", style="green")
    table.add_column("Status", justify="right")
    table.add_column("Drive Links", style="blue")

    links_str = ""
    if getattr(process_source_file, "generated_links", None):
        links_str = "\n".join([f"{lang.upper()}: {link}" for lang, link in process_source_file.generated_links.items()])

    for fname, flangs, status in results_summary:
        status_fmt = f"[green]✓ {status}[/]" if status == "Success" else f"[red]❌ {status}[/]"
        table.add_row(fname, ", ".join(flangs).upper(), status_fmt, links_str)

    console.print(table)

    sys.exit(0 if overall_success else 1)


if __name__ == "__main__":
    main()
