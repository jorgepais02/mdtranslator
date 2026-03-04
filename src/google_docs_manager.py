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

    def create_document(self, title: str, folder_id: str | None = None, lang: str = "es",
                         organize_by_language: bool = False, sequential_naming: bool = False,
                         lang_folder_names: dict | None = None,
                         sequential_naming_pattern: str | None = None) -> str:
        """Create a new Google Doc.
        
        If organize_by_language=True and folder_id is set, creates language subfolders.
        If sequential_naming=True, names documents according to sequential_naming_pattern 
        (e.g "{n} - {title}"), or simply "1", "2" if no pattern is provided.
        Otherwise uses the original title.
        """
        doc_name = title
        target_folder_id = folder_id

        if folder_id and organize_by_language:
            names = lang_folder_names or LANG_NAMES
            lang_key = lang.lower()
            lang_folder_name = names.get(lang_key, lang.upper())
            target_folder_id = self.get_or_create_subfolder(folder_id, lang_folder_name)

        if target_folder_id and sequential_naming:
            next_num = self.get_next_sequential_name(target_folder_id)
            if sequential_naming_pattern:
                doc_name = sequential_naming_pattern.replace("{n}", next_num)
                doc_name = doc_name.replace("{title}", title)
                doc_name = doc_name.replace("{lang}", lang.upper())
            else:
                doc_name = next_num

        file_metadata = {
            'name': doc_name,
            'mimeType': 'application/vnd.google-apps.document'
        }
        
        if target_folder_id:
            file_metadata['parents'] = [target_folder_id]

        file = self.drive_service.files().create(
            body=file_metadata, 
            fields='id',
            supportsAllDrives=True
        ).execute()
        return file.get('id')

    def _upload_image_to_drive(self, image_path: Path) -> dict:
        """Upload an image to Drive, make it public, and return the file dict (id and link)."""
        file_metadata = {
            'name': image_path.name,
            'mimeType': 'image/png'
        }
        media = MediaFileUpload(str(image_path), mimetype='image/png')
        file = self.drive_service.files().create(body=file_metadata, media_body=media, fields='id, webContentLink').execute()
        
        # Make the file readable by everyone with the link (required for Docs API insertion)
        self.drive_service.permissions().create(
            fileId=file.get('id'),
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()
        
        return file

    def setup_document_layout(self, doc_id: str, header_image_path: Path | None = None, is_rtl: bool = False, lang: str = "es"):
        """Setup headers, footers (page numbers), and RTL section settings."""
        requests = []
        
        # 1. Create Header
        header_resp = self.docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={'requests': [{'createHeader': {'type': 'DEFAULT'}}]}
        ).execute()
        header_id = header_resp['replies'][0]['createHeader']['headerId']
        
        uploaded_image_id = None
        
        # 2. Insert Image
        image_uri = None
        if header_image_path:
            if isinstance(header_image_path, str) and header_image_path.startswith("http"):
                image_uri = header_image_path
            elif isinstance(header_image_path, Path) and header_image_path.exists():
                file_info = self._upload_image_to_drive(header_image_path)
                image_uri = file_info.get('webContentLink')
                uploaded_image_id = file_info.get('id')
                
        if image_uri:
            requests.append({
                'insertInlineImage': {
                    'uri': image_uri,
                    'location': {'segmentId': header_id, 'index': 0},
                    'objectSize': {'width': {'magnitude': 500, 'unit': 'PT'}}
                }
            })
            requests.append({
                'updateParagraphStyle': {
                    'range': {'segmentId': header_id, 'startIndex': 0, 'endIndex': 1},
                    'paragraphStyle': {'alignment': 'CENTER'},
                    'fields': 'alignment'
                }
            })

        # Note: Google Docs REST API v1 currently does not support dynamic page numbers
        # (there is no native InsertPageNumberRequest). Any static text inserted here 
        # (like '1') would repeat on every page without incrementing.
        # So we skip adding a footer altogether for now.


        # 4. Set Document-wide RTL at section level
        if is_rtl:
            # This is complex in Docs API as it's often a paragraph property.
            # We already set it in upload_markdown_content per paragraph.
            pass

        if requests:
            self.docs_service.documents().batchUpdate(documentId=doc_id, body={'requests': requests}).execute()

        # 5. Cleanup: If we uploaded an image to Drive just for this, delete it now that it's embedded.
        if uploaded_image_id:
            try:
                self.drive_service.files().delete(fileId=uploaded_image_id).execute()
            except Exception as e:
                print(f"Warning: Failed to delete temporary header image from Drive: {e}")

    def upload_markdown_content(self, doc_id: str, lines: list[str], lang: str):
        """Parse Markdown lines and insert into Google Doc with full formatting."""
        import re

        requests_list = []
        is_rtl = lang in RTL_LANGS
        
        full_text = ""
        formats = []  # (start, end, type, level, is_consecutive)
        inline_formats = []  # (start_in_doc, end_in_doc, style_dict)
        
        current_offset = 0
        in_code_block = False
        prev_type = None

        # Inline formatting regex
        _INLINE_RE = re.compile(
            r'(?P<bold_italic>\*\*\*(.+?)\*\*\*)'
            r'|(?P<bold>\*\*(.+?)\*\*)'
            r'|(?P<italic>\*(.+?)\*)'
            r'|(?P<code>`([^`]+)`)'
            r'|(?P<link>\[([^\]]+)\]\(([^)]+)\))'
        )

        def _strip_inline_markers(text):
            clean = ""
            fmt_ranges = []
            last_end = 0
            for m in _INLINE_RE.finditer(text):
                clean += text[last_end:m.start()]
                seg_start = len(clean)
                if m.group("bold_italic"):
                    inner = m.group(2)
                    clean += inner
                    fmt_ranges.append((seg_start, seg_start + len(inner), {"bold": True, "italic": True}))
                elif m.group("bold"):
                    inner = m.group(4)
                    clean += inner
                    fmt_ranges.append((seg_start, seg_start + len(inner), {"bold": True}))
                elif m.group("italic"):
                    inner = m.group(6)
                    clean += inner
                    fmt_ranges.append((seg_start, seg_start + len(inner), {"italic": True}))
                elif m.group("code"):
                    inner = m.group(8)
                    clean += inner
                    fmt_ranges.append((seg_start, seg_start + len(inner), {"code": True}))
                elif m.group("link"):
                    link_text = m.group(10)
                    link_url = m.group(11)
                    clean += link_text
                    fmt_ranges.append((seg_start, seg_start + len(link_text), {"link": link_url}))
                last_end = m.end()
            clean += text[last_end:]
            return clean, fmt_ranges

        for line in lines:
            # Code block toggling ignores line stripping to maintain format logic
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            
            # Inside code block: preserve exact spaces, do not rstrip entirely
            if in_code_block:
                content = line + "\n"
                full_text += content
                formats.append((start, start + len(content), 'CODE_BLOCK', 0, False))
                current_offset += len(content)
                prev_type = 'CODE_BLOCK'
                continue

            # Outside code block: normal processing
            line = line.rstrip()
            if not line:
                continue

            start = 1 + current_offset

            if line.startswith("#"):
                hashes = line.split(" ")[0]
                level = len(hashes)
                raw_content = " ".join(line.split(" ")[1:])
                clean_content, fmt_ranges = _strip_inline_markers(raw_content)
                content = clean_content + "\n"
                full_text += content
                is_consecutive = (prev_type == 'HEADING')
                formats.append((start, start + len(content), 'HEADING', level, is_consecutive))
                for fs, fe, style in fmt_ranges:
                    inline_formats.append((start + fs, start + fe, style))
                current_offset += len(content)
                prev_type = 'HEADING'
            elif line.startswith("> ") or line.startswith(">"):
                quote_text = line.lstrip(">").strip()
                clean_content, fmt_ranges = _strip_inline_markers(quote_text)
                content = clean_content + "\n"
                full_text += content
                formats.append((start, start + len(content), 'BLOCKQUOTE', 0, False))
                for fs, fe, style in fmt_ranges:
                    inline_formats.append((start + fs, start + fe, style))
                current_offset += len(content)
                prev_type = 'BLOCKQUOTE'
            elif line.startswith("---") or line.startswith("***"):
                # Simpler divider logic
                full_text += "---\n"
                formats.append((start, start + 4, 'NORMAL', 0, False))
                current_offset += 4
                prev_type = 'NORMAL'
            elif line.startswith("- "):
                raw_content = line[2:]
                clean_content, fmt_ranges = _strip_inline_markers(raw_content)
                content = clean_content + "\n"
                full_text += content
                formats.append((start, start + len(content), 'BULLET', 0, False))
                for fs, fe, style in fmt_ranges:
                    inline_formats.append((start + fs, start + fe, style))
                current_offset += len(content)
                prev_type = 'BULLET'
            elif line.strip() and line[0].isdigit() and ". " in line:
                parts = line.split(". ", 1)
                raw_content = parts[1]
                clean_content, fmt_ranges = _strip_inline_markers(raw_content)
                content = clean_content + "\n"
                full_text += content
                formats.append((start, start + len(content), 'NUMBER', 0, False))
                for fs, fe, style in fmt_ranges:
                    inline_formats.append((start + fs, start + fe, style))
                current_offset += len(content)
                prev_type = 'NUMBER'
            else:
                clean_content, fmt_ranges = _strip_inline_markers(line.strip())
                content = clean_content + "\n"
                full_text += content
                
                # If this is indented and comes right after a bullet/number, treat as bullet continuation
                if (line.startswith("  ") or line.startswith("\t")) and prev_type in ('BULLET', 'NUMBER'):
                    formats.append((start, start + len(content), 'BULLET_CONT', 0, False))
                    prev_type = 'BULLET_CONT'
                elif prev_type == 'BULLET_CONT' and (line.startswith("  ") or line.startswith("\t")):
                    formats.append((start, start + len(content), 'BULLET_CONT', 0, False))
                else:
                    formats.append((start, start + len(content), 'NORMAL', 0, False))
                    prev_type = 'NORMAL'
                
                for fs, fe, style in fmt_ranges:
                    inline_formats.append((start + fs, start + fe, style))
                current_offset += len(content)

        # 1. Insert all text
        requests_list.append({
            'insertText': {
                'location': {'index': 1},
                'text': full_text
            }
        })
        
        # 2. Common styles
        total_len = len(full_text)
        if lang == 'zh':
            font_family = 'Noto Serif SC'
        elif lang == 'ar':
            font_family = 'Amiri'
        else:
            font_family = 'Times New Roman'
        
        requests_list.append({
            'updateTextStyle': {
                'range': {'startIndex': 1, 'endIndex': 1 + total_len},
                'textStyle': {
                    'weightedFontFamily': {'fontFamily': font_family},
                    'fontSize': {'magnitude': 12, 'unit': 'PT'}
                },
                'fields': 'weightedFontFamily,fontSize'
            }
        })

        if is_rtl:
            requests_list.append({
                'updateParagraphStyle': {
                    'range': {'startIndex': 1, 'endIndex': 1 + total_len},
                    'paragraphStyle': {
                        'direction': 'RIGHT_TO_LEFT',
                        'alignment': 'START',
                        'spaceBelow': {'magnitude': 8, 'unit': 'PT'},
                        'spaceAbove': {'magnitude': 0, 'unit': 'PT'},
                        'lineSpacing': 130
                    },
                    'fields': 'direction,alignment,spaceBelow,spaceAbove,lineSpacing'
                }
            })
        else:
            requests_list.append({
                'updateParagraphStyle': {
                    'range': {'startIndex': 1, 'endIndex': 1 + total_len},
                    'paragraphStyle': {
                        'alignment': 'JUSTIFIED',
                        'spaceBelow': {'magnitude': 10, 'unit': 'PT'},
                        'spaceAbove': {'magnitude': 0, 'unit': 'PT'},
                        'lineSpacing': 115
                    },
                    'fields': 'alignment,spaceBelow,spaceAbove,lineSpacing'
                }
            })

        # 3. Block-level styles
        for start, end, ftype, level, is_consecutive in formats:
            if ftype == 'HEADING':
                named_style = 'TITLE' if level == 1 else f'HEADING_{min(level - 1, 6)}'
                if is_consecutive:
                    space_below = 4
                    space_above = 6
                else:
                    space_below = 36 if level == 1 else 8
                    space_above = 0 if level == 1 else 36
                
                requests_list.append({
                    'updateParagraphStyle': {
                        'range': {'startIndex': start, 'endIndex': end},
                        'paragraphStyle': {
                            'namedStyleType': named_style,
                            'alignment': 'CENTER' if level == 1 else 'START',
                            'direction': 'RIGHT_TO_LEFT' if is_rtl else 'LEFT_TO_RIGHT',
                            'spaceBelow': {'magnitude': space_below, 'unit': 'PT'},
                            'spaceAbove': {'magnitude': space_above, 'unit': 'PT'}
                        },
                        'fields': 'namedStyleType,alignment,direction,spaceBelow,spaceAbove'
                    }
                })
                requests_list.append({
                    'updateTextStyle': {
                        'range': {'startIndex': start, 'endIndex': end},
                        'textStyle': {'weightedFontFamily': {'fontFamily': font_family}},
                        'fields': 'weightedFontFamily'
                    }
                })

            elif ftype == 'BLOCKQUOTE':
                requests_list.append({
                    'updateParagraphStyle': {
                        'range': {'startIndex': start, 'endIndex': end},
                        'paragraphStyle': {
                            'indentStart': {'magnitude': 36, 'unit': 'PT'},
                            'direction': 'RIGHT_TO_LEFT' if is_rtl else 'LEFT_TO_RIGHT',
                            'alignment': 'START',
                            'spaceBelow': {'magnitude': 4, 'unit': 'PT'},
                            'spaceAbove': {'magnitude': 4, 'unit': 'PT'},
                        },
                        'fields': 'indentStart,direction,alignment,spaceBelow,spaceAbove'
                    }
                })
                requests_list.append({
                    'updateTextStyle': {
                        'range': {'startIndex': start, 'endIndex': end},
                        'textStyle': {
                            'italic': True,
                            'foregroundColor': {'color': {'rgbColor': {'red': 0.4, 'green': 0.4, 'blue': 0.4}}}
                        },
                        'fields': 'italic,foregroundColor'
                    }
                })

            elif ftype == 'CODE_BLOCK':
                pass # Revert code block complexity back to simple normal text processing for Google Docs
            

            elif ftype == 'BULLET_CONT':
                requests_list.append({
                    'updateParagraphStyle': {
                        'range': {'startIndex': start, 'endIndex': end},
                        'paragraphStyle': {
                            'indentStart': {'magnitude': 36, 'unit': 'PT'},
                            'direction': 'RIGHT_TO_LEFT' if is_rtl else 'LEFT_TO_RIGHT',
                            'alignment': 'START',
                        },
                        'fields': 'indentStart,direction,alignment'
                    }
                })
            
            elif ftype == 'BULLET':
                requests_list.append({
                    'createParagraphBullets': {
                        'range': {'startIndex': start, 'endIndex': end},
                        'bulletPreset': 'BULLET_DISC_CIRCLE_SQUARE'
                    }
                })

            elif ftype == 'NUMBER':
                requests_list.append({
                    'createParagraphBullets': {
                        'range': {'startIndex': start, 'endIndex': end},
                        'bulletPreset': 'NUMBERED_DECIMAL_ALPHA_ROMAN'
                    }
                })
                
            if is_rtl and ftype in ('BULLET', 'NUMBER'):
                requests_list.append({
                    'updateParagraphStyle': {
                        'range': {'startIndex': start, 'endIndex': end},
                        'paragraphStyle': {
                            'direction': 'RIGHT_TO_LEFT',
                            'alignment': 'START'
                        },
                        'fields': 'direction,alignment'
                    }
                })

        # 4. Inline formatting
        for istart, iend, style in inline_formats:
            text_style = {}
            fields = []
            if style.get("bold"):
                text_style["bold"] = True
                fields.append("bold")
            if style.get("italic"):
                text_style["italic"] = True
                fields.append("italic")
            if style.get("code"):
                text_style["weightedFontFamily"] = {"fontFamily": "Courier New"}
                text_style["backgroundColor"] = {"color": {"rgbColor": {"red": 0.91, "green": 0.91, "blue": 0.91}}}
                fields.extend(["weightedFontFamily", "backgroundColor"])
            if style.get("link"):
                text_style["link"] = {"url": style["link"]}
                text_style["foregroundColor"] = {"color": {"rgbColor": {"red": 0.0, "green": 0.0, "blue": 0.93}}}
                text_style["underline"] = True
                fields.extend(["link", "foregroundColor", "underline"])

            if text_style and fields:
                requests_list.append({
                    'updateTextStyle': {
                        'range': {'startIndex': istart, 'endIndex': iend},
                        'textStyle': text_style,
                        'fields': ','.join(fields)
                    }
                })

        # Execute all updates
        if requests_list:
            self.docs_service.documents().batchUpdate(documentId=doc_id, body={'requests': requests_list}).execute()

    def get_document_url(self, doc_id: str) -> str:
        return f"https://docs.google.com/document/d/{doc_id}/edit"

