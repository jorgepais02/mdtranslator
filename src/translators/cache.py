"""Translation cache backed by SQLite with WAL mode and per-thread connections."""

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
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._ensure_schema()
        self._maybe_vacuum()

    def _connect(self) -> sqlite3.Connection:
        if not getattr(self._local, "conn", None):
            # Every pipeline thread writes through its own connection; WAL still
            # serialises writers, so wait instead of failing with "database is locked".
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return self._local.conn

    def _ensure_schema(self) -> None:
        conn = self._connect()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS translations (
                key  TEXT PRIMARY KEY,
                text TEXT NOT NULL
            )
        """)
        conn.commit()

    def _maybe_vacuum(self) -> None:
        size_mb = self.db_path.stat().st_size / (1024 * 1024)
        if size_mb > _VACUUM_THRESHOLD_MB:
            with self._init_lock:
                conn = self._connect()
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.execute("VACUUM")
                conn.commit()

    @staticmethod
    def _key(text: str, lang: str, provider: str) -> str:
        raw = f"{text}\x00{lang}\x00{provider}".encode()
        return hashlib.sha256(raw).hexdigest()

    def get(self, text: str, lang: str, provider: str) -> str | None:
        key = self._key(text, lang, provider)
        row = self._connect().execute(
            "SELECT text FROM translations WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def set(self, text: str, lang: str, provider: str, translation: str) -> None:
        self.set_many([(text, translation)], lang, provider)

    def set_many(self, pairs: list[tuple[str, str]], lang: str, provider: str) -> None:
        """Store a batch of (source, translation) pairs in a single transaction.

        A commit per line turned into thousands of fsyncs once several languages and
        files run in parallel; one transaction per provider call keeps that bounded.
        """
        if not pairs:
            return
        rows = [(self._key(src, lang, provider), tgt) for src, tgt in pairs]
        conn = self._connect()
        with conn:
            conn.executemany(
                "INSERT OR REPLACE INTO translations (key, text) VALUES (?, ?)", rows
            )
