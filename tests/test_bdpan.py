import json
import subprocess
from pathlib import Path

from salttiger_library.bdpan import BdpanError, BdpanRunner, PanDownloadService
from salttiger_library.database import LibraryDatabase
from salttiger_library.models import Book, DownloadLink, PanDownloadTask
from salttiger_library.storage import OneDriveLibrary


def _book() -> Book:
    return Book(
        title="Pan Book",
        origin_url="https://salttiger.com/pan-book/",
        slug="pan-book",
        downloads=[DownloadLink("baidu_pan", "https://pan.baidu.com/s/example", "a1b2")],
    )


class FakeRunner:
    def download_share(self, task: PanDownloadTask, destination: Path) -> dict:
        (destination / "files").mkdir()
        (destination / "files" / "book.epub").write_bytes(b"epub")
        return {"status": "success"}


class FailingRunner:
    def download_share(self, task: PanDownloadTask, destination: Path) -> dict:
        raise BdpanError("token expired")


def test_pan_download_is_imported_and_marked_synced(tmp_path: Path):
    database = LibraryDatabase(tmp_path / "library" / ".salttiger" / "library.sqlite3")
    database.initialize()
    database.upsert_book(_book())
    library = OneDriveLibrary(tmp_path / "library")

    report = PanDownloadService(database, library, FakeRunner()).download_pending()

    assert report.downloaded == 1
    assert report.failed == 0
    assert (tmp_path / "library" / "books" / "pan-book" / "files" / "book.epub").read_bytes() == b"epub"
    assert database.pan_downloads() == []


def test_failed_pan_download_can_be_retried(tmp_path: Path):
    database = LibraryDatabase(tmp_path / "library" / ".salttiger" / "library.sqlite3")
    database.initialize()
    database.upsert_book(_book())
    library = OneDriveLibrary(tmp_path / "library")

    report = PanDownloadService(database, library, FailingRunner()).download_pending()

    assert report.failed == 1
    assert database.pan_downloads() == []
    retry_tasks = database.pan_downloads(retry_failed=True)
    assert retry_tasks[0].status == "failed"
    assert retry_tasks[0].last_error == "token expired"


def test_runner_builds_share_download_without_shell(tmp_path: Path, monkeypatch):
    runner = BdpanRunner(("bdpan",))
    captured: list[str] = []

    def fake_run(arguments, *, check, timeout):
        captured.extend(arguments)
        return subprocess.CompletedProcess(["bdpan", *arguments], 0, json.dumps({"status": "success"}), "")

    monkeypatch.setattr(runner, "_run", fake_run)
    task = PanDownloadTask(
        id=7,
        book_id=2,
        book_slug="pan-book",
        book_title="Pan Book",
        url="https://pan.baidu.com/s/example",
        extract_code="a1b2",
        status="available",
        local_path=None,
        last_error=None,
    )

    runner.download_share(task, tmp_path)

    assert captured[:2] == ["download", task.url]
    assert captured[captured.index("-p") + 1] == "a1b2"
    assert captured[captured.index("-t") + 1] == "salttiger-pan-book-7"


def test_runner_accepts_bdpan_387_code_zero_success(tmp_path: Path, monkeypatch):
    runner = BdpanRunner(("bdpan",))

    monkeypatch.setattr(
        runner,
        "_run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            ["bdpan", "download"],
            0,
            json.dumps({"code": 0, "data": {"count": 2, "items": []}}),
            "",
        ),
    )

    payload = runner.download_share(
        PanDownloadTask(
            id=8,
            book_id=2,
            book_slug="pan-book",
            book_title="Pan Book",
            url="https://pan.baidu.com/s/example?pwd=a1b2",
            extract_code="a1b2",
            status="available",
            local_path=None,
            last_error=None,
        ),
        tmp_path,
    )

    assert payload["code"] == 0


def test_runner_rejects_bdpan_code_error(tmp_path: Path, monkeypatch):
    runner = BdpanRunner(("bdpan",))
    monkeypatch.setattr(
        runner,
        "_run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            ["bdpan", "download"], 0, json.dumps({"code": 1, "error": "failed"}), ""
        ),
    )

    task = PanDownloadTask(
        id=9,
        book_id=2,
        book_slug="pan-book",
        book_title="Pan Book",
        url="https://pan.baidu.com/s/example",
        extract_code=None,
        status="available",
        local_path=None,
        last_error=None,
    )
    try:
        runner.download_share(task, tmp_path)
    except BdpanError as error:
        assert "did not report success" in str(error)
    else:
        raise AssertionError("bdpan error payload should not be accepted")


def test_wsl_destination_conversion_bypasses_shell(monkeypatch):
    runner = BdpanRunner(("wsl.exe", "bdpan"), wsl=True)
    destination = Path(r"D:\OneDrive\Library\.salttiger\staging")
    captured: list[str] = []

    def fake_run(arguments, **kwargs):
        captured.extend(arguments)
        return subprocess.CompletedProcess(arguments, 0, "/mnt/d/OneDrive/Library/.salttiger/staging\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    converted = runner._destination_for_cli(destination)

    assert captured == ["wsl.exe", "--exec", "wslpath", "-a", str(destination)]
    assert converted == "/mnt/d/OneDrive/Library/.salttiger/staging"


def test_status_uses_whoami_json_authentication_state(monkeypatch):
    runner = BdpanRunner(("bdpan",))
    results = iter(
        [
            subprocess.CompletedProcess(["bdpan", "--version"], 0, "bdpan 3.8.6\n", ""),
            subprocess.CompletedProcess(
                ["bdpan", "whoami", "--json"],
                0,
                json.dumps({"authenticated": False, "has_valid_token": False}),
                "",
            ),
        ]
    )

    monkeypatch.setattr(runner, "_run", lambda *args, **kwargs: next(results))

    assert runner.status().authenticated is False
