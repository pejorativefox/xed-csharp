"""Quick-open fuzzy file finder (Ctrl+P). GTK-only; imported lazily by __init__."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import GObject, Gtk, Gdk  # type: ignore

from .intelligence import fuzzy_find
from .logging_util import debug

(COL_LABEL, COL_PATH) = range(2)
MAX_ROWS = 60


class FuzzyFinderDialog(Gtk.Dialog):
    __gsignals__ = {
        "open-file": (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_STRING,)),
    }

    def __init__(self, parent=None) -> None:
        super().__init__(title="Open File in Solution")
        try:
            self.set_modal(True)
        except Exception:
            pass
        if parent is not None:
            try:
                self.set_transient_for(parent)
            except Exception as e:
                debug(f"fuzzy transient_for failed: {e!r}")
        self.set_default_size(560, 380)
        self._files: list[tuple[str, str]] = []
        self._entry = Gtk.Entry()
        try:
            self._entry.set_placeholder_text("Type to filter…")
        except Exception:
            pass
        self._entry.connect("changed", lambda _e: self._refilter())
        self._entry.connect("key-press-event", self._on_entry_key)
        self._store = Gtk.ListStore(str, str)
        self._view = Gtk.TreeView.new_with_model(self._store)
        self._view.set_headers_visible(False)
        cell = Gtk.CellRendererText()
        cell.set_property("ellipsize", 2)  # middle-ellipsis for long paths
        col = Gtk.TreeViewColumn("File", cell, text=COL_LABEL)
        self._view.append_column(col)
        self._view.connect("row-activated", lambda _v, _p, _c: self._activate_selected())
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.add(self._view)
        area = self.get_content_area()
        area.pack_start(self._entry, False, False, 0)
        area.pack_start(scrolled, True, True, 0)
        self.show_all()

    # -- data ----------------------------------------------------------
    def set_files(self, items: list[tuple[str, str]]) -> None:
        """items: (display, path) pairs."""
        self._files = list(items)
        self._refilter()
        try:
            self._entry.grab_focus()
        except Exception:
            pass

    def _refilter(self) -> None:
        query = self._entry.get_text()
        paths = [path for _display, path in self._files]
        labels = {path: display for display, path in self._files}
        self._store.clear()
        try:
            for path in fuzzy_find(query, paths, limit=MAX_ROWS):
                self._store.append([labels.get(path, path), path])
        except Exception as e:
            debug(f"fuzzy refilter failed: {e!r}")
        self._select_row(0)

    # -- selection -----------------------------------------------------
    def _select_row(self, index: int) -> None:
        count = len(self._store)
        if count == 0:
            return
        index = max(0, min(count - 1, index))
        path = Gtk.TreePath.new_from_indices([index])
        self._view.get_selection().select_path(path)
        self._view.scroll_to_cell(path, None, False, 0, 0)

    def _selected_path(self) -> str | None:
        model, tree_iter = self._view.get_selection().get_selected()
        if tree_iter is None:
            if len(self._store) == 0:
                return None
            tree_iter = self._store.get_iter_first()
        try:
            return model.get_value(tree_iter, COL_PATH)
        except Exception:
            return None

    def _activate_selected(self) -> None:
        path = self._selected_path()
        if path:
            self.emit("open-file", path)

    def _on_entry_key(self, _entry, event) -> bool:
        try:
            name = Gdk.keyval_name(event.keyval) or ""
        except Exception:
            return False
        if name in ("Up", "KP_Up", "Down", "KP_Down"):
            model, tree_iter = self._view.get_selection().get_selected()
            current = 0
            if tree_iter is not None:
                try:
                    current = self._store.get_path(tree_iter).get_indices()[0]
                except Exception:
                    current = 0
            self._select_row(current + (-1 if name.startswith("Up") or "Up" in name else 1))
            return True
        if name in ("Return", "KP_Enter"):
            self._activate_selected()
            return True
        if name == "Escape":
            self.destroy()
            return True
        return False
