"""Side-panel Solution Explorer. GTK-only; imported lazily by __init__."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import GObject, Gtk, Gdk  # type: ignore

from .logging_util import debug
from .solution import ProjectInfo, SolutionModel, project_tree

(COL_LABEL, COL_PATH, COL_KIND, COL_HINT) = range(4)


class SolutionExplorer(Gtk.Box):
    __gsignals__ = {
        "open-file": (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_STRING,)),
        "build-solution": (GObject.SignalFlags.RUN_LAST, None, ()),
        "build-project": (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_STRING,)),
        "run-project": (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_STRING,)),
        "test-project": (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_STRING,)),
        "debug-project": (GObject.SignalFlags.RUN_LAST, None, (GObject.TYPE_STRING,)),
        "restore": (GObject.SignalFlags.RUN_LAST, None, ()),
        "refresh": (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._model: SolutionModel | None = None

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for label, signal in (
            ("Build", "build-solution"),
            ("Restore", "restore"),
            ("Refresh", "refresh"),
        ):
            btn = Gtk.Button.new_with_label(label)
            btn.connect("clicked", lambda _b, s=signal: self.emit(s))
            toolbar.pack_start(btn, True, True, 0)
        self.pack_start(toolbar, False, False, 0)

        self.store = Gtk.TreeStore(str, str, str, str)
        self.tree = Gtk.TreeView.new_with_model(self.store)
        self.tree.set_headers_visible(False)
        col = Gtk.TreeViewColumn("Solution")
        cell = Gtk.CellRendererText()
        col.pack_start(cell, True)
        col.add_attribute(cell, "text", COL_LABEL)
        self.tree.append_column(col)
        self.tree.connect("row-activated", self._on_row_activated)
        self.tree.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.tree.connect("button-press-event", self._on_button_press)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.add(self.tree)
        self.pack_start(scrolled, True, True, 0)
        self.show_all()

    # -- model -------------------------------------------------------
    def set_model(self, model: SolutionModel) -> None:
        self._model = model
        self.store.clear()
        sln_label = os.path.basename(model.path) if model.path else f"{os.path.basename(model.root_dir)}/ (no .sln/.slnx)"
        sln_iter = self.store.append(None, [sln_label, model.path or model.root_dir, "solution", ""])
        for project in model.projects:
            hint = ", ".join(project.target_frameworks) or project.output_type
            if project.is_test_project:
                hint = (hint + " [tests]").strip()
            proj_iter = self.store.append(sln_iter, [project.name, project.path, "project", hint])
            try:
                self._append_tree(proj_iter, project_tree(os.path.dirname(project.path)))
            except Exception as e:
                debug(f"explorer tree failed: {e!r}")
        self.tree.collapse_all()

    def _append_tree(self, parent, nodes) -> None:
        for node in nodes:
            if node.is_dir:
                folder_iter = self.store.append(parent, [node.name + "/", node.path, "folder", ""])
                self._append_tree(folder_iter, node.children)
            else:
                self.store.append(parent, [node.name, node.path, "file", ""])

    # -- interaction -------------------------------------------------
    def _selected(self):
        selection = self.tree.get_selection()
        model, tree_iter = selection.get_selected()
        if tree_iter is None:
            return None
        return (
            model.get_value(tree_iter, COL_LABEL),
            model.get_value(tree_iter, COL_PATH),
            model.get_value(tree_iter, COL_KIND),
        )

    def _on_row_activated(self, _tree, path, _col) -> None:
        tree_iter = self.store.get_iter(path)
        kind = self.store.get_value(tree_iter, COL_KIND)
        fpath = self.store.get_value(tree_iter, COL_PATH)
        if kind == "file" and os.path.isfile(fpath):
            self.emit("open-file", fpath)
        elif kind == "folder":
            if self.tree.row_expanded(path):
                self.tree.collapse_row(path)
            else:
                self.tree.expand_row(path, False)

    def _on_button_press(self, _tree, event) -> bool:
        if event.button != 3:
            return False
        hit = self.tree.get_path_at_pos(int(event.x), int(event.y))
        if not hit:
            return False
        path, _col, _x, _y = hit
        self.tree.get_selection().select_path(path)
        selected = self._selected()
        if not selected:
            return False
        _label, fpath, kind = selected
        if kind == "folder":
            if self.tree.row_expanded(path):
                self.tree.collapse_row(path)
            else:
                self.tree.expand_row(path, False)
            return True
        menu = Gtk.Menu()
        if kind == "file":
            item = Gtk.MenuItem.new_with_label("Open")
            item.connect("activate", lambda _i: self.emit("open-file", fpath))
            menu.append(item)
        elif kind == "project":
            for label, signal in (
                ("Build project", "build-project"),
                ("Run project", "run-project"),
                ("Test project", "test-project"),
                ("Debug project", "debug-project"),
            ):
                item = Gtk.MenuItem.new_with_label(label)
                item.connect("activate", lambda _i, s=signal, p=fpath: self.emit(s, p))
                menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(event)
        return True


def describe_project(project: ProjectInfo) -> str:
    tfm = ",".join(project.target_frameworks) or "?"
    return f"{project.name} ({tfm}, {project.output_type})"
