import argparse
import contextlib
import shlex
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
from .errors import CLIError
from .styles import LANGUAGES
from .styles import bloque, console, clear_screen, RED, VERSION, YELLOW
from .folder_picker import (configured_folder, pick_drive_folder, run_set_folder,
                            save_folder_id)
from .key_setup import run_add_key
from core.sources import ALL_FILES, collect_sources, list_source_folders
from core.config import DRIVE_FOLDER_ID
from translators.registry import AVAILABLE_TRANSLATORS, get_available_translators


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
    # nargs="?" para que valga tanto "--add-key" (pregunta de quien) como
    # "--add-key groq". El default es None y el const "", asi que "se ha pedido" y
    # "se ha dicho de quien" son dos preguntas distintas.
    parser.add_argument("--add-key", nargs="?", const="", default=None, metavar="PROVIDER",
                        help="add an API key to .env (deepl, azure, gemini, groq, cerebras)")
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

_PISTAS_CUOTA = ("quota", "429", "resource_exhausted", "rate limit", "too many requests")


def _es_fallo_de_cuota(warning: str | None) -> bool:
    texto = str(warning or "").lower()
    return any(p in texto for p in _PISTAS_CUOTA)


def _retry_provider(config: dict, results: list[dict]) -> tuple[str, str | None]:
    """Con que proveedor relanzar. API: (provider, nota para la pantalla final).

    Elegir proveedor a mano desactiva el fallback a proposito: quien pide DeepL lo pide
    por algo, y cambiarselo a mitad de ejecucion seria traducir con otro sin decirlo.
    Pero entonces un 429 de ese proveedor deja el lote sin traducir y sin mencionar en
    ninguna parte que hay otras claves cargadas que podrian acabarlo: el comando de
    reintento las ofrece, y la nota dice por que ha cambiado.
    """
    provider = config.get("provider") or "auto"
    if provider == "auto":
        return provider, None
    if not any(not r["ok"] and _es_fallo_de_cuota(r.get("warning")) for r in results):
        return provider, None
    otros = [t["name"] for t in get_available_translators() if t["id"] != provider]
    if not otros:
        return provider, None
    nombre = AVAILABLE_TRANSLATORS.get(provider, (provider,))[0]
    return "auto", (f"{nombre} ran out of quota — the command below switches to "
                    f"whichever provider answers ({', '.join(otros)}).")


def _retry_command(config: dict, provider: str | None = None) -> str:
    """El comando que vuelve a lanzar esta misma ejecucion. API: una linea de shell.

    Reanudar un lote es relanzarlo: la cache de traduccion y la de refinamiento hacen
    que solo se repita lo que quedo sin hacer. Por eso el comando se escribe entero en
    la pantalla final, en vez de dejar al usuario reconstruirlo de memoria.
    """
    partes = ["python -m src.cli.main"]
    source = config.get("source")
    if source == ALL_FILES:
        partes.append("--all")
    elif source:
        partes.append(shlex.quote(str(source)))
    if config.get("languages"):
        partes.append("--lang " + " ".join(config["languages"]))
    salida = {v: k for k, v in _OUTPUT_MAP.items()}.get(config.get("output", ""))
    if salida:
        partes.append(f"--output {salida}")
    elegido  = config.get("provider") or "auto"
    provider = provider or elegido
    # "auto" es el modo por defecto y no hace falta escribirlo, salvo cuando es un
    # cambio respecto a lo que pidio el usuario: entonces el comando tiene que
    # ensenar en que se diferencia del que acaba de fallar.
    if provider and (provider != "auto" or provider != elegido):
        partes.append(f"--provider {provider}")
    if config.get("source_lang"):
        partes.append(f"--source-lang {config['source_lang']}")
    partes.append("-y")
    return " ".join(partes)


def print_json_results(results: list[dict], total_time: float, retry_cmd: str | None = None):
    failed = sum(1 for r in results if not r["ok"])
    a_medias = [r for r in results if r.get("incomplete")]
    salida = {
        "status":     "success" if not failed else "partial_success",
        "files":      results,
        "total_time": total_time,
    }
    # Un lote lanzado desde un script tambien tiene que poder preguntar "¿quedo algo?"
    # sin leerse la tabla: el comando de reintento viaja en el JSON.
    if a_medias or failed:
        salida["incomplete"]    = len(a_medias)
        salida["retry_command"] = retry_cmd
    print(json.dumps(salida))

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
    except CLIError as e:
        # Un CLIError es un mensaje ya redactado, no un fallo inesperado: se pinta
        # tal cual (puede traer varias lineas) y se sale con su codigo.
        console.print()
        console.print(bloque("✗", e.message.lstrip("✗ "), RED, destacar=True))
        console.print()
        sys.exit(e.exit_code)

_PROVIDER_MAP = {"Azure AI Translator": "azure", "DeepL API": "deepl", "Auto (fallback)": "auto"}

def _ensure_drive_folder(config, interactive: bool) -> None:
    """Drive necesita una carpeta destino: si no hay ninguna, preguntarla.

    El wizard ya la trae en la config (la pregunta cuando el destino incluye Drive),
    asi que esto solo entra por el camino de los flags. No escribe config.json: eso lo
    hace _remember_drive_folder cuando la ejecucion arranca de verdad.
    """
    if "Google Drive" not in config["output"]:
        return
    if config.get("drive_folder_id") or DRIVE_FOLDER_ID:
        return
    if not interactive:
        print("error: no Drive folder configured — run with --set-folder first", file=sys.stderr)
        sys.exit(2)
    console.print(f"\n[{YELLOW}]No Drive folder configured yet.[/{YELLOW}]")
    elegida = pick_drive_folder()
    if not elegida:
        _abort()
    config["drive_folder_id"], config["drive_folder_name"] = elegida


def _remember_drive_folder(config) -> None:
    """Guarda la carpeta de esta ejecucion como la de la proxima.

    Se guarda al arrancar y no al elegirla: cancelar en la confirmacion no tiene que
    dejar cambiada la carpeta de la siguiente vez.
    """
    elegida = (config.get("drive_folder_id") or "").strip()
    if elegida and "Google Drive" in config["output"] and elegida != configured_folder()[0]:
        save_folder_id(elegida, config.get("drive_folder_name"))


def _run(args):
    if args.set_folder:
        sys.exit(run_set_folder())

    if args.add_key is not None:
        sys.exit(run_add_key(args.add_key or None))

    # Stage 1 — Wizard (prints its own header, no clear needed)
    if args.json or args.lang or args.all:
        config = build_config_from_args(args)
    else:
        # Sin nada en sources/ se dice aqui y no se abre el wizard: el wizard limpia la
        # pantalla en cada paso, asi que un aviso suyo se borra antes de leerse.
        if not args.file and not (collect_sources(ALL_FILES) or list_source_folders()):
            print("error: no sources — put a .md or .txt in sources/", file=sys.stderr)
            sys.exit(2)
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
    _remember_drive_folder(config)
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
        console.print(f"\n[{RED}]✗ Pipeline failed: {e}[/{RED}]\n")
        sys.exit(2)

    total_time = time.monotonic() - start

    # Stage 4 — Results
    retry_provider, retry_note = _retry_provider(config, results)
    retry_cmd = _retry_command(config, retry_provider)
    if args.json:
        print_json_results(results, total_time, retry_cmd)
    else:
        clear_screen()
        console.print()
        console.print()
        show_results(results, total_time, retry_cmd=retry_cmd, retry_note=retry_note)

    sys.exit(0 if not any(not r["ok"] for r in results) else 1)

if __name__ == "__main__":
    main()