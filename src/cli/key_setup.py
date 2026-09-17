"""
Alta de una clave de API desde la terminal: elegir proveedor, abrir su pagina, pegar
el token, comprobarlo contra la API y escribirlo en .env.

Existe porque hasta ahora lo unico que decia la interfaz de un proveedor sin clave era
el `disabled="no API key"` del wizard: el resto —a que pagina ir, como se llama la
variable, donde se escribe— habia que saberlo de memoria o leerlo en el README.

API:
    providers()                       -> las fichas: id, label, key_env, signup, free
    configurado(ficha)                -> True si su clave ya esta en el entorno
    check_key(pid, clave, extras={})  -> el error de la API, o None si la clave vale
    nota_de_modelo(pid)               -> aviso si el modelo por defecto ya no existe
    save_key({VAR: valor})            -> Path de .env
    anadir_al_orden(pid)              -> mete el proveedor en ai.fallback_order
    run_add_key(pid=None)             -> codigo de salida del proceso
CLI:
    python -m src.cli.main --add-key [provider]
"""

import json
import os
import re
import sys
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

import questionary

from .prompts import BACK, ask_confirm, ask_select, ask_text
from .styles import (bloque, console, clear_screen, elide, marca, aire_superior,
                     CONTEXT, GREEN, MARGEN, META, RED, YELLOW)

from core.config import PROJECT_ROOT

ENV_PATH = PROJECT_ROOT / ".env"

_CANCEL  = "Cancel"
_OTRA    = "Try another key"
_IGUAL   = "Save it anyway"


# ── quien puede recibir una clave ─────────────────────────────────────────────

def _comprobar_traductor(pid: str):
    def comprobar() -> None:
        from translators.registry import AVAILABLE_TRANSLATORS
        # Dos caracteres del cupo del mes: es la unica forma de saber que la clave
        # **traduce**, y no solo que la API la reconoce.
        AVAILABLE_TRANSLATORS[pid][1]().translate(["ok"], "EN")
    return comprobar


def _comprobar_modelo(pid: str):
    def comprobar() -> None:
        from ai.registry import get_model
        # El listado de modelos es un GET: dice que la clave vale sin gastar ninguna
        # de las peticiones de generacion, que es justo lo que escasea (medido: 20 al
        # dia por modelo en el plan gratuito de Gemini).
        get_model(pid).modelos_disponibles()
    return comprobar


def _de_traductores() -> list[dict]:
    from translators.registry import AVAILABLE_TRANSLATORS
    fichas = []
    for pid, (label, cls) in AVAILABLE_TRANSLATORS.items():
        if not getattr(cls, "key_env", ""):
            continue
        fichas.append({"id": pid, "label": label, "key_env": cls.key_env,
                       "extra_env": tuple(cls.extra_env), "signup": cls.signup,
                       "free": cls.free, "usos": ["translate"], "modelo": False,
                       "check": _comprobar_traductor(pid)})
    return fichas


def _de_modelos() -> list[dict]:
    # Perezoso: src/ai/gemini.py importa el SDK de Google al cargarse, y saber quien
    # puede recibir una clave no deberia arrastrarlo.
    from ai.registry import AVAILABLE_MODELS
    return [{"id": pid, "label": e["label"], "key_env": e["key_env"],
             "extra_env": (), "signup": e["signup"], "free": e["free"],
             "usos": ["refine"], "modelo": True, "check": _comprobar_modelo(pid)}
            for pid, e in AVAILABLE_MODELS.items()]


def providers() -> list[dict]:
    """Quien puede recibir una clave, con lo que hace falta para darsela. API: fichas.

    Sale de los dos registros y no de una constante nueva —la leccion del menu del
    wizard, donde Gemini estaba registrado y no aparecia— y se deduplica por
    **variable de entorno**, no por id: GEMINI_API_KEY sirve a la vez para traducir y
    para refinar, y como dos fichas seria preguntar dos veces por la misma clave.
    """
    fichas: dict[str, dict] = {}
    for ficha in _de_traductores() + _de_modelos():
        ya = fichas.get(ficha["key_env"])
        if ya is None:
            fichas[ficha["key_env"]] = ficha
            continue
        ya["usos"] += [u for u in ficha["usos"] if u not in ya["usos"]]
        if ficha["modelo"]:
            # La comprobacion del modelo gana a la del traductor: es un GET al listado
            # y no gasta cuota, mientras que la otra manda una traduccion de verdad.
            ya["check"], ya["modelo"] = ficha["check"], True
    return list(fichas.values())


def _ficha(pid: str, fichas: list[dict] | None = None) -> dict | None:
    pid = (pid or "").strip().lower()
    for f in (fichas if fichas is not None else providers()):
        if f["id"] == pid or f["key_env"].lower() == pid:
            return f
    return None


def configurado(ficha: dict) -> bool:
    """True si la clave de esa ficha ya esta en el entorno. API: bool."""
    return bool(os.getenv(ficha["key_env"], "").strip())


# ── comprobar y guardar ───────────────────────────────────────────────────────

def check_key(pid: str, clave: str, extras: dict[str, str] | None = None) -> str | None:
    """Le pregunta a la API si la clave vale. API: el error, o None si vale.

    La clave se pone en el entorno antes de comprobarla porque es de ahi de donde la
    leen los proveedores —solo dos de los cinco la aceptan por constructor—, y si no
    vale se deja el entorno como estaba: una clave mal pegada no debe quedarse puesta
    en el proceso que acaba de rechazarla.
    """
    ficha = _ficha(pid)
    if ficha is None:
        return f"unknown provider: {pid}"
    nuevos = {ficha["key_env"]: clave, **(extras or {})}
    previo = {k: os.environ.get(k) for k in nuevos}
    os.environ.update({k: v for k, v in nuevos.items() if v})
    try:
        ficha["check"]()
    except Exception as e:
        for k, v in previo.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        return str(e) or type(e).__name__
    return None


def nota_de_modelo(pid: str) -> str | None:
    """Aviso si el modelo por defecto de ese proveedor ya no esta en su lista.

    El listado y lo que de verdad responde no son lo mismo, y los ids de Groq y
    Cerebras estan puestos de memoria porque aqui no hay claves para comprobarlos: el
    momento de decirlo es justo al dar de alta la clave, que es cuando por fin se
    puede preguntar.
    """
    from ai.registry import AVAILABLE_MODELS, get_model
    entrada = AVAILABLE_MODELS.get(pid)
    if entrada is None:
        return None
    try:
        ids = get_model(pid).modelos_disponibles()
    except Exception:
        return None                      # la clave ya vale; esto era un extra
    por_defecto = entrada["default_model"]
    if not ids or por_defecto in ids:
        return None
    # En dos lineas y el comando en la suya: de una sola pieza son 101 columnas y en
    # un terminal de 100 rich parte la linea por donde cae, asi que el comando —lo
    # unico accionable del aviso— acababa cortado y empezando en la columna 0.
    return (f"{por_defecto} is not among the {len(ids)} models this key can use\n"
            f"pick another with: python -m src.ai.registry --check")


def _citar(valor: str) -> str:
    """Entre comillas solo si hace falta: un espacio o una # partirian la linea."""
    valor = valor.strip()
    if valor and not any(c in valor for c in ' \t#\'"'):
        return valor
    return '"' + valor.replace('"', '\\"') + '"'


def _asignacion(nombre: str) -> re.Pattern:
    return re.compile(rf"^\s*(?:export\s+)?{re.escape(nombre)}\s*=")


def save_key(valores: dict[str, str]) -> Path:
    """Escribe esas variables en .env conservando el resto del fichero. API: Path.

    Linea a linea y no con un volcado: .env lo escribe el usuario a mano y tiene sus
    comentarios y su orden, asi que reescribirlo entero le borraria justo lo que no
    entendemos. Una variable que ya esta se sustituye en su sitio —para no dejar dos
    asignaciones de la misma y que el valor dependa de cual gane— y una nueva se anade
    al final.
    """
    existia = ENV_PATH.exists()
    lineas = ENV_PATH.read_text(encoding="utf-8").splitlines() if existia else []
    for nombre, valor in valores.items():
        nueva = f"{nombre}={_citar(valor)}"
        patron = _asignacion(nombre)
        for i, actual in enumerate(lineas):
            if patron.match(actual):
                lineas[i] = nueva
                break
        else:
            lineas.append(nueva)
    ENV_PATH.write_text("\n".join(lineas).rstrip("\n") + "\n", encoding="utf-8")
    if not existia:
        # .env guarda secretos: el que creamos nosotros no nace legible para todos.
        ENV_PATH.chmod(0o600)
    os.environ.update({k: v for k, v in valores.items() if v})
    return ENV_PATH


def anadir_al_orden(pid: str) -> Path | None:
    """Mete el proveedor al final de ai.fallback_order. API: Path de config.json.

    Una clave nueva que no esta en el orden no se usa nunca, y eso no se ve en ninguna
    parte: la lista es un orden de preferencia y el que no aparece no se intenta. Va al
    final a proposito —lo de arriba es lo que el usuario ya eligio— y con el modelo por
    defecto, o sea sin ":".
    """
    path = PROJECT_ROOT / "config.json"
    try:
        cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        return None
    ai = cfg.setdefault("ai", {})
    orden = list(ai.get("fallback_order") or [])
    if not orden:
        from ai.registry import orden_por_defecto
        orden = orden_por_defecto()
    if any(ref.split(":")[0].strip().lower() == pid for ref in orden):
        return None
    ai["fallback_order"] = orden + [pid]
    path.write_text(json.dumps(cfg, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _en_el_orden(pid: str) -> bool:
    from ai.registry import orden_por_defecto
    return any(ref.split(":")[0].strip().lower() == pid for ref in orden_por_defecto())


# ── la pantalla ───────────────────────────────────────────────────────────────

def _pintar(ruta: str, detalle: str = "", pendiente: str | None = None) -> None:
    """Repinta la pantalla: marca, migas y aire. Igual que el selector de carpetas.

    Una pregunta cada vez: los pasos de esto son abrir la pagina, pegar la clave y
    comprobarla, y apilarlos dejaba tres preguntas contestadas encima de la viva.
    """
    clear_screen()
    for _ in range(aire_superior()):
        console.print()
    console.print(marca())
    console.print()
    linea = (f"{MARGEN}[{META}]>[/{META}] "
             f"[{CONTEXT}]{elide(ruta, max(16, console.width - 34))}[/{CONTEXT}]")
    if detalle:
        linea += f"[{META}] · {elide(detalle, max(12, console.width - len(ruta) - 12))}[/{META}]"
    console.print(linea)
    console.print()
    # El aviso de la vuelta anterior lo pinta quien limpia, o se borraria antes de
    # poder leerse: el mismo trato que le dan el wizard y el selector de carpetas.
    if pendiente:
        console.print(f"{MARGEN}[{YELLOW}]⚠ {pendiente}[/{YELLOW}]")
    console.print()


def _cancelado(que: str = "Nothing was changed.") -> int:
    console.print(f"\n{MARGEN}[{META}]Cancelled. {que}[/{META}]\n")
    return 0


def _dominio(url: str) -> str:
    return urlparse(url).netloc or url


def _preguntar_proveedor(fichas: list[dict]) -> dict | None:
    hechas = sum(1 for f in fichas if configurado(f))
    _pintar("API keys", f"{hechas} of {len(fichas)} set")

    opciones = []
    for f in fichas:
        # El ✓ va dentro del titulo y sin color: questionary pinta la etiqueta de una
        # opcion con un solo estilo, y verde es "salio bien" — tener clave es un dato,
        # no un exito. Delante y no detras para que las etiquetas queden alineadas.
        # Recortado antes de dárselo a questionary, como todo lo que va a una lista:
        # a 50 columnas prompt_toolkit cortaba el subtítulo por donde cayera y el
        # "(measured)" de Gemini desaparecía sin dejar puntos suspensivos.
        cabe = max(20, console.width - 6)
        opciones.append(questionary.Choice(
            title=elide(f"{'✓' if configurado(f) else ' '} {f['label']}", cabe), value=f,
            description=elide(f"{' + '.join(f['usos'])} · {f['free']}", cabe)))
    opciones.append(questionary.Separator(
        "  " + "─" * min(30, max(10, console.width - 6))))
    # Con la misma sangria que las demas: el ✓ desplaza dos columnas las etiquetas y
    # sin ellas "Cancel" se salia de la columna de la lista.
    opciones.append(questionary.Choice(title=f"  {_CANCEL}", value=None))

    r = ask_select("Add an API key for…", opciones)
    return None if r is None or r is BACK else r


def _pedir_clave(ficha: dict, ruta: str, pendiente: str | None) -> tuple[str, dict] | None:
    """Abre la pagina del proveedor y recoge la clave y sus extras. API: (clave, extras)."""
    detalle = " · ".join(filter(None, [" + ".join(ficha["usos"]), ficha["free"]]))
    _pintar(ruta, detalle, pendiente)

    if ficha["signup"]:
        abrir = ask_confirm(f"Open {_dominio(ficha['signup'])} to get the key?",
                            default=not configurado(ficha))
        if abrir is None or abrir is BACK:
            return None
        if abrir:
            # Si no hay navegador (una sesion por ssh), webbrowser devuelve False: la
            # URL se escribe igual, que es lo que hace falta para copiarla a mano.
            abierto = False
            try:
                abierto = webbrowser.open(ficha["signup"])
            except Exception:
                abierto = False
            marca_url = "✓ Opened" if abierto else "→ Open"
            console.print(f"{MARGEN}[{META}]{marca_url}[/{META}] "
                          f"[{CONTEXT}]{ficha['signup']}[/{CONTEXT}]")
            console.print()

    clave = ask_text(f"Paste the {ficha['label']} key", back=True,
                     validate=lambda t: True if t.strip() else "Paste the key, or ⌫ to cancel")
    if clave is None or clave is BACK or not clave.strip():
        return None

    extras: dict[str, str] = {}
    for nombre, etiqueta, defecto in ficha["extra_env"]:
        valor = ask_text(etiqueta, default=os.getenv(nombre) or defecto, back=True)
        if valor is None or valor is BACK:
            return None
        extras[nombre] = valor.strip() or defecto
    return clave.strip(), extras


def _alta(ficha: dict) -> int:
    ruta = f"API keys / {ficha['label']}"

    if configurado(ficha):
        _pintar(ruta, f"{ficha['key_env']} is already set")
        otra = ask_confirm("Replace the key that is already in .env?", default=False)
        if otra is None or otra is BACK or not otra:
            return _cancelado(f"{ficha['key_env']} stays as it is.")

    pendiente: str | None = None
    while True:
        pedido = _pedir_clave(ficha, ruta, pendiente)
        if pedido is None:
            return _cancelado()
        clave, extras = pedido

        console.print(f"{MARGEN}[{META}]Checking the key against "
                      f"{_dominio(ficha['signup']) or ficha['label']}…[/{META}]")
        error = check_key(ficha["id"], clave, extras)
        if error:
            _pintar(ruta, "the API rejected it")
            console.print(f"{MARGEN}[{RED}]✗[/{RED}] "
                          f"[{CONTEXT}]{elide(error, max(24, console.width - 6))}[/{CONTEXT}]")
            console.print()
            # Guardarla igual es una salida de verdad y no una cortesia: la API puede
            # estar caida, y la comprobacion de Azure necesita acertar tambien con la
            # region. Mejor dejarla escrita que obligar a editar .env a mano.
            que = ask_select("The key did not work", [_OTRA, _IGUAL, _CANCEL])
            if que is None or que is BACK or que == _CANCEL:
                return _cancelado()
            if que == _OTRA:
                pendiente = "That key did not work. Copy it again from the page."
                continue
        break

    path = save_key({ficha["key_env"]: clave, **extras})
    _pintar(ruta, " + ".join(ficha["usos"]))
    console.print(f"{MARGEN}[{GREEN}]✓[/{GREEN}] [{META}]Saved[/{META}] "
                  f"[{CONTEXT}]{ficha['key_env']}[/{CONTEXT}][{META}] to {path.name}"
                  f"{' (not checked)' if error else ''}[/{META}]")
    for nombre in extras:
        console.print(f"{MARGEN}  [{META}]and[/{META}] [{CONTEXT}]{nombre}[/{CONTEXT}]")

    if ficha["modelo"] and not error:
        aviso = nota_de_modelo(ficha["id"])
        if aviso:
            console.print(bloque("⚠", aviso, YELLOW))

    if ficha["modelo"] and not _en_el_orden(ficha["id"]):
        console.print()
        puesto = ask_confirm(f"Use {ficha['label']} for refining when the others "
                             f"run out of quota?", default=True)
        if puesto is True:
            destino = anadir_al_orden(ficha["id"])
            if destino:
                console.print(f"{MARGEN}[{GREEN}]✓[/{GREEN}] [{META}]Added to "
                              f"ai.fallback_order in {destino.name}[/{META}]")
    console.print()
    return 0


def run_add_key(pid: str | None = None) -> int:
    """Punto de entrada de --add-key. Devuelve el codigo de salida del proceso."""
    fichas = providers()
    if pid:
        elegida = _ficha(pid, fichas)
        if elegida is None:
            conocidos = ", ".join(f["id"] for f in fichas)
            print(f"error: unknown provider: {pid} — try one of: {conocidos}",
                  file=sys.stderr)
            return 2
    else:
        elegida = _preguntar_proveedor(fichas)
        if elegida is None:
            return _cancelado()
    return _alta(elegida)
