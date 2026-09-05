"""GtkSource framework completion provider tests.

Headless parts (cache/timeout bridge) run anywhere; Gtk parts need a
display and follow the same Xvfb-or-skip pattern as test_completion_popup.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xedcsharp import gscompletion as gs_mod
from xedcsharp import intelligence as intel


def _gui():
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("GtkSource", "4")
        from gi.repository import Gtk, GtkSource

        result = Gtk.init_check()
        ok = result[0] if isinstance(result, tuple) else bool(result)
        if not ok:
            return None
        return Gtk, GtkSource
    except Exception as e:
        print(f"SKIP gscompletion gui tests (no display: {e})")
        return None


_GUI = _gui()

_ITEMS_MSG = {
    "result": {
        "items": [
            {"label": "WriteLine", "detail": "void"},
            {"label": "Write", "detail": "void"},
        ]
    }
}


def _provider(send_request=None, ready=True, path="/tmp/A.cs"):
    if send_request is None:
        def send_request(method, params, callback):
            callback(dict(_ITEMS_MSG))
            return 1
    return gs_mod.RoslynCompletionProvider(
        is_ready=lambda: ready,
        resolve_path=lambda _buf: path,
        send_request=send_request,
    )


def test_import_without_gtksource_typelib():
    """Regression: module must load when GtkSource is missing.

    Previously the provider class statement inherited `object` twice in
    the fallback branch ("duplicate base class object" at import time).
    """
    import gi
    import importlib

    saved = sys.modules.pop("xedcsharp.gscompletion", None)
    original = gi.require_version

    def patched(namespace, version=None):
        if namespace == "GtkSource":
            raise ValueError("Namespace GtkSource not available")
        return original(namespace, version) if version else None

    gi.require_version = patched
    try:
        mod = importlib.import_module("xedcsharp.gscompletion")
        assert mod._AVAILABLE is False
        assert mod.RoslynProposal.__name__ == "RoslynProposal"
        assert mod.RoslynCompletionProvider.__name__ == "RoslynCompletionProvider"
    finally:
        gi.require_version = original
        sys.modules.pop("xedcsharp.gscompletion", None)
        if saved is not None:
            sys.modules["xedcsharp.gscompletion"] = saved


def test_word_start_offset():
    assert gs_mod.word_start_offset("Console.Wri", 11) == 8
    assert gs_mod.word_start_offset("Console.", 8) == 8
    assert gs_mod.word_start_offset("", 0) == 0
    assert gs_mod.word_start_offset("ab", 99) == 0


def test_fetch_sync_uses_cache():
    if not gs_mod._AVAILABLE:
        return
    calls = []

    def send_request(method, params, callback):
        calls.append(method)
        callback(dict(_ITEMS_MSG))
        return 7

    provider = _provider(send_request=send_request)
    first = provider.fetch_sync("/tmp/A.cs", 0, 11, "Console.Wri", 11, timeout=1.0)
    assert [i.label for i in first] == ["WriteLine", "Write"]
    second = provider.fetch_sync("/tmp/A.cs", 0, 11, "Console.Wri", 11, timeout=1.0)
    assert [i.label for i in second] == ["WriteLine", "Write"]
    assert calls == ["textDocument/completion"], calls  # second hit cache


def test_fetch_timeout_then_late_response_drained():
    if not gs_mod._AVAILABLE:
        return
    pending = []

    def send_request(method, params, callback):
        pending.append(callback)
        return 9

    provider = _provider(send_request=send_request)
    # Server too slow: returns stale (empty) cache without blocking.
    assert provider.fetch_sync("/tmp/A.cs", 0, 5, "Conso", 5, timeout=0.05) == []
    assert len(pending) == 1
    # Late arrival is stashed, not lost: next keystroke on the same line
    # picks it up with no new request.
    pending[0](dict(_ITEMS_MSG))
    got = provider.fetch_sync("/tmp/A.cs", 0, 6, "Consol", 6, timeout=0.05)
    assert [i.label for i in got] == ["WriteLine", "Write"]
    assert len(pending) == 1, pending


def test_fetch_no_transport_returns_cache():
    if not gs_mod._AVAILABLE:
        return
    provider = _provider(send_request=lambda _m, _p, _c: None)
    assert provider.fetch_sync("/tmp/A.cs", 0, 3, "Con", 3, timeout=0.1) == []


def test_proposal_carries_insert_text():
    if _GUI is None:
        return
    Gtk, GtkSource = _GUI
    item = gs_mod.RoslynProposal(label="WriteLine", insert_text="WriteLine()", info="void")
    assert item.get_label() == "WriteLine"
    assert item.insert_text == "WriteLine()"
    assert item.get_info() == "void"


def test_start_iter_and_activate_on_real_buffer():
    if _GUI is None:
        return
    Gtk, GtkSource = _GUI
    provider = _provider()
    buf = GtkSource.Buffer()
    buf.set_text("Console.Wri")
    end = buf.get_end_iter()
    start = end.copy()
    assert provider.do_get_start_iter(None, None, start) is True
    assert start.get_offset() == 8
    assert buf.get_text(start, end, True) == "Wri"
    proposal = gs_mod.RoslynProposal(label="WriteLine", insert_text="WriteLine")
    assert provider.do_activate_proposal(proposal, buf.get_end_iter()) is True
    assert buf.get_text(*buf.get_bounds(), True) == "Console.WriteLine"


def test_match_gates_non_csharp():
    if _GUI is None:
        return
    Gtk, GtkSource = _GUI
    win = Gtk.Window()
    buf = GtkSource.Buffer()
    view = GtkSource.View.new_with_buffer(buf)
    win.add(view)
    win.show_all()
    while Gtk.events_pending():
        Gtk.main_iteration()
    try:
        buf.set_text("Wri")
        provider = _provider(path="/tmp/A.cs")
        ctx = view.get_completion().create_context(buf.get_end_iter())
        assert provider.do_match(ctx) is True
        other = _provider(path=None)
        assert other.do_match(ctx) is False
        not_ready = _provider(path="/tmp/A.cs", ready=False)
        assert not_ready.do_match(ctx) is False
    finally:
        win.destroy()


def test_attach_detach_view():
    if _GUI is None:
        return
    Gtk, GtkSource = _GUI
    win = Gtk.Window()
    view = GtkSource.View.new_with_buffer(GtkSource.Buffer())
    win.add(view)
    win.show_all()
    while Gtk.events_pending():
        Gtk.main_iteration()
    try:
        import types

        provider = _provider()
        attached: set = set()
        # Plain Gtk.Window lacks Xed's get_views(); emulate an xed window.
        fake_window = types.SimpleNamespace(get_views=lambda: [view])
        before = len(view.get_completion().get_providers())
        assert gs_mod.attach_to_views(fake_window, provider, attached) == 1
        assert len(view.get_completion().get_providers()) == before + 1
        # Idempotent: second pass attaches nothing new.
        assert gs_mod.attach_to_views(fake_window, provider, attached) == 0
        gs_mod.detach_from_views(fake_window, provider, attached)
        assert len(view.get_completion().get_providers()) == before
        assert attached == set()
    finally:
        win.destroy()
