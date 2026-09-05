"""Pane visibility toggles (headless, fake Gio.Settings)."""

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins", "xedcsharp"))

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
    for name in ("_panel_widget", "_pane_visible", "_panes_settings", "_set_panes",
                 "_set_pane_action", "_pane_geometry", "_fix_pane_size",
                 "_ensure_pane_size", "_toggle_pane", "_hide_all_panels",
                 "_toggle_bottom_panel", "_toggle_side_panel"):
        setattr(ns, name, types.MethodType(getattr(cls, name), ns))
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


class _FakeAction:
    def __init__(self, active=True):
        self._active = active
        self.sets: list = []

    def get_active(self):
        return self._active

    def set_active(self, value):
        self.sets.append(bool(value))
        self._active = bool(value)


def _ns_with_actions(actions):
    cls = xedcsharp.CSharpDevKitPlugin
    manager = types.SimpleNamespace(
        get_action_groups=lambda: [
            types.SimpleNamespace(get_action=lambda name: actions.get(name))
        ]
    )
    ns = _plugin_ns()
    ns.window = types.SimpleNamespace(get_ui_manager=lambda: manager)
    return ns


def test_toggle_prefers_menu_action():
    if not HAVE_PLUGIN:
        return
    action = _FakeAction(active=True)
    ns = _ns_with_actions({"ViewBottomPane": action})
    fake = _FakeSettings()
    saved = xedcsharp.Gio
    xedcsharp.Gio = types.SimpleNamespace(
        Settings=types.SimpleNamespace(new=lambda _schema: fake)
    )
    try:
        xedcsharp.CSharpDevKitPlugin._toggle_bottom_panel(ns)
    finally:
        xedcsharp.Gio = saved
    assert action.sets == [False]
    assert fake.calls == []


def test_hide_all_drives_both_actions():
    if not HAVE_PLUGIN:
        return
    side = _FakeAction(active=True)
    bottom = _FakeAction(active=True)
    ns = _ns_with_actions({"ViewSidePane": side, "ViewBottomPane": bottom})
    xedcsharp.CSharpDevKitPlugin._hide_all_panels(ns)
    assert side.sets == [False]
    assert bottom.sets == [False]


def test_missing_action_falls_back():
    if not HAVE_PLUGIN:
        return
    ns = _plugin_ns()
    ns.window = types.SimpleNamespace(get_ui_manager=lambda: None)

    def _call(ns):
        xedcsharp.CSharpDevKitPlugin._toggle_side_panel(ns)

    fake = _run_with_fake_gio(_call)
    assert fake.calls == [("side-panel-visible", False)]


class _FakePaned:
    def __init__(self, position, max_position=1000, child1=None, child2=None):
        self._position = position
        self._max = max_position
        self._child1 = child1
        self._child2 = child2
        self.sets: list = []

    def get_position(self):
        return self._position

    def set_position(self, value):
        self.sets.append(value)
        self._position = value

    def get_property(self, name):
        assert name == "max-position"
        return self._max

    def get_child1(self):
        return self._child1

    def get_child2(self):
        return self._child2

    def get_allocation(self):
        return types.SimpleNamespace(width=800, height=600)


def _ns_with_paned(widget, paned, saved_size=287):
    ns = _plugin_ns()
    widget.get_parent = lambda: paned
    if paned._child1 is None and paned._child2 is None:
        paned._child2 = widget
    ns.window = types.SimpleNamespace(get_bottom_panel=lambda: widget)
    state = types.SimpleNamespace(get_int=lambda _k: saved_size)
    saved = xedcsharp.Gio
    xedcsharp.Gio = types.SimpleNamespace(
        Settings=types.SimpleNamespace(new=lambda _s: state)
    )
    return ns, saved


def test_bottom_collapsed_at_max_restores():
    if not HAVE_PLUGIN:
        return
    widget = _FakeWidget(visible=True, effective=True)
    paned = _FakePaned(2147483647, max_position=2147483647, child2=widget)
    ns, saved = _ns_with_paned(widget, paned)
    try:
        assert ns._fix_pane_size("bottom") is True
    finally:
        xedcsharp.Gio = saved
    assert paned.sets == [2147483647 - 287]


def test_bottom_at_zero_restores():
    if not HAVE_PLUGIN:
        return
    widget = _FakeWidget(visible=True, effective=True)
    paned = _FakePaned(0, max_position=1000, child2=widget)
    ns, saved = _ns_with_paned(widget, paned)
    try:
        assert ns._fix_pane_size("bottom") is True
    finally:
        xedcsharp.Gio = saved
    assert paned.sets == [713]


def test_sane_pane_size_untouched():
    if not HAVE_PLUGIN:
        return
    widget = _FakeWidget(visible=True, effective=True)
    paned = _FakePaned(500, max_position=1000, child2=widget)
    ns, saved = _ns_with_paned(widget, paned)
    try:
        assert ns._fix_pane_size("bottom") is False
    finally:
        xedcsharp.Gio = saved
    assert paned.sets == []


def test_side_collapsed_at_zero_restores():
    if not HAVE_PLUGIN:
        return
    widget = _FakeWidget(visible=True, effective=True)
    paned = _FakePaned(0, max_position=900, child1=widget)
    ns = _plugin_ns()
    widget.get_parent = lambda: paned
    ns.window = types.SimpleNamespace(get_side_panel=lambda: widget)
    state = types.SimpleNamespace(get_int=lambda _k: 265)
    saved = xedcsharp.Gio
    xedcsharp.Gio = types.SimpleNamespace(
        Settings=types.SimpleNamespace(new=lambda _s: state)
    )
    try:
        assert ns._fix_pane_size("side") is True
    finally:
        xedcsharp.Gio = saved
    assert paned.sets == [265]


class _FakeWidget:
    def __init__(self, visible=True, effective=None):
        self._visible = visible
        self._effective = visible if effective is None else effective
        self.calls: list = []

    def get_visible(self):
        return self._visible

    def is_visible(self):
        return self._effective

    def set_visible(self, value):
        self.calls.append(bool(value))
        self._visible = bool(value)
        self._effective = bool(value)


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


def test_toggle_reads_effective_visibility():
    # Startup-hidden pane: own flag True, ancestor hidden. First toggle
    # must show, not silently "hide" the already-hidden pane.
    if not HAVE_PLUGIN:
        return
    cls = xedcsharp.CSharpDevKitPlugin
    bottom = _FakeWidget(visible=True, effective=False)
    window = types.SimpleNamespace(
        get_side_panel=lambda: (_ for _ in ()).throw(AssertionError("unused")),
        get_bottom_panel=lambda: bottom,
    )
    ns = _plugin_ns()
    ns.window = window
    fake = _FakeSettings()
    saved = xedcsharp.Gio
    xedcsharp.Gio = types.SimpleNamespace(
        Settings=types.SimpleNamespace(new=lambda _schema: fake)
    )
    try:
        xedcsharp.CSharpDevKitPlugin._toggle_bottom_panel(ns)
    finally:
        xedcsharp.Gio = saved
    assert bottom.calls == [True]
    assert fake.calls == [("bottom-panel-visible", True)]
