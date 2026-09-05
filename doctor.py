#!/usr/bin/env python3
"""xed-csharp doctor: headless self-check for install/load problems.

Covers every failure mode seen in the wild so far:
- plugin files missing / stale __pycache__
- Xed typelib + libxed.so on private (non-standard) paths
- missing libpeas python3 loader
- missing dotnet / roslyn-language-server / netcoredbg
- plugin not enabled in dconf
- stale xed process swallowing XED_PLUGIN_DEBUG (GApplication remote)

Usage: python3 doctor.py
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
USER_PLUGIN_DIR = os.path.expanduser("~/.local/share/xed/plugins")
XED_LIBDIRS = (
    "/usr/lib64/xed",
    "/usr/lib/xed",
    "/usr/lib/x86_64-linux-gnu/xed",
    "/usr/local/lib/xed",
    "/app/lib/xed",
)

failures: list[str] = []
warnings: list[str] = []


def check(label: str, ok: bool, hint: str = "", warn_only: bool = False) -> None:
    status = "ok" if ok else ("warn" if warn_only else "FAIL")
    print(f"[{status}] {label}")
    if not ok:
        print(f"       -> {hint}")
        (warnings if warn_only else failures).append(label)


def main() -> int:
    print("== xed-csharp doctor ==\n-- files --")
    check(
        "descriptor installed",
        os.path.isfile(os.path.join(USER_PLUGIN_DIR, "xedcsharp", "xedcsharp.plugin")),
        f"run ./install.sh (looked in {USER_PLUGIN_DIR}/xedcsharp)",
    )
    check(
        "package installed",
        os.path.isfile(os.path.join(USER_PLUGIN_DIR, "xedcsharp", "xedcsharp", "__init__.py")),
        "run ./install.sh",
    )
    check(
        "no stale bytecode in install dir",
        not glob.glob(os.path.join(USER_PLUGIN_DIR, "xedcsharp", "xedcsharp", "__pycache__")),
        "rm -rf ~/.local/share/xed/plugins/xedcsharp/xedcsharp/__pycache__ (or re-run ./install.sh)",
        warn_only=True,
    )
    check(
        "no legacy flat install shadowing the folder install",
        not os.path.isfile(os.path.join(USER_PLUGIN_DIR, "xedcsharp.plugin")),
        "a pre-subfolder copy is still at the plugins root; re-run ./install.sh to remove it",
        warn_only=True,
    )

    print("\n-- xed GI plumbing (the classic silent killer) --")
    std_typelib = "/usr/lib64/girepository-1.0/Xed-1.0.typelib"
    private = [
        os.path.join(d, "girepository-1.0", "Xed-1.0.typelib")
        for d in XED_LIBDIRS
        if os.path.isfile(os.path.join(d, "girepository-1.0", "Xed-1.0.typelib"))
    ]
    check(
        "Xed-1.0.typelib on standard path",
        os.path.isfile(std_typelib) or os.path.isfile("/usr/lib/girepository-1.0/Xed-1.0.typelib"),
        "not on the standard path; the plugin self-registers xed's private dir "
        f"(found: {private or 'NONE - reinstall xed?'}). No action needed if the "
        "plugin is up to date.",
        warn_only=True,
    )
    if not private and not os.path.isfile(std_typelib):
        check("Xed typelib exists anywhere", False, "xed installation looks broken")
    check(
        "libxed.so in linker cache",
        _ldconfig_has("libxed.so"),
        "libxed.so lives in a private dir; the plugin preloads it via ctypes. "
        "No action needed if the plugin is up to date.",
        warn_only=True,
    )
    check(
        "libpeas python3 loader",
        os.path.isfile("/usr/lib64/libpeas-1.0/loaders/libpython3loader.so")
        or bool(glob.glob("/usr/lib*/libpeas-1.0/loaders/libpython3loader.so")),
        "install libpeas python3 support for your distro",
    )

    print("\n-- toolchain --")
    check("dotnet on PATH", shutil.which("dotnet") is not None, "install .NET SDK 9/10")
    check(
        "roslyn-language-server",
        shutil.which("roslyn-language-server") is not None
        or os.path.isfile(os.path.expanduser("~/.dotnet/tools/roslyn-language-server")),
        "dotnet tool install --global roslyn-language-server",
    )
    check(
        "netcoredbg (optional, debugging only)",
        shutil.which("netcoredbg") is not None,
        "https://github.com/Samsung/netcoredbg/releases",
        warn_only=True,
    )

    print("\n-- xed state --")
    check(
        "plugin enabled in dconf",
        "xedcsharp" in _dconf_active_plugins(),
        "enable it in xed: Edit -> Preferences -> Plugins -> C# DevKit for xed",
    )
    procs = _xed_processes()
    check(
        "no stale xed process (env vars don't reach running instances)",
        not procs,
        f"xed is running ({procs}). Fully quit it (File -> Quit all windows) "
        "then start with: XED_PLUGIN_DEBUG=1 xed",
        warn_only=True,
    )

    print("\n-- marker log --")
    marker = f"/tmp/xedcsharp-{os.getuid()}.log"
    if os.path.isfile(marker):
        with open(marker, encoding="utf-8") as f:
            lines = f.read().strip().splitlines()
        print(f"marker log exists ({len(lines)} lines), tail:")
        for line in lines[-5:]:
            print(f"  {line}")
    else:
        print("no marker log yet; run with XED_PLUGIN_DEBUG=1 to create it:")
        print(f"  XED_PLUGIN_DEBUG=1 xed   (after fully quitting xed)")

    print()
    if failures:
        print(f"{len(failures)} hard failure(s). Fix the FAIL items above.")
        return 1
    if warnings:
        print(f"ok with {len(warnings)} warning(s) (see above).")
        return 0
    print("all green.")
    return 0


def _ldconfig_has(name: str) -> bool:
    try:
        out = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True, timeout=15)
        return name in (out.stdout or "")
    except Exception:
        return False


def _dconf_active_plugins() -> str:
    for cmd in (["dconf", "read", "/org/x/editor/plugins/active-plugins"],
                ["gsettings", "get", "org.x.editor.plugins", "active-plugins"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout
        except Exception:
            continue
    return ""


def _xed_processes() -> list[str]:
    try:
        out = subprocess.run(["pgrep", "-a", "xed"], capture_output=True, text=True, timeout=10)
        procs = []
        for line in (out.stdout or "").splitlines():
            if "xedcsharp" in line or "pgrep" in line:
                continue
            # match the xed binary itself, not editors whose path merely contains 'xed'
            if line.rstrip().endswith("xed") or "/xed " in line or line.endswith("xed --standalone"):
                procs.append(line.strip())
        return procs
    except Exception:
        return []


if __name__ == "__main__":
    sys.exit(main())
