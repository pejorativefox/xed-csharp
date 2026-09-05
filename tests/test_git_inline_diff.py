"""git-inline-diff plugin behavior (headless)."""

import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins", "git-inline-diff"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins", "git-inline-diff", "gitinline"))

import gitinline
from gitinline import diffparse


def _has_git():
    return shutil.which("git") is not None


def _init_repo(tmp):
    subprocess.run(["git", "init"], cwd=tmp, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=tmp, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_palette_matches_tree():
    assert diffparse.COLOR_ADDED == "#73C991"
    assert diffparse.COLOR_MODIFIED == "#E2C08D"
    assert diffparse.COLOR_DELETED == "#C74E39"
    assert diffparse.CATEGORY_ADDED == "gitinline-added"
    assert diffparse.CATEGORY_MODIFIED == "gitinline-modified"
    assert diffparse.CATEGORY_DELETED == "gitinline-deleted"


def test_parse_pure_addition():
    text = (
        "diff --git a/f.txt b/f.txt\n"
        "index 1111111..2222222 100644\n"
        "--- a/f.txt\n"
        "+++ b/f.txt\n"
        "@@ -1,0 +2,2 @@\n"
    )
    out = diffparse.parse_unified_diff(text)
    assert out["added"] == [1, 2]
    assert out["modified"] == []
    assert out["deleted"] == []


def test_parse_pure_deletion_marks_line_above_gap():
    text = "@@ -3,2 +2,0 @@\n"
    out = diffparse.parse_unified_diff(text)
    assert out["deleted"] == [1]
    assert out["added"] == [] and out["modified"] == []


def test_parse_deletion_at_start_floors_at_zero():
    out = diffparse.parse_unified_diff("@@ -1,2 +0,0 @@\n")
    assert out["deleted"] == [0]


def test_parse_modification():
    out = diffparse.parse_unified_diff("@@ -5,1 +5,3 @@\n")
    assert out["modified"] == [4, 5, 6]
    assert out["added"] == [] and out["deleted"] == []


def test_parse_multi_hunk_and_empty():
    text = "@@ -1,1 +1,1 @@\n@@ -10,0 +11,2 @@\n@@ -20,3 +23,0 @@\n"
    out = diffparse.parse_unified_diff(text)
    assert out["modified"] == [0]
    assert out["added"] == [10, 11]
    assert out["deleted"] == [22]
    empty = diffparse.parse_unified_diff("")
    assert empty == {"added": [], "modified": [], "deleted": []}


def test_parse_binary_diff_yields_nothing():
    text = (
        "diff --git a/logo.png b/logo.png\n"
        "index 1111111..2222222 100644\n"
        "GIT binary patch\n"
    )
    assert diffparse.parse_unified_diff(text) == {"added": [], "modified": [], "deleted": []}


def test_clamp_lines():
    assert diffparse.clamp_lines([0, 5, 99, -3, 5], 10) == [0, 5, 9]
    assert diffparse.clamp_lines([3], 0) == []
    assert diffparse.clamp_lines([], 10) == []


def test_untracked_marks():
    assert diffparse.untracked_marks(3) == {"added": [0, 1, 2], "modified": [], "deleted": []}
    assert diffparse.untracked_marks(0)["added"] == []


def test_status_and_diff_real_repo():
    if not _has_git():
        return
    with tempfile.TemporaryDirectory() as tmp:
        _init_repo(tmp)
        tracked = os.path.join(tmp, "f.txt")
        with open(tracked, "w") as f:
            f.write("one\ntwo\nthree\n")
        subprocess.run(["git", "add", "f.txt"], cwd=tmp, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert diffparse.file_status_short(tmp, tracked) == ""
        assert diffparse.get_diff_text(tmp, tracked) == ""

        with open(tracked, "w") as f:
            f.write("one\nTWO\nthree\nfour\n")
        status = diffparse.file_status_short(tmp, tracked)
        assert status[1] == "M"
        hunks = diffparse.parse_unified_diff(diffparse.get_diff_text(tmp, tracked))
        assert 1 in hunks["modified"]  # line 2 changed (0-based 1)
        assert 3 in hunks["added"]  # appended line 4 (0-based 3)

        new = os.path.join(tmp, "new.txt")
        with open(new, "w") as f:
            f.write("hello\n")
        assert diffparse.file_status_short(tmp, new) == "??"
        assert diffparse.find_git_root(os.path.dirname(new)) == os.path.abspath(tmp)


def test_non_repo_soft_fails():
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "f.txt")
        with open(target, "w") as f:
            f.write("x\n")
        assert diffparse.file_status_short(tmp, target) == ""
        assert diffparse.get_diff_text(tmp, target) == ""
        assert diffparse.find_git_root(tmp) is None


def test_plugin_imports_headless():
    assert gitinline._diffparse is diffparse
    assert gitinline._REFRESH_DEBOUNCE_MS == 300


def test_rgba_pixel_packs_rgb_with_full_alpha():
    assert gitinline.rgba_pixel("#73C991") == 0x73C991FF
    assert gitinline.rgba_pixel("#E2C08D") == 0xE2C08DFF
    assert gitinline.rgba_pixel("#C74E39") == 0xC74E39FF
    assert gitinline.rgba_pixel("not-a-color") is None
    assert gitinline.rgba_pixel("#FFF") is None


def test_color_pixbuf_is_small_solid_square():
    pixbuf = gitinline.color_pixbuf("#73C991")
    if gitinline.GdkPixbuf is None:
        assert pixbuf is None
        return
    assert pixbuf.get_width() == gitinline._MARK_ICON_SIZE
    assert pixbuf.get_height() == gitinline._MARK_ICON_SIZE
    assert pixbuf.get_has_alpha() is True
    assert gitinline.color_pixbuf("bogus") is None


def test_configure_marks_never_sets_line_background():
    import inspect

    source = inspect.getsource(gitinline.GitInlineDiffPlugin._configure_marks)
    assert "set_background" not in source
    assert "set_pixbuf" in source
