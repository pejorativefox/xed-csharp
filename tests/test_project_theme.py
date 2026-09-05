"""project-mode tree background CSS (headless)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins", "project-mode"))

import projectmode


def test_tree_bg_css_darkens_theme_base_by_20pct():
    css = projectmode.tree_bg_css()
    assert "shade(@theme_base_color, 0.8)" in css


def test_tree_bg_css_covers_gtk3_selectors():
    css = projectmode.tree_bg_css()
    assert "treeview.view" in css
    assert "GtkTreeView" in css
    assert "background-color" in css


def test_tree_bg_css_parses_when_gtk_available():
    if projectmode.Gtk is None:
        return
    provider = projectmode.Gtk.CssProvider()
    provider.load_from_data(projectmode.tree_bg_css().encode("utf-8"))
