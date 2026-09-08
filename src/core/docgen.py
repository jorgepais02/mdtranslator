"""DOCX and PDF generation helpers."""

from __future__ import annotations
import platform
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import CONFIG, PROJECT_ROOT


def generate_docx_document(md_file: Path, lang_code: str) -> Path:
    """Generate a DOCX from a translated .md file."""
    from document.converter import convert

    docx_file  = md_file.with_suffix(".docx")
    header_cfg = CONFIG.get("document", {}).get("header_image")
    header_img = Path("public/header.png") if not header_cfg else (PROJECT_ROOT / header_cfg)

    convert(md_file, docx_file, lang=lang_code, header=header_img)
    return docx_file


def _soffice_exe() -> str:
    if platform.system() == "Darwin":
        mac_path = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
        if Path(mac_path).exists():
            return mac_path
    return "soffice"


def _soffice_convert(docx_files: list[Path], outdir: Path, timeout: int) -> None:
    """Invoca LibreOffice una vez para todos los ficheros que van a la misma carpeta."""
    # LibreOffice locks a single shared user profile: concurrent calls that reuse it
    # attach to the running instance and return 0 without writing any PDF. A private
    # profile per call keeps parallel conversions independent.
    profile = Path(tempfile.mkdtemp(prefix="mdtranslator-lo-"))
    try:
        result = subprocess.run(
            [
                _soffice_exe(),
                f"-env:UserInstallation=file://{profile}",
                "--headless", "--norestore", "--nofirststartwizard", "--nologo",
                "--convert-to", "pdf",
                "--outdir", str(outdir),
                *(str(f) for f in docx_files),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"PDF conversion failed: {result.stderr.strip()}")
    except FileNotFoundError:
        raise RuntimeError("LibreOffice not found — install: brew install --cask libreoffice")
    except subprocess.TimeoutExpired:
        raise RuntimeError("PDF conversion timed out")
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def convert_docx_to_pdf(docx_file: Path) -> None:
    """Convert a DOCX to PDF using LibreOffice headless. Raises RuntimeError on failure."""
    _soffice_convert([docx_file], docx_file.parent, timeout=180)
    if not docx_file.with_suffix(".pdf").exists():
        raise RuntimeError("PDF conversion failed: LibreOffice produced no output")


def convert_many_to_pdf(docx_files: list[Path], max_workers: int = 4) -> dict[Path, str]:
    """Convierte varios DOCX a PDF. API: {docx que ha fallado: motivo}.

    Arrancar LibreOffice cuesta ~1,4s y convertir un documento ~0,2s, así que el
    proceso es casi todo el gasto: una sola invocación para los ocho documentos de una
    carpeta tarda lo que tres invocaciones sueltas.

    Se agrupa por carpeta porque --outdir es uno solo, y los grupos van en paralelo:
    en serie, un documento en cuatro idiomas pagaba cuatro arranques seguidos y salía
    más caro que no agrupar nada. Un fallo se atribuye al fichero cuyo PDF falta.
    """
    if not docx_files:
        return {}

    por_carpeta: dict[Path, list[Path]] = {}
    for f in docx_files:
        por_carpeta.setdefault(f.parent, []).append(f)

    def _grupo(item: tuple[Path, list[Path]]) -> dict[Path, str]:
        outdir, grupo = item
        try:
            _soffice_convert(grupo, outdir, timeout=180 + 30 * len(grupo))
        except RuntimeError as e:
            motivo = str(e)
        else:
            motivo = "LibreOffice produced no output"
        return {f: motivo for f in grupo if not f.with_suffix(".pdf").exists()}

    fallos: dict[Path, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(len(por_carpeta), max_workers))) as ex:
        for parciales in ex.map(_grupo, por_carpeta.items()):
            fallos.update(parciales)
    return fallos
