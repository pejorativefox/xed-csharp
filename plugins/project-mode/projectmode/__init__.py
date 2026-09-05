# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

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

    from gi.repository import GObject, Gtk, Gdk, Gio, Xed  # type: ignore
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
    Gtk = Gio = Gdk = None  # type: ignore[no-redef]


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

            toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            choose = Gtk.Button.new_with_label("Open Folder")
            choose.connect("clicked", lambda _b: self.emit("choose-root"))
            self._root_label = Gtk.Label(label="No folder selected")
            self._root_label.set_xalign(0.0)
            toolbar.pack_start(choose, False, False, 0)
            toolbar.pack_start(self._root_label, True, True, 0)
            self.pack_start(toolbar, False, False, 0)

            self.store = Gtk.TreeStore(str, str, str, str)
            self.tree = Gtk.TreeView.new_with_model(self.store)
            self.tree.set_headers_visible(False)
            col = Gtk.TreeViewColumn("Files")
            icon = Gtk.CellRendererPixbuf()
            cell = Gtk.CellRendererText()
            col.pack_start(icon, False)
            col.pack_start(cell, True)
            col.add_attribute(icon, "icon-name", self._col_icon)
            col.add_attribute(cell, "text", self._col_label)
            self.tree.append_column(col)
            self.tree.connect("row-activated", self._on_row_activated)

            scrolled = Gtk.ScrolledWindow()
            scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            scrolled.add(self.tree)
            self.pack_start(scrolled, True, True, 0)
            self.show_all()

        def set_root(self, folder: str) -> None:
            self._root_dir = folder
            self.store.clear()
            if not folder or not os.path.isdir(folder):
                self._root_label.set_text("No folder selected")
                return
            base = os.path.basename(folder.rstrip(os.sep)) or folder
            self._root_label.set_text(folder)
            root_iter = self.store.append(
                None,
                [_TREE_FOLDER_ICON, base + "/", folder, "folder"],
            )
            for node in build_file_tree(folder):
                self._append_node(root_iter, node)
            try:
                self.tree.expand_row(Gtk.TreePath.new_from_indices([0]), False)
            except Exception:
                pass

        def _append_node(self, parent, node: FileNode) -> None:
            if node.is_dir:
                folder_iter = self.store.append(
                    parent,
                    [_TREE_FOLDER_ICON, node.name + "/", node.path, "folder"],
                )
                for child in node.children:
                    self._append_node(folder_iter, child)
            else:
                self.store.append(parent, [_TREE_FILE_ICON, node.name, node.path, "file"])

        def _on_row_activated(self, _tree, path, _col) -> None:
            tree_iter = self.store.get_iter(path)
            kind = self.store.get_value(tree_iter, self._col_kind)
            fpath = self.store.get_value(tree_iter, self._col_path)
            if kind == "file" and os.path.isfile(fpath):
                self.emit("open-file", fpath)
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

    def do_deactivate(self) -> None:
        if self._window_key_id is not None:
            try:
                self.window.disconnect(self._window_key_id)
            except Exception:
                pass
        self._window_key_id = None

        if self.browser is not None:
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

    def _choose_root(self) -> None:
        if Gtk is None:
            return
        try:
            dialog = Gtk.FileChooserDialog(
                title="Open Folder",
                action=Gtk.FileChooserAction.SELECT_FOLDER,
            )
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
