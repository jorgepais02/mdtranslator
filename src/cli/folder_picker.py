"""
Selector interactivo de la carpeta de Google Drive.

API:
    pick_drive_folder(manager=None) -> tuple[str, str] | None
    create_drive_folder(name, parent_id, manager=None) -> tuple[str, str] | None
    create_folder_next_to(name, sibling_of, manager=None) -> tuple[str, str] | None
    configured_folder() -> tuple[str, str]
    next_folder_name(name) -> str | None
    save_folder_id(folder_id, folder_name=None) -> Path
    extract_folder_id(text) -> str | None

CLI:
    python -m src.cli.main --set-folder
"""

import json
import re
from pathlib import Path

import questionary

from .prompts import ask_select, ask_text
from .styles import (console, clear_screen, elide, marca, aire_superior, CONTEXT,
                     GREEN, MARGEN, META, RED, YELLOW)

from core.config import PROJECT_ROOT

ROOT = "root"

_URL_ID_RE = re.compile(r"/folders/([A-Za-z0-9_-]{10,})|[?&]id=([A-Za-z0-9_-]{10,})")
_BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")

# El número con el que acaba un nombre, para proponer el siguiente: M18 → M19.
_SERIE_RE = re.compile(r"^(.*?)(\d+)(\D*)$")

# Sin emoji: 📁 ocupa dos celdas del terminal y ✓ una, asi que los nombres de las
# carpetas nunca quedaban alineados entre si. El sufijo "/" distingue igual de bien
# una carpeta y no rompe la cuadricula.
_USE    = "Use this folder"
_NEW    = "Create a folder here…"
_UP     = "Up one level"
_PASTE  = "Paste a Drive URL"
_CANCEL = "Cancel"


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def extract_folder_id(text: str) -> str | None:
    """Extrae el ID de una carpeta desde una URL de Drive, o acepta el ID pelado."""
    text = (text or "").strip()
    if not text:
        return None
    m = _URL_ID_RE.search(text)
    if m:
        return m.group(1) or m.group(2)
    return text if _BARE_ID_RE.match(text) else None


def next_folder_name(name: str) -> str | None:
    """El siguiente de una serie: M18 → M19, "Modulo 8" → "Modulo 9". API: str | None.

    Los módulos van uno detrás de otro y la carpeta del anterior es la que hay en el
    config, así que el nombre del nuevo casi siempre es ese más uno. Se propone, no se
    impone: es el texto que aparece ya escrito en el campo. Sin número no se propone
    nada, porque no hay ninguna serie que continuar.
    """
    m = _SERIE_RE.match((name or "").strip())
    if not m:
        return None
    prefijo, numero, sufijo = m.groups()
    # El relleno se conserva: M08 → M09, no M9, o dejaría de ordenar por nombre.
    return f"{prefijo}{int(numero) + 1:0{len(numero)}d}{sufijo}"


def _leer_cfg() -> dict:
    """La configuración tal y como está en el disco, no la que se cargó al arrancar.

    Se relee en vez de usar core.config.CONFIG porque save_folder_id acaba de
    escribirla: la copia en memoria seguiría ofreciendo la carpeta anterior durante el
    resto de la ejecución.
    """
    for nombre in ("config.json", "config.example.json"):
        path = PROJECT_ROOT / nombre
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
    return {}


def configured_folder() -> tuple[str, str]:
    """La carpeta que ya está guardada: (id, nombre). API: ("", "") si no hay ninguna.

    El nombre se guarda al lado del id justo para no tener que preguntárselo a Drive
    cada vez que hay que nombrarla: la pregunta se pinta sin red y sin autenticar.
    """
    drive = _leer_cfg().get("drive") or {}
    return (drive.get("folder_id") or "").strip(), (drive.get("folder_name") or "").strip()


def save_folder_id(folder_id: str, folder_name: str | None = None) -> Path:
    """Escribe drive.folder_id, y su nombre, en config.json conservando el resto.

    El nombre es un rótulo, no una referencia: si la carpeta se renombra en Drive el id
    sigue siendo el bueno y lo único que envejece es la etiqueta de la pregunta.
    """
    cfg = _leer_cfg()
    drive = cfg.setdefault("drive", {})
    drive["folder_id"] = folder_id
    if folder_name:
        drive["folder_name"] = folder_name
    path = PROJECT_ROOT / "config.json"
    path.write_text(json.dumps(cfg, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _manager(manager=None):
    from integrations.drive import GoogleDocsManager
    return manager or GoogleDocsManager(console=console)


def create_drive_folder(name: str, parent_id: str, manager=None) -> tuple[str, str] | None:
    """Crea una carpeta dentro de parent_id y la devuelve: (id, nombre), o None.

    Si ya existe una con ese nombre se reutiliza en vez de crear una segunda: repetir
    la creación de "M19" tiene que llevar a la misma carpeta, no a dos hermanas
    homónimas entre las que Drive no distingue a la vista.
    """
    name = (name or "").strip()
    if not name:
        return None
    try:
        return _manager(manager).get_or_create_subfolder(parent_id, name), name
    except Exception as e:
        console.print(f"[{RED}]✗ Could not create the folder: {e}[/{RED}]")
        return None


def create_folder_next_to(name: str, sibling_of: str, manager=None) -> tuple[str, str] | None:
    """Crea una carpeta donde está otra —hermana, no dentro—. API: (id, nombre) | None.

    La carpeta del config es la del módulo anterior y sus subcarpetas son los idiomas,
    así que el módulo nuevo va a su lado. Si no se puede averiguar dónde está, se cae a
    la raíz en vez de fallar: es visible y se arregla moviéndola.
    """
    g = _manager(manager)
    try:
        padre = (g.get_folder_info(sibling_of).get("parents") or [ROOT])[0]
    except Exception as e:
        console.print(f"[{RED}]✗ Could not read the current folder: {e}[/{RED}]")
        return None
    return create_drive_folder(name, padre, manager=g)


def _elegida(nombre: str, ancho_extra: int = 26) -> None:
    console.print(f"{MARGEN}[{GREEN}]✓[/{GREEN}] [{META}]Folder selected:[/{META}] "
                  f"[{CONTEXT}]{elide(nombre, max(16, console.width - ancho_extra))}[/{CONTEXT}]")


def pick_drive_folder(manager=None) -> tuple[str, str] | None:
    """Navega por Drive y devuelve la carpeta elegida: (id, nombre), o None.

    Devuelve tambien el nombre porque quien la elige es quien la guarda, y guardar solo
    el id obligaba a volver a preguntarle a Drive como se llama cada vez que hay que
    nombrarla en pantalla.
    """
    g = _manager(manager)

    current, label = ROOT, "My Drive"
    camino: list[str] = [label]          # migas de pan: donde estas, no solo el nombre
    pendiente: str | None = None         # un aviso que tiene que sobrevivir al repintado
    raiz_real: str | None = None         # "Mi unidad" tambien tiene id propio
    while True:
        ruta = " / ".join(camino)
        try:
            subs = g.list_subfolders(current)
        except Exception as e:
            console.print(f"[{RED}]✗ Could not read the folder: {e}[/{RED}]")
            return None

        # El nombre se recorta: questionary parte en dos lineas las opciones largas
        # y la carpeta seleccionada deja de leerse de un vistazo.
        cabe = max(16, console.width - 8)
        by_label = {f"{elide(f['name'], cabe)}/": f for f in subs}

        # Navegar arriba, decidir abajo, con una raya en medio: sin ella "Usar esta
        # carpeta" era una entrada mas de la lista de carpetas y se elegia sin querer.
        choices = list(by_label)
        if current != ROOT:
            choices.append(_UP)
        choices.append(questionary.Separator("  " + "─" * min(30, max(10, console.width - 6))))
        choices += [_USE, _NEW, _PASTE, _CANCEL]

        # Las mismas migas que el wizard, y en los mismos dos tonos: donde estas es
        # contexto de la pregunta, no la pregunta.
        _pintar(ruta, len(subs), pendiente)
        pendiente = None

        answer = ask_select("Choose the destination folder", choices)

        if answer is None or answer == _CANCEL:
            return None

        if answer == _USE:
            if current == ROOT:
                info = g.get_folder_info(ROOT)      # id real de "Mi unidad"
                raiz_real = info["id"]
                current, label = raiz_real, info.get("name") or label
            _elegida(ruta)
            return current, label

        if answer == _NEW:
            # Crear es elegir: quien crea la carpeta del modulo nuevo la quiere usar, y
            # obligarle a buscarla despues en la lista era un paso de mas.
            creada = create_drive_folder(ask_text("New folder name") or "",
                                         current, manager=g)
            if creada is None:
                pendiente = "No folder was created."
                continue
            _elegida(f"{ruta} / {creada[1]}")
            return creada

        if answer == _UP:
            parents = g.get_folder_info(current).get("parents") or [ROOT]
            current = parents[0]
            # El padre de una carpeta de primer nivel es "Mi unidad" con su id real,
            # no el alias "root", asi que al volver arriba la raiz dejaba de parecer
            # la raiz: "Up one level" seguia en la lista sin nada a donde subir.
            if current != ROOT:
                if raiz_real is None:
                    try:
                        raiz_real = g.get_folder_info(ROOT)["id"]
                    except Exception:
                        raiz_real = ""
                if current == raiz_real:
                    current = ROOT
            label = g.get_folder_info(current)["name"] if current != ROOT else "My Drive"
            camino = camino[:-1] or [label]
            continue

        if answer == _PASTE:
            pasted = ask_text("Paste the folder URL (or its ID)")
            folder_id = extract_folder_id(pasted or "")
            if not folder_id:
                pendiente = "That does not look like a Drive folder."
                continue
            try:
                info = g.get_folder_info(folder_id)
            except Exception as e:
                pendiente = f"Cannot open that folder: {e}"
                continue
            _elegida(info["name"])
            return info["id"], info["name"]

        entry = by_label[answer]
        current, label = entry["id"], entry["name"]
        camino.append(label)


def _aviso(texto: str) -> None:
    console.print(f"{MARGEN}[{YELLOW}]⚠ {texto}[/{YELLOW}]")


def _pintar(ruta: str, subcarpetas: int, pendiente: str | None = None) -> None:
    """Repinta la pantalla del selector: marca, migas del camino y aire.

    Igual que el wizard, y por lo mismo: antes cada nivel dejaba su cabecera y su
    filete en pantalla, asi que bajar tres carpetas eran tres preguntas iguales
    apiladas —mas la del wizard que abrio el selector— y la lista viva quedaba al
    final de una columna de restos. Aqui solo hay una pregunta cada vez; lo que
    cambia de un nivel al siguiente es el camino, que es justo lo que dicen las migas.
    """
    clear_screen()
    for _ in range(aire_superior()):
        console.print()
    console.print(marca())
    console.print()
    console.print(f"{MARGEN}[{META}]>[/{META}] "
                  f"[{CONTEXT}]{elide(ruta, max(16, console.width - 28))}[/{CONTEXT}]"
                  f"[{META}] · {_plural(subcarpetas, 'subfolder', 'subfolders')}[/{META}]")
    console.print()
    # El aviso de la vuelta anterior lo pinta quien limpia, o se borraria antes de
    # poder leerse: es el mismo trato que le da el wizard.
    if pendiente:
        _aviso(pendiente)
    console.print()


def run_set_folder() -> int:
    """Punto de entrada de --set-folder. Devuelve el código de salida del proceso."""
    elegida = pick_drive_folder()
    if not elegida:
        console.print(f"\n{MARGEN}[{META}]Cancelled. Nothing was changed.[/{META}]\n")
        return 0
    path = save_folder_id(*elegida)
    console.print(f"{MARGEN}[{META}]Saved to {path.name}[/{META}]\n")
    return 0
