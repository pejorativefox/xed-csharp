"""Unit tests for the fuzzy-finder plugin (headless, no GTK)."""

import os
import shutil
import sys
import tempfile
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins", "fuzzy-finder"))

from fuzzyfinder import files as files_mod
from fuzzyfinder import find_project_root
from fuzzyfinder.matcher import fuzzy_find, fuzzy_score


def test_score_orders_tight_over_gappy():
    tight = fuzzy_score("abc", "abc")
    gappy = fuzzy_score("abc", "aXbXc")
    assert tight is not None and gappy is not None
    assert tight < gappy


def test_score_prefers_prefix_and_segments():
    assert fuzzy_score("con", "Console") < fuzzy_score("con", "XenonConsole")
    assert fuzzy_score("sce", "ScenePresets.cs") < fuzzy_score("sce", "XenonScene.cs")


def test_score_case_insensitive_and_empty():
    assert fuzzy_score("COU", "count") == fuzzy_score("cou", "Count")
    assert fuzzy_score("", "anything") == 0
    assert fuzzy_score("xyz", "abc") is None
    assert fuzzy_score("abcd", "abc") is None


def test_find_ranks_limits_and_culls():
    paths = [
        "/repo/tests/CoreForge.Tests/Places.cs",
        "/repo/source/CoreForge/ScenePresets.cs",
        "/repo/source/CoreForge/Program.cs",
    ]
    found = fuzzy_find("scene", paths)
    assert found == ["/repo/source/CoreForge/ScenePresets.cs"]
    assert fuzzy_find("zzz", paths) == []
    assert fuzzy_find("", paths, limit=2) == paths[:2]
    many = [f"/repo/f{i:03d}.cs" for i in range(10)]
    assert len(fuzzy_find("", many, limit=3)) == 3


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("x")


def test_list_files_skips_hidden_pruned_and_links():
    with tempfile.TemporaryDirectory() as tmp:
        # Force the walk fallback even inside a git checkout.
        _touch(os.path.join(tmp, "Real.cs"))
        _touch(os.path.join(tmp, "sub", "Deep.md"))
        _touch(os.path.join(tmp, "bin", "Built.cs"))
        _touch(os.path.join(tmp, "node_modules", "lib.js"))
        _touch(os.path.join(tmp, ".hidden", "H.cs"))
        with tempfile.TemporaryDirectory() as elsewhere:
            _touch(os.path.join(elsewhere, "Linked.cs"))
            os.symlink(elsewhere, os.path.join(tmp, "link"))
        old = os.environ.get("GIT_CEILING_DIRECTORIES")
        os.environ["GIT_CEILING_DIRECTORIES"] = tmp
        try:
            found = files_mod.list_project_files(tmp)
        finally:
            if old is None:
                del os.environ["GIT_CEILING_DIRECTORIES"]
            else:
                os.environ["GIT_CEILING_DIRECTORIES"] = old
        assert os.path.join(tmp, "Real.cs") in found
        assert os.path.join(tmp, "sub", "Deep.md") in found
        assert not any("bin" in p or "node_modules" in p for p in found)
        assert not any(".hidden" in p or "link" in p for p in found)


def test_list_files_respects_gitignore():
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp:
        _touch(os.path.join(tmp, "Keep.cs"))
        _touch(os.path.join(tmp, "Skip.log"))
        with open(os.path.join(tmp, ".gitignore"), "w") as f:
            f.write("*.log\n")
        import subprocess

        subprocess.run(["git", "-C", tmp, "init", "-q"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        found = files_mod.list_project_files(tmp)
        assert os.path.join(tmp, "Keep.cs") in found
        assert os.path.join(tmp, "Skip.log") not in found


def test_list_files_bad_root():
    assert files_mod.list_project_files("") == []
    assert files_mod.list_project_files("/no/such/dir-xyz") == []


def _window_with_panel(children):
    side = types.SimpleNamespace(get_children=lambda: list(children))
    return types.SimpleNamespace(get_side_panel=lambda: side)


def test_find_project_root_from_side_panel():
    with tempfile.TemporaryDirectory() as tmp:
        browser = types.SimpleNamespace(_root_dir=tmp)
        window = _window_with_panel([browser])
        assert find_project_root(window) == os.path.abspath(tmp)


def test_find_project_root_missing():
    assert find_project_root(_window_with_panel([])) is None
    assert find_project_root(_window_with_panel([types.SimpleNamespace()])) is None
    broken = types.SimpleNamespace(get_side_panel=lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert find_project_root(broken) is None


def test_global_key_ctrl_p_shows_finder():
    import fuzzyfinder

    plugin = fuzzyfinder.FuzzyFinderPlugin()
    shown: list = []
    plugin._show_finder = lambda: shown.append(True)  # type: ignore[method-assign]
    assert plugin._handle_global_key("p", True, False, False) is True
    assert shown == [True]
    assert plugin._handle_global_key("p", False, False, False) is False
    assert plugin._handle_global_key("p", True, True, False) is False
    assert plugin._handle_global_key("p", True, False, True) is False
    assert plugin._handle_global_key("x", True, False, False) is False


def test_show_finder_without_root_prompts():
    import fuzzyfinder

    if fuzzyfinder.Gtk is None:
        return  # no GTK: _show_finder is a no-op by design
    plugin = fuzzyfinder.FuzzyFinderPlugin()
    prompted: list = []
    plugin._notify_no_root = lambda: prompted.append(True)  # type: ignore[method-assign]
    saved = fuzzyfinder.find_project_root
    fuzzyfinder.find_project_root = lambda _window: None
    try:
        plugin._show_finder()
    finally:
        fuzzyfinder.find_project_root = saved
    assert prompted == [True]
