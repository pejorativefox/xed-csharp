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

SCHEME_SETTINGS_SCHEMA = "org.x.editor.preferences.editor"
SCHEME_SETTINGS_KEY = "scheme"
ATOM_SCHEME_ID = "atom-one-dark"

#: Hardcoded Atom One Dark terminal theme. Mirrors styles/atom-one-dark.xml
#: (bg/fg/cursor/selection + red/green/yellow/blue/purple/cyan/comment/white).
#: Used when GtkSource is unavailable and as a test oracle for the XML file.
ATOM_ONE_DARK = {
    "fg": "#ABB2BF",
    "bg": "#282C34",
    "cursor": "#528BFF",
    "highlight": "#3E4451",
    # 16 ANSI entries: 0-7 normal, 8-15 bright.
    "palette": [
        "#282C34",  # 0 black (bg)
        "#E06C75",  # 1 red
        "#98C379",  # 2 green
        "#E5C07B",  # 3 yellow
        "#61AFEF",  # 4 blue
        "#C678DD",  # 5 magenta (purple)
        "#56B6C2",  # 6 cyan
        "#ABB2BF",  # 7 white (fg)
        "#5C6370",  # 8 bright black (comment)
        "#E06C75",  # 9 bright red
        "#98C379",  # 10 bright green
        "#E5C07B",  # 11 bright yellow
        "#61AFEF",  # 12 bright blue
        "#C678DD",  # 13 bright magenta
        "#56B6C2",  # 14 bright cyan
        "#DCDFE4",  # 15 bright white
    ],
}

#: Scheme style names mapped to terminal roles. Tuples are tried in order
#: (foreground unless noted). "orange" (def:number) has no ANSI slot and is
#: intentionally unused. Pure data, headless-safe.
SCHEME_STYLE_MAP = {
    "fg": (("text", "foreground"),),
    "bg": (("text", "background"),),
    "cursor": (("cursor", "foreground"),),
    "selection": (("selection", "background"),),
    "gray": (("def:comment", "foreground"),),
    "red": (
        ("def:preprocessor", "foreground"),
        ("def:identifier", "foreground"),
        ("def:error", "background"),
    ),
    "green": (("def:string", "foreground"),),
    "yellow": (("def:type", "foreground"),),
    "blue": (("def:function", "foreground"),),
    "magenta": (("def:keyword", "foreground"),),
    "cyan": (("def:operator", "foreground"),),
    "white": (("def:error", "foreground"),),
}


def atom_one_dark_theme() -> dict:
    """Atom One Dark VTE theme (fresh dict each call, headless-safe)."""
    return {
        "fg": ATOM_ONE_DARK["fg"],
        "bg": ATOM_ONE_DARK["bg"],
        "cursor": ATOM_ONE_DARK["cursor"],
        "highlight": ATOM_ONE_DARK["highlight"],
        "palette": list(ATOM_ONE_DARK["palette"]),
    }


def palette_from_scheme_colors(colors: dict) -> list[str]:
    """Build a complete 16-entry ANSI palette from semantic scheme colors.

    Missing entries fall back to fg/bg so the result is always complete.
    Keys: bg, fg, red, green, yellow, blue, magenta, cyan, gray, white.
    Pure logic, headless-safe.
    """
    fg = colors.get("fg") or "#FFFFFF"
    bg = colors.get("bg") or "#000000"
    red = colors.get("red") or fg
    green = colors.get("green") or fg
    yellow = colors.get("yellow") or fg
    blue = colors.get("blue") or fg
    magenta = colors.get("magenta") or fg
    cyan = colors.get("cyan") or fg
    gray = colors.get("gray") or fg
    white = colors.get("white") or fg
    return [
        bg, red, green, yellow, blue, magenta, cyan, fg,
        gray, red, green, yellow, blue, magenta, cyan, white,
    ]


def build_vte_theme(colors: dict | None) -> dict | None:
    """Full VTE theme from extracted scheme colors, or None to keep defaults.

    Returns None when the scheme defines no text fg/bg (e.g. tango/xed
    inherit the GTK theme, which VTE already follows). Pure, headless-safe.
    """
    if not colors:
        return None
    fg = colors.get("fg")
    bg = colors.get("bg")
    if not fg and not bg:
        return None
    fg = fg or "#FFFFFF"
    bg = bg or "#000000"
    gray = colors.get("gray") or fg
    merged = dict(colors)
    merged["fg"] = fg
    merged["bg"] = bg
    return {
        "fg": fg,
        "bg": bg,
        "cursor": colors.get("cursor") or fg,
        "highlight": colors.get("selection") or gray,
        "palette": palette_from_scheme_colors(merged),
    }

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
        gi.require_version("GtkSource", "4")
        from gi.repository import GtkSource  # type: ignore
    except Exception:
        try:
            gi.require_version("GtkSource", "3.0")
            from gi.repository import GtkSource  # type: ignore
        except Exception:
            GtkSource = None  # type: ignore

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
    Gtk = Gio = Gdk = GLib = Pango = Vte = GtkSource = None  # type: ignore[no-redef]


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


def _rgba_to_hex(rgba) -> str | None:
    """Gdk.RGBA (or "#rrggbb" string) -> "#RRGGBB". None when unusable."""
    try:
        if isinstance(rgba, str):
            text = rgba.strip()
            if len(text) == 7 and text.startswith("#"):
                int(text[1:], 16)
                return text.upper()
            return None
        red = int(round(float(rgba.red) * 255))
        green = int(round(float(rgba.green) * 255))
        blue = int(round(float(rgba.blue) * 255))
        clamp = lambda v: max(0, min(255, v))
        return f"#{clamp(red):02X}{clamp(green):02X}{clamp(blue):02X}"
    except Exception:
        return None


def current_scheme_id() -> str | None:
    """xed's current editor color-scheme id (GSettings), or None if unknown."""
    if Gio is None:
        return None
    try:
        settings = Gio.Settings.new(SCHEME_SETTINGS_SCHEMA)
        scheme_id = settings.get_string(SCHEME_SETTINGS_KEY)
    except Exception as e:
        _debug(f"editor scheme lookup failed: {e!r}")
        return None
    scheme_id = (scheme_id or "").strip()
    return scheme_id or None


def extract_scheme_colors(scheme_id: str):
    """Semantic hex colors for a GtkSource style-scheme id.

    Returns a dict of role -> "#RRGGBB" (missing roles omitted) or None
    when GtkSource is unavailable or the scheme cannot be found.
    """
    if GtkSource is None:
        return None
    wanted = (scheme_id or "").strip()
    if not wanted:
        return None
    try:
        manager = GtkSource.StyleSchemeManager.get_default()
    except Exception as e:
        _debug(f"scheme manager unavailable: {e!r}")
        return None
    # xed ships its own styles dir (install.sh); make sure the in-process
    # manager sees it even if xed hasn't appended it yet.
    try:
        seen = list(manager.get_search_path() or [])
        styledir = os.environ.get("XED_STYLE_DIR") or os.path.expanduser(
            "~/.local/share/xed/styles")
        if styledir and styledir not in seen and os.path.isdir(styledir):
            try:
                manager.append_search_path(styledir)
            except Exception:
                pass
    except Exception:
        pass
    try:
        scheme = manager.get_scheme(wanted)
    except Exception as e:
        _debug(f"scheme lookup failed for {wanted!r}: {e!r}")
        return None
    if scheme is None:
        _debug(f"scheme not found: {wanted!r}")
        return None

    def _lookup(style_name: str, kind: str) -> str | None:
        try:
            style = scheme.get_style(style_name)
        except Exception:
            return None
        if style is None:
            return None
        try:
            is_set = style.get_property(f"{kind}-set")
        except Exception:
            is_set = True
        if not is_set:
            return None
        try:
            rgba = style.get_property(kind)
        except Exception:
            return None
        return _rgba_to_hex(rgba)

    colors: dict[str, str] = {}
    for role, candidates in SCHEME_STYLE_MAP.items():
        for style_name, kind in candidates:
            found = _lookup(style_name, kind)
            if found:
                colors[role] = found
                break
    return colors


def current_editor_theme() -> dict | None:
    """VTE theme dict for xed's current scheme, or None to keep VTE defaults.

    Falls back to the hardcoded Atom One Dark theme when the active scheme
    is atom-one-dark but its XML cannot be read (e.g. no GtkSource).
    """
    try:
        scheme_id = current_scheme_id()
    except Exception:
        return None
    if not scheme_id:
        return None
    if scheme_id == ATOM_SCHEME_ID and GtkSource is None:
        return atom_one_dark_theme()
    try:
        colors = extract_scheme_colors(scheme_id)
    except Exception as e:
        _debug(f"scheme color extraction failed: {e!r}")
        colors = None
    if not colors:
        if scheme_id == ATOM_SCHEME_ID:
            return atom_one_dark_theme()
        return None
    return build_vte_theme(colors)


def apply_theme_to_terminal(term, theme: dict | None) -> bool:
    """Apply a VTE theme dict to a Vte.Terminal. Soft-only, never raises."""
    if Gdk is None or term is None or not theme:
        return False
    try:
        palette_hex = theme.get("palette") or []
        if len(palette_hex) != 16:
            return False

        def _parse(value):
            rgba = Gdk.RGBA()
            if not rgba.parse(str(value)):
                raise ValueError(f"unparsable color: {value!r}")
            return rgba

        term.set_colors(_parse(theme["fg"]), _parse(theme["bg"]),
                        [_parse(entry) for entry in palette_hex])
    except Exception as e:
        _debug(f"terminal palette apply failed: {e!r}")
        return False
    for key, method in (("cursor", "set_color_cursor"),
                        ("highlight", "set_color_highlight")):
        try:
            rgba = Gdk.RGBA()
            if rgba.parse(str(theme[key])):
                getattr(term, method)(rgba)
        except Exception as e:
            _debug(f"terminal {key} apply failed: {e!r}")
    return True


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
                self.apply_theme_to_term(term)
            except Exception as e:
                _debug(f"terminal theme failed: {e!r}")
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

        # -- editor-following theme -----------------------------------
        def apply_theme_to_term(self, term) -> bool:
            """Tint one terminal with xed's current scheme. Never raises."""
            try:
                theme = current_editor_theme()
            except Exception as e:
                _debug(f"editor theme lookup failed: {e!r}")
                return False
            if theme is None:
                return False
            return apply_theme_to_terminal(term, theme)

        def apply_editor_theme(self) -> None:
            """Re-tint every open terminal (called on scheme switches)."""
            if self.notebook is None:
                return
            try:
                theme = current_editor_theme()
            except Exception as e:
                _debug(f"editor theme lookup failed: {e!r}")
                return
            if theme is None:
                return
            try:
                pages = self.notebook.get_n_pages()
            except Exception:
                return
            for page in range(pages):
                try:
                    term = self.notebook.get_nth_page(page)
                except Exception:
                    continue
                apply_theme_to_terminal(term, theme)


class TabbedTerminalPlugin(GObject.Object, Xed.WindowActivatable):  # type: ignore[misc]
    __gtype_name__ = "XedTabbedTerminalPlugin"

    window = GObject.Property(type=Xed.Window)  # type: ignore[arg-type]

    def __init__(self) -> None:
        super().__init__()
        self.panel = None
        self._window_key_id = None
        self._scheme_settings = None
        self._scheme_changed_id = None

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
        # Live "follow the editor": re-tint open terminals on scheme switches.
        try:
            if Gio is not None:
                settings = Gio.Settings.new(SCHEME_SETTINGS_SCHEMA)
                self._scheme_settings = settings
                self._scheme_changed_id = settings.connect(
                    f"changed::{SCHEME_SETTINGS_KEY}",
                    lambda *args: self._apply_editor_theme(),
                )
        except Exception as e:
            _debug(f"scheme watch failed: {e!r}")
            self._scheme_settings = None
            self._scheme_changed_id = None

    def _apply_editor_theme(self) -> None:
        if self.panel is not None:
            try:
                self.panel.apply_editor_theme()
            except Exception as e:
                _debug(f"scheme re-tint failed: {e!r}")

    def do_deactivate(self) -> None:
        if self._window_key_id is not None:
            try:
                self.window.disconnect(self._window_key_id)
            except Exception:
                pass
        self._window_key_id = None
        if self._scheme_changed_id is not None:
            try:
                self._scheme_settings.disconnect(self._scheme_changed_id)
            except Exception:
                pass
        self._scheme_changed_id = None
        self._scheme_settings = None
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
