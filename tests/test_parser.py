from pathlib import Path

from salttiger_library.parser import classify_download, parse_archive, parse_detail


FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_archive_dates_and_urls():
    entries = parse_archive((FIXTURES / "archive.html").read_text(encoding="utf-8"))

    assert [entry.title for entry in entries] == ["Example Book", "Second Book"]
    assert entries[0].detail_url == "https://salttiger.com/example-book/"
    assert entries[0].published_at == "2026-08-12"
    assert entries[1].published_at == "2026-08-11"


def test_parse_detail_extracts_metadata_and_pan_password():
    book = parse_detail(
        (FIXTURES / "example-book.html").read_text(encoding="utf-8"),
        "https://salttiger.com/example-book/",
    )

    assert book.title == "Example Book"
    assert book.slug == "example-book"
    assert book.published_at == "2026-08-12"
    assert book.publisher == "Example Press"
    assert book.official_url == "https://publisher.example/books/example"
    assert book.cover_url == "https://salttiger.com/covers/example.jpg"
    assert book.tags == ["AI", "Python"]
    assert book.downloads[0].provider == "baidu_pan"
    assert book.downloads[0].extract_code == "a1b2"


def test_download_source_priority_classification():
    assert classify_download("https://pan.baidu.com/s/example") == "baidu_pan"
    assert classify_download("https://files.example/book.epub") == "direct"
    assert classify_download("ed2k://example") == "ed2k"
    assert classify_download("https://publisher.example/book") is None
