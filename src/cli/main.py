import argparse
import contextlib
import sys
import time
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env", override=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from .wizard import run_wizard
from .confirmation import show_confirmation
from .pipeline import run_pipeline
from .results import show_results
from .styles import LANGUAGES
from .styles import console, clear_screen
from .folder_picker import run_set_folder, pick_drive_folder, save_folder_id
from core.sources import ALL_FILES, collect_sources
from core.config import DRIVE_FOLDER_ID

VERSION = "2.1.0"

_OUTPUT_MAP = {
    "local": "Local only",
    "drive": "Google Drive",
    "both":  "Local + Google Drive",
}

def parse_args():
    parser = argparse.ArgumentParser(description="mdtranslator CLI")
    parser.add_argument("file",        nargs="?", default=None)
    parser.add_argument("--lang",      nargs="+",  default=None, metavar="LANG")
    parser.add_argument("--provider",  default=None, choices=["azure", "deepl", "auto"])
    parser.add_argument("--output",    default=None, choices=list(_OUTPUT_MAP))
    parser.add_argument("--all",       action="store_true",
                        help="process every file in sources/")
    parser.add_argument("--no-format", action="store_true",
                        help="skip Gemini formatting of raw text sources")
    parser.add_argument("--source-lang", default=None, metavar="LANG",
                        help="source language of the documents (skips auto-detection)")
    parser.add_argument("--set-folder", action="store_true",
                        help="pick the Google Drive destination folder and save it")
    parser.add_argument("--yes", "-y", action="store_true")
    parser.add_argument("--json",      action="store_true")
    parser.add_argument("--version",   action="version", version=f"mdtranslator {VERSION}")
    return parser.parse_args()

def build_config_from_args(args) -> dict:
    langs = [l.upper() for l in args.lang] if args.lang else ["EN"]
    unknown = [l for l in langs if l not in LANGUAGES]
    if unknown:
        print(f"warning: unrecognized language code(s): {', '.join(unknown)}", file=sys.stderr)
    if args.file:
        source = args.file
    elif args.all:
        source = ALL_FILES
    else:
        print("error: no source given — pass a file path or --all", file=sys.stderr)
        sys.exit(2)

    files = collect_sources(source)
    if not files:
        print(f"error: no files found for: {source}", file=sys.stderr)
        sys.exit(2)

    return {
        "source":     source,
        "provider":   args.provider or "auto",
        "output":     _OUTPUT_MAP.get(args.output or "", "Local only"),
        "languages":  langs,
        "format_raw": not args.no_format,
        "source_lang": args.source_lang,
        "files":      [p.name for p in files],
    }

def print_json_results(results: list[dict], total_time: float):
    failed = sum(1 for r in results if not r["ok"])
    print(json.dumps({
        "status":     "success" if not failed else "partial_success",
        "files":      results,
        "total_time": total_time,
    }))

def _abort():
    clear_screen()
    console.print(f"\n[dim]Cancelled.[/dim]\n")
    sys.exit(0)

def main():
    args = parse_args()
    try:
        _run(args)
    except KeyboardInterrupt:
        _abort()

_PROVIDER_MAP = {"Azure AI Translator": "azure", "DeepL API": "deepl", "Auto (fallback)": "auto"}

def _ensure_drive_folder(config, interactive: bool) -> None:
    """Drive necesita una carpeta destino: si no hay ninguna configurada, preguntarla."""
    if "Google Drive" not in config["output"] or DRIVE_FOLDER_ID:
        return
    if not interactive:
        print("error: no Drive folder configured — run with --set-folder first", file=sys.stderr)
        sys.exit(2)
    console.print("\n[yellow]No hay ninguna carpeta de Drive configurada.[/yellow]")
    folder_id = pick_drive_folder()
    if not folder_id:
        _abort()
    save_folder_id(folder_id)
    # CONFIG ya está cargado en memoria: el pipeline lee su propia copia del ID.
    from . import pipeline as _pipeline
    _pipeline.DRIVE_FOLDER_ID = folder_id
    _pipeline.CONFIG.setdefault("drive", {})["folder_id"] = folder_id


def _run(args):
    if args.set_folder:
        sys.exit(run_set_folder())

    # Stage 1 — Wizard (prints its own header, no clear needed)
    if args.json or args.lang or args.all:
        config = build_config_from_args(args)
    else:
        config = run_wizard(args.file)

    if config is None:
        _abort()

    config["provider"] = _PROVIDER_MAP.get(config["provider"], config["provider"])
    _ensure_drive_folder(config, interactive=not (args.json or args.yes))

    # Stage 2 — Confirmation
    # "Change something…" reabre el wizard con lo ya contestado puesto, en vez de
    # obligar a cancelar y empezar de cero por un idioma mal elegido.
    if not args.yes and not args.json:
        while True:
            respuesta = show_confirmation(config)
            if respuesta == "yes":
                break
            if respuesta != "back":
                _abort()
            nueva = run_wizard(args.file, previo=config)
            if nueva is None:
                _abort()
            config = nueva
            config["provider"] = _PROVIDER_MAP.get(config["provider"], config["provider"])
            _ensure_drive_folder(config, interactive=True)

    # Stage 3 — Pipeline
    if not args.json:
        clear_screen()
    start = time.monotonic()
    try:
        # En modo --json la vista Live se manda a stderr para no contaminar stdout.
        with contextlib.redirect_stdout(sys.stderr) if args.json else contextlib.nullcontext():
            results = run_pipeline(config)
    except KeyboardInterrupt:
        _abort()
    except Exception as e:
        if args.json:
            print(json.dumps({"status": "error", "error": str(e), "files": []}))
            sys.exit(2)
        console.print(f"\n[#dc3b3b]✗ Pipeline failed: {e}[/#dc3b3b]\n")
        sys.exit(2)

    total_time = time.monotonic() - start

    # Stage 4 — Results
    if args.json:
        print_json_results(results, total_time)
    else:
        clear_screen()
        console.print()
        console.print()
        show_results(results, total_time)

    sys.exit(0 if not any(not r["ok"] for r in results) else 1)

if __name__ == "__main__":
    main()