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


class Spinner:
    def __init__(self, message: str):
        self.message = message
        self.spinner = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
        self.running = False
        self.task = None

    def spin(self):
        while self.running:
            sys.stdout.write(f"\r{self.message} {next(self.spinner)}")
            sys.stdout.flush()
            time.sleep(0.1)

    def start(self):
        self.running = True
        self.task = threading.Thread(target=self.spin, daemon=True)
        self.task.start()

    def stop(self, success_msg: str):
        self.running = False
        if self.task is not None:
            self.task.join()
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()
        print(f"{self.message} {success_msg}")

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
    print(f"        DOCX → {docx_file.name}")
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
        if result.returncode == 0:
            pdf_name = docx_file.with_suffix(".pdf").name
            print(f"        PDF  → {pdf_name}")
        else:
            print(f"        ⚠ PDF conversion failed: {result.stderr.strip()}", file=sys.stderr)
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
        print("  ⚠ No translatable text found.")
        return

    # 1. Handle original Spanish file
    es_folder = TRANSLATED_DIR / "es"
    es_folder.mkdir(parents=True, exist_ok=True)
    es_file = es_folder / "es.md"
    
    if not no_local or (no_local and g_manager):
        # We need to process locally to generate DOCX if we have to upload to Drive or if no_local=False
        shutil.copy2(md_path, es_file)
        print(f"  ▸ Processing: {md_path.name} (Original ES) → {es_file.relative_to(PROJECT_ROOT)}")
        docx_file = generate_docx_document(es_file, "es")
        if not no_local:
            convert_docx_to_pdf(docx_file)
    else:
        print(f"  ▸ Processing: {md_path.name} (Original ES)")

    if g_manager:
        spinner = Spinner("      ☁️  Uploading to Google Drive...")
        spinner.start()
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
            spinner.stop("✓")
        except Exception as e:
            spinner.stop("❌")
            print(f"      Error: {e}")
            success = False

    # 2. Translate to each target language
    total_langs = len(langs)
    for idx, lang_code in enumerate(langs, 1):
        short = lang_code.lower().split("-")[0]
        lang_folder_names = CONFIG.get("drive", {}).get("language_folder_names", {})
        lang_display_name = lang_folder_names.get(short.lower(), short).upper()
        
        spinner = Spinner(f"  [{idx}/{total_langs}] Translating → {lang_display_name} ({short.upper()})…")
        spinner.start()
        try:
            translated = translator.translate(texts_to_translate, lang_code)
            rebuilt = rebuild_markdown_from_translations(parsed, translated)
            spinner.stop("✓")
        except Exception as e:
            spinner.stop("❌")
            print(f"      Error: {e}")
            success = False
            continue

        # AI Refinement for specific languages
        needs_refinement = short in ['ar', 'zh', 'ja', 'ko', 'fa', 'he', 'ur']
        if needs_refinement:
            spinner = Spinner(f"  [{idx}/{total_langs}] Refining {lang_display_name} translation with Gemini…")
            spinner.start()
            try:
                rebuilt = refine_markdown(rebuilt, lang_code)
                spinner.stop("✓")
            except Exception as e:
                spinner.stop("❌")
                print(f"      Refinement Error: {e} (Using unrefined text)")

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
            except Exception as e:
                print(f"      Local Export Error ({short}): {e}")
                success = False

        # Google Docs output
        if g_manager:
            spinner = Spinner("      ☁️  Uploading to Google Drive...")
            spinner.start()
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
                spinner.stop("✓")
            except Exception as e:
                spinner.stop("❌")
                print(f"      Error: {e}")
                success = False
        
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
        help="Markdown source file. If omitted, processes all .md in sources/.",
    )
    ap.add_argument(
        "-l", "--languages", "--langs",
        nargs="+",
        default=DEFAULT_LANGS,
        dest="langs",
        help=f"Target language codes, e.g. EN-GB FR AR ZH (default: {' '.join(DEFAULT_LANGS)})",
    )
    ap.add_argument(
        "-p", "--provider", "--api",
        default="auto",
        help="Translation provider to prioritize. 'auto' tries all configured providers in default order. (default: auto)",
    )
    ap.add_argument(
        "-d", "--drive", "--google",
        action="store_true",
        dest="google",
        help="Upload translated documents to Google Drive",
    )
    ap.add_argument(
        "-c", "--cloud-only", "--no-local",
        action="store_true",
        dest="no_local",
        help="Skip local DOCX/PDF retention. Deletes generated temporary files (use with --drive)",
    )
    ap.add_argument(
        "-v", "--verbose",
        action="store_true",
        dest="verbose",
        help="Enable verbose mode for debugging output.",
    )
    ap.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Custom output directory (default: translated/)",
    )
    ap.add_argument(
        "-f", "--folder",
        type=str,
        default=None,
        help="Target Google Drive Folder ID (overrides .env GOOGLE_DRIVE_FOLDER_ID)",
    )
    args = ap.parse_args()

    # Custom output dir
    global TRANSLATED_DIR
    if args.output:
        TRANSLATED_DIR = args.output.expanduser().resolve()

    # Initialize translator
    try:
        translator = get_translator(args.provider)
    except (TranslationError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Determine which files to process
    if args.md:
        files = [args.md.expanduser().resolve()]
    else:
        files = sorted(SOURCES_DIR.glob("*.md"))

    if not files:
        print("No .md files found in sources/", file=sys.stderr)
        sys.exit(1)

    TRANSLATED_DIR.mkdir(parents=True, exist_ok=True)

    overall_success = True
    for md_path in files:
        if not md_path.exists():
            print(f"ERROR: File not found: {md_path}", file=sys.stderr)
            overall_success = False
            continue

        print(f"\n{'='*60}")
        print(f"  File: {md_path.name}")
        print(f"{'='*60}")
        if not process_source_file(md_path, args.langs, translator, use_google=args.google, no_local=args.no_local, folder=args.folder):
            overall_success = False

    if args.no_local and args.google:
        msg = "Documents uploaded to Google Drive."
    elif args.no_local and not args.google:
        msg = "Markdown strings translated."
    else:
        msg = f"Output saved in: {TRANSLATED_DIR}"
        
    if overall_success:
        print(f"\n✓ Pipeline complete. {msg}")
    else:
        print(f"\n⚠ Pipeline finished with some errors. {msg}")

    if getattr(process_source_file, "generated_links", None):
        print("\nGoogle Docs Links:")
        for lang, link in process_source_file.generated_links.items():
            lang_label = lang.upper()
            print(f"  [·] {lang_label}: {link}")

    sys.exit(0 if overall_success else 1)


if __name__ == "__main__":
    main()
