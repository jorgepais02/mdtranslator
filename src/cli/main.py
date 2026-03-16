import argparse
import sys
import time
import json
from pathlib import Path

# Add src to sys.path so we can import internal modules easily
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from .wizard import run_wizard
from .confirmation import show_confirmation
from .pipeline import run_pipeline
from .results import show_results
from .styles import console

def parse_args():
    parser = argparse.ArgumentParser(description="mdtranslator CLI")
    parser.add_argument("file", nargs="?", help="Source file", default=None)
    parser.add_argument("--lang", help="Target language codes (space-separated)", default=None)
    parser.add_argument("--provider", help="Translation provider: azure|deepl|auto", default=None)
    parser.add_argument("--output", help="Output: local|gdrive|both", default=None)
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show debug logs")
    parser.add_argument("--version", action="version", version="mdtranslator 2.1.0")

    return parser.parse_args()

def build_config_from_args(args) -> dict:
    provider_map = {
        "Azure AI Translator": "azure",
        "DeepL API": "deepl",
        "Auto (fallback)": "auto"
    }
    prov = args.provider if args.provider else "Auto (fallback)"
    
    return {
        "source": args.file or "Process ALL files",
        "provider": provider_map.get(prov, prov),
        "output": args.output or "Local only",
        "languages": args.lang.upper().split() if args.lang else ["EN"],
    }

def print_json_results(results: list[dict], total_time: float):
    failed = sum(1 for r in results if not r["ok"])
    print(json.dumps({
        "status": "success" if failed == 0 else "partial_success",
        "files": results,
        "total_time": total_time,
    }))

def main():
    args = parse_args()

    if not args.json:
        console.print("[dim]$ mdtranslator translate[/dim]\n")

    # Stage 1
    # If any specific non-interactive arg is missing and we don't have all interactive args, maybe we should just use wizard?
    # For simplicity, if --lang is not provided, we run the wizard.
    if not args.lang and not args.file and not args.provider and not sys.stdin.isatty():
        # Edge case: piped input. Not handling wizard in non-tty here.
        config = build_config_from_args(args)
    else:
        config = run_wizard(args.file) if not args.lang else build_config_from_args(args)
    
    if config is None:
        console.print("[dim]Aborted.[/dim]")
        sys.exit(0)

    # Re-map provider if it came from the wizard (which uses the human-readable strings)
    provider_map = {
        "Azure AI Translator": "azure",
        "DeepL API": "deepl",
        "Auto (fallback)": "auto"
    }
    config["provider"] = provider_map.get(config["provider"], config["provider"])

    # Stage 2
    if not args.yes and not args.json:
        if not show_confirmation(config):
            console.print("[dim]Aborted.[/dim]")
            sys.exit(0)

    # Stage 3
    start = time.monotonic()
    
    try:
        results = run_pipeline(config)
    except Exception as e:
        console.print(f"[red]✗ Pipeline failed: {str(e)}[/red]")
        sys.exit(2)
        
    total_time = time.monotonic() - start

    # Stage 4
    if args.json:
        print_json_results(results, total_time)
    else:
        show_results(results, total_time)

    # Exit code
    failed = sum(1 for r in results if not r["ok"])
    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    main()
