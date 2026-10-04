from pathlib import Path

from salttiger_library.client import SiteClient
from salttiger_library.database import LibraryDatabase
from salttiger_library.service import SyncService
from salttiger_library.storage import OneDriveLibrary


FIXTURES = Path(__file__).parent / "fixtures"


def test_fully_offline_sync(tmp_path: Path):
    details = tmp_path / "details"
    details.mkdir()
    for name in ("example-book.html", "second-book.html"):
        (details / name).write_text((FIXTURES / name).read_text(encoding="utf-8"), encoding="utf-8")
    database = LibraryDatabase(tmp_path / "library" / ".salttiger" / "library.sqlite3")
    library = OneDriveLibrary(tmp_path / "library")
    client = SiteClient(user_agent="test", delay_seconds=0)
    try:
        report = SyncService(database, library, client).sync(
            archive_html=FIXTURES / "archive.html",
            detail_html_dir=details,
        )
    finally:
        client.close()

    assert report.discovered == 2
    assert report.saved == 2
    assert report.failed == 0
    assert database.count() == 2
    assert len(list((tmp_path / "library" / "books").iterdir())) == 2


def test_new_database_row_is_removed_when_onedrive_write_fails(tmp_path: Path, monkeypatch):
    details = tmp_path / "details"
    details.mkdir()
    (details / "example-book.html").write_text(
        (FIXTURES / "example-book.html").read_text(encoding="utf-8"), encoding="utf-8"
    )
    database = LibraryDatabase(tmp_path / "library" / ".salttiger" / "library.sqlite3")
    library = OneDriveLibrary(tmp_path / "library")
    monkeypatch.setattr(library, "materialize", lambda *_: (_ for _ in ()).throw(OSError("disk full")))
    client = SiteClient(user_agent="test", delay_seconds=0)
    try:
        report = SyncService(database, library, client).sync(
            archive_html=FIXTURES / "archive.html",
            detail_html_dir=details,
            limit=1,
        )
    finally:
        client.close()

    assert report.failed == 1
    assert database.count() == 0
