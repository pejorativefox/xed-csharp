# -*- coding: utf-8 -*-
"""Tabbed terminal (VTE) for xed's bottom panel.

Multi-tab terminal: each tab is a Vte.Terminal running /bin/bash inheriting
xed's cwd. Shortcuts (window-level so they work while a terminal is focused):
Ctrl+Shift+T new tab, Ctrl+Shift+W close current tab, Ctrl+` focus terminal.

Conventions (see AGENTS.md):
- Startup/dependency problems are soft-only: stderr line, never raise.
- Headless-safe: pure helpers (unique_label, handle_global_key) importable
  without a display; GTK/VTE parts only defined when available.
"""

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

PANEL_TITLE = "Terminal"
PANEL_ICONS = ("utilities-terminal", "terminal", "dialog-information")
SHELL_ARGV = ["/bin/bash"]
BASE_LABEL = "Terminal"

_BACKTICK_NAMES = frozenset({"grave", "quoteleft", "`", "asciigrave"})


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
        sys.stderr.write(f"[tabbed-terminal] typelib setup failed: {e!r}\n")


def _debug(message: str) -> None:
    if os.environ.get("XED_PLUGIN_DEBUG", "").strip().lower() in ("", "0", "false", "no", "off"):
        return
    try:
        sys.stderr.write(f"[tabbed-terminal] {message}\n")
        sys.stderr.flush()
    except Exception:
        pass


def unique_label(base: str, existing: list[str] | set[str] | tuple) -> str:
    """First free tab label: base, base 2, base 3, ..."""
    taken = set(existing)
    if base not in taken:
        return base
    index = 2
    while f"{base} {index}" in taken:
        index += 1
    return f"{base} {index}"


def handle_global_key(keyname: str, ctrl: bool, shift: bool, alt: bool) -> str | None:
    """Map a window keypress to a terminal action.

    Returns "new" | "close" | "focus" | None. Pure logic, headless-testable.
    """
    name = (keyname or "").lower()
    if ctrl and shift and not alt and name == "t":
        return "new"
    if ctrl and shift and not alt and name == "w":
        return "close"
    if ctrl and not shift and not alt and (keyname in _BACKTICK_NAMES or name in _BACKTICK_NAMES):
        return "focus"
    return None


try:
    import gi

    _ensure_xed_gi_paths()

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Xed", "1.0")

    from gi.repository import GObject, Gtk, Gdk, Gio, GLib, Xed, Pango  # type: ignore

    try:
        gi.require_version("Vte", "2.91")
        from gi.repository import Vte  # type: ignore
    except Exception as _vte_err:
        Vte = None  # type: ignore
        try:
            sys.stderr.write(f"[tabbed-terminal] VTE unavailable ({_vte_err}); "
                             "install gir1.2-vte-2.91 for terminal tabs.\n")
        except Exception:
            pass
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

        @classmethod
        def Property(cls, *args, **kwargs):  # noqa: N802
            return None

    class _DummyXed:
        class WindowActivatable:
            pass

        Window = object

    GObject = _DummyGObject  # type: ignore[no-redef]
    Xed = _DummyXed  # type: ignore[no-redef]
    Gtk = Gio = Gdk = GLib = Pango = Vte = None  # type: ignore[no-redef]


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


if Gtk is not None:
    class TerminalPanel(Gtk.Box):
        """Bottom-panel widget: toolbar + notebook of VTE terminals."""

        def __init__(self) -> None:
            super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            self._labels: list[str] = []
            self.notebook = None
            self._fallback = None

            toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            new_btn = Gtk.Button.new_with_label("+ New")
            new_btn.connect("clicked", lambda _b: self.new_terminal())
            close_btn = Gtk.Button.new_with_label("Close")
            close_btn.connect("clicked", lambda _b: self.close_current_terminal())
            self._status = Gtk.Label(label="Terminal")
            self._status.set_xalign(0.0)
            self._status.set_hexpand(True)
            toolbar.pack_start(new_btn, False, False, 0)
            toolbar.pack_start(close_btn, False, False, 0)
            toolbar.pack_start(self._status, True, True, 0)
            self.pack_start(toolbar, False, False, 0)

            if Vte is None:
                # Soft-only fallback (AGENTS.md): visible hint, no raise.
                self._fallback = Gtk.Label(
                    label="Terminal unavailable: install gir1.2-vte-2.91, "
                          "then restart xed.")
                self._fallback.set_xalign(0.0)
                self.pack_start(self._fallback, True, True, 0)
                self.show_all()
                return

            self.notebook = Gtk.Notebook()
            self.notebook.set_scrollable(True)
            self.pack_start(self.notebook, True, True, 0)
            self.show_all()

        # -- tab management -------------------------------------------
        def current_labels(self) -> list[str]:
            return list(self._labels)

        def _tab_label_widget(self, label: str):
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            text = Gtk.Label(label=label)
            close = Gtk.Button.new_with_label("✕")
            close.set_relief(Gtk.ReliefStyle.NONE)
            close.set_focus_on_click(False)
            close.connect("clicked", lambda _b, w=box: self._close_by_tab_widget(w))
            box.pack_start(text, True, True, 0)
            box.pack_start(close, False, False, 0)
            box.show_all()
            return box, text

        def _set_tab_text(self, page_index: int, text: str) -> None:
            try:
                tab_widget = self.notebook.get_tab_label(
                    self.notebook.get_nth_page(page_index))
                for child in tab_widget.get_children():
                    if isinstance(child, Gtk.Label):
                        child.set_text(text)
                        break
            except Exception as e:
                _debug(f"tab label update failed: {e!r}")

        def new_terminal(self) -> None:
            if Vte is None or self.notebook is None:
                return
            label = unique_label(BASE_LABEL, self._labels)
            try:
                term = Vte.Terminal()
            except Exception as e:
                _debug(f"Vte.Terminal create failed: {e!r}")
                return
            try:
                term.set_scrollback_lines(10000)
            except Exception:
                pass
            try:
                term.set_mouse_autohide(True)
            except Exception:
                pass
            try:
                term.set_audible_bell(False)
            except Exception:
                pass
            try:
                term.set_cursor_blink_mode(Vte.CursorBlinkMode.ON)
            except Exception:
                pass
            try:
                term.set_font(Pango.FontDescription("Monospace 10"))
            except Exception:
                pass
            try:
                term.connect("child-exited", self._on_child_exited)
            except Exception:
                pass
            try:
                term.connect("button-press-event", self._on_button_press)
            except Exception:
                pass
            tab_widget, _text = self._tab_label_widget(label)
            try:
                page = self.notebook.append_page(term, tab_widget)
            except Exception as e:
                _debug(f"notebook append failed: {e!r}")
                return
            self._labels.append(label)
            self.show_all()
            try:
                self.notebook.set_current_page(page)
            except Exception:
                pass
            self._spawn(term, page)
            try:
                GLib.idle_add(term.grab_focus)
            except Exception:
                pass

        def _spawn(self, term, page: int) -> None:
            try:
                # working_directory=None inherits xed's cwd ("Always bash in cwd").
                ok, _pid = term.spawn_sync(
                    Vte.PtyFlags.DEFAULT,
                    None,
                    list(SHELL_ARGV),
                    None,
                    GLib.SpawnFlags.DEFAULT,
                    None,
                    None,
                    None,
                )
                if not ok:
                    raise RuntimeError("spawn_sync returned False")
            except Exception as e:
                _debug(f"terminal spawn failed: {e!r}")
                try:
                    self._set_tab_text(page, f"{self._labels[page]} (failed)")
                except Exception:
                    pass
                try:
                    sys.stderr.write(f"[tabbed-terminal] failed to launch "
                                     f"{' '.join(SHELL_ARGV)}: {e!r}\n")
                except Exception:
                    pass

        def _on_child_exited(self, term, _status) -> None:
            try:
                page = self.notebook.page_num(term)
            except Exception:
                return
            if page < 0:
                return
            try:
                old = self._labels[page]
                self._labels[page] = f"{old} (exited)"
                self._set_tab_text(page, self._labels[page])
            except Exception:
                pass
            # Respawn a fresh shell in place so the tab stays usable.
            self._spawn(term, page)
            try:
                old = self._labels[page]
                base = old.replace(" (exited)", "").replace(" (failed)", "")
                self._labels[page] = base
                self._set_tab_text(page, base)
            except Exception:
                pass

        def _on_button_press(self, term, event) -> bool:
            try:
                is_right = event.button == 3
            except Exception:
                return False
            if not is_right:
                return False
            try:
                menu = Gtk.Menu()
                copy_item = Gtk.MenuItem.new_with_label("Copy")
                copy_item.connect("activate", lambda _m: self._copy(term))
                paste_item = Gtk.MenuItem.new_with_label("Paste")
                paste_item.connect("activate", lambda _m: self._paste(term))
                new_item = Gtk.MenuItem.new_with_label("New Tab (Ctrl+Shift+T)")
                new_item.connect("activate", lambda _m: self.new_terminal())
                menu.append(copy_item)
                menu.append(paste_item)
                menu.append(Gtk.SeparatorMenuItem())
                menu.append(new_item)
                menu.show_all()
                menu.popup(None, None, None, None, event.button, event.time)
            except Exception as e:
                _debug(f"context menu failed: {e!r}")
            return True

        @staticmethod
        def _copy(term) -> None:
            try:
                term.copy_clipboard_format(Vte.Format.TEXT)
            except Exception as e:
                _debug(f"copy failed: {e!r}")

        @staticmethod
        def _paste(term) -> None:
            try:
                term.paste_clipboard()
            except Exception as e:
                _debug(f"paste failed: {e!r}")

        def _close_by_tab_widget(self, tab_widget) -> None:
            if self.notebook is None:
                return
            try:
                pages = self.notebook.get_n_pages()
                for i in range(pages):
                    if self.notebook.get_tab_label(self.notebook.get_nth_page(i)) is tab_widget:
                        self._close_page(i)
                        return
            except Exception as e:
                _debug(f"close by widget failed: {e!r}")

        def _close_page(self, page: int) -> None:
            if self.notebook is None:
                return
            try:
                term = self.notebook.get_nth_page(page)
            except Exception:
                return
            try:
                term.feed_child(b"exit\n", -1)
            except Exception:
                pass
            try:
                self.notebook.remove_page(page)
            except Exception as e:
                _debug(f"remove page failed: {e!r}")
                return
            try:
                del self._labels[page]
            except Exception:
                pass
            try:
                term.destroy()
            except Exception:
                pass
            if self.notebook.get_n_pages() == 0:
                self.new_terminal()

        def close_current_terminal(self) -> None:
            if self.notebook is None:
                return
            try:
                page = self.notebook.get_current_page()
            except Exception:
                return
            if page < 0:
                return
            self._close_page(page)

        def focus_current(self) -> None:
            if self.notebook is None:
                return
            try:
                page = self.notebook.get_current_page()
                term = self.notebook.get_nth_page(page if page >= 0 else 0)
            except Exception:
                return
            if term is None:
                return
            try:
                term.grab_focus()
            except Exception as e:
                _debug(f"grab focus failed: {e!r}")


class TabbedTerminalPlugin(GObject.Object, Xed.WindowActivatable):  # type: ignore[misc]
    __gtype_name__ = "XedTabbedTerminalPlugin"

    window = GObject.Property(type=Xed.Window)  # type: ignore[arg-type]

    def __init__(self) -> None:
        super().__init__()
        self.panel = None
        self._window_key_id = None

    def do_activate(self) -> None:
        if Gtk is None:
            return
        _debug("activate: tabbed-terminal starting up")
        try:
            self.panel = TerminalPanel()
        except Exception as e:
            _debug(f"panel create failed: {e!r}")
            try:
                sys.stderr.write(f"[tabbed-terminal] panel failed: {e!r}\n")
            except Exception:
                pass
            self.panel = None
            return
        bottom = self._safe(lambda: self.window.get_bottom_panel())
        if bottom is not None and self.panel is not None:
            added = False
            icon = _pick_icon(PANEL_ICONS)
            for attempt in (
                lambda: bottom.add_item(self.panel, PANEL_TITLE, icon),
                lambda: bottom.add(self.panel),
            ):
                try:
                    attempt()
                    added = True
                    break
                except Exception as e:
                    _debug(f"bottom panel add attempt failed: {e!r}")
                    continue
            if not added:
                _debug("bottom panel add failed")
        try:
            if getattr(self.panel, "notebook", None) is not None:
                self.panel.new_terminal()
        except Exception as e:
            _debug(f"initial terminal failed: {e!r}")
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
        if self.panel is not None:
            bottom = self._safe(lambda: self.window.get_bottom_panel())
            if bottom is not None:
                for attempt in (lambda: bottom.remove_item(self.panel), lambda: bottom.remove(self.panel)):
                    try:
                        attempt()
                        break
                    except Exception:
                        continue
            try:
                self.panel.destroy()
            except Exception:
                pass
        self.panel = None

    def do_update_state(self) -> None:
        return

    @staticmethod
    def _safe(fn):
        try:
            return fn()
        except Exception:
            return None

    # -- actions ------------------------------------------------------
    def _new_terminal(self) -> None:
        if self.panel is not None:
            try:
                self.panel.new_terminal()
            except Exception as e:
                _debug(f"new terminal failed: {e!r}")
        self._reveal(focus=True)

    def _close_current(self) -> None:
        if self.panel is not None:
            try:
                self.panel.close_current_terminal()
            except Exception as e:
                _debug(f"close terminal failed: {e!r}")

    def _reveal(self, focus: bool = False) -> None:
        bottom = self._safe(lambda: self.window.get_bottom_panel())
        if bottom is not None and self.panel is not None:
            try:
                visible = bottom.get_visible() if hasattr(bottom, "get_visible") else True
            except Exception:
                visible = True
            if not visible:
                if not self._set_pane_action("ViewBottomPane", True):
                    try:
                        bottom.set_visible(True)
                    except Exception as e:
                        _debug(f"bottom show failed: {e!r}")
            try:
                if hasattr(bottom, "activate_item"):
                    bottom.activate_item(self.panel)
            except Exception as e:
                _debug(f"panel activate failed: {e!r}")
        if focus and self.panel is not None:
            try:
                GLib.idle_add(self.panel.focus_current)
            except Exception:
                try:
                    self.panel.focus_current()
                except Exception as e:
                    _debug(f"focus failed: {e!r}")

    def _set_pane_action(self, name: str, visible: bool) -> bool:
        try:
            manager = self.window.get_ui_manager()
            if manager is None:
                return False
            groups = manager.get_action_groups() or []
        except Exception:
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
                except Exception:
                    return False
        return False

    def _handle_global_key(self, keyname: str, ctrl: bool, shift: bool, alt: bool) -> bool:
        action = handle_global_key(keyname, ctrl, shift, alt)
        if action == "new":
            _debug("key: Ctrl+Shift+T new-terminal")
            self._new_terminal()
            return True
        if action == "close":
            _debug("key: Ctrl+Shift+W close-terminal")
            self._close_current()
            return True
        if action == "focus":
            _debug("key: Ctrl+` focus-terminal")
            self._reveal(focus=True)
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
