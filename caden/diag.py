"""Disk-backed diagnostic log.

The TUI is hard to copy text from. Every LLM call, every scheduler outcome,
every error gets appended here as a plain-text record so Sean can `cat`,
`tail -f`, or paste from a normal terminal.

Location: ~/.caden/diag.log  (single file, rotated only by hand for now).

Format: human-readable. ISO timestamp, then a section header, then the
payload. Sections are separated by a line of dashes so a wall of JSON
stays scannable.
"""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()
_PATH: Path | None = None


def _path() -> Path:
    global _PATH
    if _PATH is not None:
        return _PATH
    base = Path(os.environ.get("CADEN_DIAG_DIR") or Path.home() / ".caden")
    base.mkdir(parents=True, exist_ok=True)
    _PATH = base / "diag.log"
    return _PATH


def log(section: str, body: str) -> None:
    """Append a timestamped record. Thread-safe. Never raises."""
    try:
        ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        line = (
            f"\n{'-' * 72}\n"
            f"[{ts}] {section}\n"
            f"{body.rstrip()}\n"
        )
        with _LOCK:
            with _path().open("a", encoding="utf-8") as f:
                f.write(line)
            # Also stderr so the launching terminal shows it live.
            print(line, file=sys.stderr, flush=True)
    except Exception as e:  # diag must never crash the app
        try:
            print(f"[diag failed: {e}]", file=sys.stderr, flush=True)
        except Exception:
            pass


def path() -> str:
    return str(_path())
