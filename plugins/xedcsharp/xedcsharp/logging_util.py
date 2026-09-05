"""Shared debug logging gated by XED_PLUGIN_DEBUG."""

from __future__ import annotations

import datetime
import os
import sys

_DEBUG = os.environ.get("XED_PLUGIN_DEBUG", "").strip().lower() not in (
    "", "0", "false", "no", "off",
)


def is_debug() -> bool:
    return _DEBUG


def debug(msg: str) -> None:
    if _DEBUG:
        sys.stderr.write(f"[xed-csharp] {msg}\n")
        sys.stderr.flush()


def _append_marker(event: str) -> None:
    try:
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        with open(f"/tmp/xedcsharp-{os.getuid()}.log", "a", encoding="utf-8") as f:
            f.write(f"{stamp} pid={os.getpid()} {event}\n")
    except Exception:
        pass


def marker(event: str) -> None:
    """Append a line to the debug marker file (only when debugging is on).

    Gives bulletproof proof of load/activate even if stderr is swallowed
    (e.g. xed launched from a desktop menu, where stderr goes to the journal).
    """
    if not _DEBUG:
        return
    _append_marker(event)


def error(msg: str) -> None:
    try:
        sys.stderr.write(f"[xed-csharp] {msg}\n")
        sys.stderr.flush()
    except Exception:
        pass
    _append_marker(f"ERROR {msg}")
