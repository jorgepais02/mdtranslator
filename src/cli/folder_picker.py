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

from .styles import console, WIZARD_STYLE, GREEN, DIM, FG

from core.config import PROJECT_ROOT

ROOT = "root"

_URL_ID_RE = re.compile(r"/folders/([A-Za-z0-9_-]{10,})|[?&]id=([A-Za-z0-9_-]{10,})")
_BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")

_USE    = "✓  Usar esta carpeta"
_UP     = "↑  Subir un nivel"
_PASTE  = "🔗  Pegar una URL de Drive"
_CANCEL = "✗  Cancelar"


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
    while True:
        try:
            subs = g.list_subfolders(current)
        except Exception as e:
            console.print(f"[red]✗ No se pudo leer la carpeta: {e}[/red]")
            return None

        by_label = {f"📁  {f['name']}": f for f in subs}
        choices = [_USE, *by_label]
        if current != ROOT:
            choices.append(_UP)
        choices += [_PASTE, _CANCEL]

        console.print(f"\n[{DIM}]Carpeta actual:[/{DIM}] [{FG}]{label}[/{FG}]"
                      f"  [{DIM}]({len(subs)} subcarpeta(s))[/{DIM}]")

        answer = _ask(lambda: questionary.select(
            "Elige la carpeta de destino",
            choices=choices,
            style=WIZARD_STYLE,
            erase_when_done=True,
        ).ask())

        if answer is None or answer == _CANCEL:
            return None

        if answer == _USE:
            if current == ROOT:
                current = g.get_folder_info(ROOT)["id"]  # id real de "Mi unidad"
            console.print(f"[{GREEN}]✓ Carpeta seleccionada:[/{GREEN}] [{FG}]{label}[/{FG}]")
            return current

        if answer == _UP:
            parents = g.get_folder_info(current).get("parents") or [ROOT]
            current = parents[0]
            label = g.get_folder_info(current)["name"] if current != ROOT else "Mi unidad"
            continue

        if answer == _PASTE:
            pasted = _ask(lambda: questionary.text(
                "Pega la URL (o el ID) de la carpeta",
                style=WIZARD_STYLE,
            ).ask())
            folder_id = extract_folder_id(pasted or "")
            if not folder_id:
                console.print("[yellow]⚠ No he reconocido ninguna carpeta en eso.[/yellow]")
                continue
            try:
                info = g.get_folder_info(folder_id)
            except Exception as e:
                console.print(f"[red]✗ No puedo acceder a esa carpeta: {e}[/red]")
                continue
            console.print(f"[{GREEN}]✓ Carpeta seleccionada:[/{GREEN}] [{FG}]{info['name']}[/{FG}]")
            return info["id"]

        entry = by_label[answer]
        current, label = entry["id"], entry["name"]


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
