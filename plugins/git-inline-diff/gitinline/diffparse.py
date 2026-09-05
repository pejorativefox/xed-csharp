# -*- coding: utf-8 -*-
"""Git diff parsing for git-inline-diff. Headless-safe: no GTK imports.

Line numbers are 0-based new-file lines, matching Gtk TextBuffer lines.
"""

from __future__ import annotations

import os
import re
import subprocess

GIT_TIMEOUT_S = 10

# Same palette as the project-mode tree (VS Code gitDecoration defaults).
COLOR_ADDED = "#73C991"
COLOR_MODIFIED = "#E2C08D"
COLOR_DELETED = "#C74E39"

CATEGORY_ADDED = "gitinline-added"
CATEGORY_MODIFIED = "gitinline-modified"
CATEGORY_DELETED = "gitinline-deleted"

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def find_git_root(folder: str, timeout: int = 5) -> str | None:
    """Top-level of the repo containing folder, or None (soft-only)."""
    try:
        if not folder or not os.path.isdir(folder):
            return None
    except Exception:
        return None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=folder,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except Exception:
        proc = None
    if proc is not None and proc.returncode == 0:
        try:
            top = proc.stdout.decode("utf-8", "surrogateescape").strip()
        except Exception:
            top = ""
        if top and os.path.isdir(top):
            return os.path.abspath(top)
    try:
        current = os.path.abspath(folder)
        while True:
            if os.path.isdir(os.path.join(current, ".git")) or os.path.isfile(
                os.path.join(current, ".git")
            ):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                return None
            current = parent
    except Exception:
        return None


def file_status_short(repo_root: str, path: str, timeout: int = GIT_TIMEOUT_S) -> str:
    """Two-char porcelain status for one file ('' when clean/unknown).

    '??' = untracked, '!!' would need --ignored (never returned here).
    """
    try:
        if not repo_root or not os.path.isdir(repo_root) or not path:
            return ""
    except Exception:
        return ""
    try:
        proc = subprocess.run(
            [
                "git",
                "-c",
                "core.quotepath=false",
                "status",
                "--porcelain=v1",
                "-uall",
                "-z",
                "--",
                path,
            ],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return ""
    if proc.returncode != 0 or not proc.stdout:
        return ""
    try:
        # entries: b"XY path\x00"; path may itself contain spaces, so only
        # the first two bytes + blank are the status.
        if len(proc.stdout) >= 3 and proc.stdout[2:3] == b" ":
            return proc.stdout[:2].decode("ascii", "replace")
    except Exception:
        pass
    return ""


def get_diff_text(repo_root: str, path: str, timeout: int = GIT_TIMEOUT_S) -> str:
    """Unified diff (zero context) of path vs HEAD. '' on any failure."""
    try:
        if not repo_root or not os.path.isdir(repo_root) or not path:
            return ""
    except Exception:
        return ""
    try:
        proc = subprocess.run(
            [
                "git",
                "-c",
                "core.quotepath=false",
                "diff",
                "HEAD",
                "--no-color",
                "--no-ext-diff",
                "-U0",
                "--",
                path,
            ],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    try:
        return (proc.stdout or b"").decode("utf-8", "surrogateescape")
    except Exception:
        return ""


def parse_unified_diff(text: str) -> dict[str, list[int]]:
    """Parse `git diff -U0` output -> 0-based new-file lines per kind.

    Pure addition (old count 0) -> 'added'; pure deletion (new count 0)
    -> 'deleted' marker at the line after which text was removed
    (0-based ``new_start - 1``, floored at 0, clamped to the buffer by
    the caller); anything else -> 'modified' over the new range.
    Binary diffs ('GIT binary patch') yield no hunks -> all empty.
    """
    added: list[int] = []
    modified: list[int] = []
    deleted: list[int] = []
    if not text:
        return {"added": added, "modified": modified, "deleted": deleted}
    try:
        lines = text.splitlines()
    except Exception:
        return {"added": added, "modified": modified, "deleted": deleted}
    for line in lines:
        if not line.startswith("@@"):
            continue
        try:
            match = _HUNK_RE.match(line)
        except Exception:
            continue
        if not match:
            continue
        try:
            new_start = int(match.group(3))
            new_count = int(match.group(4)) if match.group(4) is not None else 1
            old_count = int(match.group(2)) if match.group(2) is not None else 1
        except (TypeError, ValueError):
            continue
        if old_count == 0:
            # Pure addition: new range is 1-based new_start..+count.
            added.extend(n - 1 for n in range(new_start, new_start + new_count))
        elif new_count == 0:
            # Pure deletion: marker on the line above the gap (0-based).
            deleted.append(max(0, new_start - 1))
        else:
            modified.extend(n - 1 for n in range(new_start, new_start + new_count))
    return {"added": added, "modified": modified, "deleted": deleted}


def clamp_lines(lines: list[int], line_count: int) -> list[int]:
    """Clamp 0-based lines into [0, line_count-1]; dedupe, sorted."""
    try:
        if line_count <= 0:
            return []
    except Exception:
        return []
    out: list[int] = []
    seen: set[int] = set()
    for line in lines:
        try:
            n = int(line)
        except Exception:
            continue
        n = max(0, min(line_count - 1, n))
        if n not in seen:
            seen.add(n)
            out.append(n)
    out.sort()
    return out


def untracked_marks(line_count: int) -> dict[str, list[int]]:
    """Marks for a file not yet in git: every line counts as added."""
    try:
        count = int(line_count)
    except Exception:
        count = 0
    return {
        "added": list(range(max(0, count))),
        "modified": [],
        "deleted": [],
    }
