from rich.live import Live
from rich.table import Table
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn
from rich.console import Group
from rich.text import Text
from rich.panel import Panel
import time
import shutil
from pathlib import Path
from .styles import console

# Import real processing logic
from translators import get_translator
from ai_refiner import refine_markdown
from translation_pipeline import (
    parse_markdown_lines, 
    rebuild_markdown_from_translations, 
    generate_docx_document, 
    convert_docx_to_pdf,
    TRANSLATED_DIR,
    DRIVE_FOLDER_ID,
    CONFIG
)
from google_docs_manager import GoogleDocsManager

class PipelineView:
    def __init__(self, languages: list[str], source_file: str):
        self.languages = languages
        self.source_file = source_file
        self.lang_status: dict[str, dict] = {
            lang: {"status": "waiting", "time": None} for lang in languages
        }
        self.source_done = False
        self.source_time = None
        self.overall_progress = 0

    def set_source_done(self, elapsed: float):
        self.source_done = True
        self.source_time = elapsed

    def set_lang_status(self, lang: str, status: str, elapsed: float | None = None):
        self.lang_status[lang] = {"status": status, "time": elapsed}

    def set_progress(self, pct: int):
        self.overall_progress = pct

    def render(self) -> Group:
        parts = []

        # Command echo
        parts.append(Text(
            f"$ mdtranslator translate {self.source_file} --lang {' '.join(self.languages)}",
            style="dim",
        ))
        parts.append(Text())  # spacer

        # Section: Pipeline
        parts.append(Text("Pipeline", style="bold blue"))

        # Source reading
        if self.source_done:
            bar_text = "█" * 40 + " ✓"
            style = "green"
        else:
            bar_text = "█" * 15 + "░" * 25
            style = "green"

        source_line = Text()
        source_line.append("Reading source ", style="white")
        if self.source_time:
            source_line.append(f"{self.source_time:.1f}s", style="dim")
        parts.append(source_line)
        parts.append(Text(bar_text, style=style))
        parts.append(Text())  # spacer

        # Translation status
        parts.append(Text("Translating", style="white"))

        # Overall bar
        filled = int((self.overall_progress / 100) * 40)
        bar = "█" * filled + "░" * (40 - filled)
        parts.append(Text(bar, style="blue"))

        # Per-language status
        for lang, info in self.lang_status.items():
            line = Text("  ")
            line.append(f"{lang:>3} ", style="cyan")

            status = info["status"]
            if status is None:
                status = "waiting"

            if status.startswith("✓"):
                line.append(status, style="green")
            elif status in ("translating…", "refining…"):
                line.append(status, style="yellow")
            elif status.startswith("✗"):
                line.append(status, style="red")
            else:
                line.append(status, style="dim")

            if info["time"]:
                line.append(f"  {info['time']:.1f}s", style="dim")

            parts.append(line)

        parts.append(Text())  # spacer

        # Progress summary
        progress_line = Text()
        progress_line.append("Progress ", style="white")
        prog_filled = self.overall_progress // 10
        progress_line.append("██" * prog_filled, style="blue")
        progress_line.append("░░" * (10 - prog_filled), style="dim")
        progress_line.append(f" {self.overall_progress}%", style="bold white")
        parts.append(progress_line)

        return Group(*parts)

def run_pipeline(config: dict) -> list[dict]:
    languages = config["languages"]
    source_cfg = config["source"]
    provider = config["provider"]
    output_cfg = config["output"]
    folder_id = config.get("folder")
    
    project_root = Path(__file__).resolve().parent.parent.parent
    sources_dir = project_root / "sources"
    
    if source_cfg == "Process ALL files":
        files = list(sources_dir.glob("*.md")) + list(sources_dir.glob("*.txt"))
    else:
        # source_cfg might be "sources/apuntes.md" or just "apuntes.md"
        # Since we are already appending sources_dir, we check if it already starts with it
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
    no_local = "Google Drive Only" in output_cfg
    
    # Initialize translator config
    translator = get_translator(provider)
    
    # Initialize Google Docs Manager if needed
    g_manager = None
    if use_google:
        g_manager = GoogleDocsManager()
        
    all_results = []
    
    for f_path in files:
        view = PipelineView(languages, f_path.name)
        
        with Live(view.render(), console=console, refresh_per_second=8) as live:
            start_reading = time.monotonic()
            
            # Step 1: Read source
            try:
                lines = f_path.read_text(encoding="utf-8").splitlines()
                parsed = parse_markdown_lines(lines)
                texts_to_translate = [text for kind, _pfx, text in parsed if text]
            except Exception as e:
                console.print(f"[red]✗ Failed reading {f_path.name}: {e}[/red]")
                continue
                
            elapsed_read = time.monotonic() - start_reading
            view.set_source_done(elapsed_read)
            view.set_progress(10)
            live.update(view.render())
            
            # Step 1.5: ES Original handling (local & drive sync)
            es_folder = TRANSLATED_DIR / "es"
            es_folder.mkdir(parents=True, exist_ok=True)
            es_file = es_folder / "es.md"
            es_url = None
            
            if not no_local or (no_local and g_manager):
                shutil.copy2(f_path, es_file)
                try:
                    docx_file = generate_docx_document(es_file, "es")
                    if not no_local:
                        convert_docx_to_pdf(docx_file)
                        
                    if g_manager:
                        target_folder = folder_id or DRIVE_FOLDER_ID
                        if CONFIG.get("drive", {}).get("organize_by_language", False):
                            target_folder = g_manager.resolve_language_folder(
                                target_folder, "es", CONFIG.get("drive", {}).get("language_folder_names")
                            )
                        doc_name = g_manager.resolve_filename(
                            title=f_path.stem, 
                            folder_id=target_folder, 
                            lang="es",
                            sequential_naming=CONFIG.get("drive", {}).get("sequential_naming", False),
                            sequential_naming_pattern=CONFIG.get("drive", {}).get("sequential_naming_pattern")
                        )
                        doc_id = g_manager.upload_docx(docx_file, target_folder, filename=doc_name)
                        es_url = g_manager.get_document_url(doc_id)
                except Exception:
                    pass

            # Step 2: Translate each language
            total = len(languages)
            for i, lang in enumerate(languages):
                view.set_lang_status(lang, "translating…")
                view.set_progress(10 + int((i / total) * 80))
                live.update(view.render())

                start_lang = time.monotonic()
                ok = True
                url = None
                short = lang.lower().split("-")[0]
                
                try:
                    translated = translator.translate(texts_to_translate, lang)
                    rebuilt = rebuild_markdown_from_translations(parsed, translated)

                    # Optional: refinement for specific languages
                    needs_refinement = short in ('ar', 'zh', 'ja', 'ko', 'fa', 'he', 'ur')
                    if needs_refinement:
                        view.set_lang_status(lang, "refining…")
                        live.update(view.render())
                        try:
                            rebuilt = refine_markdown(rebuilt, lang)
                        except Exception:
                            pass # keep non-refined version if fail

                    lang_folder = TRANSLATED_DIR / short
                    lang_folder.mkdir(parents=True, exist_ok=True)
                    out_file = lang_folder / f"{short}.md"
                    out_file.write_text("\n".join(rebuilt) + "\n", encoding="utf-8")
                    
                    if not no_local or (no_local and g_manager):
                        docx_file = generate_docx_document(out_file, short)
                        if not no_local:
                            convert_docx_to_pdf(docx_file)
                            
                        if g_manager:
                            view.set_lang_status(lang, "uploading…")
                            live.update(view.render())
                            
                            target_folder = folder_id or DRIVE_FOLDER_ID
                            if CONFIG.get("drive", {}).get("organize_by_language", False):
                                target_folder = g_manager.resolve_language_folder(
                                    target_folder, short, CONFIG.get("drive", {}).get("language_folder_names")
                                )
                            doc_name = g_manager.resolve_filename(
                                title=f_path.stem, 
                                folder_id=target_folder, 
                                lang=short,
                                sequential_naming=CONFIG.get("drive", {}).get("sequential_naming", False),
                                sequential_naming_pattern=CONFIG.get("drive", {}).get("sequential_naming_pattern")
                            )
                            doc_id = g_manager.upload_docx(docx_file, target_folder, filename=doc_name)
                            url = g_manager.get_document_url(doc_id)
                            
                except Exception as e:
                    ok = False
                    error_msg = str(e).lower()
                    if "auth" in error_msg:
                        view.set_lang_status(lang, "✗ auth fail")
                    elif "timeout" in error_msg:
                        view.set_lang_status(lang, "✗ timeout")
                    else:
                        view.set_lang_status(lang, "✗ failed")

                elapsed = time.monotonic() - start_lang
                
                if ok:
                    view.set_lang_status(lang, "✓ generated", elapsed)

                view.set_progress(10 + int(((i + 1) / total) * 80))
                live.update(view.render())

                all_results.append({
                    "lang": lang,
                    "file": f"{f_path.stem}_{short}.docx" if ok else "—",
                    "ok": ok,
                    "time": elapsed,
                    "gdocs_url": url
                })
                
                if no_local and lang_folder.exists():
                    shutil.rmtree(lang_folder)

            # Cleanup es
            if no_local and es_folder.exists():
                shutil.rmtree(es_folder)

            # Step 3: Finish
            view.set_progress(100)
            live.update(view.render())
            time.sleep(0.2)
            
    return all_results
