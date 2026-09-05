# -*- coding: utf-8 -*-
"""autoreload: silently reload externally modified files without local edits.

Two triggers feed the same safe-reload path:

- xed's own externally-modified tab state (fires on focus/tab switch), and
- a Gio file monitor per open file (fires immediately, even unfocused).

A reload only happens when the buffer has no unsaved changes *and* the file
content actually differs from the buffer, so own saves and mtime-only touches
are harmless no-ops. Buffers with unsaved changes are left alone, so xed's
normal infobar behavior still applies.
"""

from __future__ import annotations

import os
import sys

_RELOAD_DEBOUNCE_MS = 400
_COMPARE_CAP_BYTES = 1024 * 1024

_XED_LIBDIRS = (
    "/usr/lib64/xed",
    "/usr/lib/xed",
    "/usr/lib/x86_64-linux-gnu/xed",
    "/usr/local/lib/xed",
    "/app/lib/xed",
)


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
        sys.stderr.write(f"[autoreload] typelib setup failed: {e!r}\n")


def _debug(message: str) -> None:
    if os.environ.get("XED_PLUGIN_DEBUG", "").strip().lower() in ("", "0", "false", "no", "off"):
        return
    try:
        sys.stderr.write(f"[autoreload] {message}\n")
        sys.stderr.flush()
    except Exception:
        pass


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


try:
    _EXTERNALLY_MODIFIED_STATE = int(
        Xed.TabState.STATE_EXTERNALLY_MODIFIED_NOTIFICATION  # type: ignore[attr-defined]
    )
except Exception:
    # Stable XedTabState value; fallback keeps headless tests working.
    _EXTERNALLY_MODIFIED_STATE = 13


def doc_location(doc):
    """Best-effort Gio location for a document, or None for untitled docs."""
    try:
        location = doc.get_location()
    except Exception:
        location = None
    if location is None:
        try:
            location = doc.get_file().get_location()
        except Exception:
            location = None
    return location


def should_reload(doc) -> bool:
    """True when a doc may be reloaded without losing user edits."""
    if doc_location(doc) is None:
        return False
    try:
        if doc.get_modified():
            return False
    except Exception:
        return False
    return True


def cursor_line(doc) -> int:
    """0-based cursor line, best effort."""
    try:
        return int(doc.get_iter_at_mark(doc.get_insert()).get_line())
    except Exception:
        return 0


def doc_file_path(doc) -> str | None:
    """Local filesystem path for a document, or None for untitled/remote."""
    location = doc_location(doc)
    if location is None:
        return None
    try:
        if hasattr(location, "has_uri_scheme") and not location.has_uri_scheme("file"):
            return None
        path = location.get_path()
    except Exception:
        return None
    return path or None


def buffer_bytes(doc) -> bytes | None:
    """Buffer content as UTF-8 bytes, or None (soft-only)."""
    try:
        text = doc.get_text(doc.get_start_iter(), doc.get_end_iter(), False)
    except Exception:
        return None
    try:
        return text.encode("utf-8")
    except Exception:
        return None


def read_file_bytes(path: str, cap: int = _COMPARE_CAP_BYTES) -> bytes | None:
    """Raw file bytes up to cap, or None when missing/unreadable/too big."""
    try:
        if os.path.getsize(path) > cap:
            return None
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return None


def file_differs(doc, path: str) -> bool | None:
    """True when file content differs from the buffer.

    None means "cannot tell" (unreadable file or buffer); callers treat that
    as "do not reload", except oversized files which compare as differing so
    large clean buffers still reload.
    """
    try:
        if os.path.getsize(path) > _COMPARE_CAP_BYTES:
            return True
    except Exception:
        return None
    data = read_file_bytes(path)
    if data is None:
        return None
    content = buffer_bytes(doc)
    if content is None:
        return None
    return data != content


def _watched_events() -> set:
    """Gio monitor event codes that should trigger a reload check."""
    try:
        monitor_event = Gio.FileMonitorEvent
        names = ("CHANGED", "CHANGES_DONE_HINT", "CREATED",
                 "ATTRIBUTE_CHANGED", "RENAMED", "MOVED_IN", "MOVED_OUT")
        return {int(getattr(monitor_event, name)) for name in names}
    except Exception:
        try:
            return {int(Gio.FileMonitorEvent.CHANGES_DONE_HINT)}
        except Exception:
            return {1}


class AutoReloadPlugin(GObject.Object, Xed.WindowActivatable):  # type: ignore[misc]
    __gtype_name__ = "XedAutoReloadPlugin"

    window = GObject.Property(type=Xed.Window)  # type: ignore[arg-type]

    def __init__(self) -> None:
        super().__init__()
        self._signal_ids: list = []
        self._monitors: dict = {}
        self._pending: dict = {}

    def do_activate(self) -> None:
        self._attach(self.window)
        self._sync_watches(self.window)
        self._sweep(self.window)

    def do_deactivate(self) -> None:
        self._detach()
        self._unwatch_all()

    def do_update_state(self) -> None:
        return

    def _attach(self, window) -> None:
        for signal, handler in (
            ("tab-added", self._on_tab_added),
            ("tab-removed", self._on_tab_removed),
            ("active-tab-changed", self._on_active_tab_changed),
            ("active-tab-state-changed", self._on_tab_state_changed),
        ):
            try:
                self._signal_ids.append((window, window.connect(signal, handler)))
            except Exception as e:
                _debug(f"connect {signal} failed: {e!r}")

    def _detach(self) -> None:
        for obj, handler_id in self._signal_ids:
            try:
                obj.disconnect(handler_id)
            except Exception:
                pass
        self._signal_ids = []

    def _on_tab_added(self, window, _tab) -> None:
        self._sync_watches(window)

    def _on_tab_removed(self, window, _tab) -> None:
        self._sync_watches(window)

    def _on_active_tab_changed(self, window, *_args) -> None:
        self._sync_watches(window)
        self._sweep(window)

    def _on_tab_state_changed(self, window, *args) -> None:
        tab = None
        for candidate in args:
            if candidate is not None and hasattr(candidate, "get_document"):
                tab = candidate
                break
        if tab is None:
            return
        self._maybe_reload(tab, window)
        self._sync_watches(window)

    def _sweep(self, window) -> None:
        try:
            docs = list(window.get_documents())
        except Exception:
            return
        for doc in docs:
            try:
                location = doc_location(doc)
                tab = window.get_tab_from_location(location) if location is not None else None
            except Exception:
                tab = None
            if tab is None:
                continue
            self._maybe_reload(tab, window)

    def _maybe_reload(self, tab, window) -> bool:
        try:
            state = int(tab.get_state())
        except Exception:
            return False
        if state != _EXTERNALLY_MODIFIED_STATE:
            return False
        try:
            doc = tab.get_document()
        except Exception:
            return False
        return self._check_and_reload(window, doc, reason="externally modified")

    def _reload_doc(self, window, doc, location, reason: str) -> bool:
        line = cursor_line(doc)
        try:
            Xed.commands_load_location(window, location, None, line)
        except Exception as e:
            _debug(f"reload failed: {e!r}")
            return False
        try:
            path = location.get_path()
        except Exception:
            path = location
        _debug(f"reloaded {path} (clean, {reason})")
        return True

    def _find_doc(self, window, path: str):
        try:
            docs = list(window.get_documents())
        except Exception:
            return None
        for doc in docs:
            try:
                if doc_file_path(doc) == path:
                    return doc
            except Exception:
                continue
        return None

    def _check_and_reload(self, window, doc, reason: str) -> bool:
        if not should_reload(doc):
            return False
        location = doc_location(doc)
        if location is None:
            return False
        try:
            path = doc_file_path(doc)
        except Exception:
            path = None
        if path is not None:
            try:
                differs = file_differs(doc, path)
            except Exception:
                differs = None
            if differs is False:
                return False
            if differs is None:
                _debug(f"skip reload of {path} (cannot compare)")
                return False
        return self._reload_doc(window, doc, location, reason)

    # -- file monitors (immediate reload, no focus needed) ----------------
    def _sync_watches(self, window) -> None:
        if Gio is None:
            return
        try:
            docs = list(window.get_documents())
        except Exception:
            return
        wanted: dict = {}
        for doc in docs:
            try:
                path = doc_file_path(doc)
            except Exception:
                path = None
            if path:
                wanted[path] = doc
        for path in list(self._monitors):
            if path not in wanted:
                self._unwatch(path)
        for path in wanted:
            if path not in self._monitors:
                self._watch(window, path)

    def _watch(self, window, path: str) -> None:
        if Gio is None:
            return
        try:
            flags = getattr(Gio.FileMonitorFlags, "WATCH_MTIME", 0)
            monitor = Gio.File.new_for_path(path).monitor_file(flags, None)
        except Exception as e:
            _debug(f"watch failed for {path}: {e!r}")
            return
        try:
            handler_id = monitor.connect("changed", self._on_file_event, window, path)
        except Exception as e:
            _debug(f"watch connect failed for {path}: {e!r}")
            try:
                monitor.cancel()
            except Exception:
                pass
            return
        self._monitors[path] = (monitor, handler_id)

    def _unwatch(self, path: str) -> None:
        entry = self._monitors.pop(path, None)
        if entry is not None:
            monitor, handler_id = entry
            try:
                monitor.disconnect(handler_id)
            except Exception:
                pass
            try:
                monitor.cancel()
            except Exception:
                pass
        timer_id = self._pending.pop(path, None)
        if timer_id is not None and GLib is not None:
            try:
                GLib.source_remove(timer_id)
            except Exception:
                pass

    def _unwatch_all(self) -> None:
        for path in list(self._monitors):
            self._unwatch(path)
        self._monitors = {}
        self._pending = {}

    def _on_file_event(self, _monitor, _gfile, _other, event, window, path) -> None:
        try:
            code = int(event)
        except Exception:
            return
        if code not in _watched_events():
            return
        old_id = self._pending.pop(path, None)
        if old_id is not None and GLib is not None:
            try:
                GLib.source_remove(old_id)
            except Exception:
                pass
        if GLib is None:
            self._fire(window, path)
            return
        try:
            self._pending[path] = GLib.timeout_add(
                _RELOAD_DEBOUNCE_MS, self._fire, window, path
            )
        except Exception as e:
            _debug(f"debounce failed for {path}: {e!r}")

    def _fire(self, window, path) -> bool:
        self._pending.pop(path, None)
        try:
            doc = self._find_doc(window, path)
        except Exception:
            doc = None
        if doc is None:
            self._unwatch(path)
            return False
        self._check_and_reload(window, doc, reason="file changed on disk")
        return False
