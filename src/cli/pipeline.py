import io as _io
from rich.live import Live
from rich.console import Console as _Console, Group
from rich.table import Table
from rich.text import Text
from rich import box
import time
import shutil
import threading
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from langdetect import detect_langs as _detect_langs, DetectorFactory as _LDF
_LDF.seed = 0
from .styles import (console, elide as _elide, GREEN, BLUE, YELLOW, CYAN, DIM,
                     BRIGHT, FG, needs_refine)

from translators import get_translator
from translators.base import call_translate
from document.refiner import refine_markdown
from core.parser import parse_markdown_lines, rebuild_markdown_from_translations
from core.docgen import generate_docx_document, convert_many_to_pdf
from core.config import TRANSLATED_DIR, DRIVE_FOLDER_ID, CONFIG
from core.sources import collect_sources, load_markdown, needs_formatting
from integrations.drive import GoogleDocsManager


DEFAULT_MAX_WORKERS = 4
# Líneas que la vista gasta fuera de la tabla (cabecera, barra, encabezados, aire).
_VIEW_CHROME = 12
_MIN_ROWS    = 3
# Suelos por debajo de los cuales la vista deja de tener sentido, no del terminal.
_MIN_WIDTH   = 32
_MIN_BAR     = 12
_MIN_NAME    = 10
_SRC_COL     = 6
# Regla para medir tablas: console.measure() viene recortado al ancho real de la
# consola, asi que siempre respondia que si cabia. Esta no recorta nada.
_RULER = _Console(file=_io.StringIO(), width=10_000)
# Gemini free tier: por defecto una llamada cada vez. Subirlo arriesga un 429.
DEFAULT_GEMINI_WORKERS = 1

# Por debajo de esta confianza no se asume ningun idioma: langdetect confunde
# espanol con portugues o italiano en textos cortos, y acertar a medias significa
# crear una carpeta translated/pt/ con contenido espanol y subirla a Drive.
MIN_LANG_CONFIDENCE = 0.90
MIN_LANG_SAMPLE     = 60


def _ancho() -> int:
    """Ancho util del terminal. Live usa esta misma consola, asi que coincide."""
    return max(_MIN_WIDTH, console.width)


def _bar(pct: float, ancho: int, style: str, sufijo: str = "") -> Text:
    """Barra de progreso del ancho que quepa. Estaba fija a 40 y se partia en dos."""
    lleno = int(round((pct / 100) * ancho))
    return Text(" " + "█" * lleno + "░" * (ancho - lleno) + sufijo, style=style)


def _cabecera(izquierda: str, languages: list[str], ancho: int) -> Text:
    """Titulo + idiomas, recortando los idiomas antes que dejarlos caer a la linea 2."""
    header = Text()
    header.append(f" {izquierda}", style=FG)
    header.append("  →  ", style=DIM)
    libre  = ancho - len(izquierda) - 7
    listado = "  ".join(languages)
    if len(listado) > libre:
        cabidos, usado = [], 0
        for lang in languages:
            if usado + len(lang) + 2 > libre - 6:
                break
            cabidos.append(lang)
            usado += len(lang) + 2
        listado = "  ".join(cabidos) + f"  +{len(languages) - len(cabidos)}"
    header.append(listado, style=CYAN)
    return header


def detect_source_language(texts: list[str]) -> tuple[str | None, str | None]:
    """Idioma del documento a partir de su texto traducible. API: (lang, warning).

    Se analiza solo el texto real —sin almohadillas, tuberias de tabla ni URLs— y se
    exige confianza alta. Devuelve (None, aviso) cuando no hay certeza suficiente,
    en cuyo caso el pipeline no genera copia del documento en su idioma original.
    """
    sample = " ".join(texts)[:3000].strip()
    if len(sample) < MIN_LANG_SAMPLE:
        return None, "too short to detect the source language"
    try:
        best = _detect_langs(sample)[0]
    except Exception as e:
        return None, f"could not detect the source language: {e}"
    if best.prob < MIN_LANG_CONFIDENCE:
        return None, (f"unsure about the source language "
                      f"({best.lang} {best.prob:.0%}) — use --source-lang to set it")
    return best.lang, None


class PipelineView:
    def __init__(self, languages: list[str], source_file: str):
        self.languages   = languages
        self.source_file = source_file
        self.lang_status = {l: {"status": "waiting", "time": None} for l in languages}
        self.source_done = False
        self.source_time = None
        self.overall_pct = 0

    def set_source_done(self, elapsed: float):
        self.source_done = True
        self.source_time = elapsed

    def set_lang_status(self, lang: str, status: str, elapsed: float | None = None):
        self.lang_status[lang] = {"status": status, "time": elapsed}

    def set_progress(self, pct: int):
        self.overall_pct = pct

    def render(self) -> Group:
        parts = []
        ancho = _ancho()
        barra = max(_MIN_BAR, min(40, ancho - 5))

        # ── header ──────────────────────────────────────────────────────────
        parts.append(_cabecera(self.source_file, self.languages, ancho))
        parts.append(Text(f" {'─' * min(44, ancho - 2)}", style=DIM))
        parts.append(Text())

        # ── source bar ───────────────────────────────────────────────────────
        src_label = Text()
        src_label.append(" source", style=DIM)
        if self.source_done:
            src_label.append(f"   {self.source_time:.1f}s", style=DIM)
        parts.append(src_label)

        if self.source_done:
            parts.append(_bar(100, barra - 3, GREEN, "  ✓"))
        else:
            parts.append(_bar(37.5, barra, BLUE))

        parts.append(Text())
        parts.append(Text())

        # ── translation bar ──────────────────────────────────────────────────
        trans_label = Text()
        trans_label.append(" translating", style=DIM)
        if self.overall_pct > 0:
            trans_label.append(f"   {self.overall_pct}%", style=BRIGHT)
        parts.append(trans_label)

        parts.append(_bar(self.overall_pct, barra, BLUE))
        parts.append(Text())

        # ── per-language status ───────────────────────────────────────────────
        for lang, info in self.lang_status.items():
            status = info["status"] or "waiting"
            line = Text()
            line.append(f"   {lang:>3} ", style=CYAN)
            if status.startswith("✓"):
                line.append(status, style=GREEN)
            elif status in ("translating…", "refining…", "uploading…"):
                line.append(status, style=YELLOW)
            elif status.startswith("✗"):
                line.append(status, style="#dc3b3b")
            else:
                line.append(status, style=DIM)
            if info["time"]:
                line.append(f"   {info['time']:.1f}s", style=DIM)
            parts.append(line)

        return Group(*parts)


# Compact cell glyphs for the multi-file grid, where a column is only a few chars wide.
_CELL_GLYPHS = {
    "translating…": ("tr", YELLOW),
    "refining…":    ("rf", YELLOW),
    "uploading…":   ("up", YELLOW),
    "waiting":      ("·",  DIM),
}


class MultiFileView:
    """Live grid for parallel runs: one row per source file, one column per language."""

    def __init__(self, languages: list[str], stems: list[str], total_tasks: int):
        self.languages   = languages
        self.stems       = stems
        self.total_tasks = total_tasks
        self.completed   = 0
        # cells[stem][column] — columns are the requested languages plus "SRC".
        self.cells    = {s: {c: "waiting" for c in ["SRC", *languages]} for s in stems}
        self.src_lang = {s: "—" for s in stems}

    def set_source_lang(self, stem: str, lang: str | None):
        self.src_lang[stem] = lang or "—"

    def set_status(self, stem: str, column: str, status: str, elapsed: float | None = None):
        if stem in self.cells and column in self.cells[stem]:
            self.cells[stem][column] = status

    def mark_completed(self):
        self.completed += 1

    @property
    def pct(self) -> int:
        if not self.total_tasks:
            return 100
        return int((self.completed / self.total_tasks) * 100)

    def _cell(self, status: str) -> Text:
        if status.startswith("✓"):
            return Text("✓", style=GREEN)
        if status.startswith("✗"):
            return Text("✗", style="#dc3b3b")
        glyph, style = _CELL_GLYPHS.get(status, ("·", DIM))
        return Text(glyph, style=style)

    @staticmethod
    def _done(estado: str) -> bool:
        return estado.startswith("✓") or estado.startswith("✗")

    def visible_stems(self, alto: int | None = None) -> tuple[list[str], int]:
        """Filas que caben en pantalla, y cuántas se ocultan. API: (stems, ocultas).

        Con --all sobre treinta ficheros la tabla se salía del terminal y arrastraba
        la barra de progreso con ella. Se prioriza lo que está en marcha; lo terminado
        cede el sitio, que para eso está la tabla de resultados del final.
        """
        if alto is None:
            alto = shutil.get_terminal_size(fallback=(80, 24)).lines
        cupo = max(_MIN_ROWS, alto - _VIEW_CHROME)
        if len(self.stems) <= cupo:
            return self.stems, 0

        activos    = [s for s in self.stems
                      if any(not self._done(e) for e in self.cells[s].values())]
        terminados = [s for s in self.stems if s not in set(activos)]
        elegidos   = (activos + terminados)[:cupo]
        # Se muestran en el orden original, no en el de prioridad: si las filas bailan
        # de sitio en cada refresco no hay quien lea la tabla.
        orden = {s: i for i, s in enumerate(self.stems)}
        return sorted(elegidos, key=orden.get), len(self.stems) - len(elegidos)

    def _fila_compacta(self, stem: str, ancho_nombre: int) -> Text:
        linea = Text()
        linea.append(" " + _elide(stem, ancho_nombre).ljust(ancho_nombre), style=FG)
        linea.append(f" {self.src_lang[stem]:<3}", style=DIM)
        linea.append(" ")
        for lang in self.languages:
            estado = self.cells[stem][lang]
            if estado.startswith("✓"):
                linea.append("✓", style=GREEN)
            elif estado.startswith("✗"):
                linea.append("✗", style="#dc3b3b")
            elif estado == "waiting":
                linea.append("·", style=DIM)
            else:
                linea.append("▸", style=YELLOW)
        return linea

    def _tabla(self, stems: list[str], ancho: int):
        """Rejilla completa, o una fila compacta por fichero si no caben las columnas.

        Con catorce idiomas rich estrechaba las columnas hasta hacerlas desaparecer:
        se veía la lista de ficheros sin un solo estado al lado. Es preferible un
        glifo por idioma que una tabla que miente.
        """
        # Calcular a mano cuánto ocupa la tabla no funcionaba: rich reparte el ancho
        # con reglas propias y la mía se desviaba justo lo suficiente para que
        # comprimiera las cabeceras. Se construye y se le pregunta a rich si cabe.
        for hueco in (40, 28, 20, _MIN_NAME):
            table = Table(show_edge=False, box=box.SIMPLE, padding=(0, 1), header_style=DIM)
            table.add_column("FILE", style=FG, no_wrap=True, max_width=hueco)
            table.add_column("SRC", justify="center", no_wrap=True, width=4)
            for lang in self.languages:
                table.add_column(lang, style=CYAN, justify="center", no_wrap=True, width=2)
            for stem in stems:
                src = Text()
                src.append(f"{self.src_lang[stem]} ", style=DIM)
                src.append_text(self._cell(self.cells[stem]["SRC"]))
                table.add_row(Text(_elide(stem, hueco), style=FG), src,
                              *(self._cell(self.cells[stem][l]) for l in self.languages))
            if _RULER.measure(table).maximum <= ancho:
                return table

        hueco = max(_MIN_NAME, ancho - len(self.languages) - _SRC_COL - 2)
        # Al ancho del nombre mas largo, no a todo el hueco sobrante: rellenar hasta
        # el final dejaba un desierto entre el nombre y su estado.
        ancho_nombre = min(hueco, max((len(s) for s in stems), default=_MIN_NAME))
        return Group(*(self._fila_compacta(s, ancho_nombre) for s in stems))

    def render(self) -> Group:
        parts = []
        ancho = _ancho()
        barra = max(_MIN_BAR, min(40, ancho - 5))

        parts.append(_cabecera(f"{len(self.stems)} files", self.languages, ancho))
        parts.append(Text(f" {'─' * min(44, ancho - 2)}", style=DIM))
        parts.append(Text())

        label = Text()
        label.append(" translating", style=DIM)
        label.append(f"   {self.pct}%", style=BRIGHT)
        label.append(f"   {self.completed}/{self.total_tasks}", style=DIM)
        parts.append(label)
        parts.append(_bar(self.pct, barra, BLUE))
        parts.append(Text())

        stems, ocultas = self.visible_stems()
        parts.append(self._tabla(stems, ancho))
        if ocultas:
            parts.append(Text(f"   … y {ocultas} fichero(s) más", style=DIM))
        return Group(*parts)


def _local_stem(title: str, lang: str) -> str:
    """Resolve the local output filename stem using config.json local.naming_pattern."""
    pattern = CONFIG.get("local", {}).get("naming_pattern", "{title}.{lang}")
    return pattern.replace("{title}", title).replace("{lang}", lang)


@dataclass
class SourceDoc:
    """One source file, read and parsed once and shared by every language task."""
    path:     Path
    content:  str
    parsed:   list = field(default_factory=list)
    texts:    list[str] = field(default_factory=list)
    src_lang: str | None = None
    warning:  str | None = None

    @property
    def stem(self) -> str:
        return self.path.stem


def _failure(path: Path, warning: str) -> dict:
    return {"lang": "—", "source": path.name, "file": "—", "ok": False,
            "time": 0.0, "gdocs_url": None, "warning": warning}


def _prepare_one(path: Path, format_raw: bool, forced_lang: str | None,
                 gemini_sem: threading.Semaphore) -> SourceDoc | dict:
    """Read, format and parse one source. Returns a SourceDoc or a failure dict."""
    # El formateo con Gemini es la única parte de red de esta fase, y comparte
    # presupuesto con el refinamiento: fuera del semáforo va todo lo demás.
    if format_raw and needs_formatting(path):
        with gemini_sem:
            content, warning = load_markdown(path, allow_format=True)
    else:
        content, warning = load_markdown(path, allow_format=False)

    if not content.strip():
        return _failure(path, warning or f"{path.name} produced no content")

    doc = SourceDoc(path=path, content=content, warning=warning)
    try:
        doc.parsed = parse_markdown_lines(content.splitlines())
        doc.texts  = [text for _, _pfx, text in doc.parsed if text]
    except Exception as e:
        return _failure(path, f"Could not parse {path.name}: {e}")

    if forced_lang:
        doc.src_lang = forced_lang.lower().split("-")[0]
    else:
        doc.src_lang, lang_warning = detect_source_language(doc.texts)
        if lang_warning:
            doc.warning = doc.warning or f"{path.name}: {lang_warning}"

    return doc


def _prepare_docs(files: list[Path], format_raw: bool, forced_lang: str | None = None,
                  max_workers: int = DEFAULT_MAX_WORKERS,
                  gemini_sem: threading.Semaphore | None = None,
                  ) -> tuple[list[SourceDoc], list[dict]]:
    """Read, format and parse every source. Returns (docs, failures).

    Se hacía en serie: con --all sobre varias transcripciones, el formateo con Gemini
    de la última esperaba al de todas las anteriores antes de que el pipeline empezara
    siquiera. El orden de salida se mantiene aunque terminen desordenadas.
    """
    gemini_sem = gemini_sem or threading.Semaphore(1)
    pendientes = [p for p in files if format_raw and needs_formatting(p)]
    if pendientes:
        console.print(f"[{DIM}]Formatting {', '.join(p.name for p in pendientes)} "
                      f"with Gemini AI…[/{DIM}]")

    with ThreadPoolExecutor(max_workers=max(1, min(len(files), max_workers))) as ex:
        salida = list(ex.map(
            lambda p: _prepare_one(p, format_raw, forced_lang, gemini_sem), files))

    docs     = [r for r in salida if isinstance(r, SourceDoc)]
    failures = [r for r in salida if not isinstance(r, SourceDoc)]
    return docs, failures


def run_pipeline(config: dict) -> list[dict]:
    languages  = config["languages"]
    source_cfg = config["source"]
    provider   = config["provider"]
    output_cfg = config["output"]
    format_raw = config.get("format_raw", True)
    forced_lang = (config.get("source_lang")
                   or CONFIG.get("document", {}).get("source_language"))

    files = collect_sources(source_cfg)
    if not files:
        raise ValueError(f"No files found for: {source_cfg}")

    use_google = "Google Drive" in output_cfg
    no_local   = output_cfg == "Google Drive"
    pipe_cfg   = CONFIG.get("pipeline", {})
    max_workers = max(1, int(pipe_cfg.get("max_workers", DEFAULT_MAX_WORKERS)))
    # Presupuesto único de Gemini para toda la ejecución: el formateo de las fuentes y
    # el refinamiento van contra la misma cuota, así que comparten semáforo.
    gemini_sem = threading.Semaphore(
        max(1, int(pipe_cfg.get("gemini_workers", DEFAULT_GEMINI_WORKERS))))

    # ── Phase 0 — read, format raw text, parse ────────────────────────────────
    console.print()
    t_prepare = time.monotonic()
    docs, all_results = _prepare_docs(files, format_raw, forced_lang,
                                      max_workers=max_workers, gemini_sem=gemini_sem)
    prepare_elapsed = time.monotonic() - t_prepare
    if not docs:
        return all_results

    translator = get_translator(provider)
    # Authenticate once; each thread builds its own service objects from shared creds
    if use_google:
        GoogleDocsManager.reset_run_state()   # los listados cacheados son de esta ejecución
        _drive = GoogleDocsManager(console=console)
        _drive.ensure_fresh_credentials()     # antes del pool, no a mitad y por 4 hilos
        shared_creds = _drive.creds
    else:
        shared_creds = None

    # ── Phase 1 — build the flat task list ────────────────────────────────────
    # A task is one (document, language) output. The source-language document is a
    # task too: it skips translation but shares the write/convert/upload path.
    tasks: list[tuple[SourceDoc, str, bool]] = []
    for doc in docs:
        if doc.src_lang:
            tasks.append((doc, doc.src_lang.upper(), True))
        for lang in languages:
            if doc.src_lang and lang.lower().split("-")[0] == doc.src_lang:
                continue
            tasks.append((doc, lang, False))

    # Las tareas que pasan por Gemini van primero. El refinamiento está serializado por
    # cuota, así que si AR y ZH salen las últimas los demás hilos acaban parados
    # esperándolas; lanzándolas antes, EN y FR se solapan con su cola.
    tasks.sort(key=lambda t: not needs_refine(t[1]))

    single      = len(docs) == 1
    view        = (PipelineView(languages, docs[0].path.name) if single
                   else MultiFileView(languages, [d.stem for d in docs], len(tasks)))
    view_lock   = threading.Lock()
    used_folders: set[Path] = set()
    scratch:     set[Path] = set()        # ficheros creados aquí, borrables si no_local
    folders_lock = threading.Lock()
    cancelled    = threading.Event()      # Ctrl+C: corta las tareas que aún no han salido
    in_flight    = 0                      # tareas que ya no se pueden cancelar
    pdf_jobs: list[tuple[Path, str, str]] = []   # (docx, fichero fuente, idioma)
    completed    = 0

    if single:
        view.set_source_done(prepare_elapsed)
    else:
        for doc in docs:
            view.set_source_lang(doc.stem, doc.src_lang)

    console.print()
    console.print()

    with Live(view.render(), console=console, refresh_per_second=4) as live:

        def _update(doc: SourceDoc, lang: str, is_source: bool,
                    status: str, elapsed: float | None = None) -> None:
            with view_lock:
                if single:
                    if lang in view.lang_status:
                        view.set_lang_status(lang, status, elapsed)
                else:
                    view.set_status(doc.stem, "SRC" if is_source else lang, status, elapsed)
                    # The source language doubles as a requested target when both match.
                    if is_source and lang in view.cells[doc.stem]:
                        view.set_status(doc.stem, lang, status, elapsed)
                live.update(view.render())

        def _bump_progress() -> None:
            nonlocal completed
            with view_lock:
                completed += 1
                if single:
                    view.set_progress(int((completed / len(tasks)) * 100))
                else:
                    view.mark_completed()
                live.update(view.render())

        def _run_task(doc: SourceDoc, lang: str, is_source: bool) -> dict:
            nonlocal in_flight
            # short manda el formato del documento (RTL, CJK, plantilla); slug manda el
            # destino. Colapsar EN y EN-GB a "en" hacía que las dos tareas escribieran el
            # mismo fichero a la vez y subieran encima la una de la otra.
            short     = lang.lower().split("-")[0]
            slug      = lang.lower()
            g_manager = GoogleDocsManager(console=console, creds=shared_creds) if use_google else None

            t_lang  = time.monotonic()
            ok      = True
            url     = None
            warning = doc.warning if is_source else None

            if cancelled.is_set():
                return {"lang": lang, "source": doc.path.name, "file": "—", "ok": False,
                        "time": 0.0, "gdocs_url": None, "warning": "cancelled"}

            _update(doc, lang, is_source, "translating…")
            with folders_lock:
                in_flight += 1

            try:
                if cancelled.is_set():
                    raise KeyboardInterrupt
                if is_source:
                    new_content = doc.content if doc.content.endswith("\n") else doc.content + "\n"
                else:
                    translated = call_translate(translator, doc.texts, lang, doc.src_lang)
                    rebuilt    = rebuild_markdown_from_translations(doc.parsed, translated)

                    if needs_refine(lang):
                        _update(doc, lang, is_source, "refining…")
                        with gemini_sem:
                            rebuilt, refine_warn = refine_markdown(rebuilt, lang)
                        if refine_warn:
                            warning = refine_warn
                            _update(doc, lang, is_source, "✓ unrefined")

                    new_content = "\n".join(rebuilt) + "\n"

                if cancelled.is_set():
                    raise KeyboardInterrupt

                lang_folder = TRANSLATED_DIR / slug
                lang_folder.mkdir(parents=True, exist_ok=True)
                with folders_lock:
                    used_folders.add(lang_folder)

                out_file  = lang_folder / f"{_local_stem(doc.stem, slug)}.md"
                docx_file = out_file.with_suffix(".docx")
                pdf_file  = out_file.with_suffix(".pdf")
                with folders_lock:
                    scratch.update(f for f in (out_file, docx_file, pdf_file) if not f.exists())

                if not out_file.exists() or out_file.read_text(encoding="utf-8") != new_content:
                    out_file.write_text(new_content, encoding="utf-8")

                if not docx_file.exists() or out_file.stat().st_mtime > docx_file.stat().st_mtime:
                    docx_file = generate_docx_document(out_file, short)

                if not no_local:
                    if not pdf_file.exists() or docx_file.stat().st_mtime > pdf_file.stat().st_mtime:
                        with folders_lock:
                            pdf_jobs.append((docx_file, doc.path.name, lang))

                # The source document is only uploaded when its language was requested.
                upload = g_manager is not None and (
                    not is_source or any(l.lower().split("-")[0] == short for l in languages)
                )
                if upload and not cancelled.is_set():
                    _update(doc, lang, is_source, "uploading…")
                    tgt = DRIVE_FOLDER_ID
                    if CONFIG.get("drive", {}).get("organize_by_language"):
                        tgt = g_manager.resolve_language_folder(
                            tgt, slug, CONFIG["drive"].get("language_folder_names"))
                    drive_cfg  = CONFIG.get("drive", {})
                    name, prev = g_manager.resolve_target(
                        title=doc.stem, folder_id=tgt, lang=slug,
                        sequential_naming=drive_cfg.get("sequential_naming", False),
                        sequential_naming_pattern=drive_cfg.get("sequential_naming_pattern"),
                        replace_existing=drive_cfg.get("replace_existing", False),
                        # Sin carpeta por idioma todos comparten destino: el nombre tiene
                        # que llevar el idioma o los cuatro apuntan al mismo documento.
                        disambiguate_lang=not drive_cfg.get("organize_by_language"))
                    doc_id = g_manager.upload_docx(docx_file, tgt, filename=name, file_id=prev)
                    url = g_manager.get_document_url(doc_id)

            except KeyboardInterrupt:
                _update(doc, lang, is_source, "✗ cancelled")
                _bump_progress()
                return {"lang": lang, "source": doc.path.name, "file": "—", "ok": False,
                        "time": time.monotonic() - t_lang, "gdocs_url": None,
                        "warning": "cancelled"}
            except Exception as e:
                ok      = False
                warning = str(e)
                err     = warning.lower()
                _update(doc, lang, is_source,
                        "✗ auth fail" if "auth" in err
                        else "✗ timeout" if "timeout" in err
                        else "✗ failed")
            finally:
                with folders_lock:
                    in_flight -= 1

            elapsed = time.monotonic() - t_lang
            if ok:
                _update(doc, lang, is_source, "✓ generated", elapsed)
            _bump_progress()

            return {
                "lang":      lang,
                "source":    doc.path.name,
                "file":      f"{_local_stem(doc.stem, slug)}.docx" if ok else "—",
                "ok":        ok,
                "time":      elapsed,
                "gdocs_url": url,
                "warning":   warning,
            }

        # ── Phase 2 — one flat pool across every file and language ────────────
        executor = ThreadPoolExecutor(max_workers=max(1, min(len(tasks), max_workers)))
        try:
            futures = {executor.submit(_run_task, *t): t for t in tasks}
            for future in as_completed(futures):
                doc, lang, _is_src = futures[future]
                try:
                    all_results.append(future.result())
                except Exception as e:
                    all_results.append({
                        "lang": lang, "source": doc.path.name, "file": "—", "ok": False,
                        "time": 0.0, "gdocs_url": None, "warning": str(e),
                    })
        except KeyboardInterrupt:
            # Sin esto el pool espera a las 40 tareas ya encoladas: el Ctrl+C no se
            # nota y los documentos siguen subiendo a Drive minutos despues.
            cancelled.set()
            # Una petición HTTP ya lanzada no se puede abortar: mejor decir por qué
            # tarda en salir que dar la sensación de que el Ctrl+C se ha ignorado.
            with folders_lock:
                quedan = in_flight
            if quedan:
                console.print(f"\n[{YELLOW}]Cancelando… {quedan} petición(es) ya en curso, "
                              f"no se pueden abortar a medias.[/{YELLOW}]")
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        finally:
            executor.shutdown(wait=True)

    # ── Phase 3 — PDFs: una sola invocación de LibreOffice ────────────────────
    # Arrancar el proceso cuesta ~1,4s y convertir un documento ~0,2s. Uno por
    # documento pagaba el arranque tantas veces como tareas hubiera.
    if pdf_jobs and not cancelled.is_set():
        console.print(f"\n[{DIM}]Generating {len(pdf_jobs)} PDF(s)…[/{DIM}]")
        fallos   = convert_many_to_pdf([job[0] for job in pdf_jobs], max_workers)
        por_tarea = {(r["source"], r["lang"]): r for r in all_results}
        for docx, source, lang in pdf_jobs:
            if docx in fallos:
                resultado = por_tarea.get((source, lang))
                if resultado is not None:
                    resultado["warning"] = resultado["warning"] or fallos[docx]

    # Local files are scratch space when the output is Drive-only — clear them once
    # every task is done, never mid-run while another thread still writes there.
    # Solo se borra lo que esta ejecucion ha creado: borrar la carpeta entera se
    # llevaba por delante traducciones anteriores que el usuario si queria.
    if no_local:
        for f in scratch:
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
        for folder in used_folders:
            try:
                folder.rmdir()          # solo si quedo vacia
            except OSError:
                pass

    all_results.sort(key=lambda r: (r["source"], r["lang"]))
    return all_results
