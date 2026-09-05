"""Persistent breakpoint store. Lines are 1-based (match DAP + status display);
convert to 0-based at the editor boundary."""

from __future__ import annotations

import os
from typing import Dict, List

from .logging_util import debug


class BreakpointStore:
    def __init__(self, path: str | None = None) -> None:
        if path is None:
            base = os.path.expanduser("~/.config")
            try:
                from gi.repository import GLib  # type: ignore

                base = GLib.get_user_config_dir()
            except Exception:
                pass
            path = os.path.join(base, "xed", "plugins", "xed-csharp", "breakpoints.ini")
        self._path = path
        self._data: Dict[str, List[int]] = {}
        self.load()

    @property
    def path(self) -> str:
        return self._path

    def load(self) -> Dict[str, List[int]]:
        data: Dict[str, List[int]] = {}
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    for raw in f:
                        line = raw.strip()
                        if not line or line.startswith("#") or ":" not in line:
                            continue
                        fpath, lineno = line.rsplit(":", 1)
                        try:
                            data.setdefault(fpath, [])
                            num = int(lineno)
                            if num >= 1 and num not in data[fpath]:
                                data[fpath].append(num)
                        except ValueError:
                            continue
        except Exception as e:
            debug(f"breakpoints load failed: {e!r}")
        for lines in data.values():
            lines.sort()
        self._data = data
        return {k: list(v) for k, v in self._data.items()}

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for fpath in sorted(self._data):
                    for num in sorted(self._data[fpath]):
                        f.write(f"{fpath}:{num}\n")
            os.replace(tmp, self._path)
        except Exception as e:
            debug(f"breakpoints save failed: {e!r}")

    def toggle(self, path: str, line_1based: int) -> bool:
        """Toggle a breakpoint. Returns True if now present."""
        lines = self._data.setdefault(path, [])
        if line_1based in lines:
            lines.remove(line_1based)
            present = False
        else:
            lines.append(line_1based)
            lines.sort()
            present = True
        self.save()
        return present

    def get(self, path: str) -> List[int]:
        return list(self._data.get(path, []))

    def all(self) -> Dict[str, List[int]]:
        return {k: list(v) for k, v in self._data.items() if v}

    def clear_file(self, path: str) -> None:
        self._data.pop(path, None)
        self.save()

    def clear_all(self) -> None:
        self._data.clear()
        self.save()
