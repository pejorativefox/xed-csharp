"""Bottom-panel debugger UI: breakpoints, call stack, variables, controls.

GTK-only; imported lazily by __init__. The DAP session itself is owned by the
plugin (see dap.py); this widget only displays state and emits control signals.
"""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import GObject, Gtk, GLib  # type: ignore

(BP_PATH, BP_LINE, BP_LABEL) = range(3)


class DebugPanel(Gtk.Box):
    __gsignals__ = {
        "debug-launch": (GObject.SignalFlags.RUN_LAST, None, ()),
        "debug-stop": (GObject.SignalFlags.RUN_LAST, None, ()),
        "debug-continue": (GObject.SignalFlags.RUN_LAST, None, ()),
        "debug-step-over": (GObject.SignalFlags.RUN_LAST, None, ()),
        "debug-step-into": (GObject.SignalFlags.RUN_LAST, None, ()),
        "debug-step-out": (GObject.SignalFlags.RUN_LAST, None, ()),
        "breakpoint-toggle": (
            GObject.SignalFlags.RUN_LAST,
            None,
            (GObject.TYPE_STRING, GObject.TYPE_INT),
        ),
        "breakpoints-clear": (GObject.SignalFlags.RUN_LAST, None, ()),
        "jump-to": (
            GObject.SignalFlags.RUN_LAST,
            None,
            (GObject.TYPE_STRING, GObject.TYPE_INT, GObject.TYPE_INT),
        ),
    }

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.status = Gtk.Label(label="Not debugging.")
        self.status.set_xalign(0.0)
        self.status.set_hexpand(True)
        toolbar.pack_start(self.status, True, True, 0)
        for label, signal in (
            ("Launch (F5)", "debug-launch"),
            ("Continue", "debug-continue"),
            ("Over", "debug-step-over"),
            ("Into", "debug-step-into"),
            ("Out", "debug-step-out"),
            ("Stop", "debug-stop"),
        ):
            btn = Gtk.Button.new_with_label(label)
            btn.connect("clicked", lambda _b, s=signal: self.emit(s))
            toolbar.pack_start(btn, False, False, 0)
        self.pack_start(toolbar, False, False, 0)

        paned = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        self.pack_start(paned, True, True, 0)

        # Left: breakpoints + call stack.
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        left.pack_start(Gtk.Label(label="Breakpoints / Call Stack"), False, False, 0)
        self.bp_store = Gtk.ListStore(str, int, str)
        self.bp_tree = Gtk.TreeView.new_with_model(self.bp_store)
        for index, title in ((2, "Location / Frame"),):
            col = Gtk.TreeViewColumn(title)
            cell = Gtk.CellRendererText()
            col.pack_start(cell, True)
            col.add_attribute(cell, "text", index)
            self.bp_tree.append_column(col)
        self.bp_tree.connect("row-activated", self._on_bp_activated)
        bp_scrolled = Gtk.ScrolledWindow()
        bp_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        bp_scrolled.add(self.bp_tree)
        left.pack_start(bp_scrolled, True, True, 0)
        bp_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        clear_btn = Gtk.Button.new_with_label("Clear All")
        clear_btn.connect("clicked", lambda _b: self.emit("breakpoints-clear"))
        bp_btns.pack_start(clear_btn, True, True, 0)
        left.pack_start(bp_btns, False, False, 0)
        paned.pack1(left, True, False)

        # Right: variables.
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        right.pack_start(Gtk.Label(label="Variables"), False, False, 0)
        self.var_store = Gtk.TreeStore(str, str)
        self.var_tree = Gtk.TreeView.new_with_model(self.var_store)
        for index, title in ((0, "Name"), (1, "Value")):
            col = Gtk.TreeViewColumn(title)
            cell = Gtk.CellRendererText()
            col.pack_start(cell, True)
            col.add_attribute(cell, "text", index)
            self.var_tree.append_column(col)
        self.var_tree.connect("row-activated", self._on_var_activated)
        var_scrolled = Gtk.ScrolledWindow()
        var_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        var_scrolled.add(self.var_tree)
        right.pack_start(var_scrolled, True, True, 0)
        paned.pack2(right, True, False)
        self.show_all()

    # -- state -------------------------------------------------------
    def set_status(self, text: str) -> None:
        GLib.idle_add(self.status.set_text, text)

    def set_breakpoints(self, breakpoints: dict[str, list[int]]) -> None:
        def _apply() -> None:
            self.bp_store.clear()
            for path in sorted(breakpoints):
                for line1 in sorted(breakpoints[path]):
                    label = f"● {os.path.basename(path)}:{line1}"
                    self.bp_store.append([path, line1, label])

        GLib.idle_add(_apply)

    def set_stack(self, frames: list[dict]) -> None:
        """Show stopped call stack (replaces breakpoint list until resume)."""

        def _apply() -> None:
            self.bp_store.clear()
            for frame in frames:
                name = frame.get("name", "?")
                line = frame.get("line", 0)
                source = (frame.get("source") or {}).get("path", "")
                label = f"▸ {name} ({os.path.basename(source)}:{line})" if source else f"▸ {name}"
                self.bp_store.append([source, int(line or 1), label])

        GLib.idle_add(_apply)

    def set_variables(self, groups: list[tuple[str, list[str]]]) -> None:
        def _apply() -> None:
            self.var_store.clear()
            for scope_name, entries in groups:
                parent = self.var_store.append(None, [scope_name, ""])
                for entry in entries:
                    if ": " in entry or " = " in entry:
                        name, _, value = entry.replace(" = ", ": ", 1).partition(": ")
                        self.var_store.append(parent, [name.strip(), value.strip()])
                    else:
                        self.var_store.append(parent, [entry, ""])
            self.var_tree.expand_all()

        GLib.idle_add(_apply)

    def clear_runtime(self) -> None:
        GLib.idle_add(self.var_store.clear)

    # -- interaction -------------------------------------------------
    def _on_bp_activated(self, _tree, path, _col) -> None:
        try:
            tree_iter = self.bp_store.get_iter(path)
            fpath = self.bp_store.get_value(tree_iter, BP_PATH)
            line1 = int(self.bp_store.get_value(tree_iter, BP_LINE))
        except Exception:
            return
        if fpath and os.path.isfile(fpath):
            self.emit("jump-to", fpath, max(0, line1 - 1), 0)

    def _on_var_activated(self, _tree, path, _col) -> None:
        # Expand/collapse scope rows; leaf fetch-more is future work.
        try:
            if self.var_tree.row_expanded(path):
                self.var_tree.collapse_row(path)
            else:
                self.var_tree.expand_row(path, False)
        except Exception:
            pass
