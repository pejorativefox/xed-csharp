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
        sys.stderr.write(f"[panel-hider] typelib setup failed: {e!r}\n")


def _debug(message: str) -> None:
    if os.environ.get("XED_PLUGIN_DEBUG", "").strip().lower() in ("", "0", "false", "no", "off"):
        return
    try:
        sys.stderr.write(f"[panel-hider] {message}\n")
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

    class _DummyGLib:
        @staticmethod
        def timeout_add(_ms, _cb):
            return None

    GObject = _DummyGObject  # type: ignore[no-redef]
    Xed = _DummyXed  # type: ignore[no-redef]
    GLib = _DummyGLib  # type: ignore[no-redef]
    Gtk = Gio = Gdk = None  # type: ignore[no-redef]


class PanelHiderPlugin(GObject.Object, Xed.WindowActivatable):  # type: ignore[misc]
    __gtype_name__ = "XedPanelHiderPlugin"

    PANES_SCHEMA = "org.x.editor.preferences.ui"

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
    def _safe(fn):
        try:
            return fn()
        except Exception:
            return None

    def _panes_settings(self):
        if Gio is None:
            return None
        try:
            return Gio.Settings.new(self.PANES_SCHEMA)
        except Exception as e:
            _debug(f"panes settings unavailable: {e!r}")
            return None

    def _panel_widget(self, which: str):
        try:
            get = self.window.get_side_panel if which == "side" else self.window.get_bottom_panel
            return self._safe(get)
        except Exception:
            return None

    def _pane_visible(self, which: str) -> bool:
        widget = self._panel_widget(which)
        if widget is not None:
            try:
                return bool(widget.is_visible())
            except Exception:
                pass
            try:
                return bool(widget.get_visible())
            except Exception:
                pass
        settings = self._panes_settings()
        if settings is not None:
            try:
                key = "side-panel-visible" if which == "side" else "bottom-panel-visible"
                return bool(settings.get_boolean(key))
            except Exception:
                pass
        return True

    def _set_panes(self, side=None, bottom=None) -> None:
        for which, value in (("side", side), ("bottom", bottom)):
            if value is None:
                continue
            widget = self._panel_widget(which)
            if widget is not None:
                try:
                    widget.set_visible(bool(value))
                except Exception as e:
                    _debug(f"panes widget failed: {e!r}")
        settings = self._panes_settings()
        if settings is None:
            return
        try:
            if side is not None:
                settings.set_boolean("side-panel-visible", bool(side))
            if bottom is not None:
                settings.set_boolean("bottom-panel-visible", bool(bottom))
        except Exception as e:
            _debug(f"panes set failed: {e!r}")

    def _set_pane_action(self, name: str, visible: bool) -> bool:
        try:
            manager = self.window.get_ui_manager()
            if manager is None:
                return False
            groups = manager.get_action_groups() or []
        except Exception as e:
            _debug(f"pane action lookup failed: {e!r}")
            return False
        for group in groups:
            try:
                action = group.get_action(name)
            except Exception:
                continue
            if action is None:
                continue
            try:
                action.set_active(bool(visible))
                return True
            except Exception:
                try:
                    action.activate()
                    return True
                except Exception as e:
                    _debug(f"pane action activate failed: {e!r}")
                    return False
        return False

    def _hide_all_panels(self) -> None:
        _debug("panels: hiding side + bottom")
        ok_side = self._set_pane_action("ViewSidePane", False)
        ok_bottom = self._set_pane_action("ViewBottomPane", False)
        if not ok_side or not ok_bottom:
            self._set_panes(side=None if ok_side else False, bottom=None if ok_bottom else False)

    def _pane_geometry(self, which: str):
        try:
            widget = self._panel_widget(which)
            if widget is None or Gio is None:
                return None
            paned = widget.get_parent()
            pos = int(paned.get_position())
            try:
                max_pos = int(paned.get_property("max-position"))
            except Exception:
                max_pos = -1
            try:
                if paned.get_child1() is widget:
                    pane_number = 1
                elif paned.get_child2() is widget:
                    pane_number = 2
                else:
                    pane_number = 0
            except Exception:
                pane_number = 0
            try:
                state = Gio.Settings.new("org.x.editor.state.window")
                key = "bottom-panel-size" if which == "bottom" else "side-panel-size"
                saved = int(state.get_int(key))
            except Exception:
                saved = 0
            if saved <= 0:
                saved = 300 if which == "bottom" else 250
            return paned, pane_number, pos, max_pos, saved
        except Exception as e:
            _debug(f"panels: {which} geometry probe failed: {e!r}")
            return None

    def _fix_pane_size(self, which: str) -> bool:
        info = self._pane_geometry(which)
        if info is None:
            return False
        paned, pane_number, pos, max_pos, saved = info
        target = None
        if pane_number == 2 and max_pos > 0:
            if pos >= max_pos - 1 or pos <= 0:
                target = max(0, max_pos - saved)
        elif pane_number == 1:
            if pos <= 1:
                target = saved
        elif pos <= 0:
            target = saved
        if target is None:
            return False
        try:
            paned.set_position(target)
            _debug(f"panels: {which} size restored to {target}")
            return True
        except Exception as e:
            _debug(f"panels size restore failed: {e!r}")
            return False

    def _ensure_pane_size(self, which: str) -> None:
        self._fix_pane_size(which)
        try:
            GLib.timeout_add(250, lambda: self._delayed_pane_size(which))
        except Exception:
            pass

    def _delayed_pane_size(self, which: str) -> bool:
        try:
            self._fix_pane_size(which)
        except Exception as e:
            _debug(f"panes delayed size failed: {e!r}")
        return False

    def _toggle_pane(self, action_name: str, which: str) -> None:
        target = not self._pane_visible(which)
        if self._set_pane_action(action_name, target):
            _debug(f"panels: {which} toggled via menu action")
        else:
            _debug(f"panels: {which} -> {target} (fallback)")
            self._set_panes(**{which: target})
        if target:
            self._ensure_pane_size(which)

    def _toggle_bottom_panel(self) -> None:
        self._toggle_pane("ViewBottomPane", "bottom")

    def _toggle_side_panel(self) -> None:
        self._toggle_pane("ViewSidePane", "side")

    def _handle_global_key(self, keyname: str, ctrl: bool, shift: bool, alt: bool) -> bool:
        if ctrl and not shift and not alt and keyname.lower() == "b":
            _debug("key: Ctrl+B hide-panels")
            self._hide_all_panels()
            return True
        if ctrl and not shift and not alt and keyname.lower() == "j":
            _debug("key: Ctrl+J toggle-bottom-panel")
            self._toggle_bottom_panel()
            return True
        if ctrl and not shift and not alt and keyname.lower() == "e":
            _debug("key: Ctrl+E toggle-side-panel")
            self._toggle_side_panel()
            return True
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
