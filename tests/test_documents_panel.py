"""Hiding xed's built-in documents list (headless, fake widgets)."""

import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import xedcsharp

HAVE_PLUGIN = hasattr(xedcsharp.CSharpDevKitPlugin, "_hide_documents_panel")

DocsPanel = type("XedDocumentsPanel", (), {})


class _Box:
    def __init__(self, children=()):
        self._children = list(children)

    def get_children(self):
        return list(self._children)


class _Side(_Box):
    def __init__(self, children=()):
        super().__init__(children)
        self.removed: list = []
        self.added: list = []

    def remove_item(self, widget):
        self.removed.append(widget)
        return True

    def add_item(self, widget, name, icon):
        self.added.append((widget, name, icon))


class _Settings:
    def __init__(self, value):
        self._value = value

    def get(self, key):
        return self._value


def _ns(**kw):
    cls = xedcsharp.CSharpDevKitPlugin
    ns = types.SimpleNamespace(
        _safe=cls._safe,
        _hidden_docs=None,
        explorer=None,
        testpanel=None,
        output=None,
        debugpanel=None,
        settings=None,
        window=None,
    )
    for key, value in kw.items():
        setattr(ns, key, value)
    return ns


def test_find_locates_nested_panel():
    if not HAVE_PLUGIN:
        return
    docs = DocsPanel()
    side = _Side([_Box([docs])])
    assert xedcsharp._find_documents_widget(side) is docs


def test_find_skips_owned_panels():
    if not HAVE_PLUGIN:
        return
    inner = DocsPanel()
    owned = _Box([inner])
    outer = DocsPanel()
    side = _Side([owned, outer])
    assert xedcsharp._find_documents_widget(side, skip=(owned,)) is outer
    assert xedcsharp._find_documents_widget(owned, skip=(owned,)) is None


def test_hide_removes_and_records():
    if not HAVE_PLUGIN:
        return
    docs = DocsPanel()
    side = _Side([docs])
    plugin = _ns(window=types.SimpleNamespace(get_side_panel=lambda: side))
    xedcsharp.CSharpDevKitPlugin._hide_documents_panel(plugin)
    assert plugin._hidden_docs is docs
    assert side.removed == [docs]


def test_hide_respects_setting_off():
    if not HAVE_PLUGIN:
        return
    docs = DocsPanel()
    side = _Side([docs])
    plugin = _ns(
        window=types.SimpleNamespace(get_side_panel=lambda: side),
        settings=_Settings(False),
    )
    xedcsharp.CSharpDevKitPlugin._hide_documents_panel(plugin)
    assert plugin._hidden_docs is None
    assert side.removed == []


def test_restore_readds_with_label():
    if not HAVE_PLUGIN:
        return
    docs = DocsPanel()
    side = _Side([])
    plugin = _ns(
        _hidden_docs=docs,
        window=types.SimpleNamespace(get_side_panel=lambda: side),
    )
    xedcsharp.CSharpDevKitPlugin._restore_documents_panel(plugin)
    assert plugin._hidden_docs is None
    assert side.added == [(docs, "Documents", "text-x-generic")]


def test_hide_enabled_by_default():
    from xedcsharp.settings import DEFAULTS

    assert DEFAULTS.get("hide_documents_panel") is True
