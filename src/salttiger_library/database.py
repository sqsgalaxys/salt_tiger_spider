from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .models import Book, PanDownloadTask, StoredBook


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    publisher TEXT,
    published_at TEXT,
    origin_url TEXT NOT NULL UNIQUE,
    official_url TEXT,
    cover_url TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_books_title ON books(title);
CREATE INDEX IF NOT EXISTS idx_books_published_at ON books(published_at DESC);

CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    url TEXT NOT NULL,
    extract_code TEXT,
    label TEXT,
    status TEXT NOT NULL DEFAULT 'available',
    local_path TEXT,
    last_error TEXT,
    last_checked_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(book_id, url)
);
"""


class LibraryDatabase:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(SCHEMA)
            columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(downloads)")}
            if "last_error" not in columns:
                connection.execute("ALTER TABLE downloads ADD COLUMN last_error TEXT")
            connection.commit()

    def upsert_book(self, book: Book) -> int:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO books (
                    slug, title, publisher, published_at, origin_url,
                    official_url, cover_url, tags_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(origin_url) DO UPDATE SET
                    slug = excluded.slug,
                    title = excluded.title,
                    publisher = excluded.publisher,
                    published_at = COALESCE(excluded.published_at, books.published_at),
                    official_url = excluded.official_url,
                    cover_url = excluded.cover_url,
                    tags_json = excluded.tags_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    book.slug,
                    book.title,
                    book.publisher,
                    book.published_at,
                    book.origin_url,
                    book.official_url,
                    book.cover_url,
                    json.dumps(book.tags, ensure_ascii=False),
                ),
            )
            row = connection.execute("SELECT id FROM books WHERE origin_url = ?", (book.origin_url,)).fetchone()
            if row is None:
                raise RuntimeError("book upsert did not return an id")
            book_id = int(row["id"])
            for download in book.downloads:
                connection.execute(
                    """
                    INSERT INTO downloads (book_id, provider, url, extract_code, label)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(book_id, url) DO UPDATE SET
                        provider = excluded.provider,
                        extract_code = excluded.extract_code,
                        label = excluded.label,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (book_id, download.provider, download.url, download.extract_code, download.label),
                )
            current_urls = [download.url for download in book.downloads]
            if current_urls:
                placeholders = ", ".join("?" for _ in current_urls)
                connection.execute(
                    f"DELETE FROM downloads WHERE book_id = ? AND provider != 'local' AND status = 'available' AND url NOT IN ({placeholders})",
                    (book_id, *current_urls),
                )
            else:
                connection.execute(
                    "DELETE FROM downloads WHERE book_id = ? AND provider != 'local' AND status = 'available'",
                    (book_id,),
                )
            connection.commit()
            return book_id

    def delete_book(self, book_id: int) -> None:
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM books WHERE id = ?", (book_id,))
            connection.commit()

    def exists(self, origin_url: str) -> bool:
        with closing(self._connect()) as connection:
            return connection.execute(
                "SELECT 1 FROM books WHERE origin_url = ?", (origin_url,)
            ).fetchone() is not None

    def get(self, book_id: int) -> StoredBook | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
            return self._stored_book(row) if row else None

    def search(self, query: str, limit: int = 50) -> list[StoredBook]:
        pattern = f"%{query}%"
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM books
                WHERE title LIKE ? OR publisher LIKE ? OR tags_json LIKE ?
                ORDER BY COALESCE(published_at, created_at) DESC
                LIMIT ?
                """,
                (pattern, pattern, pattern, limit),
            ).fetchall()
            return [self._stored_book(row) for row in rows]

    def latest(self, limit: int = 20) -> list[StoredBook]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM books ORDER BY COALESCE(published_at, created_at) DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._stored_book(row) for row in rows]

    def count(self) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM books").fetchone()
            return int(row["count"])

    def attach_local_file(self, book_id: int, path: Path) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO downloads (book_id, provider, url, status, local_path)
                VALUES (?, 'local', ?, 'synced', ?)
                ON CONFLICT(book_id, url) DO UPDATE SET
                    status = 'synced', local_path = excluded.local_path, updated_at = CURRENT_TIMESTAMP
                """,
                (book_id, path.as_uri(), str(path)),
            )
            connection.commit()

    def pan_downloads(self, limit: int = 20, *, retry_failed: bool = False) -> list[PanDownloadTask]:
        statuses = ("available", "failed", "downloading") if retry_failed else ("available",)
        placeholders = ", ".join("?" for _ in statuses)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT d.*, b.slug AS book_slug, b.title AS book_title
                FROM downloads AS d
                JOIN books AS b ON b.id = d.book_id
                WHERE d.provider = 'baidu_pan' AND d.status IN ({placeholders})
                ORDER BY COALESCE(b.published_at, b.created_at) DESC, d.id DESC
                LIMIT ?
                """,
                (*statuses, limit),
            ).fetchall()
            return [
                PanDownloadTask(
                    id=int(row["id"]),
                    book_id=int(row["book_id"]),
                    book_slug=str(row["book_slug"]),
                    book_title=str(row["book_title"]),
                    url=str(row["url"]),
                    extract_code=row["extract_code"],
                    status=str(row["status"]),
                    local_path=row["local_path"],
                    last_error=row["last_error"],
                )
                for row in rows
            ]

    def update_download_status(
        self,
        download_id: int,
        status: str,
        *,
        local_path: str | None = None,
        last_error: str | None = None,
    ) -> None:
        allowed = {"available", "downloading", "synced", "failed"}
        if status not in allowed:
            raise ValueError(f"unsupported download status: {status}")
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE downloads
                SET status = ?, local_path = ?, last_error = ?,
                    last_checked_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, local_path, last_error, download_id),
            )
            connection.commit()

    @staticmethod
    def _stored_book(row: sqlite3.Row) -> StoredBook:
        return StoredBook(
            id=int(row["id"]),
            title=str(row["title"]),
            slug=str(row["slug"]),
            origin_url=str(row["origin_url"]),
            published_at=row["published_at"],
            publisher=row["publisher"],
            official_url=row["official_url"],
            cover_url=row["cover_url"],
            tags=json.loads(row["tags_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
