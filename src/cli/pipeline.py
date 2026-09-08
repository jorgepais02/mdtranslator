from rich.live import Live
from rich.console import Group
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
from .styles import console, GREEN, BLUE, YELLOW, CYAN, DIM, BRIGHT, FG, needs_refine

from translators import get_translator
from translators.base import call_translate
from document.refiner import refine_markdown
from core.parser import parse_markdown_lines, rebuild_markdown_from_translations
from core.docgen import generate_docx_document, convert_docx_to_pdf
from core.config import TRANSLATED_DIR, DRIVE_FOLDER_ID, CONFIG
from core.sources import collect_sources, load_markdown, needs_formatting
from integrations.drive import GoogleDocsManager


DEFAULT_MAX_WORKERS = 4

# Por debajo de esta confianza no se asume ningun idioma: langdetect confunde
# espanol con portugues o italiano en textos cortos, y acertar a medias significa
# crear una carpeta translated/pt/ con contenido espanol y subirla a Drive.
MIN_LANG_CONFIDENCE = 0.90
MIN_LANG_SAMPLE     = 60


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

        # ── header ──────────────────────────────────────────────────────────
        header = Text()
        header.append(f" {self.source_file}", style=FG)
        header.append("  →  ", style=DIM)
        header.append("  ".join(self.languages), style=CYAN)
        parts.append(header)
        parts.append(Text(f" {'─' * 44}", style=DIM))
        parts.append(Text())

        # ── source bar ───────────────────────────────────────────────────────
        src_label = Text()
        src_label.append(" source", style=DIM)
        if self.source_done:
            src_label.append(f"   {self.source_time:.1f}s", style=DIM)
        parts.append(src_label)

        if self.source_done:
            parts.append(Text(" " + "█" * 40 + "  ✓", style=GREEN))
        else:
            parts.append(Text(" " + "█" * 15 + "░" * 25, style=BLUE))

        parts.append(Text())
        parts.append(Text())

        # ── translation bar ──────────────────────────────────────────────────
        trans_label = Text()
        trans_label.append(" translating", style=DIM)
        if self.overall_pct > 0:
            trans_label.append(f"   {self.overall_pct}%", style=BRIGHT)
        parts.append(trans_label)

        filled = int((self.overall_pct / 100) * 40)
        parts.append(Text(" " + "█" * filled + "░" * (40 - filled), style=BLUE))
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

    def render(self) -> Group:
        parts = []

        header = Text()
        header.append(f" {len(self.stems)} files", style=FG)
        header.append("  →  ", style=DIM)
        header.append("  ".join(self.languages), style=CYAN)
        parts.append(header)
        parts.append(Text(f" {'─' * 44}", style=DIM))
        parts.append(Text())

        label = Text()
        label.append(" translating", style=DIM)
        label.append(f"   {self.pct}%", style=BRIGHT)
        label.append(f"   {self.completed}/{self.total_tasks}", style=DIM)
        parts.append(label)

        filled = int((self.pct / 100) * 40)
        parts.append(Text(" " + "█" * filled + "░" * (40 - filled), style=BLUE))
        parts.append(Text())

        table = Table(show_edge=False, box=box.SIMPLE, padding=(0, 1), header_style=DIM)
        table.add_column("FILE", style=FG, no_wrap=True)
        table.add_column("SRC", justify="center")
        for lang in self.languages:
            table.add_column(lang, style=CYAN, justify="center")

        for stem in self.stems:
            row = [Text(stem, style=FG)]
            src = Text()
            src.append(f"{self.src_lang[stem]} ", style=DIM)
            src.append_text(self._cell(self.cells[stem]["SRC"]))
            row.append(src)
            row.extend(self._cell(self.cells[stem][lang]) for lang in self.languages)
            table.add_row(*row)

        parts.append(table)
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


def _prepare_docs(files: list[Path], format_raw: bool,
                  forced_lang: str | None = None) -> tuple[list[SourceDoc], list[dict]]:
    """Read, format and parse every source. Returns (docs, failures)."""
    docs:     list[SourceDoc] = []
    failures: list[dict] = []

    for path in files:
        if format_raw and needs_formatting(path):
            console.print(f"[{DIM}]Formatting {path.name} with Gemini AI…[/{DIM}]")
        content, warning = load_markdown(path, allow_format=format_raw)
        if not content.strip():
            failures.append({
                "lang": "—", "source": path.name, "file": "—", "ok": False,
                "time": 0.0, "gdocs_url": None,
                "warning": warning or f"{path.name} produced no content",
            })
            continue

        doc = SourceDoc(path=path, content=content, warning=warning)
        try:
            doc.parsed = parse_markdown_lines(content.splitlines())
            doc.texts  = [text for _, _pfx, text in doc.parsed if text]
        except Exception as e:
            failures.append({
                "lang": "—", "source": path.name, "file": "—", "ok": False,
                "time": 0.0, "gdocs_url": None,
                "warning": f"Could not parse {path.name}: {e}",
            })
            continue

        if forced_lang:
            doc.src_lang = forced_lang.lower().split("-")[0]
        else:
            doc.src_lang, lang_warning = detect_source_language(doc.texts)
            if lang_warning:
                doc.warning = doc.warning or f"{path.name}: {lang_warning}"

        docs.append(doc)

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
    max_workers = max(1, int(CONFIG.get("pipeline", {}).get("max_workers", DEFAULT_MAX_WORKERS)))

    # ── Phase 0 — read, format raw text, parse ────────────────────────────────
    console.print()
    t_prepare = time.monotonic()
    docs, all_results = _prepare_docs(files, format_raw, forced_lang)
    prepare_elapsed = time.monotonic() - t_prepare
    if not docs:
        return all_results

    translator = get_translator(provider)
    # Authenticate once; each thread builds its own service objects from shared creds
    if use_google:
        GoogleDocsManager.reset_run_state()   # los listados cacheados son de esta ejecución
        shared_creds = GoogleDocsManager(console=console).creds
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

    single      = len(docs) == 1
    view        = (PipelineView(languages, docs[0].path.name) if single
                   else MultiFileView(languages, [d.stem for d in docs], len(tasks)))
    view_lock   = threading.Lock()
    gemini_sem  = threading.Semaphore(1)  # Gemini free tier: serialize refinement calls
    used_folders: set[Path] = set()
    scratch:     set[Path] = set()        # ficheros creados aquí, borrables si no_local
    folders_lock = threading.Lock()
    cancelled    = threading.Event()      # Ctrl+C: corta las tareas que aún no han salido
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
            short     = lang.lower().split("-")[0]
            g_manager = GoogleDocsManager(console=console, creds=shared_creds) if use_google else None

            t_lang  = time.monotonic()
            ok      = True
            url     = None
            warning = doc.warning if is_source else None

            if cancelled.is_set():
                return {"lang": lang, "source": doc.path.name, "file": "—", "ok": False,
                        "time": 0.0, "gdocs_url": None, "warning": "cancelled"}

            _update(doc, lang, is_source, "translating…")

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

                lang_folder = TRANSLATED_DIR / short
                lang_folder.mkdir(parents=True, exist_ok=True)
                with folders_lock:
                    used_folders.add(lang_folder)

                out_file  = lang_folder / f"{_local_stem(doc.stem, short)}.md"
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
                        try:
                            convert_docx_to_pdf(docx_file)
                        except Exception as pdf_err:
                            warning = warning or str(pdf_err)

                # The source document is only uploaded when its language was requested.
                upload = g_manager is not None and (
                    not is_source or any(l.lower().split("-")[0] == short for l in languages)
                )
                if upload and not cancelled.is_set():
                    _update(doc, lang, is_source, "uploading…")
                    tgt = DRIVE_FOLDER_ID
                    if CONFIG.get("drive", {}).get("organize_by_language"):
                        tgt = g_manager.resolve_language_folder(
                            tgt, short, CONFIG["drive"].get("language_folder_names"))
                    drive_cfg  = CONFIG.get("drive", {})
                    name, prev = g_manager.resolve_target(
                        title=doc.stem, folder_id=tgt, lang=short,
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

            elapsed = time.monotonic() - t_lang
            if ok:
                _update(doc, lang, is_source, "✓ generated", elapsed)
            _bump_progress()

            return {
                "lang":      lang,
                "source":    doc.path.name,
                "file":      f"{_local_stem(doc.stem, short)}.docx" if ok else "—",
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
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        finally:
            executor.shutdown(wait=True)

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
