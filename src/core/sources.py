"""
Descubrimiento y normalización de ficheros fuente.

API:
    collect_sources(selection, sources_dir=SOURCES_DIR) -> list[Path]
    list_source_folders(sources_dir=SOURCES_DIR) -> list[tuple[Path, int]]
    needs_formatting(path) -> bool
    load_markdown(path, allow_format=True) -> tuple[str, str | None]
"""

import re
from pathlib import Path

from .config import PROJECT_ROOT, SOURCES_DIR

ALL_FILES  = "Process ALL files"
VALID_EXTS = {".md", ".txt"}

# Un .md ya formateado siempre trae al menos un heading ATX.
_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)

# Al deduplicar por stem, el .md gana: un .txt homónimo es su materia prima.
_EXT_PRIORITY = {".md": 0, ".txt": 1}


def _dedupe(paths: list[Path]) -> list[Path]:
    by_stem: dict[str, Path] = {}
    for p in sorted(paths, key=lambda q: (q.stem.lower(), _EXT_PRIORITY.get(q.suffix.lower(), 9))):
        by_stem.setdefault(p.stem, p)
    return sorted(by_stem.values(), key=lambda q: q.name.lower())


def _en_carpeta(carpeta: Path) -> list[Path]:
    """Las fuentes de una carpeta, sin bajar a sus subcarpetas.

    No es recursivo a propósito: una subcarpeta de sources/ es un lote —un módulo, un
    curso— y lo que contiene son sus documentos. Bajando el árbol, "todos los de este
    módulo" arrastraría los del anterior en cuanto se anidaran dos.
    """
    if not carpeta.exists():
        return []
    return _dedupe([p for p in carpeta.iterdir()
                    if p.is_file() and p.suffix.lower() in VALID_EXTS])


def _ruta(selection: str, sources_dir: Path) -> Path:
    p = Path(selection)
    if p.is_absolute():
        return p
    if selection.startswith("sources/"):
        return PROJECT_ROOT / selection
    return sources_dir / selection


def collect_sources(selection: str, sources_dir: Path = SOURCES_DIR) -> list[Path]:
    """
    selection — ALL_FILES, un nombre suelto, una subcarpeta de sources/, una ruta
    'sources/...' o una ruta absoluta.

    ALL_FILES son los ficheros sueltos de sources/, no todo el arbol: las subcarpetas
    son lotes y se eligen por su nombre. Dentro de un lote los stems duplicados
    colapsan en una sola entrada, de modo que apuntes.md y apuntes.txt no compiten por
    el mismo fichero de salida.
    """
    if selection == ALL_FILES:
        return _en_carpeta(sources_dir)

    path = _ruta(selection, sources_dir)
    if path.is_dir():
        return _en_carpeta(path)
    return [path] if path.is_file() else []


def list_source_folders(sources_dir: Path = SOURCES_DIR) -> list[tuple[Path, int]]:
    """Subcarpetas de sources/ que traen fuentes, y cuántas. API: [(Path, n)].

    Las vacías no salen: una carpeta sin .md ni .txt es una opción que no lleva a
    ningún sitio, y el wizard tendría que avisar de que no hay nada dentro.
    """
    if not sources_dir.exists():
        return []
    lotes = [(d, len(_en_carpeta(d)))
             for d in sorted(sources_dir.iterdir(), key=lambda p: p.name.lower())
             if d.is_dir()]
    return [(d, n) for d, n in lotes if n]


def needs_formatting(path: Path) -> bool:
    """
    True cuando la fuente es texto en crudo y debe pasar por Gemini antes de traducir.

    Todo .txt es crudo. Un .md solo lo es si no tiene ni un heading ATX, es decir,
    es una transcripción que casualmente lleva esa extensión.
    """
    if path.suffix.lower() == ".txt":
        return True
    try:
        return _HEADING_RE.search(path.read_text(encoding="utf-8")) is None
    except OSError:
        return False


def load_markdown(path: Path, allow_format: bool = True) -> tuple[str, str | None]:
    """
    Lee una fuente como Markdown académico, invocando Gemini si está en crudo.

    Un .txt se escribe además como .md hermano para que las siguientes ejecuciones lo
    reutilicen; un .md en crudo se formatea solo en memoria y nunca se sobrescribe.
    Devuelve (markdown, warning): ante un fallo devuelve el texto crudo y un aviso,
    de forma que el pipeline continúe en vez de abortar el fichero.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        return "", f"Could not read {path.name}: {e}"

    if not raw.strip():
        return "", f"{path.name} is empty"

    if not allow_format or not needs_formatting(path):
        return raw, None

    try:
        from integrations.generate_md import generate_markdown
        md = generate_markdown(raw.strip(), title=path.stem)
    except Exception as e:
        return raw, f"Gemini formatting failed for {path.name}: {e}"

    if not md.strip():
        return raw, f"Gemini returned nothing for {path.name}"

    md = md.rstrip() + "\n"

    if path.suffix.lower() == ".txt":
        try:
            path.with_suffix(".md").write_text(md, encoding="utf-8")
        except OSError as e:
            return md, f"Could not save formatted Markdown for {path.name}: {e}"

    return md, None
