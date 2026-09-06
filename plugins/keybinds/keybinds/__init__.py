# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys

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
        sys.stderr.write(f"[keybinds] typelib setup failed: {e!r}\n")


def _debug(message: str) -> None:
    if os.environ.get("XED_PLUGIN_DEBUG", "").strip().lower() in ("", "0", "false", "no", "off"):
        return
    try:
        sys.stderr.write(f"[keybinds] {message}\n")
        sys.stderr.flush()
    except Exception:
        pass

def _get_clipboard_text():
    try:
        return Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()
    except Exception:
        return None


def _set_clipboard_text(text) -> bool:
    try:
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
        return True
    except Exception:
        return False


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

    class _DummyGLib:
        @staticmethod
        def timeout_add(_ms, _cb):
            return None

    GObject = _DummyGObject  # type: ignore[no-redef]
    Xed = _DummyXed  # type: ignore[no-redef]
    GLib = _DummyGLib  # type: ignore[no-redef]
    Gtk = Gio = Gdk = None  # type: ignore[no-redef]


class KeybindsPlugin(GObject.Object, Xed.WindowActivatable):  # type: ignore[misc]
    __gtype_name__ = "XedKeybindsPlugin"

    window = GObject.Property(type=Xed.Window)  # type: ignore[arg-type]

    def __init__(self) -> None:
        super().__init__()
        self._window_key_id = None

    def do_activate(self) -> None:
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

    def do_update_state(self) -> None:
        return

    @staticmethod
    def _doc_location(doc):
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

    def _step_tab(self, direction: int) -> None:
        try:
            docs = list(self.window.get_documents())
            if len(docs) < 2:
                return
            tabs = []
            for doc in docs:
                try:
                    tab = self.window.get_tab_from_location(self._doc_location(doc))
                except Exception:
                    tab = None
                if tab is not None:
                    tabs.append(tab)
            if len(tabs) < 2:
                return
            try:
                active = self.window.get_active_tab()
            except Exception:
                active = None
            try:
                idx = tabs.index(active)
            except ValueError:
                idx = 0
            self.window.set_active_tab(tabs[(idx + direction) % len(tabs)])
        except Exception as e:
            _debug(f"tab step failed: {e!r}")

    def _open_preferences(self) -> bool:
        try:
            ui_manager = self.window.get_ui_manager()
        except Exception as e:
            _debug(f"preferences ui-manager failed: {e!r}")
            return False
        try:
            groups = ui_manager.get_action_groups()
        except Exception as e:
            _debug(f"preferences action-groups failed: {e!r}")
            return False
        for group in groups or ():
            try:
                action = group.get_action("EditPreferences")
            except Exception:
                action = None
            if action is None:
                continue
            try:
                action.activate()
            except Exception as e:
                _debug(f"preferences activate failed: {e!r}")
                return False
            return True
        _debug("preferences action EditPreferences not found")
        return False


    def _active_editor_view(self):
        try:
            view = self.window.get_active_view()
        except Exception:
            return None
        try:
            if view is None or not view.is_focus():
                return None
        except Exception:
            return None
        return view

    def _handle_clipboard_key(self, lowered, view) -> bool:
        try:
            buffer = view.get_buffer()
            if buffer.get_has_selection() or not view.get_editable():
                return False
            if lowered in ("c", "x"):
                insert = buffer.get_insert()
                line = buffer.get_iter_at_mark(insert).get_line()
                start = buffer.get_iter_at_line(line)
                end = start.copy()
                end.forward_to_line_end()
                text = buffer.get_text(start, end, True)
                _set_clipboard_text(text + "\n")
                if lowered == "c":
                    return True
                try:
                    buffer.begin_user_action()
                    del_end = end.copy()
                    if not del_end.is_end():
                        del_end.forward_char()
                    buffer.delete(start, del_end)
                finally:
                    try:
                        buffer.end_user_action()
                    except Exception:
                        pass
                try:
                    target = min(line, buffer.get_line_count() - 1)
                    buffer.place_cursor(buffer.get_iter_at_line(target))
                except Exception:
                    pass
                return True
            if lowered == "v":
                text = _get_clipboard_text()
                if not text or not text.endswith("\n"):
                    return False
                stripped = text[:-1]
                cursor_line = buffer.get_iter_at_mark(buffer.get_insert()).get_line()
                try:
                    buffer.begin_user_action()
                    buffer.insert(buffer.get_iter_at_line(cursor_line), stripped + "\n")
                finally:
                    try:
                        buffer.end_user_action()
                    except Exception:
                        pass
                return True
            return False
        except Exception as e:
            _debug(f"clipboard key failed: {e!r}")
            return False

    def _handle_global_key(self, keyname: str, ctrl: bool, shift: bool, alt: bool) -> bool:
        if not (ctrl and not shift and not alt):
            return False
        lowered = (keyname or "").lower()
        if lowered in ("page_up", "kp_page_up"):
            _debug("key: Ctrl+PageUp previous-tab")
            self._step_tab(-1)
            return True
        if lowered in ("page_down", "kp_page_down"):
            _debug("key: Ctrl+PageDown next-tab")
            self._step_tab(+1)
            return True
        if lowered in ("c", "x", "v"):
            view = self._active_editor_view()
            if view is None:
                return False
            return self._handle_clipboard_key(lowered, view)
        if lowered == "comma":
            _debug("key: Ctrl+comma preferences")
            return self._open_preferences()
        return False

    def _on_window_key_press(self, _window, event) -> bool:
        try:
            mods = event.state & Gtk.accelerator_get_default_mod_mask()
            keyname = Gdk.keyval_name(event.keyval) or ""
            ctrl = bool(mods & Gdk.ModifierType.CONTROL_MASK)
            shift = bool(mods & Gdk.ModifierType.SHIFT_MASK)
            alt = bool(mods & Gdk.ModifierType.MOD1_MASK)
        except Exception:
            return False
        return self._handle_global_key(keyname, ctrl, shift, alt)
