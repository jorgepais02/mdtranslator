import io
import contextlib
import os
import pickle
import re
import base64
import threading
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from rich.console import Console

SCOPES = [
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/drive'
]

RTL_LANGS = {"ar", "he", "fa", "ur"}

LANG_NAMES = {
    "es": "Español",
    "en": "Inglés",
    "en-gb": "Inglés",
    "en-us": "Inglés",
    "fr": "Francés",
    "ar": "Árabe",
    "zh": "Chino"
}

class GoogleDocsManager:
    """Manages Google Docs creation, text insertion, and Drive uploads.

    El pipeline crea una instancia por hilo (compartiendo credenciales), asi que el
    estado que debe ser unico para toda la ejecucion vive a nivel de clase: la cache
    de carpetas y los nombres ya reservados. Sin esto, dos ficheros que se suben a la
    vez al mismo idioma leen la carpeta antes de que ninguno haya escrito y ambos
    resuelven el mismo numero.
    """

    _creds_lock   = threading.Lock()
    _locks_lock   = threading.Lock()
    _locks:        dict[str, threading.Lock] = {}
    _folder_cache: dict[tuple[str, str], str] = {}
    _files_cache:  dict[str, list[dict]] = {}
    _reserved:     dict[str, set[str]] = {}

    @classmethod
    def _lock_for(cls, key: str) -> threading.Lock:
        """Lock propio de una carpeta: dos carpetas distintas no deben esperarse."""
        with cls._locks_lock:
            return cls._locks.setdefault(key, threading.Lock())

    @classmethod
    def reset_run_state(cls) -> None:
        """Olvida lo cacheado de la ejecucion anterior. El pipeline lo llama al arrancar."""
        with cls._locks_lock:
            cls._locks.clear()
        cls._folder_cache.clear()
        cls._files_cache.clear()
        cls._reserved.clear()

    def __init__(self, credentials_path: str = 'secrets/credentials.json', token_path: str = 'secrets/token.json', console: Console | None = None, creds=None):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self._console = console or Console()
        self.creds = creds or self._authenticate()
        self.docs_service = build('docs', 'v1', credentials=self.creds)
        self.drive_service = build('drive', 'v3', credentials=self.creds)

    def _authenticate(self):
        from google.auth.exceptions import RefreshError
        creds = None
        if os.path.exists(self.token_path):
            try:
                with open(self.token_path, 'rb') as token:
                    creds = pickle.load(token)
            except Exception:
                os.remove(self.token_path)
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except RefreshError:
                    if os.path.exists(self.token_path):
                        os.remove(self.token_path)
                    creds = None
            if not creds:
                if not os.path.exists(self.credentials_path):
                    raise FileNotFoundError(
                        f"ERROR: {self.credentials_path} not found. "
                        "Please download it from Google Cloud Console and place it in secrets/credentials.json"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                self._console.print("\n[bold yellow]Google Drive — autorización requerida[/bold yellow]")
                self._console.print("[dim]Abriendo el navegador… si no se abre automáticamente, visita la URL que aparece a continuación.[/dim]")
                # Una app en modo «Testing» invalida el refresh token cada 7 días, así
                # que esto reaparece cada semana aunque no hayas tocado nada.
                self._console.print(
                    "[dim]Si esto te lo pide cada pocos días: publica la app en Google Cloud "
                    "Console › OAuth consent screen › Publish app. En modo Testing el permiso "
                    "caduca cada 7 días.[/dim]\n")
                try:
                    captured = io.StringIO()
                    with contextlib.redirect_stdout(captured):
                        creds = flow.run_local_server(port=0)
                    output = captured.getvalue()
                    url_match = re.search(r'https://accounts\.google\.com\S+', output)
                    if url_match:
                        self._console.print(f"[blue]{url_match.group(0)}[/blue]\n")
                    if creds and creds.valid:
                        self._console.print("[green]✓ Autorización completada.[/green]\n")
                    else:
                        self._console.print("[yellow]⚠ Autorización incompleta.[/yellow]\n")
                except Exception as e:
                    self._console.print(f"[red]✗ Error durante la autorización: {e}[/red]\n")
                    raise
            with open(self.token_path, 'wb') as token:
                pickle.dump(creds, token)

        return creds

    def ensure_fresh_credentials(self, min_remaining: int = 900) -> bool:
        """Renueva el token si le queda poco. API: True si se ha renovado.

        Las credenciales se comparten entre todos los hilos del pipeline. Si caducan a
        mitad de la ejecución, cada hilo intenta refrescarlas por su cuenta y a la vez.
        Renovarlas antes de arrancar el pool deja esa ventana prácticamente cerrada:
        un token dura una hora y una ejecución dura minutos.
        """
        import datetime

        expiry = getattr(self.creds, "expiry", None)
        if expiry is None or not getattr(self.creds, "refresh_token", None):
            return False
        restante = (expiry - datetime.datetime.utcnow()).total_seconds()
        if restante > min_remaining:
            return False

        with GoogleDocsManager._creds_lock:
            self.creds.refresh(Request())
            try:
                with open(self.token_path, 'wb') as token:
                    pickle.dump(self.creds, token)
            except OSError:
                pass       # renovado en memoria; el próximo arranque lo repetirá
        return True

    def get_or_create_subfolder(self, parent_id: str, folder_name: str) -> str:
        key = (parent_id, folder_name.strip().lower())
        cached = GoogleDocsManager._folder_cache.get(key)
        if cached:
            return cached
        # Un lock por carpeta: sin esto, dos idiomas que crean carpetas distintas se
        # esperaban el uno al otro durante una llamada de red entera.
        with GoogleDocsManager._lock_for(f"folder:{key}"):
            cached = GoogleDocsManager._folder_cache.get(key)
            if cached:
                return cached
            folder_id = self._lookup_or_create_subfolder(parent_id, folder_name)
            GoogleDocsManager._folder_cache[key] = folder_id
            return folder_id

    def _lookup_or_create_subfolder(self, parent_id: str, folder_name: str) -> str:
        query = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        target_name_normalized = folder_name.strip().lower()
        page_token = None
        while True:
            results = self.drive_service.files().list(
                q=query,
                fields='nextPageToken, files(id, name)',
                corpora='allDrives',
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                pageToken=page_token
            ).execute()
            for f in results.get('files', []):
                if f.get('name', '').strip().lower() == target_name_normalized:
                    return f.get('id')
            page_token = results.get('nextPageToken')
            if not page_token:
                break
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        folder = self.drive_service.files().create(
            body=file_metadata, fields='id', supportsAllDrives=True
        ).execute()
        return folder.get('id')

    def _list_files(self, folder_id: str) -> list[dict]:
        query = f"'{folder_id}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed=false"
        files: list[dict] = []
        page_token = None
        while True:
            results = self.drive_service.files().list(
                q=query, fields='nextPageToken, files(id, name)',
                corpora='allDrives', includeItemsFromAllDrives=True,
                supportsAllDrives=True, pageToken=page_token,
            ).execute()
            files.extend(results.get('files', []))
            page_token = results.get('nextPageToken')
            if not page_token:
                break
        return files

    def _cached_files(self, folder_id: str) -> list[dict]:
        """Listado de la carpeta, leido una sola vez por ejecucion.

        Se llamaba a la API dos veces por documento —una para buscar el que se
        reemplaza y otra para calcular el numero— y ademas con un lock global, asi que
        40 subidas eran 80 peticiones estrictamente en fila. Lo que esta ejecucion crea
        no hace falta releerlo: los nombres nuevos viven en _reserved y una
        actualizacion en sitio no cambia el nombre de nada.
        """
        cached = GoogleDocsManager._files_cache.get(folder_id)
        if cached is None:
            cached = self._list_files(folder_id)
            GoogleDocsManager._files_cache[folder_id] = cached
        return cached

    def list_subfolders(self, parent_id: str) -> list[dict]:
        """Subcarpetas directas de parent_id, ordenadas por nombre. API: [{id, name}]."""
        query = (f"'{parent_id}' in parents and "
                 "mimeType='application/vnd.google-apps.folder' and trashed=false")
        folders: list[dict] = []
        page_token = None
        while True:
            results = self.drive_service.files().list(
                q=query, fields='nextPageToken, files(id, name)', orderBy='name',
                corpora='allDrives', includeItemsFromAllDrives=True,
                supportsAllDrives=True, pageToken=page_token,
            ).execute()
            folders.extend(results.get('files', []))
            page_token = results.get('nextPageToken')
            if not page_token:
                break
        return folders

    def get_folder_info(self, folder_id: str) -> dict:
        """Nombre y padre de una carpeta. API: {id, name, parents}."""
        return self.drive_service.files().get(
            fileId=folder_id, fields='id, name, parents', supportsAllDrives=True).execute()

    @staticmethod
    def _pattern_to_regex(pattern: str, title: str | None = None,
                          lang: str | None = None) -> re.Pattern:
        """Convierte un patron en regex. Con title, casa solo los de ESE documento."""
        parts = re.split(r'(\{[^}]+\})', pattern)
        regex = ''
        for part in parts:
            if part == '{n}':
                regex += r'(\d+)'
            elif part == '{title}':
                regex += re.escape(title) if title is not None else r'.+?'
            elif part == '{lang}':
                regex += re.escape(lang.upper()) if lang else r'.+?'
            elif part.startswith('{') and part.endswith('}'):
                regex += r'.+?'
            else:
                regex += re.escape(part)
        return re.compile('^' + regex + '$')

    def _find_next_number(self, folder_id: str, pattern: str | None,
                          extra_used: set[str] | None = None) -> int:
        names = [f['name'] for f in self._cached_files(folder_id)] + sorted(extra_used or ())
        if not names:
            return 1
        # Se cuentan los que casan con el patron actual y, ademas, cualquier nombre que
        # empiece por un numero: al cambiar de patron ("{n}" a "{n}. {title}") los
        # documentos ya subidos siguen contando y la numeracion no se reinicia.
        patterns = [re.compile(r'^(\d+)(?:\D|$)')]
        if pattern and '{n}' in pattern:
            patterns.append(self._pattern_to_regex(pattern))
        used: set[int] = set()
        for name in names:
            for rx in patterns:
                m = rx.match(name)
                if m:
                    try:
                        used.add(int(m.group(1)))
                    except (ValueError, IndexError):
                        pass
                    break
        n = 1
        while n in used:
            n += 1
        return n

    def resolve_language_folder(self, folder_id: str, lang: str, lang_folder_names: dict | None = None) -> str:
        names = lang_folder_names or LANG_NAMES
        lang_folder_name = names.get(lang.lower(), lang.upper())
        return self.get_or_create_subfolder(folder_id, lang_folder_name)

    @staticmethod
    def _effective_pattern(pattern: str | None, disambiguate_lang: bool) -> str | None:
        """Anade {lang} al patron cuando varios idiomas comparten carpeta.

        Sin esto, con organize_by_language en false los cuatro idiomas del mismo
        documento resolvian al mismo nombre y, con replace_existing, se sobrescribian
        entre ellos: cuatro traducciones y un solo documento en Drive.
        """
        if pattern and disambiguate_lang and '{lang}' not in pattern:
            return pattern + ' ({lang})'
        return pattern

    @staticmethod
    def _plain_name(title: str, lang: str, disambiguate_lang: bool) -> str:
        return f"{title} ({lang.upper()})" if disambiguate_lang else title

    def resolve_filename(self, title: str, folder_id: str, lang: str, sequential_naming: bool = False,
                         sequential_naming_pattern: str | None = None,
                         disambiguate_lang: bool = False) -> str:
        # La reserva se hace bajo lock: Drive todavia no conoce los nombres que otros
        # hilos estan subiendo en este mismo instante.
        pattern = self._effective_pattern(sequential_naming_pattern, disambiguate_lang)
        with GoogleDocsManager._lock_for(folder_id):
            return self._reserve_name(title, folder_id, lang, sequential_naming,
                                      pattern, disambiguate_lang)

    def resolve_target(self, title: str, folder_id: str, lang: str,
                       sequential_naming: bool = False,
                       sequential_naming_pattern: str | None = None,
                       replace_existing: bool = False,
                       disambiguate_lang: bool = False) -> tuple[str, str | None]:
        """Nombre de destino y, si procede, id del documento que debe reemplazarse.

        Con replace_existing, un documento anterior del mismo titulo se actualiza en
        sitio: conserva enlace, comentarios e historial de versiones, y la carpeta no
        se llena de duplicados en cada pasada. Con disambiguate_lang, el idioma entra
        en el nombre porque la carpeta es compartida. Devuelve (nombre, file_id | None).
        """
        pattern = self._effective_pattern(sequential_naming_pattern, disambiguate_lang)
        with GoogleDocsManager._lock_for(folder_id):
            if replace_existing:
                if sequential_naming and pattern:
                    rx = self._pattern_to_regex(pattern, title=title, lang=lang)
                    match = lambda n: rx.match(n) is not None
                else:
                    plain = self._plain_name(title, lang, disambiguate_lang)
                    match = lambda n: n == plain
                # Ordenado por nombre: si el mismo titulo aparece dos veces, se reemplaza
                # siempre el mismo y no el que Drive devuelva primero esta vez.
                for f in sorted(self._cached_files(folder_id), key=lambda f: f['name']):
                    if match(f['name']):
                        return f['name'], f['id']

            name = self._reserve_name(title, folder_id, lang, sequential_naming,
                                      pattern, disambiguate_lang)
            return name, None

    def _reserve_name(self, title: str, folder_id: str, lang: str,
                      sequential_naming: bool, pattern: str | None,
                      disambiguate_lang: bool = False) -> str:
        if not sequential_naming:
            return self._plain_name(title, lang, disambiguate_lang)
        taken    = GoogleDocsManager._reserved.setdefault(folder_id, set())
        next_num = str(self._find_next_number(folder_id, pattern, taken))
        if pattern:
            doc_name = pattern.replace("{n}", next_num)
            doc_name = doc_name.replace("{title}", title)
            doc_name = doc_name.replace("{lang}", lang.upper())
        else:
            doc_name = next_num
        taken.add(doc_name)
        return doc_name

    def upload_docx(self, docx_path: Path, folder_id: str | None = None,
                    filename: str | None = None, file_id: str | None = None) -> str:
        import time
        from googleapiclient.errors import HttpError

        if not filename:
            filename = docx_path.name
        file_metadata = {
            'name': filename,
            'mimeType': 'application/vnd.google-apps.document'
        }
        if folder_id:
            file_metadata['parents'] = [folder_id]

        media = MediaFileUpload(
            str(docx_path),
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            resumable=True
        )
        max_retries = 4
        base_delay = 2
        for attempt in range(max_retries):
            try:
                if file_id:
                    # Reemplazo en sitio: mismo id, mismo enlace, y Drive guarda la
                    # version anterior en el historial del documento.
                    file = self.drive_service.files().update(
                        fileId=file_id, media_body=media, fields='id', supportsAllDrives=True
                    ).execute()
                else:
                    file = self.drive_service.files().create(
                        body=file_metadata, media_body=media, fields='id', supportsAllDrives=True
                    ).execute()
                return file.get('id')
            except HttpError as e:
                if e.resp.status >= 500 and attempt < max_retries - 1:
                    time.sleep(base_delay * (2 ** attempt))
                else:
                    raise

    def get_document_url(self, doc_id: str) -> str:
        return f"https://docs.google.com/document/d/{doc_id}/edit"
