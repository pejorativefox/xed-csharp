# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass, field

try:
    from . import gitstatus as _gitstatus
except Exception:
    try:
        import gitstatus as _gitstatus  # type: ignore[no-redef]
    except Exception:
        _gitstatus = None  # type: ignore[assignment]

_XED_LIBDIRS = (
    "/usr/lib64/xed",
    "/usr/lib/xed",
    "/usr/lib/x86_64-linux-gnu/xed",
    "/usr/local/lib/xed",
    "/app/lib/xed",
)

_PRUNE_DIRS = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        ".cache",
        ".dotnet",
        ".nuget",
        "bin",
        "obj",
        "node_modules",
        ".vs",
        ".idea",
        "dosdevices",
        "drive_c",
    }
)

_PANEL_ICONS = ("system-file-manager", "folder", "view-list-tree")
_TREE_FOLDER_ICON = "folder"

#: TreeView background: the theme's view base color darkened 20%.
#: Both legacy (GtkTreeView) and modern (treeview.view) selectors so it
#: applies across GTK 3.x versions. Resolved live by the theme engine,
#: so light/dark theme switches update automatically.
_TREE_BG_CSS = (
    "GtkTreeView.view, GtkTreeView, treeview.view {"
    " background-color: shade(@theme_base_color, 0.8); }"
)


def tree_bg_css() -> str:
    """CSS for the file-tree background (pure string, headless-safe)."""
    return _TREE_BG_CSS
_TREE_FILE_ICON = "text-x-generic"


def _ensure_xed_gi_paths() -> None:
    try:
        typelib_dirs = [
            os.path.join(d, "girepository-1.0")
            for d in _XED_LIBDIRS
            if os.path.isfile(os.path.join(d, "girepository-1.0", "Xed-1.0.typelib"))
        ]
        if typelib_dirs:
            old = os.environ.get("GI_TYPELIB_PATH", "")
            os.environ["GI_TYPELIB_PATH"] = ":".join(typelib_dirs + ([old] if old else []))
            try:
                import gi as _gi

                try:
                    _gi.require_version("GIRepository", "3.0")
                except Exception:
                    try:
                        _gi.require_version("GIRepository", "2.0")
                    except Exception:
                        pass
                from gi.repository import GIRepository  # type: ignore

                repo = None
                for method in ("dup_default", "get_default"):
                    try:
                        repo = getattr(GIRepository.Repository, method)()
                        break
                    except Exception:
                        continue
                if repo is not None:
                    for path in typelib_dirs:
                        try:
                            repo.prepend_search_path(path)
                        except Exception:
                            pass
            except Exception:
                pass
        for libdir in _XED_LIBDIRS:
            candidate = os.path.join(libdir, "libxed.so")
            if os.path.isfile(candidate):
                try:
                    import ctypes

                    ctypes.CDLL(candidate, mode=ctypes.RTLD_GLOBAL)
                except Exception:
                    pass
                break
    except Exception as e:
        sys.stderr.write(f"[project-mode] typelib setup failed: {e!r}\n")


def _debug(message: str) -> None:
    if os.environ.get("XED_PLUGIN_DEBUG", "").strip().lower() in ("", "0", "false", "no", "off"):
        return
    try:
        sys.stderr.write(f"[project-mode] {message}\n")
        sys.stderr.flush()
    except Exception:
        pass


def _pick_icon(candidates: tuple[str, ...]) -> str:
    if Gtk is None:
        return candidates[0]
    try:
        theme = Gtk.IconTheme.get_default()
    except Exception:
        theme = None
    if theme is not None:
        for name in candidates:
            try:
                if theme.has_icon(name):
                    return name
            except Exception:
                continue
    return candidates[0]


#: One-shot handoff written by the `xed-code` launcher: the folder xed-code
#: was pointed at. Read once per window activation, then consumed (deleted),
#: so it acts as launch intent — not as persisted state. Lives under the
#: user cache dir because xed is single-instance: cwd/env of a `xed-code`
#: invocation never reach an already-running xed process.
PENDING_FILENAME = "pending-root"
PENDING_MAX_AGE_S = 60

#: Top-level names that mark a directory as a project worth auto-loading.
_PROJECT_MARKER_NAMES = frozenset(
    {
        ".git",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "CMakeLists.txt",
        "Makefile",
        "meson.build",
        "pyproject.toml",
    }
)

#: Top-level suffixes that mark a directory as a project.
_PROJECT_MARKER_SUFFIXES = (".sln", ".slnx", ".csproj")


def _cache_dir() -> str:
    if GLib is not None:
        try:
            return os.path.join(GLib.get_user_cache_dir(), "xed", "project-mode")
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~/.cache"), "xed", "project-mode")


def pending_root_path(base: str | None = None) -> str:
    """Path of the one-shot `xed-code` handoff file."""
    return os.path.join(base or _cache_dir(), PENDING_FILENAME)


def write_pending_root(folder: str, path: str | None = None) -> str | None:
    """Record launch intent for the next window activation. Returns the path."""
    target = path or pending_root_path()
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(os.path.abspath(folder) + "\n")
    except OSError as e:
        _debug(f"pending write failed: {e!r}")
        return None
    return target


def take_pending_root(
    path: str | None = None,
    max_age_s: int = PENDING_MAX_AGE_S,
    now: float | None = None,
) -> str | None:
    """Read and consume the `xed-code` handoff (fresh entries only).

    Always unlinks the file when present so one launch never affects a
    later window. Returns the abspath, or None when missing/stale/empty.
    """
    target = path or pending_root_path()
    try:
        mtime = os.path.getmtime(target)
    except OSError:
        return None
    try:
        with open(target, encoding="utf-8") as f:
            content = f.read().strip()
    except OSError:
        content = ""
    try:
        os.unlink(target)
    except OSError as e:
        _debug(f"pending consume failed: {e!r}")
    moment = time.time() if now is None else now
    if moment - mtime > max_age_s or not content:
        return None
    return os.path.abspath(content)


def has_project_markers(folder: str) -> bool:
    """True when folder's top level looks like a project (no recursion)."""
    try:
        entries = os.scandir(folder)
    except OSError:
        return False
    with entries:
        for entry in entries:
            name = entry.name
            lowered = name.lower()
            if lowered in _PROJECT_MARKER_NAMES:
                return True
            if lowered.endswith(_PROJECT_MARKER_SUFFIXES):
                return True
    return False


def is_unsafe_root(folder: str) -> bool:
    """True for $HOME, anything above it, or / — never auto-load these."""
    try:
        real = os.path.realpath(os.path.abspath(folder))
        home = os.path.realpath(os.path.expanduser("~"))
        return real == home or real == os.path.dirname(home) or real == "/"
    except Exception:
        return True


def resolve_startup_root(
    cwd: str | None, pending: str | None
) -> tuple[str, str | None]:
    """Decide the startup folder: ("load"|"prompt"|"none", dir|None).

    Explicit `xed-code` intent (pending) with no markers still prompts;
    an incidental cwd without markers (or any unsafe root reached via cwd)
    is silently ignored so plain `xed` from $HOME never crawls or nags.
    """
    if pending:
        candidate = os.path.abspath(pending)
        if not os.path.isdir(candidate):
            return ("none", None)
        if is_unsafe_root(candidate) or not has_project_markers(candidate):
            return ("prompt", candidate)
        return ("load", candidate)
    if cwd:
        candidate = os.path.abspath(cwd)
        if not os.path.isdir(candidate) or is_unsafe_root(candidate):
            return ("none", None)
        if has_project_markers(candidate):
            return ("load", candidate)
    return ("none", None)


#: Debounce for file-monitor-triggered git refreshes. The old 500ms value
#: let a `.git/index` touch from our own `git status` re-fire the monitor
#: into a steady ~2Hz refresh loop (subprocess + full tree recolor each
#: cycle). 1200ms coalesces bursts without feeling stale.
GIT_REFRESH_DEBOUNCE_MS = 1200

#: Debounce for working-tree file edits. Our own `git status` only ever
#: touches `.git/index`, never working-tree files, so these events cannot
#: self-trigger — no long gate needed, keep colors snappy while typing.
GIT_DIR_DEBOUNCE_MS = 500

#: Minimum time between two monitor-triggered `git status` runs. Manual
#: refreshes (set_root) bypass this via force=True. Prevents a hot
#: `.git/` (fetch/gc/index rewrite) from keeping the editor busy.
GIT_REFRESH_MIN_INTERVAL_S = 10.0

#: Debounce for filesystem-triggered tree rebuilds (create/delete/move).
#: Off-thread walk + idle populate, so a shorter window than git feels live
#: without hammering the disk during bursts (e.g. `git checkout`).
TREE_REFRESH_DEBOUNCE_MS = 800

#: Cap on recursive directory watches (inotify handles). Beyond this we
#: watch the top level only and rely on the debounced rebuild.
MAX_WATCH_DIRS = 250

#: Relative paths inside `.git/` that genuinely change status output.
#: Everything else (objects/, logs/, index.lock, *.tmp, …) is noise —
#: notably `git status` itself may rewrite `index`, which used to
#: self-trigger the next refresh.
_GIT_RELEVANT_FILES = frozenset({"HEAD", "index", "packed-refs", "ORIG_HEAD", "FETCH_HEAD"})

_GIT_NOISE_SUFFIXES = (".lock", ".tmp", ".swp", "~")


def _rel_within(path: str, base: str) -> str | None:
    """Relative path of `path` under `base`, or None when outside."""
    try:
        abs_path = os.path.abspath(path)
        abs_base = os.path.abspath(base)
    except Exception:
        return None
    try:
        rel = os.path.relpath(abs_path, abs_base)
    except Exception:
        return None
    if rel == ".":
        return ""
    if rel.startswith(".." + os.sep) or rel == "..":
        return None
    return rel


def should_refresh_for_git_event(
    root_dir: str,
    file_path: str | None,
    other_path: str | None = None,
    event_type: str = "",
) -> bool:
    """Headless-safe filter: does this monitor event merit a re-query?

    - Events inside `.git/` only count for status-relevant files
      (HEAD/index/refs/...). objects/logs/locks are ignored so our own
      `git status` touching `index` cannot self-trigger a loop.
    - Events elsewhere under the root (top-level dir monitor) count —
      they may signal added/removed files.
    - Events outside the root never count.
    """
    try:
        candidates = [p for p in (file_path, other_path) if p]
        if not candidates:
            # Conservative: unknown file, but only if some monitor fired —
            # treat as relevant so we never miss a real change.
            return True
        git_dir = os.path.join(os.path.abspath(root_dir), ".git")
        for candidate in candidates:
            rel_root = _rel_within(candidate, root_dir)
            if rel_root is None:
                continue
            if rel_root == ".git" or rel_root.startswith(".git" + os.sep):
                rel_git = _rel_within(candidate, git_dir)
                if rel_git is None or rel_git == "":
                    # The `.git` dir itself changed (e.g. created) — refresh.
                    return True
                base = os.path.basename(rel_git)
                if base.endswith(_GIT_NOISE_SUFFIXES):
                    continue
                first = rel_git.split(os.sep, 1)[0]
                if rel_git in _GIT_RELEVANT_FILES or first == "refs":
                    return True
                # Noise inside .git (objects/logs/info/hooks/…) — ignore.
                continue
            # A real path under the project root changed.
            return True
        return False
    except Exception:
        return True


def should_rebuild_tree_for_event(
    root_dir: str,
    file_path: str | None,
    other_path: str | None = None,
) -> bool:
    """Headless-safe filter: does this event change the file tree?

    True for creates/deletes/moves anywhere under the root except inside
    `.git/` (git colors handle that side). Outside the root never counts.
    Unknown paths count so a delete is never missed.
    """
    try:
        candidates = [p for p in (file_path, other_path) if p]
        if not candidates:
            return True
        for candidate in candidates:
            rel = _rel_within(candidate, root_dir)
            if rel is None:
                continue
            if rel == ".git" or rel.startswith(".git" + os.sep):
                continue
            return True
        return False
    except Exception:
        return True


def collect_watch_dirs(
    root_dir: str, max_depth: int = 10, max_dirs: int = MAX_WATCH_DIRS
) -> list[str]:
    """Directories to monitor recursively (headless-safe, no GTK/Gio).

    Mirrors build_file_tree pruning (hidden, _PRUNE_DIRS, symlinks) so we
    never watch build output or symlink farms. Always includes root_dir.
    """
    out: list[str] = []
    try:
        if not os.path.isdir(root_dir):
            return out
        out.append(os.path.abspath(root_dir))
        stack: list[tuple[str, int]] = [(os.path.abspath(root_dir), 0)]
        while stack:
            current, depth = stack.pop()
            if depth >= max_depth or len(out) >= max_dirs:
                continue
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            if not entry.is_dir(follow_symlinks=False):
                                continue
                            name = entry.name
                            if name.startswith("."):
                                continue
                            if name in _PRUNE_DIRS:
                                continue
                            path = os.path.abspath(entry.path)
                            if os.path.islink(path):
                                continue
                            if not os.path.isdir(path):
                                continue
                            out.append(path)
                            if len(out) >= max_dirs:
                                break
                            stack.append((path, depth + 1))
                        except OSError:
                            continue
            except OSError:
                continue
    except Exception:
        pass
    return out


def git_monitor_target(folder: str) -> str | None:
    """`.git` path to monitor for folder (headless-safe, no GTK/Gio).

    Resolves the enclosing repo root so opening a subdirectory still
    watches the real `.git`; falls back to `folder/.git` when the root
    cannot be determined. Returns None for an empty folder.
    """
    try:
        if not folder:
            return None
        git_root = None
        try:
            if _gitstatus is not None:
                git_root = _gitstatus.find_git_root(folder)
        except Exception:
            git_root = None
        base = git_root or folder
        return os.path.join(base, ".git")
    except Exception:
        return None


def git_event_paths(file_obj, other_obj=None) -> tuple[str | None, str | None]:
    """Best-effort Gio.File -> filesystem path (headless-safe)."""
    def _one(obj) -> str | None:
        if obj is None:
            return None
        try:
            get_path = getattr(obj, "get_path", None)
            if callable(get_path):
                value = get_path()
                return value if isinstance(value, str) else None
        except Exception:
            pass
        return None

    try:
        return (_one(file_obj), _one(other_obj))
    except Exception:
        return (None, None)


@dataclass
class FileNode:
    name: str
    path: str
    is_dir: bool
    children: list["FileNode"] = field(default_factory=list)


def build_file_tree(root_dir: str, max_depth: int = 10) -> list[FileNode]:
    nodes: list[FileNode] = []
    try:
        entries = sorted(
            os.scandir(root_dir),
            key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()),
        )
    except OSError:
        return []
    for entry in entries:
        name = entry.name
        path = entry.path
        try:
            if name.startswith("."):
                continue
            if os.path.islink(path):
                continue
            if entry.is_dir(follow_symlinks=False):
                if (
                    name in _PRUNE_DIRS
                    or max_depth <= 0
                ):
                    continue
                children = build_file_tree(path, max_depth - 1)
                nodes.append(FileNode(name=name, path=path, is_dir=True, children=children))
            else:
                nodes.append(FileNode(name=name, path=path, is_dir=False, children=[]))
        except OSError:
            continue
    return nodes


try:
    import gi

    _ensure_xed_gi_paths()

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Xed", "1.0")

    from gi.repository import GObject, Gtk, Gdk, Gio, GLib, Xed  # type: ignore
except Exception:
    class _DummyObject:
        def __init__(self, *args, **kwargs) -> None:
            pass

        @classmethod
        def Property(cls, *args, **kwargs):  # noqa: N802
            return None

    class _DummyGObject:
        Object = _DummyObject
        SignalFlags = type("SignalFlags", (), {"RUN_LAST": 0})
        TYPE_STRING = str

        @classmethod
        def Property(cls, *args, **kwargs):  # noqa: N802
            return None

    class _DummyXed:
        class WindowActivatable:
            pass

        Window = object

    GObject = _DummyGObject  # type: ignore[no-redef]
    Xed = _DummyXed  # type: ignore[no-redef]
    Gtk = Gio = Gdk = GLib = None  # type: ignore[no-redef]


if Gtk is not None:
    class ProjectBrowser(Gtk.Box):
        __gsignals__ = {
            "open-file": (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_STRING,)),
            "choose-root": (GObject.SignalFlags.RUN_LAST, None, ()),
        }

        def __init__(self) -> None:
            super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            self._root_dir = ""
            self._col_icon = 0
            self._col_label = 1
            self._col_path = 2
            self._col_kind = 3
            self._col_fg = 4
            self._col_fg_set = 5
            self._git_statuses: dict = {}
            self._git_generation = 0
            self._monitors: list = []
            self._refresh_timer = None
            self._refresh_interval_s = GIT_REFRESH_MIN_INTERVAL_S
            self._tree_timer = None
            self._watched_dirs: set = set()
            self._git_root_cached: str | None = None
            self._last_git_refresh = 0.0
            self._tree_generation = 0

            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            self._root_label = Gtk.Label(label="No folder selected")
            self._root_label.set_xalign(0.0)
            header.pack_start(self._root_label, True, True, 0)
            self.pack_start(header, False, False, 0)

            self.store = Gtk.TreeStore(str, str, str, str, str, bool)
            self.tree = Gtk.TreeView.new_with_model(self.store)
            self.tree.set_headers_visible(False)
            col = Gtk.TreeViewColumn("Files")
            icon = Gtk.CellRendererPixbuf()
            cell = Gtk.CellRendererText()
            col.pack_start(icon, False)
            col.pack_start(cell, True)
            col.add_attribute(icon, "icon-name", self._col_icon)
            col.add_attribute(cell, "text", self._col_label)
            col.add_attribute(cell, "foreground", self._col_fg)
            col.add_attribute(cell, "foreground-set", self._col_fg_set)
            self.tree.append_column(col)
            self.tree.connect("row-activated", self._on_row_activated)
            try:
                provider = Gtk.CssProvider()
                provider.load_from_data(tree_bg_css().encode("utf-8"))
                self.tree.get_style_context().add_provider(
                    provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
            except Exception as e:
                _debug(f"tree bg css failed: {e!r}")

            scrolled = Gtk.ScrolledWindow()
            scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            scrolled.add(self.tree)
            self.pack_start(scrolled, True, True, 0)
            self.show_all()

        def set_root(self, folder: str) -> None:
            self._git_generation += 1
            self._tree_generation += 1
            generation = self._tree_generation
            self._cancel_monitors()
            self._root_dir = folder
            self._git_statuses = {}
            self._git_root_cached = None
            try:
                self.store.clear()
            except Exception:
                pass
            if not folder or not os.path.isdir(folder):
                self._root_label.set_text("No folder selected")
                return
            base = os.path.basename(folder.rstrip(os.sep)) or folder
            self._root_label.set_text(base)
            try:
                root_iter = self.store.append(
                    None,
                    [_TREE_FOLDER_ICON, base + "/", folder, "folder", None, False],
                )
                self.store.append(
                    root_iter, [_TREE_FILE_ICON, "Loading…", folder, "loading", None, False]
                )
            except Exception:
                root_iter = None
            try:
                self.tree.expand_row(Gtk.TreePath.new_from_indices([0]), False)
            except Exception:
                pass
            self._setup_git_monitors(folder)
            # Build the file list off the UI thread; even mid-size repos
            # made the old synchronous walk hitch the editor on open.
            try:
                thread = threading.Thread(
                    target=self._build_tree_thread,
                    args=(folder, generation),
                    daemon=True,
                )
                thread.start()
            except Exception as e:
                _debug(f"tree build spawn failed: {e!r}")
                try:
                    self._populate_tree(build_file_tree(folder), generation)
                except Exception:
                    pass
            self.refresh_git_statuses(force=True)

        def _build_tree_thread(self, folder: str, generation: int) -> None:
            try:
                nodes = build_file_tree(folder)
            except Exception as e:
                _debug(f"tree build failed for {folder}: {e!r}")
                nodes = []
            try:
                if GLib is not None:
                    GLib.idle_add(self._populate_tree, nodes, generation)
                else:
                    self._populate_tree(nodes, generation)
            except Exception as e:
                _debug(f"tree populate schedule failed: {e!r}")

        def _expanded_dir_paths(self) -> set:
            """Filesystem paths of expanded folder rows (survives rebuild)."""
            out: set = set()
            try:
                store, tree = self.store, self.tree
                def walk(tree_iter) -> None:
                    current = tree_iter
                    while current is not None:
                        try:
                            kind = store.get_value(current, self._col_kind)
                            path = store.get_value(current, self._col_path)
                            tpath = store.get_path(current)
                        except Exception:
                            kind = path = tpath = None
                        if kind == "folder" and isinstance(path, str) and tpath is not None:
                            try:
                                if tree.row_expanded(tpath):
                                    out.add(os.path.abspath(path))
                            except Exception:
                                pass
                        try:
                            child = store.iter_children(current)
                        except Exception:
                            child = None
                        if child is not None:
                            walk(child)
                        try:
                            current = store.iter_next(current)
                        except Exception:
                            break
                first = store.get_iter_first()
                if first is not None:
                    walk(first)
            except Exception:
                pass
            return out

        def _restore_expanded(self, paths: set) -> None:
            if not paths:
                return
            try:
                store, tree = self.store, self.tree
                def walk(tree_iter) -> None:
                    current = tree_iter
                    while current is not None:
                        try:
                            kind = store.get_value(current, self._col_kind)
                            path = store.get_value(current, self._col_path)
                            tpath = store.get_path(current)
                        except Exception:
                            kind = path = tpath = None
                        if kind == "folder" and isinstance(path, str) and tpath is not None:
                            try:
                                if os.path.abspath(path) in paths:
                                    tree.expand_row(tpath, False)
                            except Exception:
                                pass
                        try:
                            child = store.iter_children(current)
                        except Exception:
                            child = None
                        if child is not None:
                            walk(child)
                        try:
                            current = store.iter_next(current)
                        except Exception:
                            break
                first = store.get_iter_first()
                if first is not None:
                    walk(first)
            except Exception:
                pass

        def refresh_tree(self) -> None:
            """Re-walk the root off-thread (create/delete/move updates)."""
            root = self._root_dir
            if not root or not os.path.isdir(root):
                return
            self._tree_generation += 1
            generation = self._tree_generation
            try:
                thread = threading.Thread(
                    target=self._build_tree_thread,
                    args=(root, generation),
                    daemon=True,
                )
                thread.start()
            except Exception as e:
                _debug(f"tree refresh spawn failed: {e!r}")

        def _populate_tree(self, nodes, generation: int) -> bool:
            if generation != self._tree_generation:
                return False
            keep_expanded = self._expanded_dir_paths()
            try:
                self.store.clear()
            except Exception:
                return False
            folder = self._root_dir
            if not folder or not os.path.isdir(folder):
                return False
            base = os.path.basename(folder.rstrip(os.sep)) or folder
            try:
                root_iter = self.store.append(
                    None,
                    [_TREE_FOLDER_ICON, base + "/", folder, "folder", None, False],
                )
            except Exception:
                return False
            try:
                self._freeze_tree(True)
                # Color rows with the last known statuses right away: the
                # post-build _apply_git_statuses below is skipped when the
                # statuses are unchanged, which is exactly when a rebuild
                # (content edit, same git status) would otherwise leave
                # every row uncolored forever.
                known = dict(self._git_statuses or {})
                child_colors: list = []
                for node in nodes:
                    child_colors.append(self._append_node(root_iter, node, known))
                gs = _gitstatus if _gitstatus is not None else None
                try:
                    root_color = gs.aggregate_dir_color(child_colors) if gs is not None else None
                except Exception:
                    root_color = None
                try:
                    self.store.set_value(root_iter, self._col_fg, root_color)
                    self.store.set_value(root_iter, self._col_fg_set, root_color is not None)
                except Exception:
                    pass
            except Exception as e:
                _debug(f"tree populate failed: {e!r}")
            finally:
                try:
                    self._freeze_tree(False)
                except Exception:
                    pass
            try:
                self.tree.expand_row(Gtk.TreePath.new_from_indices([0]), False)
            except Exception:
                pass
            try:
                self._restore_expanded(keep_expanded)
            except Exception:
                pass
            try:
                self._refresh_dir_monitors()
            except Exception:
                pass
            # Statuses may have arrived while the tree was building.
            if self._git_statuses:
                try:
                    self._apply_git_statuses(self._git_statuses, self._git_generation)
                except Exception:
                    pass
            return False

        def _freeze_tree(self, freeze: bool) -> None:
            try:
                if freeze:
                    self.tree.freeze_child_notify()
                else:
                    self.tree.thaw_child_notify()
            except Exception:
                pass

        def _append_node(self, parent, node: FileNode, statuses: dict | None = None) -> str | None:
            gs = _gitstatus if _gitstatus is not None else None
            if statuses is None:
                statuses = self._git_statuses
            if node.is_dir:
                child_colors: list = []
                # Append first so children have a parent, then set the
                # folder color once the subtree aggregate is known.
                folder_iter = self.store.append(
                    parent,
                    [_TREE_FOLDER_ICON, node.name + "/", node.path, "folder", None, False],
                )
                for child in node.children:
                    child_colors.append(self._append_node(folder_iter, child, statuses))
                color = gs.aggregate_dir_color(child_colors) if gs is not None else None
                try:
                    self.store.set_value(folder_iter, self._col_fg, color)
                    self.store.set_value(folder_iter, self._col_fg_set, color is not None)
                except Exception:
                    pass
                return color
            color = gs.color_for_path(statuses, node.path) if gs is not None else None
            self.store.append(
                parent, [_TREE_FILE_ICON, node.name, node.path, "file", color, color is not None]
            )
            return color

        # -- git -------------------------------------------------------
        def refresh_git_statuses(self, force: bool = False, min_interval_s=None) -> None:
            """Re-query `git status` off the UI thread, then repaint colors.

            Monitor-triggered callers pass force=False and are rate-limited
            so a hot `.git/` cannot keep the editor busy; set_root passes
            force=True. Working-tree edits (via _on_dir_changed) pass a
            zero interval — our own `git status` never touches those files,
            so they cannot self-trigger and stay snappy.
            """
            root = self._root_dir
            if not root or not os.path.isdir(root):
                return
            if _gitstatus is None:
                return
            try:
                interval = float(GIT_REFRESH_MIN_INTERVAL_S if min_interval_s is None else min_interval_s)
            except Exception:
                interval = GIT_REFRESH_MIN_INTERVAL_S
            if not force:
                try:
                    now = time.monotonic()
                except Exception:
                    now = 0.0
                try:
                    last = float(getattr(self, "_last_git_refresh", 0.0) or 0.0)
                except Exception:
                    last = 0.0
                if interval > 0 and now and last and (now - last) < interval:
                    try:
                        remaining_ms = int((interval - (now - last)) * 1000)
                    except Exception:
                        remaining_ms = 0
                    if remaining_ms > 0:
                        self._arm_git_timer(
                            max(remaining_ms, GIT_REFRESH_DEBOUNCE_MS),
                            self._git_generation,
                            interval,
                        )
                    return
            self._git_generation += 1
            generation = self._git_generation
            try:
                self._last_git_refresh = time.monotonic()
            except Exception:
                pass
            try:
                thread = threading.Thread(
                    target=self._query_git_thread,
                    args=(root, generation),
                    daemon=True,
                )
                thread.start()
            except Exception as e:
                _debug(f"git refresh spawn failed: {e!r}")

        def _query_git_thread(self, root: str, generation: int) -> None:
            statuses: dict = {}
            try:
                git_root = getattr(self, "_git_root_cached", None)
                if not git_root or not os.path.isdir(git_root):
                    git_root = _gitstatus.find_git_root(root)
                    try:
                        self._git_root_cached = git_root
                    except Exception:
                        pass
                if git_root:
                    statuses = _gitstatus.get_git_statuses(git_root)
            except Exception as e:
                _debug(f"git status failed for {root}: {e!r}")
                statuses = {}
            try:
                if GLib is not None:
                    GLib.idle_add(self._apply_git_statuses, statuses, generation)
                else:
                    self._apply_git_statuses(statuses, generation)
            except Exception as e:
                _debug(f"git apply schedule failed: {e!r}")

        def _status_color_map(self, statuses: dict) -> dict:
            """Precompute {abspath: color} once per refresh (no per-row abspath)."""
            color_map: dict = {}
            gs = _gitstatus
            if gs is None or not statuses:
                return color_map
            try:
                for path, code in statuses.items():
                    try:
                        color = gs.status_to_color(code[0], code[1])
                    except Exception:
                        continue
                    if color is None:
                        continue
                    try:
                        color_map[os.path.abspath(path)] = color
                    except Exception:
                        continue
            except Exception:
                pass
            return color_map

        def _apply_git_statuses(self, statuses: dict, generation: int) -> bool:
            if generation != self._git_generation:
                return False
            statuses = statuses or {}
            if statuses == self._git_statuses:
                # Steady state (e.g. our own index touch re-firing the
                # monitor): skip the full tree walk entirely.
                return False
            self._git_statuses = statuses
            try:
                root_iter = self.store.get_iter_first()
            except Exception:
                root_iter = None
            if root_iter is None:
                return False
            color_map = self._status_color_map(statuses)
            try:
                self._freeze_tree(True)
                child = self.store.iter_children(root_iter)
                colors: list = []
                while child is not None:
                    colors.append(self._recolor_subtree(child, color_map))
                    try:
                        child = self.store.iter_next(child)
                    except Exception:
                        break
                gs = _gitstatus
                root_color = gs.aggregate_dir_color(colors) if gs is not None else None
                try:
                    current = self.store.get_value(root_iter, self._col_fg)
                except Exception:
                    current = object()
                try:
                    current_set = self.store.get_value(root_iter, self._col_fg_set)
                except Exception:
                    current_set = object()
                want_set = root_color is not None
                if current != root_color or current_set != want_set:
                    try:
                        self.store.set_value(root_iter, self._col_fg, root_color)
                        self.store.set_value(root_iter, self._col_fg_set, want_set)
                    except Exception:
                        pass
            except Exception as e:
                _debug(f"git recolor failed: {e!r}")
            finally:
                try:
                    self._freeze_tree(False)
                except Exception:
                    pass
            return False

        def _recolor_subtree(self, tree_iter, color_map: dict | None = None) -> str | None:
            gs = _gitstatus
            if color_map is None:
                color_map = self._status_color_map(self._git_statuses)
            try:
                kind = self.store.get_value(tree_iter, self._col_kind)
                path = self.store.get_value(tree_iter, self._col_path)
            except Exception:
                return None
            if kind == "file":
                color = None
                try:
                    if isinstance(path, str):
                        color = color_map.get(os.path.abspath(path))
                except Exception:
                    color = None
                try:
                    current = self.store.get_value(tree_iter, self._col_fg)
                except Exception:
                    current = object()
                try:
                    current_set = self.store.get_value(tree_iter, self._col_fg_set)
                except Exception:
                    current_set = object()
                want_set = color is not None
                if current != color or current_set != want_set:
                    try:
                        self.store.set_value(tree_iter, self._col_fg, color)
                        self.store.set_value(tree_iter, self._col_fg_set, want_set)
                    except Exception:
                        pass
                return color
            # Folder: recurse into children, then aggregate.
            colors: list = []
            try:
                child = self.store.iter_children(tree_iter)
            except Exception:
                child = None
            while child is not None:
                colors.append(self._recolor_subtree(child, color_map))
                try:
                    child = self.store.iter_next(child)
                except Exception:
                    break
            color = gs.aggregate_dir_color(colors) if gs is not None else None
            try:
                current = self.store.get_value(tree_iter, self._col_fg)
            except Exception:
                current = object()
            try:
                current_set = self.store.get_value(tree_iter, self._col_fg_set)
            except Exception:
                current_set = object()
            want_set = color is not None
            if current != color or current_set != want_set:
                try:
                    self.store.set_value(tree_iter, self._col_fg, color)
                    self.store.set_value(tree_iter, self._col_fg_set, want_set)
                except Exception:
                    pass
            return color

        def _setup_git_monitors(self, folder: str) -> None:
            if Gio is None:
                return
            try:
                watched: list = []
                watch_dirs = collect_watch_dirs(folder)
                try:
                    self._watched_dirs = set(watch_dirs)
                except Exception:
                    pass
                for watch_dir in watch_dirs:
                    try:
                        monitor = Gio.File.new_for_path(watch_dir).monitor_directory(
                            Gio.FileMonitorFlags.NONE, None
                        )
                    except Exception as e:
                        _debug(f"dir monitor failed for {watch_dir}: {e!r}")
                        continue
                    try:
                        monitor.connect("changed", self._on_dir_changed)
                    except Exception:
                        continue
                    watched.append(monitor)
                git_path = git_monitor_target(folder)
                try:
                    git_monitor = None
                    if git_path is not None and os.path.isdir(git_path):
                        git_monitor = Gio.File.new_for_path(git_path).monitor_directory(
                            Gio.FileMonitorFlags.NONE, None
                        )
                    elif git_path is not None and os.path.isfile(git_path):
                        git_monitor = Gio.File.new_for_path(git_path).monitor_file(
                            Gio.FileMonitorFlags.NONE, None
                        )
                    if git_monitor is not None:
                        try:
                            git_monitor.connect("changed", self._on_git_changed)
                        except Exception:
                            pass
                        watched.append(git_monitor)
                except Exception as e:
                    _debug(f"git monitor failed for {git_path}: {e!r}")
                self._monitors = watched
            except Exception as e:
                _debug(f"git monitors setup failed: {e!r}")
                self._monitors = []

        def _refresh_dir_monitors(self) -> None:
            """Re-watch subdirs after a rebuild (new folders appear)."""
            if Gio is None or not self._root_dir:
                return
            try:
                wanted = set(collect_watch_dirs(self._root_dir))
            except Exception:
                return
            try:
                current = set(getattr(self, "_watched_dirs", set()) or set())
            except Exception:
                current = set()
            if wanted == current:
                return
            try:
                for monitor in list(self._monitors):
                    try:
                        monitor.cancel()
                    except Exception:
                        continue
                self._monitors = []
                self._setup_git_monitors(self._root_dir)
            except Exception as e:
                _debug(f"dir monitors refresh failed: {e!r}")

        def _arm_git_timer(self, delay_ms: int, generation: int, min_interval_s=None) -> None:
            if GLib is None:
                return
            try:
                try:
                    self._refresh_interval_s = float(
                        GIT_REFRESH_MIN_INTERVAL_S if min_interval_s is None else min_interval_s
                    )
                except Exception:
                    self._refresh_interval_s = GIT_REFRESH_MIN_INTERVAL_S
                if self._refresh_timer is not None:
                    try:
                        GLib.source_remove(self._refresh_timer)
                    except Exception:
                        pass
                    self._refresh_timer = None
                self._refresh_timer = GLib.timeout_add(
                    max(50, int(delay_ms)), self._on_git_changed_fire, generation
                )
            except Exception as e:
                _debug(f"git change debounce failed: {e!r}")

        def _on_git_changed(self, _monitor, _file, _other=None, _event=None) -> None:
            if GLib is None:
                return
            try:
                file_path, other_path = git_event_paths(_file, _other)
                try:
                    event_type = str(getattr(_event, "value_nick", None) or _event or "")
                except Exception:
                    event_type = ""
                if not should_refresh_for_git_event(
                    self._root_dir, file_path, other_path, event_type
                ):
                    return
                self._arm_git_timer(GIT_REFRESH_DEBOUNCE_MS, self._git_generation)
            except Exception as e:
                _debug(f"git change debounce failed: {e!r}")

        def _on_git_changed_fire(self, generation: int) -> bool:
            self._refresh_timer = None
            if generation != self._git_generation:
                return False
            try:
                self.refresh_git_statuses(
                    min_interval_s=getattr(
                        self, "_refresh_interval_s", GIT_REFRESH_MIN_INTERVAL_S
                    )
                )
            except Exception as e:
                _debug(f"git auto-refresh failed: {e!r}")
            return False

        def _arm_tree_timer(self, delay_ms: int, generation: int) -> None:
            if GLib is None:
                try:
                    self.refresh_tree()
                except Exception:
                    pass
                return
            try:
                if self._tree_timer is not None:
                    try:
                        GLib.source_remove(self._tree_timer)
                    except Exception:
                        pass
                    self._tree_timer = None
                self._tree_timer = GLib.timeout_add(
                    max(50, int(delay_ms)), self._on_tree_changed_fire, generation
                )
            except Exception as e:
                _debug(f"tree change debounce failed: {e!r}")

        def _on_dir_changed(self, _monitor, _file, _other=None, _event=None) -> None:
            try:
                file_path, other_path = git_event_paths(_file, _other)
                if not should_rebuild_tree_for_event(
                    self._root_dir, file_path, other_path
                ):
                    return
                if GLib is None:
                    return
                self._arm_tree_timer(TREE_REFRESH_DEBOUNCE_MS, self._tree_generation)
                try:
                    if should_refresh_for_git_event(
                        self._root_dir, file_path, other_path
                    ):
                        # Working-tree edit: bypass the `.git/` storm gate
                        # (our own status runs never touch these files).
                        self._arm_git_timer(
                            GIT_DIR_DEBOUNCE_MS, self._git_generation, 0.0
                        )
                except Exception:
                    pass
            except Exception as e:
                _debug(f"tree change debounce failed: {e!r}")

        def _on_tree_changed_fire(self, generation: int) -> bool:
            self._tree_timer = None
            if generation != self._tree_generation:
                return False
            try:
                self.refresh_tree()
            except Exception as e:
                _debug(f"tree auto-refresh failed: {e!r}")
            return False

        def _cancel_monitors(self) -> None:
            if GLib is not None:
                for attr in ("_refresh_timer", "_tree_timer"):
                    try:
                        timer = getattr(self, attr, None)
                    except Exception:
                        timer = None
                    if timer is not None:
                        try:
                            GLib.source_remove(timer)
                        except Exception:
                            pass
                    try:
                        setattr(self, attr, None)
                    except Exception:
                        pass
            try:
                self._refresh_interval_s = GIT_REFRESH_MIN_INTERVAL_S
            except Exception:
                pass
            else:
                try:
                    self._refresh_timer = None
                except Exception:
                    pass
                try:
                    self._tree_timer = None
                except Exception:
                    pass
            for monitor in self._monitors:
                try:
                    monitor.cancel()
                except Exception:
                    continue
            self._monitors = []
            try:
                self._watched_dirs = set()
            except Exception:
                pass

        def cleanup(self) -> None:
            try:
                self._git_generation += 1
            except Exception:
                pass
            try:
                self._tree_generation += 1
            except Exception:
                pass
            self._cancel_monitors()

        def _on_row_activated(self, _tree, path, _col) -> None:
            tree_iter = self.store.get_iter(path)
            kind = self.store.get_value(tree_iter, self._col_kind)
            fpath = self.store.get_value(tree_iter, self._col_path)
            if kind == "file":
                if os.path.isfile(fpath):
                    self.emit("open-file", fpath)
                    return
                try:
                    self.refresh_tree()
                except Exception:
                    pass
                return
            if self.tree.row_expanded(path):
                self.tree.collapse_row(path)
            else:
                self.tree.expand_row(path, False)


class ProjectModePlugin(GObject.Object, Xed.WindowActivatable):  # type: ignore[misc]
    __gtype_name__ = "XedProjectModePlugin"

    window = GObject.Property(type=Xed.Window)  # type: ignore[arg-type]

    def __init__(self) -> None:
        super().__init__()
        self.browser = None
        self._window_key_id = None
        self._root_dir = None
        self._tab_states: dict = {}
        self._tab_signal_ids: list = []

    def do_activate(self) -> None:
        if Gtk is None or Gio is None:
            return
        try:
            self.browser = ProjectBrowser()
            self.browser.connect("open-file", lambda _w, p: self._open_file(p))
            self.browser.connect("choose-root", lambda _w: self._choose_root())
        except Exception as e:
            _debug(f"browser create failed: {e!r}")
            self.browser = None
            return

        side = self._safe(lambda: self.window.get_side_panel())
        if side is not None and self.browser is not None:
            added = False
            panel_icon = _pick_icon(_PANEL_ICONS)
            for attempt in (
                lambda: side.add_item(self.browser, "Project Mode", panel_icon),
                lambda: side.add(self.browser),
            ):
                try:
                    attempt()
                    added = True
                    break
                except Exception:
                    continue
            if not added:
                _debug("side panel add failed")

        try:
            self._window_key_id = self.window.connect("key-press-event", self._on_window_key_press)
        except Exception as e:
            _debug(f"window keys connect failed: {e!r}")
            self._window_key_id = None
        for signal, handler in (
            ("tab-added", self._on_project_tab_added),
            ("tab-removed", self._on_project_tab_removed),
            ("active-tab-state-changed", self._on_project_tab_state_changed),
        ):
            try:
                self._tab_signal_ids.append(
                    self.window.connect(signal, handler)
                )
            except Exception as e:
                _debug(f"window {signal} connect failed: {e!r}")

        self._startup_load()

    def do_deactivate(self) -> None:
        if self._window_key_id is not None:
            try:
                self.window.disconnect(self._window_key_id)
            except Exception:
                pass
        self._window_key_id = None
        for handler_id in list(getattr(self, "_tab_signal_ids", []) or []):
            try:
                self.window.disconnect(handler_id)
            except Exception:
                pass
        try:
            self._tab_signal_ids = []
        except Exception:
            pass
        try:
            self._tab_states = {}
        except Exception:
            pass

        if self.browser is not None:
            try:
                cleanup = getattr(self.browser, "cleanup", None)
                if callable(cleanup):
                    cleanup()
            except Exception:
                pass
            side = self._safe(lambda: self.window.get_side_panel())
            if side is not None:
                for attempt in (lambda: side.remove_item(self.browser), lambda: side.remove(self.browser)):
                    try:
                        attempt()
                        break
                    except Exception:
                        continue
            try:
                self.browser.destroy()
            except Exception:
                pass
        self.browser = None

    def do_update_state(self) -> None:
        return

    @staticmethod
    def _safe(fn):
        try:
            return fn()
        except Exception:
            return None

    def _handle_global_key(self, keyname: str, ctrl: bool, shift: bool, alt: bool) -> bool:
        if ctrl and shift and not alt and keyname.lower() == "o":
            _debug("key: Ctrl+Shift+O choose-root")
            self._choose_root()
            return True
        return False

    def _on_window_key_press(self, _window, event) -> bool:
        if Gtk is None or Gdk is None:
            return False
        try:
            mods = event.state & Gtk.accelerator_get_default_mod_mask()
            keyname = Gdk.keyval_name(event.keyval) or ""
            ctrl = bool(mods & Gdk.ModifierType.CONTROL_MASK)
            shift = bool(mods & Gdk.ModifierType.SHIFT_MASK)
            alt = bool(mods & Gdk.ModifierType.MOD1_MASK)
        except Exception:
            return False
        return self._handle_global_key(keyname, ctrl, shift, alt)

    def _project_saved_path(self, tab):
        """On-disk path for a tab, or None for untitled/unresolvable."""
        try:
            doc = tab.get_document()
        except Exception:
            return None
        if doc is None:
            return None
        try:
            location = doc.get_location()
        except Exception:
            return None
        if location is None:
            return None
        try:
            path = location.get_path()
        except Exception:
            return None
        return path if isinstance(path, str) and path else None

    def _refresh_browser_for_path(self, path: str | None) -> None:
        """Re-query git colors (+ tree) when a saved path is under the root."""
        if not path:
            return
        try:
            browser = self.browser
        except Exception:
            return
        if browser is None:
            return
        try:
            root = browser._root_dir or self._root_dir
        except Exception:
            root = None
        if not root:
            return
        try:
            if _rel_within(path, root) is None:
                return
        except Exception:
            return
        try:
            arm_git = getattr(browser, "_arm_git_timer", None)
            if callable(arm_git):
                arm_git(GIT_DIR_DEBOUNCE_MS, browser._git_generation, 0.0)
        except Exception:
            pass
        try:
            arm_tree = getattr(browser, "_arm_tree_timer", None)
            if callable(arm_tree):
                arm_tree(TREE_REFRESH_DEBOUNCE_MS, browser._tree_generation)
        except Exception:
            pass

    def _on_project_tab_added(self, window, tab) -> None:
        try:
            states = self._tab_states
        except Exception:
            return
        try:
            states[hash(tab)] = str(tab.get_state())
        except Exception:
            pass
        try:
            self._refresh_browser_for_path(self._project_saved_path(tab))
        except Exception:
            pass

    def _on_project_tab_removed(self, _window, tab) -> None:
        try:
            states = self._tab_states
        except Exception:
            return
        try:
            states.pop(hash(tab), None)
        except Exception:
            pass

    def _on_project_tab_state_changed(self, window, *args) -> None:
        """Refresh colors when a save completes (SAVING -> NORMAL)."""
        tab = None
        for candidate in args:
            if candidate is not None and hasattr(candidate, "get_document"):
                tab = candidate
                break
        if tab is None:
            try:
                tab = window.get_active_tab()
            except Exception:
                return
        if tab is None:
            return
        try:
            state = str(tab.get_state())
        except Exception:
            return
        try:
            key = hash(tab)
        except Exception:
            return
        try:
            previous = self._tab_states.get(key, "")
            self._tab_states[key] = state
        except Exception:
            previous = ""
        if "SAVING" in previous and state.endswith("NORMAL"):
            try:
                self._refresh_browser_for_path(self._project_saved_path(tab))
            except Exception:
                pass

    def _startup_load(self) -> None:
        """Load a project folder at window startup (`code .` equivalent).

        Prefers explicit `xed-code` intent (one-shot handoff file), falls
        back to xed's cwd on cold start. Marker-less or unsafe candidates
        never auto-load; explicit ones prompt instead. Soft-only throughout.
        """
        try:
            pending = take_pending_root()
        except Exception as e:
            _debug(f"pending read failed: {e!r}")
            pending = None
        try:
            cwd = os.getcwd()
        except Exception:
            cwd = None
        try:
            action, folder = resolve_startup_root(cwd, pending)
        except Exception as e:
            _debug(f"startup resolve failed: {e!r}")
            return
        if action == "load" and folder:
            _debug(f"startup: auto-loading {folder}")
            self._set_root(folder)
        elif action == "prompt" and folder:
            _debug(f"startup: prompting for {folder}")
            try:
                if GLib is not None:
                    GLib.idle_add(self._prompt_startup_root, folder)
                else:
                    self._prompt_startup_root(folder)
            except Exception as e:
                _debug(f"startup prompt failed: {e!r}")

    def _prompt_startup_root(self, folder: str) -> bool:
        try:
            self._choose_root(initial_folder=folder)
        except Exception as e:
            _debug(f"startup chooser failed: {e!r}")
        return False

    def _choose_root(self, initial_folder: str | None = None) -> None:
        if Gtk is None:
            return
        try:
            dialog = Gtk.FileChooserDialog(
                title="Open Folder",
                action=Gtk.FileChooserAction.SELECT_FOLDER,
            )
            if initial_folder and os.path.isdir(initial_folder):
                try:
                    dialog.set_current_folder(initial_folder)
                except Exception:
                    pass
            try:
                dialog.set_transient_for(self.window)
                dialog.set_modal(True)
            except Exception:
                pass
            dialog.add_buttons(
                "_Cancel",
                Gtk.ResponseType.CANCEL,
                "_Open",
                Gtk.ResponseType.ACCEPT,
            )
        except Exception as e:
            _debug(f"folder chooser create failed: {e!r}")
            return
        try:
            folder = dialog.get_filename() if dialog.run() == Gtk.ResponseType.ACCEPT else None
        except Exception as e:
            _debug(f"folder chooser failed: {e!r}")
            folder = None
        finally:
            try:
                dialog.destroy()
            except Exception:
                pass
        if not folder:
            return
        self._set_root(folder)

    def _set_root(self, folder: str) -> None:
        if not folder or not os.path.isdir(folder):
            return
        try:
            if is_unsafe_root(folder):
                _debug(f"refusing unsafe root: {folder}")
                return
        except Exception:
            return
        self._root_dir = os.path.abspath(folder)
        if self.browser is not None:
            self.browser.set_root(self._root_dir)

    def _open_file(self, path: str) -> None:
        if Gio is None:
            return
        if not path:
            return
        try:
            location = Gio.File.new_for_path(path)
        except Exception:
            return
        existing = None
        try:
            existing = self.window.get_tab_from_location(location)
        except Exception:
            existing = None
        try:
            if existing is not None:
                self.window.set_active_tab(existing)
            else:
                self.window.create_tab_from_location(location, None, 0, True, True)
        except Exception as e:
            _debug(f"open file failed for {path}: {e!r}")
