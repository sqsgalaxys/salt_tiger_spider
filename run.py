"""Compatibility launcher; prefer the installed ``st`` command."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from salttiger_library.cli import app


if __name__ == "__main__":
    app()
