from rich.table import Table
from rich.text import Text
from rich.console import Group
from rich.columns import Columns
from rich.rule import Rule
from rich import box
from .styles import console, GREEN, BLUE, CYAN, DIM, BRIGHT, FG, RED, VERSION, YELLOW

def _short_warning(msg: str) -> str:
    msg = str(msg)
    lo  = msg.lower()

    # ── Modelos de IA (refinado) ──────────────────────────────────────
    # Con varios modelos en la lista, el aviso ya no es de Gemini sino del conjunto:
    # decir "Gemini quota exceeded" cuando tambien se intento con Groq seria mentir
    # sobre lo que hay que arreglar.
    if "no quota left on any model" in lo:
        return "No AI model has quota left — text not refined"
    if "no ai model configured" in lo:
        return "No AI model configured — add a key to .env (e.g. GEMINI_API_KEY)"
    if "no ai model answered" in lo:
        return "No AI model answered — text not refined"

    # ── Gemini refiner ────────────────────────────────────────────────
    if "resource_exhausted" in lo or ("quota" in lo and "gemini" in lo) \
            or ("429" in msg and "gemini" in lo):
        return "Gemini quota exceeded — text not refined"
    if "gemini_api_key" in lo or ("gemini" in lo and "api_key" in lo):
        return "Gemini API key not set — text not refined"
    if "gemini" in lo and ("init failed" in lo or "unavailable" in lo
                           or "500" in msg or "503" in msg):
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
    # Solo si de verdad viene de Google: un 503 de Gemini caia aqui y se anunciaba
    # como un fallo de Drive en una ejecucion que ni siquiera subia nada.
    if ("500" in msg or "503" in msg or "server error" in lo) \
            and ("google" in lo or "drive" in lo):
        return "Google Drive server error — retry"

    # ── Generic timeout ───────────────────────────────────────────────
    if "timeout" in lo or "timed out" in lo:
        return "Request timed out"

    # ── Fallback: truncate at word boundary ───────────────────────────
    if len(msg) <= 80:
        return msg
    cut = msg[:77].rsplit(" ", 1)[0]
    return cut + "…"


def _por_modelo(results: list[dict]) -> dict[tuple, int]:
    """Cuántos documentos refinó cada modelo que no era el preferido. API: dict."""
    cuenta: dict[tuple, int] = {}
    for r in results:
        cambio = r.get("refine_model")
        if not cambio:
            continue
        clave = (cambio["used"], cambio["instead_of"], cambio["reason"])
        cuenta[clave] = cuenta.get(clave, 0) + 1
    return cuenta


def show_results(results: list[dict], total_time: float, version: str = VERSION,
                 retry_cmd: str | None = None,
                 retry_note: str | None = None):
    parts = []
    # Several source files land in one table, so name the source to keep rows apart.
    multi = len({r.get("source") for r in results if r.get("source")}) > 1

    # ── Results table ─────────────────────────────────────────────────
    # Los titulos van en blanco y no en azul: en esta pantalla no hay cursor, y el
    # azul competia con la columna de ✓, que es lo unico que se viene a mirar aqui.
    parts.append(Text("Results", style=f"bold {BRIGHT}"))

    file_table = Table(
        show_edge=True,
        border_style=DIM,
        box=box.ROUNDED,
        padding=(0, 1),
        header_style=DIM,   # dim uppercase headers per spec
    )
    # Anchos ajustados al contenido: con 8 cada una, LANG y STATUS se quedaban el
    # sitio que necesita el nombre del fichero. FILE es la unica columna elastica y
    # no lleva no_wrap: con el, rich le daba todo el ancho y vaciaba a las demas.
    file_table.add_column("LANG",   style=CYAN,  width=6, no_wrap=True)
    if multi:
        file_table.add_column("SOURCE", style=DIM, overflow="ellipsis")
    file_table.add_column("FILE",   style=FG,   overflow="ellipsis")
    file_table.add_column("STATUS", width=6, justify="center")
    file_table.add_column("TIME",   style=DIM, justify="right", width=7, no_wrap=True)

    for r in results:
        status = Text("✓", style=GREEN) if r["ok"] else Text("✗", style=RED)
        row = [r["lang"]]
        if multi:
            row.append(r.get("source", "—"))
        row.extend([r["file"], status, f"{r['time']:.1f}s"])
        file_table.add_row(*row)

    parts.append(file_table)
    parts.append(Text())

    # ── Google Docs table ─────────────────────────────────────────────
    if any(r.get("gdocs_url") for r in results):
        parts.append(Text("Google Docs", style=f"bold {BRIGHT}"))

        gdocs_table = Table(
            show_edge=True,
            border_style=DIM,
            box=box.ROUNDED,
            padding=(0, 1),
            header_style=DIM,
        )
        gdocs_table.add_column("LANG", style=CYAN, width=6, no_wrap=True)
        if multi:
            gdocs_table.add_column("SOURCE", style=DIM, overflow="ellipsis")
        gdocs_table.add_column("URL", overflow="ellipsis")

        for r in results:
            if r.get("gdocs_url"):
                url = r["gdocs_url"]
                short_url = url if len(url) <= 45 else url[:42] + "…"
                link = Text()
                link.append(short_url, style=f"link {url} {BLUE} underline")
                row = [r["lang"]]
                if multi:
                    row.append(r.get("source", "—"))
                row.append(link)
                gdocs_table.add_row(*row)

        parts.append(gdocs_table)
        parts.append(Text())

    # ── Warnings ──────────────────────────────────────────────────────
    warnings = [(r["lang"], r.get("source"), _short_warning(r["warning"]))
                for r in results if r.get("warning")]
    # El modelo con el que se refinó es un aviso más, y solo aparece cuando no fue el
    # preferido: "salió, pero no del que pediste" es justo lo que hay que contar, y
    # amarillo ya significa "avisa", así que no hace falta ningún color nuevo.
    #
    # Va en **una** línea por cambio, no una por documento: con dieciséis tareas en
    # árabe y chino eran dieciséis filas idénticas debajo de la tabla, y la línea que
    # de verdad se lee es cuántos documentos salieron de otro modelo.
    for cambio, cuantos in _por_modelo(results).items():
        used, instead_of, reason = cambio
        plural = "document" if cuantos == 1 else "documents"
        warnings.append(("", None, f"{cuantos} {plural} refined with {used} — "
                                   f"{instead_of} had {reason}"))
    if warnings:
        parts.append(Text("Warnings", style=f"bold {YELLOW}"))
        # Rejilla en vez de líneas sueltas: un aviso largo se partía y la segunda
        # línea empezaba en la columna 0, desalineada del idioma que la encabeza.
        warn_grid = Table.grid(padding=(0, 2))
        warn_grid.add_column(style=CYAN, justify="right", width=5, no_wrap=True)
        if multi:
            warn_grid.add_column(style=DIM, no_wrap=True, overflow="ellipsis", max_width=20)
        warn_grid.add_column(style=DIM, overflow="fold")
        for lang, source, msg in warnings:
            fila = [lang]
            if multi:
                fila.append(source or "—")
            fila.append(msg)
            warn_grid.add_row(*fila)
        parts.append(warn_grid)
        parts.append(Text())

    # ── Lo que quedó a medias ─────────────────────────────────────────
    # Un documento sin refinar está subido y se usa, así que no es un fallo; pero si
    # nadie dice que se puede recuperar, se queda así para siempre. El comando va
    # escrito entero porque la pregunta de verdad no es "¿qué falta?" sino "¿y ahora
    # qué hago?", y relanzar sale barato: lo ya hecho está en la caché.
    a_medias = [r for r in results if r.get("incomplete")]
    fallidos = [r for r in results if not r["ok"]]
    if a_medias or fallidos:
        parts.append(Text("Unfinished", style=f"bold {YELLOW}"))
        # La sangría la pone una columna vacía, como en Warnings: un comando largo se
        # parte, y sin ella la segunda línea arrancaba en la columna 0 y se leía como
        # otro comando distinto.
        detalle = Table.grid(padding=(0, 0))
        detalle.add_column(width=3, no_wrap=True)
        detalle.add_column(overflow="fold")
        if fallidos:
            detalle.add_row("", Text(f"{len(fallidos)} of {len(results)} documents did "
                                     f"not come out.", style=DIM))
        if a_medias:
            detalle.add_row("", Text(f"{len(a_medias)} of {len(results)} documents are "
                                     f"missing the refining pass.", style=DIM))
        if retry_note:
            detalle.add_row("", Text(retry_note, style=DIM))
        detalle.add_row("", Text("Run the same command again — only what is missing is "
                                 "redone, the rest comes from the cache.", style=DIM))
        if retry_cmd:
            detalle.add_row("", "")
            detalle.add_row("", Text(retry_cmd, style=BRIGHT))
        parts.append(detalle)
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
            style=f"bold {YELLOW}",
        )
    else:
        footer_left.append(f"✓ Completed in {total_time:.1f}s", style=f"bold {GREEN}")

    footer_right = Text(f"mdtranslator v{version}", style=DIM, justify="right")

    console.print(Columns([footer_left, footer_right], expand=True))
    console.print()