from __future__ import annotations

import json
import hashlib
import re
import shutil
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from .client import SiteClient
from .models import Book, StoredBook


_INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def safe_name(value: str, *, maximum: int = 120) -> str:
    value = _INVALID_WINDOWS_CHARS.sub("_", value).strip().rstrip(".")
    value = re.sub(r"\s+", " ", value)
    if not value:
        value = "untitled"
    if value.split(".", 1)[0].upper() in _RESERVED_NAMES:
        value = f"_{value}"
    return value[:maximum].rstrip()


class OneDriveLibrary:
    def __init__(self, root: Path):
        self.root = root

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def book_directory(self, book: Book | StoredBook) -> Path:
        return self.root / "books" / safe_name(book.slug)

    def materialize(self, book_id: int, book: Book) -> Path:
        directory = self.book_directory(book)
        directory.mkdir(parents=True, exist_ok=True)
        metadata = {
            "id": book_id,
            **asdict(book),
        }
        metadata_path = directory / "metadata.json"
        temporary = metadata_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(metadata_path)
        self._write_shortcut(directory / "SaltTiger.url", book.origin_url)
        if book.official_url:
            self._write_shortcut(directory / "Official.url", book.official_url)
        provider_counts: dict[str, int] = {}
        for download in book.downloads:
            provider_counts[download.provider] = provider_counts.get(download.provider, 0) + 1
            suffix = "" if provider_counts[download.provider] == 1 else f"-{provider_counts[download.provider]}"
            name = safe_name(f"{download.provider}{suffix}.url")
            self._write_shortcut(directory / name, download.url)
        return directory

    def import_file(self, source: Path, book: StoredBook, *, replace: bool = False) -> Path:
        source = source.resolve(strict=True)
        if not source.is_file():
            raise ValueError(f"not a file: {source}")
        directory = self.book_directory(book)
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / safe_name(source.name, maximum=180)
        if destination.exists() and not replace:
            raise FileExistsError(f"destination already exists: {destination}")
        shutil.copy2(source, destination)
        return destination.resolve()

    def import_download_tree(self, source_root: Path, book: StoredBook, source_url: str) -> list[Path]:
        directory = self.book_directory(book)
        directory.mkdir(parents=True, exist_ok=True)
        imported: list[Path] = []
        digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:8]
        for source in sorted(
            path
            for path in source_root.rglob("*")
            if path.is_file() and not path.is_symlink() and not path.name.endswith(".part")
        ):
            relative = source.relative_to(source_root)
            safe_parts = [safe_name(part, maximum=120) for part in relative.parts]
            destination = directory.joinpath(*safe_parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if self._same_file(source, destination):
                    imported.append(destination.resolve())
                    continue
                destination = destination.with_name(f"{destination.stem}-{digest}{destination.suffix}")
                if destination.exists() and self._same_file(source, destination):
                    imported.append(destination.resolve())
                    continue
            shutil.copy2(source, destination)
            destination.with_suffix(destination.suffix + ".source-url").write_text(source_url + "\n", encoding="utf-8")
            imported.append(destination.resolve())
        return imported

    def download_direct_links(self, book: Book, client: SiteClient) -> list[Path]:
        directory = self.book_directory(book)
        downloaded: list[Path] = []
        for index, link in enumerate((item for item in book.downloads if item.provider == "direct"), 1):
            name = PurePosixPath(urlparse(link.url).path).name or f"download-{index}.bin"
            destination = directory / safe_name(name, maximum=180)
            source_marker = destination.with_suffix(destination.suffix + ".source-url")
            if (
                destination.exists()
                and source_marker.exists()
                and source_marker.read_text(encoding="utf-8", errors="ignore").strip() == link.url
            ):
                downloaded.append(destination)
                continue
            if destination.exists():
                digest = hashlib.sha256(link.url.encode("utf-8")).hexdigest()[:8]
                destination = destination.with_name(f"{destination.stem}-{digest}{destination.suffix}")
            downloaded.append(client.download(link.url, destination))
            destination.with_suffix(destination.suffix + ".source-url").write_text(link.url + "\n", encoding="utf-8")
        return downloaded

    @staticmethod
    def _write_shortcut(path: Path, url: str) -> None:
        path.write_text(f"[InternetShortcut]\nURL={url}\n", encoding="utf-8")

    @staticmethod
    def _same_file(left: Path, right: Path) -> bool:
        if left.stat().st_size != right.stat().st_size:
            return False
        return OneDriveLibrary._file_hash(left) == OneDriveLibrary._file_hash(right)

    @staticmethod
    def _file_hash(path: Path) -> bytes:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.digest()
