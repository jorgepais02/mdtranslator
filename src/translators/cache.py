"""Translation cache backed by SQLite with WAL mode and a persistent connection."""

import hashlib
import sqlite3
import threading
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DB_PATH = _PROJECT_ROOT / "cache" / "translations.db"
_VACUUM_THRESHOLD_MB = 50


class TranslationCache:
    def __init__(self, db_path: Path = _DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS translations (
                key  TEXT PRIMARY KEY,
                text TEXT NOT NULL
            )
        """)
        self._conn.commit()
        self._maybe_vacuum()

    def _maybe_vacuum(self) -> None:
        size_mb = self.db_path.stat().st_size / (1024 * 1024)
        if size_mb > _VACUUM_THRESHOLD_MB:
            with self._lock:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._conn.execute("VACUUM")
                self._conn.commit()

    @staticmethod
    def _key(text: str, lang: str, provider: str) -> str:
        raw = f"{text}\x00{lang}\x00{provider}".encode()
        return hashlib.sha256(raw).hexdigest()

    def get(self, text: str, lang: str, provider: str) -> str | None:
        key = self._key(text, lang, provider)
        with self._lock:
            row = self._conn.execute(
                "SELECT text FROM translations WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def set(self, text: str, lang: str, provider: str, translation: str) -> None:
        key = self._key(text, lang, provider)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO translations (key, text) VALUES (?, ?)",
                (key, translation),
            )
            self._conn.commit()
