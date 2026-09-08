"""
Selector interactivo de la carpeta de Google Drive.

API:
    pick_drive_folder(manager=None) -> str | None
    save_folder_id(folder_id) -> Path
    extract_folder_id(text) -> str | None

CLI:
    python -m src.cli.main --set-folder
"""

import json
import re
from pathlib import Path

import questionary

from .prompts import ask_select, ask_text
from .styles import console, elide, BRIGHT, CYAN, DIM, FG, GREEN

from core.config import PROJECT_ROOT

ROOT = "root"

_URL_ID_RE = re.compile(r"/folders/([A-Za-z0-9_-]{10,})|[?&]id=([A-Za-z0-9_-]{10,})")
_BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")

# Sin emoji: 📁 ocupa dos celdas del terminal y ✓ una, asi que los nombres de las
# carpetas nunca quedaban alineados entre si. El sufijo "/" distingue igual de bien
# una carpeta y no rompe la cuadricula.
_USE    = "Usar esta carpeta"
_UP     = "Subir un nivel"
_PASTE  = "Pegar una URL de Drive"
_CANCEL = "Cancelar"


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


def save_folder_id(folder_id: str) -> Path:
    """Escribe drive.folder_id en config.json conservando el resto de la configuración."""
    path = PROJECT_ROOT / "config.json"
    if path.exists():
        cfg = json.loads(path.read_text(encoding="utf-8"))
    else:
        example = PROJECT_ROOT / "config.example.json"
        cfg = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
    cfg.setdefault("drive", {})["folder_id"] = folder_id
    path.write_text(json.dumps(cfg, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _ask(fn):
    try:
        return fn()
    except KeyboardInterrupt:
        return None


def pick_drive_folder(manager=None) -> str | None:
    """Navega por las carpetas de Drive y devuelve el ID elegido, o None si se cancela."""
    from integrations.drive import GoogleDocsManager

    g = manager or GoogleDocsManager(console=console)

    current, label = ROOT, "Mi unidad"
    camino: list[str] = [label]          # migas de pan: donde estas, no solo el nombre
    while True:
        ruta = " / ".join(camino)
        try:
            subs = g.list_subfolders(current)
        except Exception as e:
            console.print(f"[red]✗ No se pudo leer la carpeta: {e}[/red]")
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
        choices += [_USE, _PASTE, _CANCEL]

        console.print(f"\n[{DIM}]En:[/{DIM}] "
                      f"[{BRIGHT}]{elide(ruta, max(16, console.width - 28))}[/{BRIGHT}]"
                      f"  [{DIM}]{_plural(len(subs), 'subcarpeta', 'subcarpetas')}[/{DIM}]")

        answer = ask_select("Elige la carpeta de destino", choices)

        if answer is None or answer == _CANCEL:
            return None

        if answer == _USE:
            if current == ROOT:
                current = g.get_folder_info(ROOT)["id"]  # id real de "Mi unidad"
            console.print(f"[{GREEN}]✓[/{GREEN}] [{DIM}]Carpeta seleccionada:[/{DIM}] "
                          f"[{BRIGHT}]{elide(ruta, max(16, console.width - 26))}[/{BRIGHT}]")
            return current

        if answer == _UP:
            parents = g.get_folder_info(current).get("parents") or [ROOT]
            current = parents[0]
            label = g.get_folder_info(current)["name"] if current != ROOT else "Mi unidad"
            camino = camino[:-1] or [label]
            continue

        if answer == _PASTE:
            pasted = ask_text("Pega la URL (o el ID) de la carpeta")
            folder_id = extract_folder_id(pasted or "")
            if not folder_id:
                console.print("[yellow]⚠ No he reconocido ninguna carpeta en eso.[/yellow]")
                continue
            try:
                info = g.get_folder_info(folder_id)
            except Exception as e:
                console.print(f"[red]✗ No puedo acceder a esa carpeta: {e}[/red]")
                continue
            console.print(f"[{GREEN}]✓[/{GREEN}] [{DIM}]Carpeta seleccionada:[/{DIM}] "
                          f"[{BRIGHT}]{elide(info['name'], max(16, console.width - 26))}[/{BRIGHT}]")
            return info["id"]

        entry = by_label[answer]
        current, label = entry["id"], entry["name"]
        camino.append(label)


def run_set_folder() -> int:
    """Punto de entrada de --set-folder. Devuelve el código de salida del proceso."""
    console.print("\n[bold white]mdtranslator[/bold white] [dim]— carpeta de Google Drive[/dim]")
    folder_id = pick_drive_folder()
    if not folder_id:
        console.print(f"\n[{DIM}]Cancelado. No se ha cambiado nada.[/{DIM}]\n")
        return 0
    path = save_folder_id(folder_id)
    console.print(f"[{DIM}]Guardado en {path.name}[/{DIM}]\n")
    return 0
