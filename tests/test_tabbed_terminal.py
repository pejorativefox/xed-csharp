"""tabbed-terminal plugin behavior (headless)."""

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins", "tabbed-terminal"))

import tabbedterminal


def test_shell_is_fixed_bash():
    assert tabbedterminal.SHELL_ARGV == ["/bin/bash"]
    assert tabbedterminal.PANEL_TITLE == "Terminal"


def test_unique_label_first_free():
    assert tabbedterminal.unique_label("Terminal", []) == "Terminal"
    assert tabbedterminal.unique_label("Terminal", ["Terminal"]) == "Terminal 2"
    assert tabbedterminal.unique_label("Terminal", ["Terminal", "Terminal 2"]) == "Terminal 3"
    # gap fill
    assert tabbedterminal.unique_label("Terminal", ["Terminal", "Terminal 3"]) == "Terminal 2"


def test_unique_label_accepts_set_and_tuple():
    assert tabbedterminal.unique_label("Terminal", {"Terminal"}) == "Terminal 2"
    assert tabbedterminal.unique_label("Terminal", ("Terminal",)) == "Terminal 2"


def test_keybinding_new_close():
    assert tabbedterminal.handle_global_key("t", True, True, False) == "new"
    assert tabbedterminal.handle_global_key("T", True, True, False) == "new"
    assert tabbedterminal.handle_global_key("w", True, True, False) == "close"
    assert tabbedterminal.handle_global_key("W", True, True, False) == "close"


def test_keybinding_focus_backtick():
    for name in ("grave", "quoteleft", "`"):
        assert tabbedterminal.handle_global_key(name, True, False, False) == "focus", name


def test_keybinding_rejects_wrong_modifiers():
    assert tabbedterminal.handle_global_key("t", False, True, False) is None
    assert tabbedterminal.handle_global_key("t", True, False, False) is None
    assert tabbedterminal.handle_global_key("t", True, True, True) is None
    assert tabbedterminal.handle_global_key("w", True, False, False) is None
    assert tabbedterminal.handle_global_key("grave", False, False, False) is None
    assert tabbedterminal.handle_global_key("grave", True, True, False) is None
    assert tabbedterminal.handle_global_key("x", True, True, False) is None
    assert tabbedterminal.handle_global_key("", True, True, False) is None


def _plugin_ns():
    cls = tabbedterminal.TabbedTerminalPlugin
    ns = types.SimpleNamespace()
    for name in ("_new_terminal", "_close_current", "_reveal", "_handle_global_key"):
        setattr(ns, name, types.MethodType(getattr(cls, name), ns))
    return ns


def test_plugin_dispatches_new_close_focus():
    ns = _plugin_ns()
    called = []
    ns.panel = types.SimpleNamespace(
        new_terminal=lambda: called.append("new"),
        close_current_terminal=lambda: called.append("close"),
        focus_current=lambda: called.append("focus"),
    )
    ns._reveal = lambda focus=False: called.append(f"reveal:{focus}")
    assert ns._handle_global_key("t", True, True, False) is True
    assert ns._handle_global_key("w", True, True, False) is True
    assert ns._handle_global_key("grave", True, False, False) is True
    assert ns._handle_global_key("x", True, False, False) is False
    assert called == ["new", "reveal:True", "close", "reveal:True"]


def test_reveal_activates_panel_and_focuses():
    if tabbedterminal.Gtk is None:
        print("SKIP reveal test (no Gtk)")
        return
    cls = tabbedterminal.TabbedTerminalPlugin
    activated = []
    bottom = types.SimpleNamespace(
        get_visible=lambda: True,
        activate_item=lambda item: activated.append(item),
        set_visible=lambda v: (_ for _ in ()).throw(AssertionError("should stay visible")),
    )
    focused = []
    ns = types.SimpleNamespace(
        panel=types.SimpleNamespace(focus_current=lambda: focused.append(True)),
        window=types.SimpleNamespace(get_bottom_panel=lambda: bottom),
    )
    ns._safe = staticmethod(cls._safe)
    ns._set_pane_action = lambda *a: True
    saved = tabbedterminal.GLib
    tabbedterminal.GLib = types.SimpleNamespace(idle_add=lambda fn, *a: fn(*a))
    try:
        types.MethodType(cls._reveal, ns)(focus=True)
    finally:
        tabbedterminal.GLib = saved
    assert activated == [ns.panel]
    assert focused == [True]


def test_window_key_press_drives_handler():
    if tabbedterminal.Gtk is None or tabbedterminal.Gdk is None:
        print("SKIP tabbed-terminal key test (no Gtk/Gdk)")
        return
    from gi.repository import Gdk

    ns = _plugin_ns()
    called = []
    ns._handle_global_key = lambda *args: (called.append(tuple(args)), True)[1]
    event = types.SimpleNamespace(
        state=int(Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK),
        keyval=Gdk.keyval_from_name("t"),
    )
    cls = tabbedterminal.TabbedTerminalPlugin
    assert types.MethodType(cls._on_window_key_press, ns)(None, event) is True
    assert called and called[0][0] == "t"
