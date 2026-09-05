"""Unit tests for the quick-open fuzzy matcher (headless)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xedcsharp import intelligence as intel


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
