"""Shared debug logging gated by XED_DEBUG_CSHARP."""

from __future__ import annotations

import datetime
import os
import sys

_DEBUG = os.environ.get("XED_DEBUG_CSHARP", "").strip().lower() not in (
    "", "0", "false", "no", "off",
)


def is_debug() -> bool:
    return _DEBUG


def debug(msg: str) -> None:
    if _DEBUG:
        sys.stderr.write(f"[xed-csharp] {msg}\n")
        sys.stderr.flush()


def marker(event: str) -> None:
    """Append a line to the debug marker file (only when debugging is on).

    Gives bulletproof proof of load/activate even if stderr is swallowed
    (e.g. xed launched from a desktop menu, where stderr goes to the journal).
    """
    if not _DEBUG:
        return
    try:
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        with open(f"/tmp/xedcsharp-{os.getuid()}.log", "a", encoding="utf-8") as f:
            f.write(f"{stamp} pid={os.getpid()} {event}\n")
    except Exception:
        pass
