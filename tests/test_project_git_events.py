"""project-mode git monitor filtering (headless)."""

import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins", "project-mode"))

import projectmode


def test_git_noise_ignored():
    root = "/repo"
    assert projectmode.should_refresh_for_git_event(root, "/repo/.git/objects/ab/cd") is False
    assert projectmode.should_refresh_for_git_event(root, "/repo/.git/logs/HEAD") is False
    assert projectmode.should_refresh_for_git_event(root, "/repo/.git/index.lock") is False
    assert projectmode.should_refresh_for_git_event(root, "/repo/.git/hooks/x.tmp") is False


def test_git_relevant_allowed():
    root = "/repo"
    assert projectmode.should_refresh_for_git_event(root, "/repo/.git/HEAD") is True
    assert projectmode.should_refresh_for_git_event(root, "/repo/.git/index") is True
    assert projectmode.should_refresh_for_git_event(root, "/repo/.git/refs/heads/main") is True
    assert projectmode.should_refresh_for_git_event(root, "/repo/.git/packed-refs") is True
    assert projectmode.should_refresh_for_git_event(root, "/repo/src/a.cs") is True


def test_git_outside_root_ignored():
    assert projectmode.should_refresh_for_git_event("/repo", "/other/f") is False


def test_git_event_paths_headless():
    class Fake:
        def __init__(self, p):
            self._p = p

        def get_path(self):
            return self._p

    assert projectmode.git_event_paths(Fake("/a"), Fake("/b")) == ("/a", "/b")
    assert projectmode.git_event_paths(None, None) == (None, None)


def test_set_root_refuses_unsafe():
    cls = projectmode.ProjectModePlugin
    ns = types.SimpleNamespace(_root_dir=None)
    called = []
    ns.browser = types.SimpleNamespace(set_root=lambda path: called.append(path))
    ns._set_root = types.MethodType(cls._set_root, ns)

    with tempfile.TemporaryDirectory() as tmp:
        ns._set_root(tmp)
        assert called, "safe tmp root must still load"

    home = os.path.expanduser("~")
    ns._root_dir = None
    called.clear()
    ns._set_root(home)
    assert called == [], "unsafe $HOME root must be refused"
    assert ns._root_dir is None
