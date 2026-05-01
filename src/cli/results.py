from rich.table import Table
from rich.text import Text
from rich.console import Group
from rich.columns import Columns
from rich.rule import Rule
from rich import box
from .styles import console, GREEN, BLUE, CYAN, DIM, BRIGHT, FG, YELLOW

def _short_warning(msg: str) -> str:
    msg = str(msg)
    lo  = msg.lower()

    # ── Gemini refiner ────────────────────────────────────────────────
    if "resource_exhausted" in lo or ("quota" in lo and "gemini" in lo) \
            or ("429" in msg and "gemini" in lo):
        return "Gemini quota exceeded — text not refined"
    if "gemini_api_key" in lo or ("gemini" in lo and "api_key" in lo):
        return "Gemini API key not set — text not refined"
    if "gemini" in lo and ("init failed" in lo or "unavailable" in lo):
        return "Gemini unavailable — text not refined"

    # ── Translation failures ──────────────────────────────────────────
    if "all translation providers failed" in lo:
        return "All translation providers failed — check API keys and quotas"
    if "no translation provider" in lo:
        return "No translation provider configured — add API key to .env"
    if "deepl quota exceeded" in lo or ("quota exceeded" in lo and "deepl" in lo):
        return "DeepL quota exceeded"
    if "out of call volume quota" in lo or ("quota" in lo and "azure" in lo):
        return "Azure quota exceeded"
    if "deepl_api_key not found" in lo:
        return "DeepL API key not set — add DEEPL_API_KEY to .env"
    if "azure_translator_key not found" in lo:
        return "Azure API key not set — add AZURE_TRANSLATOR_KEY to .env"
    if "request failed" in lo and ("deepl" in lo or "azure" in lo or "gemini" in lo):
        return "Translation API timed out" if "timeout" in lo else "Translation API request failed"

    # ── Missing packages ─────────────────────────────────────────────
    if "no module named 'pil'" in lo or "no module named 'pillow'" in lo:
        return "Pillow not installed — run: pip install Pillow"

    # ── PDF ───────────────────────────────────────────────────────────
    if "libreoffice not found" in lo:
        return "LibreOffice not found — PDF skipped (DOCX available)"
    if "pdf conversion failed" in lo:
        return "PDF conversion failed — DOCX available"
    if "pdf conversion timed out" in lo:
        return "PDF conversion timed out — DOCX available"

    # ── Drive / network ───────────────────────────────────────────────
    if "read operation timed out" in lo or ("timeout" in lo and "drive" in lo):
        return "Google Drive request timed out — retry"
    if "auth" in lo and ("credential" in lo or "token" in lo or "google" in lo):
        return "Google Drive auth error — check credentials"
    if "500" in msg or "503" in msg or "server error" in lo:
        return "Google Drive server error — retry"

    # ── Generic timeout ───────────────────────────────────────────────
    if "timeout" in lo or "timed out" in lo:
        return "Request timed out"

    # ── Fallback: truncate at word boundary ───────────────────────────
    if len(msg) <= 80:
        return msg
    cut = msg[:77].rsplit(" ", 1)[0]
    return cut + "…"


def show_results(results: list[dict], total_time: float, version: str = "2.1.0"):
    parts = []

    # ── Results table ─────────────────────────────────────────────────
    parts.append(Text("Results", style=f"bold {BLUE}"))

    file_table = Table(
        show_edge=True,
        border_style=DIM,
        box=box.ROUNDED,
        padding=(0, 1),
        header_style=DIM,   # dim uppercase headers per spec
    )
    file_table.add_column("LANG",   style=CYAN,  width=8)
    file_table.add_column("FILE",   style=FG)
    file_table.add_column("STATUS", width=8)
    file_table.add_column("TIME",   style=DIM, justify="right", width=8)

    for r in results:
        status = Text("✓", style=GREEN) if r["ok"] else Text("✗", style="#e05555")
        file_table.add_row(r["lang"], r["file"], status, f"{r['time']:.1f}s")

    parts.append(file_table)
    parts.append(Text())

    # ── Google Docs table ─────────────────────────────────────────────
    if any(r.get("gdocs_url") for r in results):
        parts.append(Text("Google Docs", style=f"bold {BLUE}"))

        gdocs_table = Table(
            show_edge=True,
            border_style=DIM,
            box=box.ROUNDED,
            padding=(0, 1),
            header_style=DIM,
        )
        gdocs_table.add_column("LANG", style=CYAN, width=8)
        gdocs_table.add_column("URL")

        for r in results:
            if r.get("gdocs_url"):
                url = r["gdocs_url"]
                short_url = url if len(url) <= 45 else url[:42] + "…"
                link = Text()
                link.append(short_url, style=f"link {url} {BLUE} underline")
                gdocs_table.add_row(r["lang"], link)

        parts.append(gdocs_table)
        parts.append(Text())

    # ── Warnings ──────────────────────────────────────────────────────
    warnings = [(r["lang"], r["warning"]) for r in results if r.get("warning")]
    if warnings:
        parts.append(Text("Warnings", style=f"bold {YELLOW}"))
        for lang, msg in warnings:
            line = Text()
            line.append(f"  {lang:>3}  ", style=CYAN)
            line.append(_short_warning(msg), style=DIM)
            parts.append(line)
        parts.append(Text())

    # ── Footer ────────────────────────────────────────────────────────
    parts.append(Rule(style=DIM))

    console.print(Group(*parts))

    failed = any(not r["ok"] for r in results)
    footer_left = Text()
    if failed:
        ok_count = sum(1 for r in results if r["ok"])
        footer_left.append(
            f"⚠ Completed with errors ({ok_count}/{len(results)}) in {total_time:.1f}s",
            style="bold yellow",
        )
    else:
        footer_left.append(f"✓ Completed in {total_time:.1f}s", style=f"bold {GREEN}")

    footer_right = Text(f"mdtranslator v{version}", style=DIM, justify="right")

    console.print(Columns([footer_left, footer_right], expand=True))
    console.print()