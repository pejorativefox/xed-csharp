"""Unit tests for the quick-open fuzzy matcher (headless)."""

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import xedcsharp
from xedcsharp import intelligence as intel

HAVE_PLUGIN = hasattr(xedcsharp, "CSharpDevKitPlugin") and hasattr(
    xedcsharp.CSharpDevKitPlugin, "_show_fuzzy_finder"
)


def test_score_orders_tight_over_gappy():
    tight = intel.fuzzy_score("abc", "abc")
    gappy = intel.fuzzy_score("abc", "aXbXc")
    assert tight is not None and gappy is not None
    assert tight < gappy


def test_score_prefers_prefix_and_segments():
    assert intel.fuzzy_score("con", "Console") < intel.fuzzy_score("con", "XenonConsole")
    assert intel.fuzzy_score("sce", "ScenePresets.cs") < intel.fuzzy_score("sce", "XenonScene.cs")


def test_score_case_insensitive_and_empty():
    assert intel.fuzzy_score("COU", "count") == intel.fuzzy_score("cou", "Count")
    assert intel.fuzzy_score("", "anything") == 0
    assert intel.fuzzy_score("xyz", "abc") is None
    assert intel.fuzzy_score("abcd", "abc") is None


def test_find_ranks_limits_and_culls():
    paths = [
        "/repo/tests/CoreForge.Tests/Places.cs",
        "/repo/source/CoreForge/ScenePresets.cs",
        "/repo/source/CoreForge/Program.cs",
    ]
    found = intel.fuzzy_find("scene", paths)
    assert found == ["/repo/source/CoreForge/ScenePresets.cs"]
    assert intel.fuzzy_find("zzz", paths) == []
    assert intel.fuzzy_find("", paths, limit=2) == paths[:2]
    many = [f"/repo/f{i:03d}.cs" for i in range(10)]
    assert len(intel.fuzzy_find("", many, limit=3)) == 3


def test_empty_index_falls_back_to_folder_picker():
    if not HAVE_PLUGIN:
        return
    cls = xedcsharp.CSharpDevKitPlugin
    refreshed: list = []
    picked: list = []
    ns = types.SimpleNamespace(
        _solution_files=[],
        output=None,
        _refresh_solution=lambda: refreshed.append(True),
        _open_solution_folder=lambda: picked.append(True),
    )
    cls._show_fuzzy_finder(ns)
    assert refreshed == [True]
    assert picked == [True]


def test_indexed_files_run_dialog():
    if not HAVE_PLUGIN:
        return
    cls = xedcsharp.CSharpDevKitPlugin
    shown: dict = {}
    jumped: list = []

    class FakeDialog:
        def __init__(self, parent=None):
            shown["parent"] = parent

        def set_files(self, items):
            shown["items"] = items

        def connect(self, signal, callback):
            shown["callback"] = callback

        def run(self):
            shown["ran"] = True

        def destroy(self):
            shown["destroyed"] = True

    saved = xedcsharp.FuzzyFinderDialog
    xedcsharp.FuzzyFinderDialog = FakeDialog
    window = object()
    ns = types.SimpleNamespace(
        _solution_files=["/repo/A.cs"],
        _model=types.SimpleNamespace(root_dir="/repo"),
        window=window,
        output=None,
        _jump_to=lambda p, line, char: jumped.append(p),
    )
    try:
        cls._show_fuzzy_finder(ns)
    finally:
        xedcsharp.FuzzyFinderDialog = saved
    assert shown["parent"] is window
    assert shown["items"] == [("A.cs", "/repo/A.cs")]
    assert shown.get("ran") is True
    shown["callback"](None, "/repo/A.cs")
    assert jumped == ["/repo/A.cs"]
    assert shown.get("destroyed") is True


def _open_module():
    from importlib.machinery import SourceFileLoader

    path = os.path.join(os.path.dirname(__file__), "..", "xed-open")
    return SourceFileLoader("xed_open", path).load_module()


def test_parse_location_colon_forms():
    xed_open = _open_module()
    assert xed_open.parse_location("a.cs") == ("a.cs", None, None)
    assert xed_open.parse_location("a.cs:25") == ("a.cs", 25, None)
    assert xed_open.parse_location("a.cs:25:17") == ("a.cs", 25, 17)
    assert xed_open.parse_location("src/A B.cs:3") == ("src/A B.cs", 3, None)


def test_parse_location_msbuild_forms():
    xed_open = _open_module()
    assert xed_open.parse_location("a.cs(25)") == ("a.cs", 25, None)
    assert xed_open.parse_location("a.cs(25,17)") == ("a.cs", 25, 17)
    assert xed_open.parse_location("a.cs(25:17)") == ("a.cs", 25, 17)


def test_open_location_missing_file():
    xed_open = _open_module()
    assert xed_open.open_location("/no/such/file.cs", 3) == 2
    assert xed_open.open_location("", None) == 2
