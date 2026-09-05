"""Window-level global shortcuts (headless, real ViewTracker)."""

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins", "xedcsharp"))


def _tracker():
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
    except Exception as e:
        print(f"SKIP window key tests ({e})")
        return None
    from xedcsharp.views import ViewTracker

    return ViewTracker()


def _collect(tracker):
    fired: list = []
    for signal in ("hide-panels", "toggle-bottom-panel", "toggle-side-panel",
                   "fuzzy-finder", "open-folder"):
        tracker.connect(signal, lambda _w, s=signal: fired.append(s))
    return fired


def test_global_keys_emit():
    tracker = _tracker()
    if tracker is None:
        return
    fired = _collect(tracker)
    assert tracker._handle_global_key("b", True, False, False) is True
    assert tracker._handle_global_key("j", True, False, False) is True
    assert tracker._handle_global_key("e", True, False, False) is True
    assert tracker._handle_global_key("p", True, False, False) is True
    assert tracker._handle_global_key("o", True, True, False) is True
    assert fired == ["hide-panels", "toggle-bottom-panel", "toggle-side-panel",
                     "fuzzy-finder", "open-folder"]


def test_global_keys_reject_modifiers_and_plain():
    tracker = _tracker()
    if tracker is None:
        return
    fired = _collect(tracker)
    assert tracker._handle_global_key("b", False, False, False) is False
    assert tracker._handle_global_key("b", True, True, False) is False
    assert tracker._handle_global_key("b", True, False, True) is False
    assert tracker._handle_global_key("x", True, False, False) is False
    assert fired == []


def test_window_key_press_drives_globals():
    tracker = _tracker()
    if tracker is None:
        return
    from gi.repository import Gdk

    fired = _collect(tracker)
    event = types.SimpleNamespace(
        state=int(Gdk.ModifierType.CONTROL_MASK),
        keyval=Gdk.keyval_from_name("b"),
    )
    assert tracker._on_window_key_press(None, event) is True
    assert fired == ["hide-panels"]


def test_view_handler_ignores_globals():
    tracker = _tracker()
    if tracker is None:
        return
    from gi.repository import Gdk

    fired = _collect(tracker)
    event = types.SimpleNamespace(
        state=int(Gdk.ModifierType.CONTROL_MASK),
        keyval=Gdk.keyval_from_name("b"),
    )
    # No C# doc here; must not emit (window level owns these now).
    assert tracker._on_key_press(None, event, object()) is False
    assert fired == []


def test_attach_detach_window_keys():
    tracker = _tracker()
    if tracker is None:
        return
    connected: dict = {}
    disconnected: list = []

    class _Window:
        def get_views(self):
            return []

        def connect(self, signal, handler):
            connected[signal] = handler
            return len(connected)

        def disconnect(self, handler_id):
            disconnected.append(handler_id)

    window = _Window()
    tracker.attach(window)
    assert "key-press-event" in connected
    key_id = tracker._window_key_id
    assert key_id is not None
    tracker.detach()
    assert key_id in disconnected
    assert tracker._window_key_id is None
