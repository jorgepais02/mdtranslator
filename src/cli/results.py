from rich.table import Table
from rich.text import Text
from rich.console import Group
from rich.columns import Columns
from rich.rule import Rule
from rich import box
from .styles import (console, elide, GREEN, BLUE, CYAN, DIM, BRIGHT, FG, RED,
                     VERSION, YELLOW)

def _short_warning(msg: str) -> str:
    msg = str(msg)
    lo  = msg.lower()

    # ── Traduccion: el mensaje agregado se mira primero ───────────────
    # FallbackTranslator mete dentro del suyo el error de cada proveedor, asi que un
    # 429 del traductor Gemini viajaba con "RESOURCE_EXHAUSTED" dentro y las reglas
    # del refinado —que van debajo— lo anunciaban como "text not refined" en un
    # documento que no habia llegado ni a traducirse. Medido con --lang XX: DeepL 400,
    # Azure 400 "the target language is not valid" y Gemini 429, y la pantalla final
    # decia "Gemini quota exceeded — text not refined".
    if "all translation providers failed" in lo:
        fallos = [l.strip() for l in msg.splitlines()[1:] if l.strip()]
        def _es_cuota(linea: str) -> bool:
            b = linea.lower()
            return "429" in linea or "quota" in b or "resource_exhausted" in b
        # "todos sin cuota" solo si lo son todos: con dos 400 y un 429 seria mentira,
        # y lo que hay que arreglar no es esperar sino el codigo de idioma.
        if fallos and all(_es_cuota(f) for f in fallos):
            return "All translation providers are out of quota — retry later"
        if "target language is not valid" in lo or "target_lang" in lo:
            return "Target language rejected by the providers — check the code"
        return "All translation providers failed — check API keys and quotas"

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
    # El caso agregado se resuelve arriba; aqui quedan los que llegan pelados
    # (un proveedor suelto invocado desde un modulo, o un fallo de configuracion).
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


# LANG(6) + STATUS(6) + TIME(7), cinco bordes y dos de relleno por columna: lo que
# queda es para los nombres, y se reparte aqui en vez de dejarselo a rich.
_FIJAS = 6 + 6 + 7 + 5 + 10
_MIN_NOMBRE = 18


def _anchos(multi: bool, ancho: int) -> tuple[int, int | None]:
    """Cuanto mide cada columna de nombre, y si cabe la del fichero. API: (source, file).

    Con el nombre en crudo rich lo envuelve, y en un modulo entero cada fila ocupaba
    tres renglones: "6. Jaulas de Faraday en / investigaciones forenses DFIR / (I).md"
    dos veces por fila, porque SOURCE y FILE son casi la misma cadena. Dieciseis
    tareas eran cuarenta y cinco lineas de tabla y el pie se iba de la pantalla.
    Recortar es lo que hace el resto de las vistas (styles.elide), y el reparto es
    explicito: mitad y mitad, y si no llegan a _MIN_NOMBRE se sacrifica FILE —el
    nombre de salida es el de la fuente con el idioma detras— antes que dejar las dos
    columnas ilegibles.
    """
    libre = max(_MIN_NOMBRE, ancho - _FIJAS)
    if not multi:
        return libre, libre
    mitad = libre // 2
    if mitad < _MIN_NOMBRE:
        return libre, None
    return mitad, libre - mitad


def _agrupar(avisos: list[tuple[str, str | None, str]]) -> list[tuple[str, str | None, str]]:
    """El mismo aviso en varios documentos, en una sola linea. API: la lista corta.

    Con dieciseis tareas en arabe y chino sin cuota eran dieciseis filas identicas
    debajo de la tabla, y el bloque Unfinished —lo unico accionable de la pantalla— se
    iba por abajo en un terminal de cincuenta lineas. Cual de los documentos se quedo
    sin refinar no es accionable: el comando de reintento los repasa todos y la cache
    se salta los que ya estan; lo que se lee es cuantos y en que idiomas. Misma forma
    que la linea del cambio de modelo, que ya se colapsa por lo mismo.
    """
    grupos: dict[str, list[tuple[str, str | None]]] = {}
    for lang, source, msg in avisos:
        grupos.setdefault(msg, []).append((lang, source))
    salida: list[tuple[str, str | None, str]] = []
    for msg, filas in grupos.items():
        if len(filas) == 1:
            salida.append((filas[0][0], filas[0][1], msg))
            continue
        idiomas = list(dict.fromkeys(l for l, _ in filas if l))
        cuales  = f" ({', '.join(idiomas)})" if idiomas else ""
        salida.append(("", None, f"{len(filas)} documents{cuales} · {msg}"))
    return salida


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
    # sitio que necesita el nombre del fichero. Los nombres van recortados a mano y
    # con no_wrap: el reparto lo decide _anchos, porque dejandoselo a rich cada fila
    # se envolvia en tres renglones (ver _anchos).
    ancho_src, ancho_file = _anchos(multi, console.width)
    file_table.add_column("LANG",   style=CYAN,  width=6, no_wrap=True)
    if multi:
        file_table.add_column("SOURCE", style=DIM, no_wrap=True, width=ancho_src)
    if ancho_file:
        file_table.add_column("FILE", style=FG, no_wrap=True, width=ancho_file)
    file_table.add_column("STATUS", width=6, justify="center")
    file_table.add_column("TIME",   style=DIM, justify="right", width=7, no_wrap=True)

    for r in results:
        status = Text("✓", style=GREEN) if r["ok"] else Text("✗", style=RED)
        row = [r["lang"]]
        if multi:
            row.append(elide(r.get("source", "—"), ancho_src))
        if ancho_file:
            row.append(elide(r["file"], ancho_file))
        row.extend([status, f"{r['time']:.1f}s"])
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
            gdocs_table.add_column("SOURCE", style=DIM, no_wrap=True, width=ancho_src)
        gdocs_table.add_column("URL", overflow="ellipsis")

        for r in results:
            if r.get("gdocs_url"):
                url = r["gdocs_url"]
                short_url = url if len(url) <= 45 else url[:42] + "…"
                link = Text()
                link.append(short_url, style=f"link {url} {BLUE} underline")
                row = [r["lang"]]
                if multi:
                    row.append(elide(r.get("source", "—"), ancho_src))
                row.append(link)
                gdocs_table.add_row(*row)

        parts.append(gdocs_table)
        parts.append(Text())

    # ── Warnings ──────────────────────────────────────────────────────
    warnings = _agrupar([(r["lang"], r.get("source"), _short_warning(r["warning"]))
                         for r in results if r.get("warning")])
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
        # El motivo es el predicado entero, no un complemento: "had no quota" se lee,
        # pero "had failed" no es ingles, y `reason` vale las dos cosas. El valor crudo
        # se queda como esta para --json.
        dicho = f"had {reason}" if reason == "no quota" else reason
        warnings.append(("", None, f"{cuantos} {plural} refined with {used} — "
                                   f"{instead_of} {dicho}"))
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
                # Vacio y no "—": las unicas filas sin fuente son las que ya no hablan
                # de un documento suelto (el aviso agrupado, el cambio de modelo), y
                # ahi el guion se leia como "fuente desconocida".
                fila.append(source or "")
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