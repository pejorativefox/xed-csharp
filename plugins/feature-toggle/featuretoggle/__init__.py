# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys

try:
    from gi.repository import GLib
except Exception:
    GLib = None  # type: ignore

_XED_LIBDIRS = (
    "/usr/lib64/xed",
    "/usr/lib/xed",
    "/usr/lib/x86_64-linux-gnu/xed",
    "/usr/local/lib/xed",
    "/app/lib/xed",
)

GROUP = "FeatureToggle"
DEFAULTS = {
    "hide_documents_panel": True,
    "close_untitled_on_startup": True,
}


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
        sys.stderr.write(f"[feature-toggle] typelib setup failed: {e!r}\n")


def _debug(message: str) -> None:
    if os.environ.get("XED_PLUGIN_DEBUG", "").strip().lower() in ("", "0", "false", "no", "off"):
        return
    try:
        sys.stderr.write(f"[feature-toggle] {message}\n")
        sys.stderr.flush()
    except Exception:
        pass


def _config_dir() -> str:
    if GLib is not None:
        try:
            base = GLib.get_user_config_dir()
        except Exception:
            base = os.path.expanduser("~/.config")
    else:
        base = os.path.expanduser("~/.config")
    return os.path.join(base, "xed", "plugins", "feature-toggle")


class SettingsStore:
    def __init__(self, path: str | None = None) -> None:
        config_dir = _config_dir()
        os.makedirs(config_dir, exist_ok=True)
        self._path = path or os.path.join(config_dir, "settings.ini")
        self._data = dict(DEFAULTS)
        self.load()

    def load(self) -> dict:
        data = dict(DEFAULTS)
        try:
            if os.path.exists(self._path):
                current_group = None
                with open(self._path, "r", encoding="utf-8") as f:
                    for raw in f:
                        line = raw.strip()
                        if not line or line.startswith(("#", ";")):
                            continue
                        if line.startswith("[") and line.endswith("]"):
                            current_group = line[1:-1]
                            continue
                        if current_group != GROUP or "=" not in line:
                            continue
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip()
                        if key in DEFAULTS:
                            data[key] = value.lower() in ("1", "true", "yes", "on")
        except Exception as e:
            _debug(f"settings load failed: {e!r}")
        self._data = data
        return dict(self._data)

    def save(self) -> None:
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(f"[{GROUP}]\n")
                for key in DEFAULTS:
                    value = self._data.get(key, DEFAULTS[key])
                    f.write(f"{key}={'true' if value else 'false'}\n")
            os.replace(tmp, self._path)
        except Exception as e:
            _debug(f"settings save failed: {e!r}")

    def get(self, key: str):
        return self._data.get(key, DEFAULTS.get(key))

    def set(self, key: str, value) -> None:
        if key in DEFAULTS:
            self._data[key] = bool(value)


def _doc_path(doc) -> str | None:
    try:
        location = doc.get_location()
    except Exception:
        location = None
    if location is None:
        try:
            location = doc.get_file().get_location()
        except Exception:
            location = None
    if location is None:
        return None
    try:
        if not location.has_uri_scheme("file"):
            return None
        return location.get_path()
    except Exception:
        return None


def _find_documents_widget(widget, skip: tuple = ()): 
    try:
        if any(widget is owned for owned in skip):
            return None
    except Exception:
        pass
    try:
        if type(widget).__name__ == "XedDocumentsPanel":
            return widget
    except Exception:
        return None
    try:
        children = widget.get_children()
    except Exception:
        return None
    for child in children or []:
        found = _find_documents_widget(child, skip)
        if found is not None:
            return found
    return None


try:
    import gi

    _ensure_xed_gi_paths()

    gi.require_version("Gtk", "3.0")
    gi.require_version("Xed", "1.0")

    from gi.repository import GObject, GLib, Xed  # type: ignore
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

    class _DummyGLib:
        @staticmethod
        def idle_add(fn, *args):
            try:
                return fn(*args)
            except Exception:
                return None

    GObject = _DummyGObject  # type: ignore[no-redef]
    Xed = _DummyXed  # type: ignore[no-redef]
    GLib = _DummyGLib  # type: ignore[no-redef]


class FeatureTogglePlugin(GObject.Object, Xed.WindowActivatable):  # type: ignore[misc]
    __gtype_name__ = "XedFeatureTogglePlugin"

    window = GObject.Property(type=Xed.Window)  # type: ignore[arg-type]

    def __init__(self) -> None:
        super().__init__()
        self.settings = SettingsStore()
        self._hidden_docs = None
        self._signal_ids: list[tuple[object, int]] = []

    def do_activate(self) -> None:
        self._hide_documents_panel()
        try:
            GLib.idle_add(self._close_untouched_starter_doc)
        except Exception:
            pass
        for signal in ("active-tab-changed", "tab-added"):
            try:
                handler_id = self.window.connect(signal, lambda *_a: self._hide_documents_panel())
                self._signal_ids.append((self.window, handler_id))
            except Exception as e:
                _debug(f"connect {signal} failed: {e!r}")

    def do_deactivate(self) -> None:
        self._restore_documents_panel()
        for obj, handler_id in self._signal_ids:
            try:
                obj.disconnect(handler_id)  # type: ignore[attr-defined]
            except Exception:
                pass
        self._signal_ids.clear()

    def do_update_state(self) -> None:
        return

    @staticmethod
    def _safe(fn):
        try:
            return fn()
        except Exception as e:
            _debug(f"window accessor failed: {e!r}")
            return None

    def _hide_documents_panel(self) -> None:
        try:
            if getattr(self, "_hidden_docs", None) is not None:
                return
            settings = getattr(self, "settings", None)
            try:
                enabled = bool(settings.get("hide_documents_panel")) if settings else True
            except Exception:
                enabled = True
            if not enabled:
                return
            side = self._safe(lambda: self.window.get_side_panel())
            if side is None:
                return
            found = _find_documents_widget(side)
            if found is None:
                return
            try:
                removed = bool(side.remove_item(found))
            except Exception:
                removed = False
            if not removed:
                try:
                    side.remove(found)
                    removed = True
                except Exception as e:
                    _debug(f"documents panel remove failed: {e!r}")
                    return
            self._hidden_docs = found
            _debug("documents panel hidden")
        except Exception as e:
            _debug(f"documents panel hide failed: {e!r}")

    def _restore_documents_panel(self) -> None:
        widget, self._hidden_docs = getattr(self, "_hidden_docs", None), None
        if widget is None:
            return
        try:
            side = self._safe(lambda: self.window.get_side_panel())
            if side is None:
                return
            try:
                side.add_item(widget, "Documents", "text-x-generic")
            except Exception:
                try:
                    side.add(widget)
                except Exception as e:
                    _debug(f"documents panel restore failed: {e!r}")
        except Exception as e:
            _debug(f"documents panel restore failed: {e!r}")

    def _close_untouched_starter_doc(self) -> None:
        try:
            settings = getattr(self, "settings", None)
            if settings is not None and not bool(settings.get("close_untitled_on_startup")):
                return
        except Exception:
            pass
        try:
            docs = list(self.window.get_documents())
        except Exception:
            return
        if len(docs) != 1:
            return
        doc = docs[0]
        try:
            if not doc.is_untouched() or _doc_path(doc) is not None:
                return
        except Exception:
            return
        try:
            tab = self.window.get_active_tab()
        except Exception:
            tab = None
        if tab is None:
            return
        try:
            self.window.close_tab(tab)
            _debug("closed untouched starter doc")
        except Exception as e:
            _debug(f"starter doc close failed: {e!r}")
