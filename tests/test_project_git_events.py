"""project-mode git monitor filtering (headless)."""

import os
import sys
import tempfile
import types

import pytest

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


def test_tree_rebuild_on_delete():
    assert projectmode.should_rebuild_tree_for_event("/repo", "/repo/src/a.cs") is True
    assert projectmode.should_rebuild_tree_for_event("/repo", None, None) is True
    assert projectmode.should_rebuild_tree_for_event("/repo", "/other/f") is False
    assert projectmode.should_rebuild_tree_for_event("/repo", "/repo/.git/HEAD") is False
    assert projectmode.should_rebuild_tree_for_event("/repo", "/repo/.git/objects/x") is False


def test_collect_watch_dirs_prunes():
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "src", "sub"))
        os.makedirs(os.path.join(tmp, ".git"))
        os.makedirs(os.path.join(tmp, "bin"))
        with open(os.path.join(tmp, "src", "a.txt"), "w") as f:
            f.write("x")
        watched = projectmode.collect_watch_dirs(tmp)
        assert os.path.abspath(tmp) in watched
        assert os.path.abspath(os.path.join(tmp, "src")) in watched
        assert os.path.abspath(os.path.join(tmp, "src", "sub")) in watched
        assert all("/.git" not in w and "/bin" not in w for w in watched)


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


def test_working_tree_refresh_bypasses_storm_gate():
    import time

    if not hasattr(projectmode, "ProjectBrowser"):
        pytest.skip("no Gtk")
    saved_glib = projectmode.GLib
    timers = []
    projectmode.GLib = types.SimpleNamespace(
        timeout_add=lambda ms, cb, *a: timers.append((ms, cb, a)) or len(timers),
        source_remove=lambda i: None,
    )
    try:
        with tempfile.TemporaryDirectory() as tmp:
            ns = types.SimpleNamespace(
                _root_dir=tmp,
                _git_generation=0,
                _last_git_refresh=time.monotonic(),
                _refresh_timer=None,
                _refresh_interval_s=projectmode.GIT_REFRESH_MIN_INTERVAL_S,
                _query_git_thread=lambda *a: None,
            )
            ns.refresh_git_statuses = types.MethodType(
                projectmode.ProjectBrowser.refresh_git_statuses, ns)
            ns._arm_git_timer = types.MethodType(
                projectmode.ProjectBrowser._arm_git_timer, ns)
            ns._on_git_changed_fire = lambda *a: False
            # Default gate: refreshed a moment ago -> re-arm, no new query.
            ns.refresh_git_statuses()
            assert ns._git_generation == 0
            assert timers, "gated refresh must re-arm a timer"
            # Working-tree edit: zero interval proceeds immediately.
            queries = []
            ns._query_git_thread = lambda *a: queries.append(a)
            ns.refresh_git_statuses(min_interval_s=0.0)
            assert ns._git_generation == 1
    finally:
        projectmode.GLib = saved_glib


def test_git_timer_preserves_interval_through_fire():
    if not hasattr(projectmode, "ProjectBrowser"):
        pytest.skip("no Gtk")
    saved_glib = projectmode.GLib
    projectmode.GLib = types.SimpleNamespace(
        timeout_add=lambda ms, cb, *a: 7,
        source_remove=lambda i: None,
    )
    try:
        ns = types.SimpleNamespace(
            _git_generation=5,
            _refresh_timer=None,
            _refresh_interval_s=projectmode.GIT_REFRESH_MIN_INTERVAL_S,
        )
        ns._arm_git_timer = types.MethodType(
            projectmode.ProjectBrowser._arm_git_timer, ns)
        ns._on_git_changed_fire = types.MethodType(
            projectmode.ProjectBrowser._on_git_changed_fire, ns)
        calls = []
        ns.refresh_git_statuses = lambda *a, **k: calls.append(k)
        ns._arm_git_timer(500, 5, 0.0)
        assert ns._refresh_interval_s == 0.0
        ns._on_git_changed_fire(5)
        assert calls == [{"min_interval_s": 0.0}]
        ns._on_git_changed_fire(4)  # stale generation: ignored
        assert len(calls) == 1
    finally:
        projectmode.GLib = saved_glib
