"""Pane visibility toggles (headless, fake Gio.Settings)."""

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import xedcsharp

HAVE_PLUGIN = hasattr(xedcsharp.CSharpDevKitPlugin, "_hide_all_panels")


class _FakeSettings:
    def __init__(self):
        self.state = {"side-panel-visible": True, "bottom-panel-visible": True}
        self.calls: list = []

    def set_boolean(self, key, value):
        self.calls.append((key, value))
        self.state[key] = value

    def get_boolean(self, key):
        return self.state[key]


def _plugin_ns():
    cls = xedcsharp.CSharpDevKitPlugin
    ns = types.SimpleNamespace(PANES_SCHEMA=cls.PANES_SCHEMA)
    ns._safe = cls._safe
    ns._panel_widget = types.MethodType(cls._panel_widget, ns)
    ns._pane_visible = types.MethodType(cls._pane_visible, ns)
    ns._panes_settings = types.MethodType(cls._panes_settings, ns)
    ns._set_panes = types.MethodType(cls._set_panes, ns)
    return ns


def _run_with_fake_gio(fn):
    fake = _FakeSettings()
    saved = xedcsharp.Gio
    xedcsharp.Gio = types.SimpleNamespace(
        Settings=types.SimpleNamespace(new=lambda _schema: fake)
    )
    try:
        fn(_plugin_ns())
    finally:
        xedcsharp.Gio = saved
    return fake


def test_hide_all_panels_sets_both_false():
    if not HAVE_PLUGIN:
        return

    def _call(ns):
        xedcsharp.CSharpDevKitPlugin._hide_all_panels(ns)

    fake = _run_with_fake_gio(_call)
    assert ("side-panel-visible", False) in fake.calls
    assert ("bottom-panel-visible", False) in fake.calls


def test_toggle_bottom_flips_current_state():
    if not HAVE_PLUGIN:
        return
    fake = _FakeSettings()
    saved = xedcsharp.Gio
    xedcsharp.Gio = types.SimpleNamespace(
        Settings=types.SimpleNamespace(new=lambda _schema: fake)
    )
    try:
        ns = _plugin_ns()
        xedcsharp.CSharpDevKitPlugin._toggle_bottom_panel(ns)
        xedcsharp.CSharpDevKitPlugin._toggle_bottom_panel(ns)
    finally:
        xedcsharp.Gio = saved
    assert fake.calls == [
        ("bottom-panel-visible", False),
        ("bottom-panel-visible", True),
    ]


def test_toggle_side_only_touches_side():
    if not HAVE_PLUGIN:
        return

    def _call(ns):
        xedcsharp.CSharpDevKitPlugin._toggle_side_panel(ns)

    fake = _run_with_fake_gio(_call)
    assert fake.calls == [("side-panel-visible", False)]


class _FakeWidget:
    def __init__(self, visible=True):
        self._visible = visible
        self.calls: list = []

    def get_visible(self):
        return self._visible

    def set_visible(self, value):
        self.calls.append(bool(value))
        self._visible = bool(value)


def test_set_panes_updates_widget_live_and_persists():
    if not HAVE_PLUGIN:
        return
    cls = xedcsharp.CSharpDevKitPlugin
    side = _FakeWidget(visible=True)
    bottom = _FakeWidget(visible=True)
    window = types.SimpleNamespace(
        get_side_panel=lambda: side,
        get_bottom_panel=lambda: bottom,
    )

    ns = _plugin_ns()
    ns.window = window
    ns._hide_all_panels = types.MethodType(cls._hide_all_panels, ns)
    fake = _FakeSettings()
    saved = xedcsharp.Gio
    xedcsharp.Gio = types.SimpleNamespace(
        Settings=types.SimpleNamespace(new=lambda _schema: fake)
    )
    try:
        assert ns._pane_visible("side") is True
        ns._hide_all_panels()
    finally:
        xedcsharp.Gio = saved
    assert side.calls == [False]
    assert bottom.calls == [False]
    assert ("side-panel-visible", False) in fake.calls
    assert ("bottom-panel-visible", False) in fake.calls
