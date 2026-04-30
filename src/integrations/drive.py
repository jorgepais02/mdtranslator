import io
import contextlib
import os
import pickle
import re
import base64
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
    """Manages Google Docs creation, text insertion, and Drive uploads."""

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
                self._console.print("[dim]Abriendo el navegador… si no se abre automáticamente, visita la URL que aparece a continuación.[/dim]\n")
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

    def get_or_create_subfolder(self, parent_id: str, folder_name: str) -> str:
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

    def _list_file_names(self, folder_id: str) -> list[str]:
        query = f"'{folder_id}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed=false"
        names = []
        page_token = None
        while True:
            results = self.drive_service.files().list(
                q=query, fields='nextPageToken, files(name)',
                corpora='allDrives', includeItemsFromAllDrives=True,
                supportsAllDrives=True, pageToken=page_token,
            ).execute()
            names.extend(f['name'] for f in results.get('files', []))
            page_token = results.get('nextPageToken')
            if not page_token:
                break
        return names

    @staticmethod
    def _pattern_to_regex(pattern: str) -> re.Pattern:
        parts = re.split(r'(\{[^}]+\})', pattern)
        regex = ''
        for part in parts:
            if part == '{n}':
                regex += r'(\d+)'
            elif part.startswith('{') and part.endswith('}'):
                regex += r'.+?'
            else:
                regex += re.escape(part)
        return re.compile('^' + regex + '$')

    def _find_next_number(self, folder_id: str, pattern: str | None) -> int:
        names = self._list_file_names(folder_id)
        if not names:
            return 1
        if pattern and '{n}' in pattern:
            rx = self._pattern_to_regex(pattern)
        else:
            rx = re.compile(r'^(\d+)$')
        used: set[int] = set()
        for name in names:
            m = rx.match(name)
            if m:
                try:
                    used.add(int(m.group(1)))
                except (ValueError, IndexError):
                    pass
        n = 1
        while n in used:
            n += 1
        return n

    def resolve_language_folder(self, folder_id: str, lang: str, lang_folder_names: dict | None = None) -> str:
        names = lang_folder_names or LANG_NAMES
        lang_folder_name = names.get(lang.lower(), lang.upper())
        return self.get_or_create_subfolder(folder_id, lang_folder_name)

    def resolve_filename(self, title: str, folder_id: str, lang: str, sequential_naming: bool = False,
                         sequential_naming_pattern: str | None = None) -> str:
        if not sequential_naming:
            return title
        next_num = str(self._find_next_number(folder_id, sequential_naming_pattern))
        if sequential_naming_pattern:
            doc_name = sequential_naming_pattern.replace("{n}", next_num)
            doc_name = doc_name.replace("{title}", title)
            doc_name = doc_name.replace("{lang}", lang.upper())
            return doc_name
        return next_num

    def upload_docx(self, docx_path: Path, folder_id: str | None = None, filename: str | None = None) -> str:
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
                file = self.drive_service.files().create(
                    body=file_metadata, media_body=media, fields='id', supportsAllDrives=True
                ).execute()
                return file.get('id')
            except HttpError as e:
                if e.resp.status >= 500 and attempt < max_retries - 1:
                    sleep_time = base_delay * (2 ** attempt)
                    self._console.print(f"[yellow]⚠ Drive API error {e.resp.status} — reintentando en {sleep_time}s…[/yellow]")
                    time.sleep(sleep_time)
                else:
                    raise

    def get_document_url(self, doc_id: str) -> str:
        return f"https://docs.google.com/document/d/{doc_id}/edit"
