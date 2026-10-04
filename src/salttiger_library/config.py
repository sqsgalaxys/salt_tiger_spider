from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_RELATIVE_LIBRARY = Path("OneDrive") / "30_Knowledge_笔记阅读学习" / "salttiger_book"


def default_library_dir() -> Path:
    configured = os.environ.get("SALTTIGER_LIBRARY_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / DEFAULT_RELATIVE_LIBRARY


@dataclass(slots=True, frozen=True)
class Settings:
    library_dir: Path
    delay_seconds: float = 3.0
    timeout_seconds: float = 30.0
    user_agent: str = "SaltTigerLibrary/0.1 (personal metadata index; contact: local-user)"

    @property
    def state_dir(self) -> Path:
        return self.library_dir / ".salttiger"

    @property
    def database_path(self) -> Path:
        return self.state_dir / "library.sqlite3"

