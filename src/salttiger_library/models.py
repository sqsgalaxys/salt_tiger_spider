from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True, frozen=True)
class ArchiveEntry:
    title: str
    detail_url: str
    published_at: str | None = None


@dataclass(slots=True, frozen=True)
class DownloadLink:
    provider: str
    url: str
    extract_code: str | None = None
    label: str | None = None


@dataclass(slots=True)
class Book:
    title: str
    origin_url: str
    slug: str
    published_at: str | None = None
    publisher: str | None = None
    official_url: str | None = None
    cover_url: str | None = None
    tags: list[str] = field(default_factory=list)
    downloads: list[DownloadLink] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class StoredBook:
    id: int
    title: str
    slug: str
    origin_url: str
    published_at: str | None
    publisher: str | None
    official_url: str | None
    cover_url: str | None
    tags: list[str]
    created_at: str
    updated_at: str


@dataclass(slots=True, frozen=True)
class PanDownloadTask:
    id: int
    book_id: int
    book_slug: str
    book_title: str
    url: str
    extract_code: str | None
    status: str
    local_path: str | None
    last_error: str | None
