"""Keybinds tab-switching shortcuts (headless)."""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins", "keybinds"))

import keybinds

HAVE_PLUGIN = hasattr(keybinds.KeybindsPlugin, "_step_tab")


class _FakeDoc:
    def __init__(self, location):
        self._location = location

    def get_location(self):
        return self._location

    def get_file(self):
        raise AttributeError("no file")


class _FakeWindow:
    def __init__(self, n):
        self.tabs = [object() for _ in range(n)]
        self.docs = [_FakeDoc(f"loc{i}") for i in range(n)]
        self._by_location = {f"loc{i}": self.tabs[i] for i in range(n)}
        self.active = self.tabs[0] if self.tabs else None
        self.activated = []

    def get_documents(self):
        return list(self.docs)

    def get_tab_from_location(self, location):
        return self._by_location[location]

    def get_active_tab(self):
        return self.active

    def set_active_tab(self, tab):
        self.activated.append(tab)
        self.active = tab


def _plugin_ns(n=3):
    window = _FakeWindow(n)
    cls = keybinds.KeybindsPlugin
    ns = types.SimpleNamespace(window=window)
    ns._doc_location = cls._doc_location
    for name in (
        "_step_tab",
        "_handle_global_key",
        "_on_window_key_press",
    ):
        setattr(ns, name, types.MethodType(getattr(cls, name), ns))
    return ns, window


def test_ctrl_page_down_advances():
    if not HAVE_PLUGIN:
        pytest.skip("plugin not available")
    ns, window = _plugin_ns()
    assert ns._handle_global_key("Page_Down", True, False, False) is True
    assert window.activated == [window.tabs[1]]


def test_ctrl_page_up_goes_back():
    if not HAVE_PLUGIN:
        pytest.skip("plugin not available")
    ns, window = _plugin_ns()
    window.active = window.tabs[1]
    assert ns._handle_global_key("Page_Up", True, False, False) is True
    assert window.activated == [window.tabs[0]]


def test_wraparound_last_to_first():
    if not HAVE_PLUGIN:
        pytest.skip("plugin not available")
    ns, window = _plugin_ns()
    window.active = window.tabs[2]
    assert ns._handle_global_key("Page_Down", True, False, False) is True
    assert window.activated == [window.tabs[0]]


def test_wraparound_first_to_last():
    if not HAVE_PLUGIN:
        pytest.skip("plugin not available")
    ns, window = _plugin_ns()
    assert ns._handle_global_key("Page_Up", True, False, False) is True
    assert window.activated == [window.tabs[2]]


def test_keypad_variants():
    if not HAVE_PLUGIN:
        pytest.skip("plugin not available")
    ns, window = _plugin_ns()
    assert ns._handle_global_key("KP_Page_Down", True, False, False) is True
    assert ns._handle_global_key("KP_Page_Up", True, False, False) is True
    assert window.activated == [window.tabs[1], window.tabs[0]]


def test_single_tab_noop():
    if not HAVE_PLUGIN:
        pytest.skip("plugin not available")
    ns, window = _plugin_ns(n=1)
    assert ns._handle_global_key("Page_Down", True, False, False) is True
    assert window.activated == []


def test_unknown_active_falls_back_to_first():
    if not HAVE_PLUGIN:
        pytest.skip("plugin not available")
    ns, window = _plugin_ns()
    window.active = object()
    assert ns._handle_global_key("Page_Down", True, False, False) is True
    assert window.activated == [window.tabs[1]]


def test_wrong_modifiers_ignored():
    if not HAVE_PLUGIN:
        pytest.skip("plugin not available")
    ns, window = _plugin_ns()
    assert ns._handle_global_key("Page_Down", True, True, False) is False
    assert ns._handle_global_key("Page_Down", True, False, True) is False
    assert ns._handle_global_key("Page_Down", False, False, False) is False
    assert ns._handle_global_key("Page_Up", True, True, False) is False
    assert window.activated == []


def test_other_keys_ignored():
    if not HAVE_PLUGIN:
        pytest.skip("plugin not available")
    ns, window = _plugin_ns()
    assert ns._handle_global_key("x", True, False, False) is False
    assert ns._handle_global_key("Tab", True, False, False) is False
    assert window.activated == []


def test_window_key_press_drives_handler():
    if not HAVE_PLUGIN:
        pytest.skip("plugin not available")
    try:
        import gi

        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk
    except Exception as e:
        pytest.skip(f"no Gdk ({e})")
    ns, window = _plugin_ns()
    event = types.SimpleNamespace(
        state=int(Gdk.ModifierType.CONTROL_MASK),
        keyval=Gdk.keyval_from_name("Page_Down"),
    )
    assert ns._on_window_key_press(None, event) is True
    assert window.activated == [window.tabs[1]]
