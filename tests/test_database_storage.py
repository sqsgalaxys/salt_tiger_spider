import json
from pathlib import Path

from salttiger_library.database import LibraryDatabase
from salttiger_library.models import Book, DownloadLink
from salttiger_library.storage import OneDriveLibrary, safe_name


def sample_book() -> Book:
    return Book(
        title='Example: A/B? "Book"',
        origin_url="https://salttiger.com/example-book/",
        slug="example-book",
        published_at="2026-08-12",
        publisher="Example Press",
        tags=["AI"],
        downloads=[DownloadLink("baidu_pan", "https://pan.baidu.com/s/example", "a1b2")],
    )


def test_upsert_search_and_materialize(tmp_path: Path):
    database = LibraryDatabase(tmp_path / ".salttiger" / "library.sqlite3")
    database.initialize()
    book = sample_book()

    first_id = database.upsert_book(book)
    second_id = database.upsert_book(book)
    assert first_id == second_id
    assert database.count() == 1
    assert database.search("Example Press")[0].id == first_id

    directory = OneDriveLibrary(tmp_path).materialize(first_id, book)
    assert directory.parent == tmp_path / "books"
    assert not any(character in directory.name for character in '<>:"/\\|?*')
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["downloads"][0]["extract_code"] == "a1b2"
    assert "https://pan.baidu.com" in (directory / "baidu_pan.url").read_text(encoding="utf-8")


def test_safe_name_handles_windows_reserved_names():
    assert safe_name("CON") == "_CON"
    assert safe_name("LPT1.pdf") == "_LPT1.pdf"
