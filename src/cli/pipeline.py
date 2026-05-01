from rich.live import Live
from rich.console import Group
from rich.text import Text
import time
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from langdetect import detect as _detect_lang, DetectorFactory as _LDF
_LDF.seed = 0
from .styles import console, GREEN, BLUE, YELLOW, CYAN, DIM, BRIGHT, FG, needs_refine

from translators import get_translator
from document.refiner import refine_markdown
from core.parser import parse_markdown_lines, rebuild_markdown_from_translations
from core.docgen import generate_docx_document, convert_docx_to_pdf
from core.config import TRANSLATED_DIR, DRIVE_FOLDER_ID, CONFIG
from integrations.drive import GoogleDocsManager


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


def _local_stem(title: str, lang: str) -> str:
    """Resolve the local output filename stem using config.json local.naming_pattern."""
    pattern = CONFIG.get("local", {}).get("naming_pattern", "{title}.{lang}")
    return pattern.replace("{title}", title).replace("{lang}", lang)


def run_pipeline(config: dict) -> list[dict]:
    languages  = config["languages"]
    source_cfg = config["source"]
    provider   = config["provider"]
    output_cfg = config["output"]

    project_root = Path(__file__).resolve().parent.parent.parent
    sources_dir  = project_root / "sources"

    if source_cfg == "Process ALL files":
        files = list(sources_dir.glob("*.md")) + list(sources_dir.glob("*.txt"))
    else:
        p = Path(source_cfg)
        if p.is_absolute():
            file_path = p
        elif source_cfg.startswith("sources/"):
            file_path = project_root / source_cfg
        else:
            file_path = sources_dir / source_cfg
        files = [file_path] if file_path.exists() else []

    if not files:
        raise ValueError(f"No files found for: {source_cfg}")

    use_google = "Google Drive" in output_cfg
    no_local   = output_cfg == "Google Drive"

    translator = get_translator(provider)
    # Authenticate once; each thread builds its own service objects from shared creds
    shared_creds = GoogleDocsManager(console=console).creds if use_google else None
    all_results = []

    for f_path in files:
        view = PipelineView(languages, f_path.name)

        console.print()
        console.print()
        with Live(view.render(), console=console, refresh_per_second=4) as live:

            t0 = time.monotonic()
            try:
                src_content = f_path.read_text(encoding="utf-8")
                lines  = src_content.splitlines()
                parsed = parse_markdown_lines(lines)
                texts  = [text for _, _pfx, text in parsed if text]
            except Exception as e:
                console.print(f"[#dc3b3b]✗ Failed reading {f_path.name}: {e}[/#dc3b3b]")
                continue

            view.set_source_done(time.monotonic() - t0)
            view.set_progress(10)
            live.update(view.render())

            # Source original — always generate DOCX locally; upload to Drive only if selected
            try:
                src_lang = _detect_lang(src_content[:1000])
            except Exception:
                src_lang = None

            if src_lang:
                src_folder = TRANSLATED_DIR / src_lang
                src_folder.mkdir(parents=True, exist_ok=True)
                src_stem = _local_stem(f_path.stem, src_lang)
                src_file = src_folder / f"{src_stem}.md"
                if not src_file.exists() or src_file.read_text(encoding="utf-8") != src_content:
                    src_file.write_text(src_content, encoding="utf-8")
                src_ok      = True
                src_url     = None
                src_warning = None
                src_selected = {l for l in languages if l.lower().split("-")[0] == src_lang}
                try:
                    docx_src = src_file.with_suffix(".docx")
                    if not docx_src.exists() or src_file.stat().st_mtime > docx_src.stat().st_mtime:
                        docx_src = generate_docx_document(src_file, src_lang)
                    if not no_local:
                        pdf_src = docx_src.with_suffix(".pdf")
                        if not pdf_src.exists() or docx_src.stat().st_mtime > pdf_src.stat().st_mtime:
                            try:
                                convert_docx_to_pdf(docx_src)
                            except Exception as pdf_err:
                                src_warning = str(pdf_err)
                    if use_google and src_selected:
                        gm  = GoogleDocsManager(console=console, creds=shared_creds)
                        tgt = DRIVE_FOLDER_ID
                        if CONFIG.get("drive", {}).get("organize_by_language"):
                            tgt = gm.resolve_language_folder(tgt, src_lang, CONFIG["drive"].get("language_folder_names"))
                        name = gm.resolve_filename(title=f_path.stem, folder_id=tgt, lang=src_lang,
                            sequential_naming=CONFIG.get("drive", {}).get("sequential_naming", False),
                            sequential_naming_pattern=CONFIG.get("drive", {}).get("sequential_naming_pattern"))
                        doc_id = gm.upload_docx(docx_src, tgt, filename=name)
                        src_url = gm.get_document_url(doc_id)
                except Exception as src_err:
                    src_ok = False
                    src_warning = str(src_err)
                all_results.append({
                    "lang":      src_lang.upper(),
                    "file":      f"{src_stem}.docx" if src_ok else "—",
                    "ok":        src_ok,
                    "time":      0.0,
                    "gdocs_url": src_url,
                    "warning":   src_warning,
                })

            non_src_languages = [l for l in languages if src_lang is None or l.lower().split("-")[0] != src_lang]
            total        = len(non_src_languages)
            completed    = 0
            view_lock    = threading.Lock()
            gemini_sem   = threading.Semaphore(1)  # Gemini free tier: serialize refinement calls

            def _update(lang: str | None = None, status: str | None = None,
                        elapsed: float | None = None, pct: int | None = None) -> None:
                with view_lock:
                    if lang and status is not None:
                        view.set_lang_status(lang, status, elapsed)
                    if pct is not None:
                        view.set_progress(pct)
                    live.update(view.render())

            def _process_lang(lang: str) -> dict:
                nonlocal completed
                short     = lang.lower().split("-")[0]
                g_manager = GoogleDocsManager(console=console, creds=shared_creds) if use_google else None

                _update(lang=lang, status="translating…")

                t_lang      = time.monotonic()
                ok          = True
                url         = None
                warning     = None

                try:
                    translated = translator.translate(texts, lang)
                    rebuilt    = rebuild_markdown_from_translations(parsed, translated)

                    if needs_refine(lang):
                        _update(lang=lang, status="refining…")
                        with gemini_sem:
                            rebuilt, refine_warn = refine_markdown(rebuilt, lang)
                        if refine_warn:
                            warning = refine_warn
                            _update(lang=lang, status="✓ unrefined")

                    lang_folder = TRANSLATED_DIR / short
                    lang_folder.mkdir(parents=True, exist_ok=True)
                    out_file = lang_folder / f"{_local_stem(f_path.stem, short)}.md"
                    new_content = "\n".join(rebuilt) + "\n"
                    if not out_file.exists() or out_file.read_text(encoding="utf-8") != new_content:
                        out_file.write_text(new_content, encoding="utf-8")

                    docx_file = out_file.with_suffix(".docx")
                    if not docx_file.exists() or out_file.stat().st_mtime > docx_file.stat().st_mtime:
                        docx_file = generate_docx_document(out_file, short)

                    if not no_local:
                        pdf_file = docx_file.with_suffix(".pdf")
                        if not pdf_file.exists() or docx_file.stat().st_mtime > pdf_file.stat().st_mtime:
                            try:
                                convert_docx_to_pdf(docx_file)
                            except Exception as pdf_err:
                                warning = warning or str(pdf_err)

                    if g_manager:
                        _update(lang=lang, status="uploading…")
                        tgt = DRIVE_FOLDER_ID
                        if CONFIG.get("drive", {}).get("organize_by_language"):
                            tgt = g_manager.resolve_language_folder(tgt, short, CONFIG["drive"].get("language_folder_names"))
                        name = g_manager.resolve_filename(title=f_path.stem, folder_id=tgt, lang=short,
                            sequential_naming=CONFIG.get("drive", {}).get("sequential_naming", False),
                            sequential_naming_pattern=CONFIG.get("drive", {}).get("sequential_naming_pattern"))
                        doc_id = g_manager.upload_docx(docx_file, tgt, filename=name)
                        url = g_manager.get_document_url(doc_id)

                except Exception as e:
                    ok      = False
                    warning = str(e)
                    err     = warning.lower()
                    _update(lang=lang, status="✗ auth fail" if "auth" in err else "✗ timeout" if "timeout" in err else "✗ failed")

                elapsed = time.monotonic() - t_lang
                if ok:
                    _update(lang=lang, status="✓ generated", elapsed=elapsed)

                with view_lock:
                    completed += 1
                    view.set_progress(10 + int((completed / total) * 80))
                    live.update(view.render())

                if no_local and (TRANSLATED_DIR / short).exists():
                    shutil.rmtree(TRANSLATED_DIR / short)

                return {
                    "lang":      lang,
                    "file":      f"{_local_stem(f_path.stem, short)}.docx" if ok else "—",
                    "ok":        ok,
                    "time":      elapsed,
                    "gdocs_url": url,
                    "warning":   warning,
                }

            if non_src_languages:
                max_workers = min(len(non_src_languages), 4)
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {executor.submit(_process_lang, lang): lang for lang in non_src_languages}
                    for future in as_completed(futures):
                        try:
                            all_results.append(future.result())
                        except Exception:
                            pass

            if no_local and src_lang and src_folder.exists():
                shutil.rmtree(src_folder)

            _update(pct=100)

    return all_results
