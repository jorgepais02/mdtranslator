"""
Quien hay, con que modelo por defecto y en que orden se intentan.

Calcado de translators/registry.py: AVAILABLE_MODELS es dato puro, para que anadir un
proveedor sea una fila y no tocar tres sitios. La lista de fallback se escribe en
config.json como refs "proveedor:modelo"; una entrada sin ":" usa el modelo por
defecto del proveedor.

API:
    AVAILABLE_MODELS          — dict con la etiqueta, la clase, la clave y el alta
    get_available_models()    — los proveedores cuya clave esta en el entorno
    parse_ref(ref)            — "gemini:gemini-3.5-flash" -> ("gemini", "gemini-3.5-flash")
    orden_por_defecto()       — el orden de config.json, o el de fabrica
    modelo_de(pid)            — con que modelo de ese proveedor: lo que diga el orden
    get_model(orden=None)     — el AIModel (o FallbackModel) que hay que usar
CLI:
    python -m src.ai.registry [--check]
"""

from .base import AIError, AIModel, FallbackModel
from .gemini import GeminiModel, DEFAULT_MODEL as GEMINI_DEFAULT
from .openai_compat import OpenAICompatModel


# Los proveedores gratuitos que se manejan hoy. El "signup" es la pagina donde se saca
# la clave: lo consume la pantalla de alta, que va en la tanda siguiente.
#
# "free" y "label" se pintan tal cual (la tabla de --check, y luego esa pantalla), asi
# que van en ingles como el resto de la interfaz. Y el numero de Gemini es el **medido**
# en el 429 —limit: 20 al dia por modelo—, no el que publica la pagina: prometer 1.500
# y cortar a las 20 es peor que no decir nada.
#
# El de Groq esta comprobado contra su API con una clave del free tier (18-09-2026): de
# sus 13 modelos, los que refinan son openai/gpt-oss-120b, openai/gpt-oss-20b y
# qwen/qwen3.8-27b —el resto son Whisper, clasificadores de prompts y TTS—, y el que
# estaba puesto de memoria, llama-3.3-70b-versatile, **no esta**. El de Cerebras sigue
# sin comprobar: si un id ha caducado la API responde 404, el fallback pasa al siguiente
# y `python -m src.ai.registry --check` dice cuales acepta de verdad.
AVAILABLE_MODELS: dict[str, dict] = {
    "gemini": {
        "label":         "Gemini (Google AI)",
        "cls":           GeminiModel,
        "key_env":       "GEMINI_API_KEY",
        "default_model": GEMINI_DEFAULT,
        "signup":        "https://aistudio.google.com/apikey",
        "free":          "20 requests/day per model (measured)",
        "kwargs":        {},
    },
    "groq": {
        "label":         "Groq",
        "cls":           OpenAICompatModel,
        "key_env":       "GROQ_API_KEY",
        "default_model": "openai/gpt-oss-120b",
        "signup":        "https://console.groq.com/keys",
        "free":          "1,000 requests/day, 30/min",
        "kwargs":        {"base_url": "https://api.groq.com/openai/v1"},
    },
    "cerebras": {
        "label":         "Cerebras",
        "cls":           OpenAICompatModel,
        "key_env":       "CEREBRAS_API_KEY",
        "default_model": "llama-3.3-70b",
        "signup":        "https://cloud.cerebras.ai/platform/apikeys",
        "free":          "1M tokens/day, 30/min",
        "kwargs":        {"base_url": "https://api.cerebras.ai/v1"},
    },
}

# El de fabrica encadena varios modelos del **mismo** proveedor a proposito: la cuota
# gratuita de Google se cuenta por modelo —medido, 20 peticiones al dia cada uno—, asi
# que eso ya desatasca un lote sin pedirle al usuario ninguna clave nueva. Con dos no
# llego: un lote de 16 documentos AR/ZH gasto los dos cubos y dejo el ultimo sin
# refinar, asi que la lista lleva tres. El orden va del mejor al mas ligero, porque
# cuando el bueno se agota lo que importa es que quede alguno.
ORDEN_DE_FABRICA = ["gemini:gemini-2.5-flash", "gemini:gemini-3.5-flash",
                    "gemini:gemini-3.5-flash-lite", "groq", "cerebras"]


def parse_ref(ref: str) -> tuple[str, str | None]:
    """"proveedor:modelo" -> (proveedor, modelo). Sin ":", el modelo es None."""
    pid, _, modelo = str(ref).partition(":")
    return pid.strip().lower(), (modelo.strip() or None)


def _instanciar(pid: str, modelo: str | None = None) -> AIModel:
    entrada = AVAILABLE_MODELS.get(pid)
    if entrada is None:
        raise AIError(f"unknown AI provider: {pid}")
    return entrada["cls"](
        model=modelo or entrada["default_model"],
        name=pid,
        label=entrada["label"],
        key_env=entrada["key_env"],
        **entrada["kwargs"],
    )


def get_available_models() -> list[dict]:
    """Los proveedores cuya clave esta en el entorno. API: lista de dicts."""
    disponibles = []
    for pid, entrada in AVAILABLE_MODELS.items():
        try:
            _instanciar(pid)
        except AIError:
            continue
        disponibles.append({"id": pid, "name": entrada["label"],
                            "model": entrada["default_model"]})
    return disponibles


def orden_por_defecto() -> list[str]:
    """El orden de fallback de config.json, o el de fabrica. API: lista de refs."""
    try:
        from core.config import CONFIG      # perezoso: src/ai no depende de core
    except ImportError:
        return list(ORDEN_DE_FABRICA)
    orden = (CONFIG.get("ai") or {}).get("fallback_order") or []
    return [str(x) for x in orden] or list(ORDEN_DE_FABRICA)


def modelo_de(pid: str) -> str:
    """El modelo que toca usar de ese proveedor. API: id del modelo.

    Lo dice el orden de fallback —el primero suyo que aparezca— y no una constante
    aparte: si el usuario ha puesto gemini:gemini-3.5-flash arriba, el traductor
    Gemini tambien tiene que hablar con ese.
    """
    entrada = AVAILABLE_MODELS.get(pid, {})
    for ref in orden_por_defecto():
        suyo, modelo = parse_ref(ref)
        if suyo == pid:
            return modelo or entrada.get("default_model", "")
    return entrada.get("default_model", "")


def get_model(orden: list[str] | str | None = None) -> AIModel:
    """El modelo que hay que usar. API: AIModel, o FallbackModel si hay varios.

    Los proveedores sin clave se caen de la lista en silencio, como en traduccion: la
    lista es un orden de preferencia, no una eleccion para esta ejecucion, y quedarse
    sin refinar porque la tercera opcion no tiene clave no ayuda a nadie. Si no queda
    ninguno, lanza AIError diciendo que clave falta.
    """
    if isinstance(orden, str):
        orden = [orden]
    refs = list(orden) if orden else orden_por_defecto()

    modelos: list[AIModel] = []
    fallos: list[str] = []
    vistos: set[str] = set()
    for ref in refs:
        pid, modelo = parse_ref(ref)
        entrada = AVAILABLE_MODELS.get(pid)
        clave = f"{pid}:{modelo or (entrada or {}).get('default_model')}"
        if clave in vistos:
            continue
        vistos.add(clave)
        try:
            modelos.append(_instanciar(pid, modelo))
        except AIError as e:
            fallos.append(str(e))

    if not modelos:
        detalle = "; ".join(dict.fromkeys(fallos)) or "empty fallback_order"
        raise AIError(f"no AI model configured ({detalle}) — "
                      f"add a key to .env, e.g. GEMINI_API_KEY")
    return modelos[0] if len(modelos) == 1 else FallbackModel(modelos)


if __name__ == "__main__":
    import argparse, sys
    from pathlib import Path

    from dotenv import load_dotenv
    from rich.console import Console
    from rich.table import Table
    from rich import box

    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env", override=True)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    ap = argparse.ArgumentParser(description="AI model providers")
    ap.add_argument("--check", action="store_true",
                    help="ask each API which model ids it accepts today")
    args = ap.parse_args()

    console = Console()
    tabla = Table(box=box.ROUNDED, border_style="dim", header_style="dim")
    tabla.add_column("PROVIDER")
    tabla.add_column("KEY")
    tabla.add_column("DEFAULT MODEL")
    tabla.add_column("FREE TIER")
    con_clave = {m["id"] for m in get_available_models()}
    for pid, e in AVAILABLE_MODELS.items():
        tabla.add_row(pid, "✓" if pid in con_clave else f"— {e['key_env']}",
                      e["default_model"], e["free"])
    console.print(tabla)
    console.print(f"fallback order: {' → '.join(orden_por_defecto())}")

    if args.check:
        for pid in con_clave:
            try:
                ids = _instanciar(pid).modelos_disponibles()
            except (AIError, AttributeError) as err:
                console.print(f"[yellow]{pid}: {err}[/yellow]")
                continue
            por_defecto = AVAILABLE_MODELS[pid]["default_model"]
            marca = "✓" if por_defecto in ids else "✗ not in the list"
            console.print(f"\n[bold]{pid}[/bold] — {len(ids)} models · "
                          f"default {por_defecto} {marca}")
            console.print(", ".join(sorted(ids)[:40]), style="dim")
