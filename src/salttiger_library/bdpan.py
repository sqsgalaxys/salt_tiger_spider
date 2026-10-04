from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .database import LibraryDatabase
from .models import PanDownloadTask
from .storage import OneDriveLibrary


class BdpanError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class BdpanStatus:
    command: tuple[str, ...]
    version: str | None
    authenticated: bool
    identity: str | None = None


@dataclass(slots=True)
class PanDownloadReport:
    planned: int = 0
    downloaded: int = 0
    failed: int = 0
    files: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class BdpanRunner:
    def __init__(self, command: tuple[str, ...], *, wsl: bool = False, timeout_seconds: int = 7200):
        if not command:
            raise ValueError("bdpan command must not be empty")
        self.command = command
        self.wsl = wsl
        self.timeout_seconds = timeout_seconds

    @classmethod
    def discover(cls, configured: str | None = None) -> "BdpanRunner":
        configured = configured or os.environ.get("SALTTIGER_BDPAN_COMMAND")
        if configured:
            command = tuple(shlex.split(configured, posix=os.name != "nt"))
            return cls(command, wsl=command[0].lower().endswith(("wsl", "wsl.exe")))
        executable = shutil.which("bdpan")
        if executable:
            return cls((executable,))
        wsl = shutil.which("wsl.exe") if os.name == "nt" else None
        if wsl:
            return cls((wsl, "bdpan"), wsl=True)
        raise BdpanError(
            "bdpan was not found. Install the official baidu-drive skill/CLI in WSL, "
            "or set SALTTIGER_BDPAN_COMMAND."
        )

    def status(self) -> BdpanStatus:
        version_result = self._run(["--version"], check=False, timeout=30)
        if version_result.returncode != 0:
            raise BdpanError(self._error_message("bdpan is unavailable", version_result))
        identity_result = self._run(["whoami", "--json"], check=False, timeout=30)
        identity = identity_result.stdout.strip() or identity_result.stderr.strip() or None
        authenticated = identity_result.returncode == 0
        if identity_result.stdout.strip():
            try:
                identity_payload = self._json_payload(identity_result.stdout)
            except BdpanError:
                pass
            else:
                if "authenticated" in identity_payload:
                    authenticated = bool(identity_payload["authenticated"])
                    if "has_valid_token" in identity_payload:
                        authenticated = authenticated and bool(identity_payload["has_valid_token"])
                elif "code" in identity_payload:
                    authenticated = identity_payload["code"] in {0, "0"} and not identity_payload.get("error")
        return BdpanStatus(
            command=self.command,
            version=version_result.stdout.strip() or version_result.stderr.strip() or None,
            authenticated=authenticated,
            identity=identity,
        )

    def download_share(self, task: PanDownloadTask, destination: Path) -> dict:
        destination.mkdir(parents=True, exist_ok=True)
        local_destination = self._destination_for_cli(destination)
        remote_name = f"salttiger-{task.book_slug}-{task.id}"
        arguments = ["download", task.url, local_destination, "--json", "-t", remote_name]
        if task.extract_code and "pwd" not in parse_qs(urlparse(task.url).query):
            arguments.extend(["-p", task.extract_code])
        result = self._run(arguments, check=False, timeout=self.timeout_seconds)
        if result.returncode != 0:
            raise BdpanError(self._error_message(f"bdpan download failed for {task.book_title}", result))
        payload = self._json_payload(result.stdout)
        status = str(payload.get("status", "")).lower()
        code_success = payload.get("code") in {0, "0"} and not payload.get("error")
        if status not in {"success", "ok"} and not code_success:
            raise BdpanError(f"bdpan did not report success: {payload}")
        return payload

    def _destination_for_cli(self, destination: Path) -> str:
        if not self.wsl:
            return str(destination)
        result = subprocess.run(
            [self.command[0], "--exec", "wslpath", "-a", str(destination)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise BdpanError(self._error_message("could not convert the OneDrive staging path for WSL", result))
        return result.stdout.strip()

    def _run(
        self,
        arguments: list[str],
        *,
        check: bool,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*self.command, *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=check,
        )

    @staticmethod
    def _json_payload(output: str) -> dict:
        for line in reversed(output.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as error:
            raise BdpanError(f"bdpan returned no JSON result: {output[-1000:]}") from error
        if not isinstance(payload, dict):
            raise BdpanError("bdpan JSON result is not an object")
        return payload

    @staticmethod
    def _error_message(message: str, result: subprocess.CompletedProcess[str]) -> str:
        detail = (result.stderr.strip() or result.stdout.strip())[-1500:]
        return f"{message}: {detail or f'exit code {result.returncode}'}"


class PanDownloadService:
    def __init__(self, database: LibraryDatabase, library: OneDriveLibrary, runner: BdpanRunner):
        self.database = database
        self.library = library
        self.runner = runner

    def download_pending(self, *, limit: int = 20, retry_failed: bool = False) -> PanDownloadReport:
        self.database.initialize()
        self.library.ensure()
        tasks = self.database.pan_downloads(limit, retry_failed=retry_failed)
        report = PanDownloadReport(planned=len(tasks))
        staging_root = self.library.root / ".salttiger" / "staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        for task in tasks:
            self.database.update_download_status(task.id, "downloading")
            try:
                book = self.database.get(task.book_id)
                if book is None:
                    raise BdpanError(f"book #{task.book_id} no longer exists")
                with tempfile.TemporaryDirectory(prefix=f"pan-{task.id}-", dir=staging_root) as temporary:
                    temporary_path = Path(temporary)
                    self.runner.download_share(task, temporary_path)
                    files = self.library.import_download_tree(temporary_path, book, task.url)
                    if not files:
                        raise BdpanError("bdpan reported success but no files were downloaded")
                self.database.update_download_status(
                    task.id,
                    "synced",
                    local_path=json.dumps([str(path) for path in files], ensure_ascii=False),
                )
                report.downloaded += 1
                report.files.extend(files)
            except KeyboardInterrupt:
                self.database.update_download_status(task.id, "failed", last_error="interrupted by user")
                raise
            except Exception as error:
                self.database.update_download_status(task.id, "failed", last_error=str(error))
                report.failed += 1
                report.errors.append(f"{task.book_title}: {error}")
        return report
