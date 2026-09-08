"""DOCX and PDF generation helpers."""

from __future__ import annotations
import platform
import shutil
import subprocess
import tempfile
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


def convert_docx_to_pdf(docx_file: Path) -> None:
    """Convert a DOCX to PDF using LibreOffice headless. Raises RuntimeError on failure."""
    outdir = docx_file.parent
    pdf_file = docx_file.with_suffix(".pdf")

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
                str(docx_file),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            raise RuntimeError(f"PDF conversion failed: {result.stderr.strip()}")
        if not pdf_file.exists():
            raise RuntimeError("PDF conversion failed: LibreOffice produced no output")
    except FileNotFoundError:
        raise RuntimeError("LibreOffice not found — install: brew install --cask libreoffice")
    except subprocess.TimeoutExpired:
        raise RuntimeError("PDF conversion timed out")
    finally:
        shutil.rmtree(profile, ignore_errors=True)
