"""Debugging support via Samsung netcoredbg (DAP/MI).

P5 scope is intentionally a bridge, not a full debugger UI:
- Detect `netcoredbg` availability and explain installation when missing.
- Provide launch-config generation (`launch.json`-style dict) for `dotnet run` targets.
- Offer a one-click "debug project" that spawns netcoredbg in MI mode inside the
  output panel pipeline. Full breakpoint gutter UI is follow-up work.

This keeps the MVP honest: test/build/intelligence work without netcoredbg,
and debugging degrades to a clear install hint instead of silent failure.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import List, Optional

from . import dotnet_cli
from .logging_util import debug

INSTALL_HINT = (
    "netcoredbg not found. Install it from https://github.com/Samsung/netcoredbg/releases "
    "or your distro package (e.g. AUR 'netcoredbg'), then set its path in the plugin settings."
)


@dataclass
class DebugTarget:
    project_path: str
    dll_path: str = ""
    args: str = ""


def find_netcoredbg(configured: str = "netcoredbg") -> Optional[str]:
    if not configured:
        return None
    expanded = os.path.expanduser(configured)
    if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
        return expanded
    found = shutil.which(expanded if os.path.sep in expanded else configured)
    debug(f"find_netcoredbg {configured!r} -> {found!r}")
    return found


def build_dll_path(project_path: str, configuration: str = "Debug", tfm: str = "") -> str:
    """Best-effort bin path: bin/Debug/[tfm]/<Name>.dll."""
    project_dir = os.path.dirname(os.path.abspath(project_path))
    name = os.path.splitext(os.path.basename(project_path))[0]
    candidates: List[str] = []
    if tfm:
        candidates.append(os.path.join(project_dir, "bin", configuration, tfm, f"{name}.dll"))
    candidates.append(os.path.join(project_dir, "bin", configuration, f"{name}.dll"))
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return candidates[0] if candidates else ""


def debug_argv(netcoredbg: str, dotnet: str, dll: str, args: str = "") -> List[str]:
    argv = [netcoredbg, "--interpreter=vscode", "--", dotnet, dll]
    if args:
        argv.extend(args.split())
    return argv


def ensure_built(dotnet: str, project_path: str) -> bool:
    result = dotnet_cli.run_sync([dotnet, "build", project_path, "-v", "q", "--nologo"])
    return result.returncode == 0
