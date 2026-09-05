"""GI arity guard: every Xed method the plugin calls, checked against the
real typelib when present.

Regression test for the create_tab_from_location 6-vs-7-args bug, which only
surfaced inside xed. Skips cleanly on machines without xed installed.
"""

import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# NOTE: importing the package also runs _ensure_xed_gi_paths(), which
# registers xed's private typelib dir when present.
try:
    from xedcsharp import _ensure_xed_gi_paths

    _ensure_xed_gi_paths()
    import gi

    gi.require_version("Xed", "1.0")
    from gi.repository import Xed

    _HAVE_XED = True
    _SKIP_REASON = ""
except Exception as e:
    Xed = None  # type: ignore
    _HAVE_XED = False
    _SKIP_REASON = str(e)


def _signature(ns_cls, method):
    if not _HAVE_XED:
        print(f"SKIP gi arity {method} ({_SKIP_REASON[:100]})")
        return None
    return inspect.signature(getattr(ns_cls, method))


def test_create_tab_from_location_arity():
    sig = _signature(Xed.Window, "create_tab_from_location")
    if sig is None:
        return
    params = list(sig.parameters)
    assert params == ["self", "location", "encoding", "line_pos", "create", "jump_to"], params


def test_navigation_arities():
    cases = [
        (Xed.Window, "get_tab_from_location", ["self", "location"]),
        (Xed.Window, "set_active_tab", ["self", "tab"]),
        (Xed.Document, "goto_line", ["self", "line"]),
        (Xed.Tab, "get_view", ["self"]),
        (Xed.Tab, "get_document", ["self"]),
        (Xed.Window, "get_views", ["self"]),
        (Xed.Window, "get_documents", ["self"]),
        (Xed.Window, "get_active_view", ["self"]),
        (Xed.Window, "get_active_document", ["self"]),
    ]
    if not _HAVE_XED:
        print(f"SKIP gi arity navigation ({_SKIP_REASON[:100]})")
        return
    for cls, method, expected in cases:
        params = list(inspect.signature(getattr(cls, method)).parameters)
        assert params == expected, f"{method}: {params} != {expected}"
