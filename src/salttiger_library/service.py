from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .client import SiteClient
from .database import LibraryDatabase
from .models import ArchiveEntry, Book
from .parser import parse_archive, parse_detail
from .storage import OneDriveLibrary


ARCHIVE_URL = "https://salttiger.com/archives/"


@dataclass(slots=True)
class SyncReport:
    discovered: int = 0
    saved: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


class SyncService:
    def __init__(self, database: LibraryDatabase, library: OneDriveLibrary, client: SiteClient):
        self.database = database
        self.library = library
        self.client = client

    def sync(
        self,
        *,
        limit: int | None = None,
        refresh: bool = False,
        archive_html: Path | None = None,
        detail_html_dir: Path | None = None,
        download_direct: bool = False,
    ) -> SyncReport:
        self.database.initialize()
        self.library.ensure()
        archive_text = archive_html.read_text(encoding="utf-8") if archive_html else self.client.get_text(ARCHIVE_URL)
        entries = parse_archive(archive_text, ARCHIVE_URL)
        entries.sort(key=lambda entry: entry.published_at or "", reverse=True)
        if limit is not None:
            entries = entries[:limit]
        report = SyncReport(discovered=len(entries))
        for entry in entries:
            was_existing = self.database.exists(entry.detail_url)
            if not refresh and not download_direct and was_existing:
                report.skipped += 1
                continue
            book_id: int | None = None
            try:
                detail_text = self._detail_text(entry, detail_html_dir)
                book = parse_detail(
                    detail_text,
                    entry.detail_url,
                    fallback_title=entry.title,
                    fallback_date=entry.published_at,
                )
                book_id = self.database.upsert_book(book)
                self.library.materialize(book_id, book)
                if download_direct:
                    self.library.download_direct_links(book, self.client)
                report.saved += 1
            except Exception as error:  # continue other books and summarize failures
                if book_id is not None and not was_existing:
                    self.database.delete_book(book_id)
                report.failed += 1
                report.errors.append(f"{entry.detail_url}: {error}")
        return report

    def import_detail_html(self, html_path: Path, origin_url: str) -> tuple[int, Book]:
        self.database.initialize()
        self.library.ensure()
        book = parse_detail(html_path.read_text(encoding="utf-8"), origin_url)
        book_id = self.database.upsert_book(book)
        self.library.materialize(book_id, book)
        return book_id, book

    def _detail_text(self, entry: ArchiveEntry, detail_html_dir: Path | None) -> str:
        if detail_html_dir:
            candidate = detail_html_dir / f"{Path(entry.detail_url.rstrip('/')).name}.html"
            if candidate.exists():
                return candidate.read_text(encoding="utf-8")
        return self.client.get_text(entry.detail_url)
