import os
import pickle
import base64
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Scopes required for Google Drive and Docs
# Added Drive for image uploading
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
    """Manages Google Docs creation, text insertion, and advanced formatting."""
    
    def __init__(self, credentials_path: str = 'secrets/credentials.json', token_path: str = 'secrets/token.json'):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.creds = self._authenticate()
        self.docs_service = build('docs', 'v1', credentials=self.creds)
        self.drive_service = build('drive', 'v3', credentials=self.creds)

    def _authenticate(self):
        """Standard Google API OAuth2 authentication flow."""
        creds = None
        if os.path.exists(self.token_path):
            with open(self.token_path, 'rb') as token:
                creds = pickle.load(token)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_path):
                    raise FileNotFoundError(
                        f"ERROR: {self.credentials_path} not found. "
                        "Please download it from Google Cloud Console and place it in secrets/credentials.json"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            
            with open(self.token_path, 'wb') as token:
                pickle.dump(creds, token)
        
        return creds

    def get_or_create_subfolder(self, parent_id: str, folder_name: str) -> str:
        """Find a subfolder by name within a parent folder case-insensitively, or create it if it doesn't exist."""
        # Query all folders inside the parent
        query = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        target_name_normalized = folder_name.strip().lower()
        
        page_token = None
        while True:
            # We add includeItemsFromAllDrives so Shared Drives aren't skipped
            results = self.drive_service.files().list(
                q=query, 
                fields='nextPageToken, files(id, name)',
                corpora='allDrives',
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                pageToken=page_token
            ).execute()
            
            files = results.get('files', [])
            
            # Case insensitive exact match in Python
            for f in files:
                if f.get('name', '').strip().lower() == target_name_normalized:
                    return f.get('id')
                    
            page_token = results.get('nextPageToken')
            if not page_token:
                break
            
        # Create folder if it doesn't exist
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        folder = self.drive_service.files().create(
            body=file_metadata,
            fields='id',
            supportsAllDrives=True
        ).execute()
        return folder.get('id')
        
    def get_next_sequential_name(self, folder_id: str) -> str:
        """Count the number of files in a folder and return the next sequential number as a string."""
        query = f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.document' and trashed=false"
        # Using pagination to get accurate count if there are many files
        count = 0
        page_token = None
        while True:
            results = self.drive_service.files().list(
                q=query, 
                fields='nextPageToken, files(id)', 
                corpora='allDrives',
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                pageToken=page_token
            ).execute()
            count += len(results.get('files', []))
            page_token = results.get('nextPageToken')
            if not page_token:
                break
        
        return str(count + 1)

    def resolve_language_folder(self, folder_id: str, lang: str, lang_folder_names: dict | None = None) -> str:
        """Find or create a language-specific subfolder."""
        names = lang_folder_names or LANG_NAMES
        lang_key = lang.lower()
        lang_folder_name = names.get(lang_key, lang.upper())
        return self.get_or_create_subfolder(folder_id, lang_folder_name)

    def resolve_filename(self, title: str, folder_id: str, lang: str, sequential_naming: bool = False,
                         sequential_naming_pattern: str | None = None) -> str:
        """Resolve the final file name, applying sequential naming if requested."""
        if not sequential_naming:
            return title

        next_num = self.get_next_sequential_name(folder_id)
        if sequential_naming_pattern:
            doc_name = sequential_naming_pattern.replace("{n}", next_num)
            doc_name = doc_name.replace("{title}", title)
            doc_name = doc_name.replace("{lang}", lang.upper())
            return doc_name
        
        return next_num

    def upload_docx(self, docx_path: Path, folder_id: str | None = None, filename: str | None = None) -> str:
        """Upload a local DOCX file to Google Drive directly, converting it to a Google Doc."""
        if not filename:
            filename = docx_path.name
            
        file_metadata = {
            'name': filename
        }
        if folder_id:
            file_metadata['parents'] = [folder_id]
            
        # application/vnd.google-apps.document as mimetype in MediaFileUpload or in create? 
        # Using media mimetype as docx and telling Drive to convert it by not specifying mimeType in metadata 
        # but the user said Drive does it automatically if opened, but we want it as a Google Doc type.
        # Actually, simply setting mimeType in metadata to 'application/vnd.google-apps.document' forces conversion
        file_metadata['mimeType'] = 'application/vnd.google-apps.document'

        # Correct MIME type for DOCX uploading
        media = MediaFileUpload(
            str(docx_path), 
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            resumable=True
        )

        file = self.drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        ).execute()

        return file.get('id')

    def get_document_url(self, doc_id: str) -> str:
        return f"https://docs.google.com/document/d/{doc_id}/edit"

