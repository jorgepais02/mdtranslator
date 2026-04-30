"""Project-wide configuration and path constants."""

import json
from pathlib import Path

PROJECT_ROOT    = Path(__file__).resolve().parent.parent.parent
SOURCES_DIR     = PROJECT_ROOT / "sources"
TRANSLATED_DIR  = PROJECT_ROOT / "translated"


def load_config() -> dict:
    """Load user config from config.json, falling back to config.example.json."""
    for name in ("config.json", "config.example.json"):
        p = PROJECT_ROOT / name
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return {"drive": {}, "document": {}}


CONFIG = load_config()

DRIVE_FOLDER_ID = CONFIG.get("drive", {}).get("folder_id", "").strip()

DEFAULT_LANGS = CONFIG.get("document", {}).get("default_languages", ["EN", "FR", "AR", "ZH"])
