import argparse
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
from .styles import console, clear_screen

VERSION = "2.1.0"

def parse_args():
    parser = argparse.ArgumentParser(description="mdtranslator CLI")
    parser.add_argument("file",        nargs="?", default=None)
    parser.add_argument("--lang",      default=None)
    parser.add_argument("--provider",  default=None)
    parser.add_argument("--output",    default=None)
    parser.add_argument("--yes", "-y", action="store_true")
    parser.add_argument("--json",      action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--version",   action="version", version=f"mdtranslator {VERSION}")
    return parser.parse_args()

def build_config_from_args(args) -> dict:
    provider_map = {"Azure AI Translator": "azure", "DeepL API": "deepl", "Auto (fallback)": "auto"}
    return {
        "source":    args.file or "Process ALL files",
        "provider":  provider_map.get(args.provider or "", args.provider or "auto"),
        "output":    args.output or "Local only",
        "languages": args.lang.upper().split() if args.lang else ["EN"],
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

def _run(args):
    provider_map = {"Azure AI Translator": "azure", "DeepL API": "deepl", "Auto (fallback)": "auto"}

    # Stage 1 — Wizard (prints its own header, no clear needed)
    if args.json or args.lang:
        config = build_config_from_args(args)
    else:
        config = run_wizard(args.file)

    if config is None:
        _abort()

    config["provider"] = provider_map.get(config["provider"], config["provider"])

    # Stage 2 — Confirmation
    if not args.yes and not args.json:
        if not show_confirmation(config):
            _abort()

    # Stage 3 — Pipeline
    clear_screen()
    start = time.monotonic()
    try:
        results = run_pipeline(config)
    except KeyboardInterrupt:
        _abort()
    except Exception as e:
        console.print(f"\n[#dc3b3b]✗ Pipeline failed: {e}[/#dc3b3b]\n")
        sys.exit(2)

    total_time = time.monotonic() - start

    # Stage 4 — Results
    clear_screen()
    console.print()
    console.print()
    show_results(results, total_time)

    sys.exit(0 if not any(not r["ok"] for r in results) else 1)

if __name__ == "__main__":
    main()