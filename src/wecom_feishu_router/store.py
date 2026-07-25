from __future__ import annotations

import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredMedia:
    file_key: str
    file_name: str


class MediaStore:
    def __init__(self, path: Path, ttl_seconds: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._ttl_seconds = ttl_seconds
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS media (
                    media_id TEXT PRIMARY KEY,
                    route_key TEXT NOT NULL,
                    file_key TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                )
                """
            )

    def put(self, route_key: str, file_key: str, file_name: str) -> str:
        media_id = f"router_{secrets.token_urlsafe(24)}"
        expires_at = int(time.time()) + self._ttl_seconds
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO media(media_id, route_key, file_key, file_name, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (media_id, route_key, file_key, file_name, expires_at),
            )
            self._connection.execute(
                "DELETE FROM media WHERE expires_at < ?", (int(time.time()),)
            )
        return media_id

    def get(self, route_key: str, media_id: str) -> StoredMedia | None:
        now = int(time.time())
        with self._lock, self._connection:
            row = self._connection.execute(
                """
                SELECT file_key, file_name
                FROM media
                WHERE media_id = ? AND route_key = ? AND expires_at >= ?
                """,
                (media_id, route_key, now),
            ).fetchone()
        if row is None:
            return None
        return StoredMedia(file_key=row[0], file_name=row[1])

    def close(self) -> None:
        with self._lock:
            self._connection.close()
