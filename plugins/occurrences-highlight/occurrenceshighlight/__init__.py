# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys

_XED_LIBDIRS = (
    "/usr/lib64/xed",
    "/usr/lib/xed",
    "/usr/lib/x86_64-linux-gnu/xed",
    "/usr/local/lib/xed",
    "/app/lib/xed",
)


def _ensure_xed_gi_paths() -> None:
    try:
        typelib_dirs = [
            os.path.join(d, "girepository-1.0")
            for d in _XED_LIBDIRS
            if os.path.isfile(os.path.join(d, "girepository-1.0", "Xed-1.0.typelib"))
        ]
        if typelib_dirs:
            old = os.environ.get("GI_TYPELIB_PATH", "")
            os.environ["GI_TYPELIB_PATH"] = ":".join(typelib_dirs + ([old] if old else []))
            try:
                import gi as _gi

                try:
                    _gi.require_version("GIRepository", "3.0")
                except Exception:
                    try:
                        _gi.require_version("GIRepository", "2.0")
                    except Exception:
                        pass
                from gi.repository import GIRepository  # type: ignore

                repo = None
                for method in ("dup_default", "get_default"):
                    try:
                        repo = getattr(GIRepository.Repository, method)()
                        break
                    except Exception:
                        continue
                if repo is not None:
                    for path in typelib_dirs:
                        try:
                            repo.prepend_search_path(path)
                        except Exception:
                            pass
            except Exception:
                pass
        for libdir in _XED_LIBDIRS:
            candidate = os.path.join(libdir, "libxed.so")
            if os.path.isfile(candidate):
                try:
                    import ctypes

                    ctypes.CDLL(candidate, mode=ctypes.RTLD_GLOBAL)
                except Exception:
                    pass
                break
    except Exception as e:
        sys.stderr.write(f"[occurrences-highlight] typelib setup failed: {e!r}\n")


def _debug(message: str) -> None:
    if os.environ.get("XED_PLUGIN_DEBUG", "").strip().lower() in ("", "0", "false", "no", "off"):
        return
    try:
        sys.stderr.write(f"[occurrences-highlight] {message}\n")
        sys.stderr.flush()
    except Exception:
        pass


try:
    import gi

    _ensure_xed_gi_paths()

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Xed", "1.0")

    from gi.repository import GObject, Gtk, Gdk, Gio, GLib, Xed  # type: ignore

    try:
        gi.require_version("GtkSource", "4")
        from gi.repository import GtkSource  # type: ignore

        _GTKSOURCE_AVAILABLE = True
    except Exception:
        try:
            gi.require_version("GtkSource", "3.0")
            from gi.repository import GtkSource  # type: ignore

            _GTKSOURCE_AVAILABLE = True
        except Exception as _e:
            GtkSource = None  # type: ignore
            _GTKSOURCE_AVAILABLE = False
            _debug(f"missing optional dependency: GtkSource typelib ({_e}). Gutter styling skipped.")
except Exception:
    class _DummyObject:
        def __init__(self, *args, **kwargs) -> None:
            pass

        @classmethod
        def Property(cls, *args, **kwargs):  # noqa: N802
            return None

    class _DummyGObject:
        Object = _DummyObject

        @classmethod
        def Property(cls, *args, **kwargs):  # noqa: N802
            return None

    class _DummyXed:
        class WindowActivatable:
            pass

        Window = object

    class _DummyGLib:
        @staticmethod
        def timeout_add(_ms, _cb, *args):
            return None

        @staticmethod
        def source_remove(_sid):
            return None

    GObject = _DummyGObject  # type: ignore[no-redef]
    Xed = _DummyXed  # type: ignore[no-redef]
    GLib = _DummyGLib  # type: ignore[no-redef]
    Gtk = Gio = Gdk = None  # type: ignore[no-redef]
    GtkSource = None  # type: ignore[no-redef]
    _GTKSOURCE_AVAILABLE = False


TAG_NAME = "occurrences-highlight"
MARK_CATEGORY = "occurrences-highlight"
HIGHLIGHT_COLOR = "#37332a"
DEBOUNCE_MS = 150
MAX_MATCHES = 1000
MIN_WORD_LEN = 2

try:
    from .search import find_occurrences as _find_occurrences
    from .search import word_at as _word_at
except Exception:
    try:
        from occurrenceshighlight.search import find_occurrences as _find_occurrences  # type: ignore
        from occurrenceshighlight.search import word_at as _word_at  # type: ignore
    except Exception:
        _find_occurrences = None  # type: ignore
        _word_at = None  # type: ignore


class OccurrencesPlugin(GObject.Object, Xed.WindowActivatable):  # type: ignore[misc]
    __gtype_name__ = "XedOccurrencesPlugin"

    window = GObject.Property(type=Xed.Window)  # type: ignore[arg-type]

    def __init__(self) -> None:
        super().__init__()
        self._tracked: dict[int, dict] = {}
        self._window_ids: list = []
        self._mark_views_configured: set = set()

    # -- lifecycle ---------------------------------------------------
    def do_activate(self) -> None:
        if Gtk is None:
            return
        try:
            self.window = self.window
        except Exception:
            pass
        for signal, handler in (
            ("tab-added", self._on_tab_added),
            ("tab-removed", self._on_tab_removed),
            ("active-tab-changed", self._on_active_tab_changed),
        ):
            try:
                hid = self.window.connect(signal, handler)
                self._window_ids.append((self.window, hid))
            except Exception as e:
                _debug(f"window connect {signal} failed: {e!r}")
        try:
            for view in self.window.get_views():
                try:
                    self._track_view(view)
                except Exception as e:
                    _debug(f"track view failed: {e!r}")
        except Exception as e:
            _debug(f"initial views failed: {e!r}")

    def do_deactivate(self) -> None:
        try:
            for record in list(self._tracked.values()):
                try:
                    self._untrack_record(record)
                except Exception as e:
                    _debug(f"untrack failed: {e!r}")
        finally:
            self._tracked.clear()
            self._mark_views_configured.clear()
        for obj, hid in self._window_ids:
            try:
                obj.disconnect(hid)
            except Exception:
                pass
        self._window_ids = []

    def do_update_state(self) -> None:
        return

    # -- window signals ----------------------------------------------
    def _on_tab_added(self, window, tab) -> None:
        try:
            try:
                view = tab.get_view()
            except Exception:
                view = None
            if view is not None:
                self._track_view(view)
        except Exception as e:
            _debug(f"tab-added failed: {e!r}")

    def _on_tab_removed(self, window, tab) -> None:
        try:
            self._reap_dead_docs()
        except Exception as e:
            _debug(f"tab-removed failed: {e!r}")

    def _on_active_tab_changed(self, window, tab) -> None:
        try:
            try:
                view = tab.get_view() if tab is not None else None
            except Exception:
                view = None
            if view is not None:
                self._track_view(view)
                try:
                    doc = view.get_buffer()
                    self._schedule(doc)
                except Exception as e:
                    _debug(f"active-tab update failed: {e!r}")
        except Exception as e:
            _debug(f"active-tab-changed failed: {e!r}")

    # -- tracking ----------------------------------------------------
    def _doc_key(self, doc) -> int | None:
        try:
            return hash(doc)
        except Exception:
            try:
                return id(doc)
            except Exception:
                return None

    def _track_view(self, view) -> None:
        try:
            doc = view.get_buffer()
        except Exception as e:
            _debug(f"get_buffer failed: {e!r}")
            return
        key = self._doc_key(doc)
        if key is None:
            return
        if key in self._tracked:
            return
        ids: list = []
        try:
            hid = doc.connect("mark-set", self._on_mark_set, key)
            ids.append((doc, hid))
        except Exception as e:
            _debug(f"mark-set connect failed: {e!r}")
        try:
            hid = doc.connect("changed", self._on_buffer_changed, key)
            ids.append((doc, hid))
        except Exception as e:
            _debug(f"changed connect failed: {e!r}")
        record = {"view": view, "doc": doc, "ids": ids, "pending": None,
                  "strip": None, "strip_ids": [], "lines": [], "line_count": 1}
        self._tracked[key] = record
        try:
            self._configure_marks(view)
        except Exception as e:
            _debug(f"configure marks failed: {e!r}")
        try:
            strip = self._attach_strip(view, key)
            record["strip"] = strip
        except Exception as e:
            _debug(f"attach strip failed: {e!r}")
        self._schedule(doc)

    def _untrack_record(self, record: dict) -> None:
        try:
            pending = record.get("pending")
            if pending is not None:
                try:
                    GLib.source_remove(pending)
                except Exception:
                    pass
                record["pending"] = None
        except Exception:
            pass
        try:
            doc = record.get("doc")
            if doc is not None:
                try:
                    self._clear_doc(doc, record)
                except Exception:
                    pass
        except Exception:
            pass
        for obj, hid in list(record.get("ids", [])):
            try:
                obj.disconnect(hid)
            except Exception:
                pass
        record["ids"] = []
        for obj, hid in list(record.get("strip_ids", [])):
            try:
                obj.disconnect(hid)
            except Exception:
                pass
        record["strip_ids"] = []
        strip = record.get("strip")
        record["strip"] = None
        if strip is not None:
            try:
                strip.destroy()
            except Exception:
                pass

    def _reap_dead_docs(self) -> None:
        try:
            live: set = set()
            for view in self.window.get_views():
                try:
                    live.add(self._doc_key(view.get_buffer()))
                except Exception:
                    continue
        except Exception:
            return
        for key in list(self._tracked.keys()):
            if key not in live:
                record = self._tracked.pop(key)
                try:
                    self._untrack_record(record)
                except Exception as e:
                    _debug(f"reap untrack failed: {e!r}")

    # -- buffer signals ----------------------------------------------
    def _on_mark_set(self, doc, it, mark, doc_key) -> None:
        try:
            try:
                if mark != doc.get_insert():
                    return
            except Exception:
                pass
            self._schedule(doc)
        except Exception as e:
            _debug(f"mark-set failed: {e!r}")

    def _on_buffer_changed(self, doc, doc_key=None) -> None:
        try:
            self._schedule(doc)
        except Exception as e:
            _debug(f"buffer changed failed: {e!r}")

    def _schedule(self, doc) -> None:
        try:
            key = self._doc_key(doc)
            record = self._tracked.get(key) if key is not None else None
            if record is None:
                return
            old = record.get("pending")
            if old is not None:
                try:
                    GLib.source_remove(old)
                except Exception:
                    pass
                record["pending"] = None
            if GLib is None:
                return
            try:
                record["pending"] = GLib.timeout_add(DEBOUNCE_MS, self._fire, key)
            except Exception as e:
                _debug(f"debounce schedule failed: {e!r}")
        except Exception as e:
            _debug(f"schedule failed: {e!r}")

    def _fire(self, doc_key) -> bool:
        try:
            record = self._tracked.get(doc_key)
            if record is None:
                return False
            record["pending"] = None
            try:
                self._update(record)
            except Exception as e:
                _debug(f"update failed: {e!r}")
        except Exception as e:
            _debug(f"fire failed: {e!r}")
        return False

    # -- highlight ---------------------------------------------------
    def _update(self, record: dict) -> None:
        doc = record.get("doc")
        if doc is None or _word_at is None or _find_occurrences is None:
            return
        try:
            start, end = doc.get_bounds()
            text = doc.get_text(start, end, True)
        except Exception:
            try:
                text = doc.get_text(doc.get_start_iter(), doc.get_end_iter(), True)
            except Exception as e:
                _debug(f"text snapshot failed: {e!r}")
                return
        try:
            mark = doc.get_insert()
            offset = doc.get_iter_at_mark(mark).get_offset()
        except Exception as e:
            _debug(f"cursor offset failed: {e!r}")
            return
        try:
            found = _word_at(text, offset)
        except Exception as e:
            _debug(f"word_at failed: {e!r}")
            return
        if found is None:
            try:
                self._clear_doc(doc, record)
            except Exception as e:
                _debug(f"clear failed: {e!r}")
            return
        word = found[0]
        try:
            hits = _find_occurrences(text, word, MAX_MATCHES)
        except Exception as e:
            _debug(f"find_occurrences failed: {e!r}")
            return
        try:
            self._apply(doc, record, hits)
        except Exception as e:
            _debug(f"apply failed: {e!r}")

    def _ensure_tag(self, doc):
        try:
            table = doc.get_tag_table()
        except Exception:
            return None
        try:
            tag = table.lookup(TAG_NAME)
        except Exception:
            tag = None
        if tag is not None:
            return tag
        try:
            return doc.create_tag(TAG_NAME, background=HIGHLIGHT_COLOR)
        except Exception as e:
            _debug(f"tag create failed: {e!r}")
            return None

    def _apply(self, doc, record: dict, hits: list) -> None:
        tag = self._ensure_tag(doc)
        try:
            start, end = doc.get_bounds()
        except Exception as e:
            _debug(f"bounds failed: {e!r}")
            return
        if tag is not None:
            try:
                doc.remove_tag(tag, start, end)
            except Exception:
                pass
            for s, e in hits:
                try:
                    doc.apply_tag(tag, doc.get_iter_at_offset(s), doc.get_iter_at_offset(e))
                except Exception:
                    continue
        # gutter marks: one per matched line
        try:
            doc.remove_source_marks(start, end, MARK_CATEGORY)
        except Exception as e:
            _debug(f"remove marks failed: {e!r}")
        lines: list[int] = []
        try:
            line_count = doc.get_line_count()
        except Exception:
            line_count = 0
        seen: set[int] = set()
        for s, _e in hits:
            try:
                line = doc.get_iter_at_offset(s).get_line()
            except Exception:
                continue
            if line in seen:
                continue
            seen.add(line)
            try:
                if line_count and not 0 <= line < line_count:
                    continue
                doc.create_source_mark(None, MARK_CATEGORY, doc.get_iter_at_line(line))
                lines.append(line)
            except Exception:
                continue
        record["lines"] = lines
        try:
            record["line_count"] = line_count if line_count else 1
        except Exception:
            record["line_count"] = 1
        strip = record.get("strip")
        if strip is not None:
            try:
                strip.queue_draw()
            except Exception:
                pass

    def _clear_doc(self, doc, record: dict | None = None) -> None:
        try:
            start, end = doc.get_bounds()
        except Exception:
            return
        try:
            table = doc.get_tag_table()
            tag = table.lookup(TAG_NAME)
        except Exception:
            tag = None
        if tag is not None:
            try:
                doc.remove_tag(tag, start, end)
            except Exception:
                pass
        try:
            doc.remove_source_marks(start, end, MARK_CATEGORY)
        except Exception as e:
            _debug(f"clear marks failed: {e!r}")
        if record is not None:
            record["lines"] = []
            strip = record.get("strip")
            if strip is not None:
                try:
                    strip.queue_draw()
                except Exception:
                    pass

    def _configure_marks(self, view) -> None:
        if not _GTKSOURCE_AVAILABLE:
            return
        try:
            if hash(view) in self._mark_views_configured:
                return
        except Exception:
            if id(view) in self._mark_views_configured:
                return
        try:
            view.set_show_line_marks(True)
            try:
                attrs = GtkSource.MarkAttributes()
                rgba = Gdk.RGBA()
                if rgba.parse(HIGHLIGHT_COLOR):
                    attrs.set_background(rgba)
                view.set_mark_attributes(MARK_CATEGORY, attrs, 10)
            except Exception as e:
                _debug(f"mark attributes {MARK_CATEGORY} failed: {e!r}")
            try:
                self._mark_views_configured.add(hash(view))
            except Exception:
                self._mark_views_configured.add(id(view))
        except Exception as e:
            _debug(f"configure marks failed: {e!r}")

    # -- scrollbar tick strip (best-effort) ---------------------------
    def _attach_strip(self, view, doc_key):
        if Gtk is None:
            return None
        try:
            sw = None
            p = None
            try:
                p = view.get_parent()
            except Exception:
                return None
            for _ in range(8):
                if p is None:
                    break
                try:
                    p.get_vscrollbar()
                    sw = p
                    break
                except Exception:
                    pass
                try:
                    p = p.get_parent()
                except Exception:
                    break
            if sw is None:
                _debug("no ScrolledWindow found; gutter marks only")
                return None
            strip = Gtk.DrawingArea()
            try:
                strip.set_size_request(8, -1)
            except Exception:
                pass
            try:
                strip.connect("draw", self._on_strip_draw, doc_key)
            except Exception as e:
                _debug(f"strip draw connect failed: {e!r}")
                return None
            record = self._tracked.get(doc_key)
            try:
                sb = sw.get_vscrollbar()
            except Exception:
                sb = None
            placed = False
            if sb is not None:
                try:
                    parent = sb.get_parent()
                except Exception:
                    parent = None
                if parent is not None:
                    for meth in ("pack_start", "pack_end", "add"):
                        try:
                            fn = getattr(parent, meth, None)
                            if fn is None:
                                continue
                            if meth.startswith("pack"):
                                fn(strip, False, False, 0)
                            else:
                                fn(strip)
                            placed = True
                            break
                        except Exception:
                            continue
                    if not placed:
                        try:
                            parent.add(strip)
                            placed = True
                        except Exception as e:
                            _debug(f"strip pack failed: {e!r}")
                try:
                    hid = sb.connect("value-changed", self._on_scroll_changed, doc_key)
                    if record is not None:
                        record.setdefault("strip_ids", []).append((sb, hid))
                except Exception:
                    pass
                try:
                    hid = sb.connect("size-allocate", self._on_scroll_changed, doc_key)
                    if record is not None:
                        record.setdefault("strip_ids", []).append((sb, hid))
                except Exception:
                    pass
            if not placed:
                _debug("strip pack unavailable; gutter marks only")
                try:
                    strip.destroy()
                except Exception:
                    pass
                return None
            try:
                strip.show()
            except Exception:
                pass
            return strip
        except Exception as e:
            _debug(f"attach strip failed: {e!r}")
            return None

    def _on_strip_draw(self, area, cr, doc_key) -> bool:
        try:
            record = self._tracked.get(doc_key)
            if record is None:
                return False
            lines = record.get("lines", [])
            if not lines:
                return False
            try:
                alloc = area.get_allocation()
                height = alloc.height
                width = alloc.width
            except Exception:
                return False
            if height <= 0 or width <= 0:
                return False
            line_count = record.get("line_count", 1) or 1
            try:
                rgba = Gdk.RGBA()
                ok = rgba.parse(HIGHLIGHT_COLOR)
                if ok:
                    try:
                        Gdk.cairo_set_source_rgba(cr, rgba)
                    except Exception:
                        cr.set_source_rgb(rgba.red, rgba.green, rgba.blue)
                else:
                    cr.set_source_rgb(0.9, 0.86, 0.45)
            except Exception:
                try:
                    cr.set_source_rgb(0.9, 0.86, 0.45)
                except Exception:
                    return False
            for line in lines:
                try:
                    y = int(line / max(1, line_count) * height)
                    if y + 3 > height:
                        y = height - 3
                    cr.rectangle(0, y, width, 3)
                except Exception:
                    continue
            try:
                cr.fill()
            except Exception:
                pass
        except Exception as e:
            _debug(f"strip draw failed: {e!r}")
        return False

    def _on_scroll_changed(self, *args) -> None:
        try:
            doc_key = args[-1] if args else None
            record = self._tracked.get(doc_key)
            if record is None:
                return
            strip = record.get("strip")
            if strip is not None:
                try:
                    strip.queue_draw()
                except Exception:
                    pass
        except Exception as e:
            _debug(f"scroll changed failed: {e!r}")
