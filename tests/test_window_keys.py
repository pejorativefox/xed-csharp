"""ViewTracker lifecycle (headless, real ViewTracker).

Window-level global shortcuts used to live here for the Ctrl+P fuzzy
finder; that finder now belongs to the fuzzy-finder plugin (see
tests/test_fuzzyfinder.py).
"""

import os
import sys

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


def test_view_handler_ignores_ctrl_p_without_doc():
    tracker = _tracker()
    if tracker is None:
        return
    from gi.repository import Gdk

    import types

    event = types.SimpleNamespace(
        state=int(Gdk.ModifierType.CONTROL_MASK),
        keyval=Gdk.keyval_from_name("p"),
    )
    # No C# doc here; must not emit anything.
    assert tracker._on_key_press(None, event, object()) is False


def test_attach_detach_tab_signals():
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
    for signal in ("tab-added", "tab-removed", "active-tab-changed", "active-tab-state-changed"):
        assert signal in connected
    tracker.detach()
    assert tracker._window is None
