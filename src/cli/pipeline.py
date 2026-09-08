from rich.live import Live
from rich.console import Group
from rich.text import Text
import time
import shutil
import threading
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from langdetect import detect_langs as _detect_langs, DetectorFactory as _LDF
_LDF.seed = 0
from .styles import (console, elide as _elide, status_style as _status_style,
                     STATUS_QUEUED, GREEN, BLUE, YELLOW, RED, CYAN, DIM,
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
    # Una barra llena de una tarea que sigue en marcha se lee como terminada. Solo se
    # llena del todo al 100% de verdad; el redondeo cede el ultimo bloque.
    if pct < 100:
        lleno = min(lleno, ancho - 1)
    return Text(" " + "█" * lleno + "░" * (ancho - lleno) + sufijo, style=style)


def _cabecera(izquierda: str, languages: list[str], ancho: int) -> Text:
    """Titulo + idiomas, recortando los idiomas antes que dejarlos caer a la linea 2."""
    header = Text()
    header.append(f" {izquierda}", style=f"bold {BRIGHT}")
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


# Cuanto lleva hecho una tarea dentro de su fila. La barra no interpola contra un
# reloj: se mueve en los momentos en que de verdad pasa algo, y se para si algo se
# atasca —que es justamente lo que quieres ver.
_FASES = {
    "translating…": 0.30,
    "refining…":    0.60,
    "uploading…":   0.85,
}
# La barra tiene tope: estirada a 100 columnas deja de leerse como una barra y el
# ojo pierde el salto entre lleno y vacio. Lo que sobra a la derecha se queda vacio.
_MAX_BAR    = 28
_TIEMPO_COL = 6


@dataclass
class Track:
    """Una fila de la vista: un idioma con un fichero, o un fichero con --all."""
    key:      str
    total:    int = 1                 # tareas que caen en esta fila
    hechas:   int = 0
    status:   str = STATUS_QUEUED
    detail:   str = ""                # idioma en curso, cuando la fila es un fichero
    started:  float | None = None
    finished: float | None = None
    fallos:   int = 0

    @property
    def pct(self) -> float:
        if self.hechas >= self.total:
            return 100.0
        return min(100.0, (self.hechas + _FASES.get(self.status, 0.0)) / self.total * 100)

    @property
    def viva(self) -> bool:
        return self.started is not None and self.finished is None

    def elapsed(self, ahora: float) -> float | None:
        """Segundos que lleva. Sigue contando mientras la fila esta viva."""
        if self.started is None:
            return None
        return (self.finished or ahora) - self.started

    def etiqueta(self) -> str:
        """El estado como se lee. Sin glifo ni puntos suspensivos: el color ya dice
        si fue bien y la barra ya dice que sigue en marcha."""
        texto = self.status.lstrip("✓✗ ").rstrip("…") or STATUS_QUEUED
        return f"{texto} {self.detail}".strip()


class ProgressView:
    """Una fila por pista, con su barra, su estado y su cronometro.

    Con un fichero las pistas son sus idiomas; con --all son los ficheros. Antes eran
    dos vistas distintas: esta y una rejilla fichero × idioma, con su modo compacto,
    su recorte de columnas y su propio vocabulario de glifos. La rejilla se quito
    porque no contestaba a nada que se pudiera hacer —ver que tema03 en arabe va por
    la mitad no permite reordenar, ni cancelar esa celda, ni saltarse el fichero— y lo
    unico que si contestaba, "¿se ha atascado algo?", cabe en la linea de resumen y en
    que una barra deje de moverse.

    API:
        update(key, status, detail="")   cambia el estado de una fila
        complete(key, ok=True)           una tarea de esa fila ha terminado
        render()                         Group de rich para el Live
    """

    def __init__(self, header_left: str, languages: list[str],
                 tracks: dict[str, int], *, show_langs: bool,
                 prepare_time: float | None = None):
        self.header_left  = header_left
        self.languages    = languages
        self.show_langs   = show_langs
        self.prepare_time = prepare_time
        self.tracks       = {k: Track(k, total=n) for k, n in tracks.items()}
        self.total_tasks  = sum(tracks.values()) or 1
        self.completed    = 0
        self.failed       = 0
        self.started      = time.monotonic()

    # ── entradas ──────────────────────────────────────────────────────────────

    def update(self, key: str, status: str, detail: str = "") -> None:
        t = self.tracks.get(key)
        if t is None:
            return
        if t.started is None:
            t.started = time.monotonic()
        t.status, t.detail = status, detail

    def complete(self, key: str, ok: bool = True) -> None:
        t = self.tracks.get(key)
        self.completed += 1
        if not ok:
            self.failed += 1
        if t is None:
            return
        t.hechas += 1
        if not ok:
            t.fallos += 1
        if t.hechas >= t.total:
            t.finished = time.monotonic()
            # El detalle es "en que idioma va": una fila terminada no va en ninguno,
            # y dejarlo puesto la dejaba diciendo "generated FR" para siempre.
            t.detail = ""

    @property
    def pct(self) -> int:
        return int((self.completed / self.total_tasks) * 100)

    # ── pintado ───────────────────────────────────────────────────────────────

    def _resumen(self) -> Text:
        partes = []
        if self.prepare_time is not None:
            partes.append(f"parsed in {self.prepare_time:.1f}s")
        if self.show_langs:
            partes.append(f"{self.completed} of {self.total_tasks} documents")
        else:
            partes.append(f"{len(self.tracks)} languages")
            partes.append(f"{self.completed} done")
        vivas = sum(1 for t in self.tracks.values() if t.viva)
        if vivas:
            partes.append(f"{vivas} running")
        if self.failed:
            partes.append(f"{self.failed} failed")
        # Se recorta en vez de envolver: una segunda linea de resumen empuja las filas
        # hacia abajo y con --all la vista entera baila en cada refresco.
        return Text(" " + _elide(" · ".join(partes), _ancho() - 2), style=DIM)

    def visible_tracks(self, alto: int | None = None) -> tuple[list[Track], int]:
        """Filas que caben a lo alto, y cuantas se ocultan. API: (tracks, ocultas).

        Con --all sobre treinta ficheros la lista se salia del terminal y se llevaba
        por delante la linea de resumen. Lo que esta en marcha tiene prioridad; lo
        terminado cede el sitio, que para eso esta la tabla de resultados del final.
        """
        if alto is None:
            alto = shutil.get_terminal_size(fallback=(80, 24)).lines
        cupo = max(_MIN_ROWS, alto - _VIEW_CHROME)
        todas = list(self.tracks.values())
        if len(todas) <= cupo:
            return todas, 0
        orden = {t.key: i for i, t in enumerate(todas)}
        activas = [t for t in todas if t.finished is None]
        elegidas = (activas + [t for t in todas if t.finished is not None])[:cupo]
        # En el orden original, no en el de prioridad: si las filas bailan de sitio en
        # cada refresco no hay quien las lea.
        return sorted(elegidas, key=lambda t: orden[t.key]), len(todas) - len(elegidas)

    def _medidas(self, ancho: int) -> tuple[int, int, int, int]:
        """Reparto horizontal: (nombre, barra, estado, ancho del bloque).

        El bloque no ocupa todo el terminal: la barra tiene tope y el total de abajo
        se alinea con la columna de tiempos, no con el borde derecho de la pantalla.
        """
        nombre = min(max((len(t.key) for t in self.tracks.values()), default=_MIN_NAME),
                     max(_MIN_NAME, ancho // 3))
        # "translating FR" es la etiqueta mas larga que se puede formar; sin detalle,
        # "translating" a secas.
        estado = 14 if self.show_langs else 11
        fijo   = 2 + nombre + 1 + 1 + _TIEMPO_COL
        barra  = min(_MAX_BAR, ancho - fijo - estado - 1)
        if barra < _MIN_BAR:
            # Antes de estrechar la barra hasta que deje de significar nada, se
            # sacrifica el texto del estado: el color de la barra ya lo cuenta.
            estado = max(0, ancho - fijo - _MIN_BAR - 1)
            # Por debajo de seis columnas el estado ya no es una palabra sino un
            # muñón ("ge…", "up…"): mejor quitarlo y que hable el color de la barra.
            if estado < 6:
                estado = 0
            barra  = max(_MIN_BAR, min(_MAX_BAR, ancho - fijo - estado - 1))
        return nombre, barra, estado, min(ancho, fijo + barra + estado)

    def _fila(self, t: Track, ahora: float, nombre: int, barra: int, estado: int) -> Text:
        estilo = _status_style(t.status)
        linea = Text()
        linea.append("  " + _elide(t.key, nombre).ljust(nombre), style=BRIGHT)
        linea.append_text(_bar(t.pct, barra, estilo))
        linea.append(" ")
        if estado:
            # El detalle (el idioma en curso) es lo primero que se cae si no cabe:
            # "uploading" entero dice mas que "uploading …".
            texto = t.etiqueta()
            if len(texto) > estado and t.detail:
                texto = t.status.lstrip("✓✗ ").rstrip("…")
            linea.append(_elide(texto, estado).ljust(estado), style=estilo)
        segundos = t.elapsed(ahora)
        linea.append(f"{segundos:.1f}s".rjust(_TIEMPO_COL) if segundos is not None
                     else "—".rjust(_TIEMPO_COL), style=DIM)
        return linea

    def render(self) -> Group:
        ancho = _ancho()
        ahora = time.monotonic()
        nombre, barra, estado, bloque = self._medidas(ancho)

        partes: list = []
        if self.show_langs:
            partes.append(_cabecera(self.header_left, self.languages, ancho))
        else:
            partes.append(Text(f" {_elide(self.header_left, ancho - 2)}",
                               style=f"bold {BRIGHT}"))
        partes.append(self._resumen())
        partes.append(Text())

        visibles, ocultas = self.visible_tracks()
        for t in visibles:
            partes.append(self._fila(t, ahora, nombre, barra, estado))
        if ocultas:
            partes.append(Text(f"  … and {ocultas} more", style=DIM))

        partes.append(Text())
        total = Text()
        total.append("total".rjust(max(0, bloque - _TIEMPO_COL - 1)), style=DIM)
        total.append(f"{ahora - self.started:.1f}s".rjust(_TIEMPO_COL + 1), style=DIM)
        partes.append(total)
        return Group(*partes)


class _Vivo:
    """Renderable que vuelve a preguntarle a la vista en cada refresco del Live.

    Pasandole un Group ya construido, el Live redibujaba siempre el mismo: los
    cronometros solo avanzaban cuando una tarea cambiaba de estado, y una fila que se
    quedaba diez segundos subiendo parecia congelada.
    """

    def __init__(self, view):
        self.view = view

    def __rich__(self):
        return self.view.render()


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

    # Las filas de la vista, en el orden en que se leen: los idiomas cuando hay un
    # fichero, los ficheros cuando hay varios. Se calcula antes de reordenar las
    # tareas, porque el orden de ejecucion y el de lectura no tienen por que coincidir.
    single = len(docs) == 1
    filas: dict[str, int] = {}
    for _doc, _lang, _is_src in tasks:
        clave = _lang if single else _doc.stem
        filas[clave] = filas.get(clave, 0) + 1

    # Las tareas que pasan por Gemini van primero. El refinamiento está serializado por
    # cuota, así que si AR y ZH salen las últimas los demás hilos acaban parados
    # esperándolas; lanzándolas antes, EN y FR se solapan con su cola.
    tasks.sort(key=lambda t: not needs_refine(t[1]))

    view = ProgressView(docs[0].path.name if single else f"{len(docs)} files",
                        languages, filas, show_langs=not single,
                        prepare_time=prepare_elapsed)
    view_lock   = threading.Lock()
    used_folders: set[Path] = set()
    scratch:     set[Path] = set()        # ficheros creados aquí, borrables si no_local
    folders_lock = threading.Lock()
    cancelled    = threading.Event()      # Ctrl+C: corta las tareas que aún no han salido
    in_flight    = 0                      # tareas que ya no se pueden cancelar
    pdf_jobs: list[tuple[Path, str, str]] = []   # (docx, fichero fuente, idioma)

    console.print()
    console.print()

    with Live(_Vivo(view), console=console, refresh_per_second=4) as live:

        def _update(doc: SourceDoc, lang: str, is_source: bool,
                    status: str, elapsed: float | None = None) -> None:
            with view_lock:
                view.update(lang if single else doc.stem, status, "" if single else lang)
                live.refresh()

        def _bump_progress(doc: SourceDoc, lang: str, ok: bool = True) -> None:
            with view_lock:
                view.complete(lang if single else doc.stem, ok)
                live.refresh()

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
            refined = True
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
                            refined = False

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
                _bump_progress(doc, lang, ok=False)
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
                # "unrefined" se marcaba antes de subir y luego lo pisaba "generated":
                # el documento salia sin refinar y la vista decia que todo bien.
                _update(doc, lang, is_source,
                        "✓ generated" if refined else "✓ unrefined", elapsed)
            _bump_progress(doc, lang, ok)

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
