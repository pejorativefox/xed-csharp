# -*- coding: utf-8 -*-
"""C# DevKit-like plugin for xed (Linux Mint).

Single multi-feature plugin: solution explorer + test explorer (side panel),
build output + problems + debugger (bottom panel), Roslyn LSP intelligence
(completion, hover, go-to-definition, references, format, code actions,
diagnostics in-editor), test runner, netcoredbg DAP debugging.
"""

from __future__ import annotations

import os
import sys
import threading
import traceback

_XED_LIBDIRS = (
    "/usr/lib64/xed",
    "/usr/lib/xed",
    "/usr/lib/x86_64-linux-gnu/xed",
    "/usr/local/lib/xed",
    "/app/lib/xed",
)


def _ensure_xed_gi_paths() -> None:
    """Register xed's private typelib/library dirs (missing on some builds).

    Some xed builds install Xed-1.0.typelib and libxed.so to a private dir
    (e.g. /usr/lib64/xed/...) without adding it to GI's or the linker's
    search paths, which breaks *every* Python plugin with
    "Namespace Xed not available". Point GI and the loader at it ourselves.
    """
    try:
        typelib_dirs = [
            os.path.join(d, "girepository-1.0")
            for d in _XED_LIBDIRS
            if os.path.isfile(os.path.join(d, "girepository-1.0", "Xed-1.0.typelib"))
        ]
        if typelib_dirs:
            old = os.environ.get("GI_TYPELIB_PATH", "")
            os.environ["GI_TYPELIB_PATH"] = ":".join(
                typelib_dirs + ([old] if old else [])
            )
            try:
                import gi as _gi

                try:
                    _gi.require_version("GIRepository", "3.0")
                except Exception:
                    try:
                        _gi.require_version("GIRepository", "2.0")
                    except Exception:
                        pass
                from gi.repository import GIRepository  # noqa: E402  # type: ignore

                repo = None
                for meth in ("dup_default", "get_default"):
                    try:
                        repo = getattr(GIRepository.Repository, meth)()
                        break
                    except Exception:
                        continue
                if repo is not None:
                    for path in typelib_dirs:
                        try:
                            repo.prepend_search_path(path)
                        except Exception:
                            pass
            except Exception as e:
                sys.stderr.write(f"[xed-csharp] GI path setup failed: {e!r}\n")
        for libdir in _XED_LIBDIRS:
            candidate = os.path.join(libdir, "libxed.so")
            if os.path.isfile(candidate):
                try:
                    import ctypes

                    ctypes.CDLL(candidate, mode=ctypes.RTLD_GLOBAL)
                except Exception as e:
                    sys.stderr.write(f"[xed-csharp] libxed preload failed: {e!r}\n")
                break
    except Exception as e:
        sys.stderr.write(f"[xed-csharp] typelib setup failed: {e!r}\n")


try:
    import gi

    _ensure_xed_gi_paths()

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Pango", "1.0")
    gi.require_version("Xed", "1.0")

    from gi.repository import GObject, Gtk, Gdk, Gio, GLib, Pango, Xed  # type: ignore

    from .logging_util import debug, error, marker
    from .settings import SettingsStore
    from . import deps as deps_mod
    from . import dotnet_cli
    from . import solution as solution_mod
    from . import roslyn as roslyn_mod
    from . import intelligence as intel
    from . import testing as testing_mod
    from . import debugging as debugging_mod
    from . import dap as dap_mod
    from . import breakpoints as breakpoints_mod
    from .explorer import SolutionExplorer
    from .output import OutputView
    from .testpanel import TestPanel
    from .debugpanel import DebugPanel
    from .fuzzy import FuzzyFinderDialog
    from .completion import COMMIT_CHARS, CompletionPopup, NAV_KEYS
    from . import gscompletion as gs_mod
    from .views import (
        ViewTracker,
        buffer_text,
        cursor_line0,
        cursor_offset,
        doc_path,
        is_csharp_doc,
    )

    try:
        gi.require_version("GtkSource", "4")
        from gi.repository import GtkSource  # type: ignore

        _GTKSOURCE_AVAILABLE = True
    except Exception as _e:
        GtkSource = None  # type: ignore
        _GTKSOURCE_AVAILABLE = False
        try:
            error(f"missing optional dependency: GtkSource-4 typelib ({_e}). "
                  "Falling back to the custom completion popup.")
        except Exception:
            pass

    _GTK_AVAILABLE = True
    _note_imported = globals().get("marker")
    if callable(_note_imported):
        _note_imported("module-imported gtk_ok=True")
except Exception:  # headless unit tests / missing typelib outside xed
    # LOUD fallback: never swallow import errors inside xed. If this branch
    # runs inside xed (rather than headless tests), something is broken and
    # the user must see the traceback instead of total silence.
    traceback.print_exc()
    try:
        from .logging_util import error as _fallback_error

        _fallback_error("IMPORT-FALLBACK: GUI imports failed, dummy plugin active. "
                        "See traceback above; likely missing python3-gi or Xed typelib.")
    except Exception:
        pass
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
        def idle_add(fn, *args):
            try:
                return fn(*args)
            except Exception:
                return None

        @staticmethod
        def timeout_add(_ms, _cb):
            return None

        @staticmethod
        def source_remove(_sid):
            return None

        @staticmethod
        def get_user_cache_dir():
            import tempfile

            return tempfile.gettempdir()

    GObject = _DummyGObject  # type: ignore[no-redef]
    Xed = _DummyXed  # type: ignore[no-redef]
    GLib = _DummyGLib  # type: ignore[no-redef]
    Gtk = Gio = Gdk = Pango = None  # type: ignore[no-redef]
    GtkSource = None  # type: ignore[no-redef]
    SolutionExplorer = OutputView = TestPanel = None  # type: ignore[no-redef]
    FuzzyFinderDialog = None  # type: ignore[no-redef]
    DebugPanel = CompletionPopup = ViewTracker = None  # type: ignore[no-redef]
    NAV_KEYS = frozenset()  # type: ignore[no-redef]
    COMMIT_CHARS = frozenset({".", "(", "["})  # type: ignore[no-redef]
    SettingsStore = None  # type: ignore[no-redef]
    buffer_text = cursor_line0 = cursor_offset = doc_path = None  # type: ignore[no-redef]
    is_csharp_doc = None  # type: ignore[no-redef]

    from . import dotnet_cli  # noqa: E402
    from . import solution as solution_mod  # noqa: E402
    from . import roslyn as roslyn_mod  # noqa: E402
    from . import intelligence as intel  # noqa: E402
    from . import testing as testing_mod  # noqa: E402
    from . import debugging as debugging_mod  # noqa: E402
    from . import dap as dap_mod  # noqa: E402
    from . import breakpoints as breakpoints_mod  # noqa: E402
    from . import gscompletion as gs_mod  # noqa: E402
    from . import deps as deps_mod  # noqa: E402
    from .logging_util import debug, error  # noqa: E402

    _GTK_AVAILABLE = False
    _GTKSOURCE_AVAILABLE = False


def _note(*args, **kwargs) -> None:
    """Env-gated activation marker; no-op when GUI imports are unavailable."""
    fn = globals().get("marker")
    if callable(fn):
        fn(*args, **kwargs)


DIAG_TAG_NAMES = {1: "xedcsharp-diag-error", 2: "xedcsharp-diag-warning", 3: "xedcsharp-diag-info"}
DIAG_MARK_CATEGORY = "xedcsharp-diagnostic"
BP_MARK_CATEGORY = "xedcsharp-breakpoint"
FRAME_MARK_CATEGORY = "xedcsharp-frame"


def _gio_file_path(location) -> str | None:
    try:
        if location is None:
            return None
        if location.has_uri_scheme("file"):
            return location.get_path()
        return None
    except Exception:
        return None


PANEL_ICONS = {
    "solution": ("application-x-executable", "folder", "package-x-generic"),
    "tests": ("applications-science", "system-run", "dialog-information"),
    "output": ("utilities-terminal", "text-x-generic", "dialog-information"),
    "debug": ("media-playback-start", "system-run", "dialog-information"),
}


def _pick_panel_icon(candidates) -> str:
    """First installed icon name (names verified against Adwaita/Legacy)."""
    try:
        from gi.repository import Gtk as _Gtk

        theme = _Gtk.IconTheme.get_default()
        if theme is not None:
            for name in candidates:
                try:
                    if theme.has_icon(name):
                        return name
                except Exception:
                    continue
    except Exception:
        pass
    return candidates[0]


def _add_to_panel(panel, widget, title: str, icon_key: str) -> bool:
    # XedPanel.add_item(item, name, icon_name): name and icon are what the
    # tab shows. Passing anything else as icon_name renders the broken-image
    # placeholder (circle with a cross).
    icon = _pick_panel_icon(PANEL_ICONS.get(icon_key, ("dialog-information",)))
    for attempt in (
        lambda: panel.add_item(widget, title, icon),
        lambda: panel.add(widget),
    ):
        try:
            attempt()
            return True
        except Exception as e:
            debug(f"panel add attempt failed: {e!r}")
            continue
    return False


def _remove_from_panel(panel, widget) -> None:
    for attempt in (lambda: panel.remove_item(widget), lambda: panel.remove(widget)):
        try:
            attempt()
            return
        except Exception as e:
            debug(f"panel remove attempt failed: {e!r}")
            continue


def _find_documents_widget(widget, skip: tuple = ()):
    """Locate xed's built-in open-documents list (XedDocumentsPanel).

    Not exposed in the GIR, so match by runtime type name. Never descends
    into our own panels.
    """
    try:
        if any(widget is owned for owned in skip):
            return None
    except Exception:
        pass
    try:
        if type(widget).__name__ == "XedDocumentsPanel":
            return widget
    except Exception:
        return None
    try:
        children = widget.get_children()
    except Exception:
        return None
    for child in children or []:
        found = _find_documents_widget(child, skip)
        if found is not None:
            return found
    return None


class CSharpDevKitPlugin(GObject.Object, Xed.WindowActivatable):  # type: ignore[misc]
    __gtype_name__ = "XedCSharpDevKitPlugin"

    window = GObject.Property(type=Xed.Window)  # type: ignore[arg-type]

    def __init__(self) -> None:
        super().__init__()
        self.settings = SettingsStore()
        self.explorer: SolutionExplorer | None = None
        self.testpanel: TestPanel | None = None
        self.output: OutputView | None = None
        self.debugpanel: DebugPanel | None = None
        self.tracker: ViewTracker | None = None
        self.completion_popup: CompletionPopup | None = None
        self._gs_provider = None
        self._gs_attached: set = set()
        self.roslyn = roslyn_mod.RoslynManager(
            on_diagnostics=self._on_diagnostics,
            ui_dispatch=lambda fn: GLib.idle_add(fn),
            on_error=self._on_roslyn_error,
            on_ready=self._on_roslyn_ready,
        )
        self.dap = dap_mod.DapSession(
            on_event=self._on_dap_event,
            ui_dispatch=lambda fn: GLib.idle_add(fn),
        )
        self.breakpoints = breakpoints_mod.BreakpointStore()
        self.diagnostics: dict[str, list[intel.Diagnostic]] = {}
        self._model: solution_mod.SolutionModel | None = None
        self._signal_ids: list[tuple[object, int]] = []
        self._refresh_source: int | None = None
        self._doc_versions: dict[str, int] = {}
        self._pending_completion: dict | None = None
        self._completion_forward: tuple | None = None
        self._mark_views_configured: set[int] = set()
        self._dap_thread: int | None = None
        self._dap_project: str | None = None
        self._discovering_tests = False
        self._completion_warned = ""
        self._solution_files: list[str] = []
        self._hidden_docs = None
        self._workspace_override: str | None = None

    # -- activation --------------------------------------------------
    def do_activate(self) -> None:
        _note("do_activate called")
        debug("activate: C# DevKit for xed starting up")
        self.explorer = SolutionExplorer()
        self.testpanel = TestPanel()
        self.output = OutputView()
        self.debugpanel = DebugPanel()
        self.tracker = ViewTracker()
        self.completion_popup = CompletionPopup()

        side = self._safe(lambda: self.window.get_side_panel())
        bottom = self._safe(lambda: self.window.get_bottom_panel())
        if side is not None:
            if self.explorer is not None and not _add_to_panel(side, self.explorer, "C# Solution", "solution"):
                debug("side panel (explorer) add failed")
            if self.testpanel is not None and not _add_to_panel(side, self.testpanel, "C# Tests", "tests"):
                debug("side panel (tests) add failed")
        if bottom is not None:
            if self.output is not None and not _add_to_panel(bottom, self.output, "C# Output", "output"):
                debug("bottom panel (output) add failed")
            if self.debugpanel is not None and not _add_to_panel(bottom, self.debugpanel, "C# Debug", "debug"):
                debug("bottom panel (debug) add failed")
        self._report_startup_deps()
        self._hide_documents_panel()
        try:
            GLib.idle_add(self._close_untouched_starter_doc)
        except Exception:
            pass

        if self.explorer is not None:
            self._connect(self.explorer, "open-file", lambda _w, p: self._jump_to(p, 0, 0))
            self._connect(self.explorer, "build-solution", lambda _w: self._build_solution())
            self._connect(self.explorer, "build-project", lambda _w, p: self._build_project(p))
            self._connect(self.explorer, "run-project", lambda _w, p: self._run_project(p))
            self._connect(self.explorer, "test-project", lambda _w, p: self._run_test_project(p))
            self._connect(self.explorer, "debug-project", lambda _w, p: self._debug_project(p))
            self._connect(self.explorer, "restore", lambda _w: self._restore())
            self._connect(self.explorer, "refresh", lambda _w: self._schedule_refresh())
        if self.testpanel is not None:
            self._connect(self.testpanel, "run-test", lambda _w, p, f: self._run_test_project(p, f or None))
            self._connect(self.testpanel, "run-all-tests", lambda _w: self._run_all_tests())
            self._connect(self.testpanel, "refresh-tests", lambda _w: self._refresh_tests())
        if self.output is not None:
            self._connect(self.output, "jump-to", lambda _w, p, l, c: self._jump_to(p, l, c))
        if self.debugpanel is not None:
            self._connect(self.debugpanel, "debug-launch", lambda _w: self._debug_project(None))
            self._connect(self.debugpanel, "debug-stop", lambda _w: self._debug_stop())
            self._connect(self.debugpanel, "debug-continue", lambda _w: self._dap_simple("continue"))
            self._connect(self.debugpanel, "debug-step-over", lambda _w: self._dap_step("next"))
            self._connect(self.debugpanel, "debug-step-into", lambda _w: self._dap_step("stepIn"))
            self._connect(self.debugpanel, "debug-step-out", lambda _w: self._dap_step("stepOut"))
            self._connect(self.debugpanel, "breakpoints-clear", lambda _w: self._breakpoints_clear())
            self._connect(self.debugpanel, "jump-to", lambda _w, p, l, c: self._jump_to(p, l, c))
        if self.tracker is not None:
            self._connect(self.tracker, "doc-changed", lambda _w, p: self._sync_doc(p))
            self._connect(self.tracker, "doc-saved", lambda _w, p: self._on_doc_saved(p))
            self._connect(self.tracker, "doc-closed", lambda _w, p: self._on_doc_closed(p))
            self._connect(self.tracker, "completion-request", self._on_completion_request)
            self._connect(self.tracker, "goto-definition", self._on_goto_definition)
            self._connect(self.tracker, "find-references", self._on_find_references)
            self._connect(self.tracker, "hover-request", self._on_hover_request)
            self._connect(self.tracker, "format-request", lambda _w, p: self._format_doc_path(p))
            self._connect(self.tracker, "code-action-request", self._on_code_action_request)
            self._connect(self.tracker, "toggle-breakpoint", lambda _w, p, l: self._toggle_breakpoint(p, l))
            self._connect(self.tracker, "launch-debug", lambda _w: self._debug_project(None))
            self._connect(self.tracker, "fuzzy-finder", lambda _w: self._show_fuzzy_finder())
            self._connect(self.tracker, "open-folder", lambda _w: self._open_solution_folder())
            try:
                self.tracker.attach(self.window)
            except Exception as e:
                debug(f"tracker attach failed: {e!r}")
            self._setup_framework_completion()
        if self.completion_popup is not None:
            self._connect(self.completion_popup, "item-activated", lambda _w, i: self._apply_completion(i))
            self._connect(self.completion_popup, "dismissed", lambda _w: self._clear_pending_completion())

        self._connect(self.window, "active-tab-changed", lambda *_a: self._schedule_refresh())
        self._connect(self.window, "tab-added", lambda *_a: self._schedule_refresh())
        if self.debugpanel is not None:
            self.debugpanel.set_breakpoints(self.breakpoints.all())
        self._schedule_refresh()

    def do_deactivate(self) -> None:
        debug("deactivate")
        self._restore_documents_panel()
        if self._refresh_source is not None:
            try:
                GLib.source_remove(self._refresh_source)
            except Exception:
                pass
            self._refresh_source = None
        if self.tracker is not None:
            try:
                self.tracker.detach()
            except Exception:
                pass
            self.tracker = None
        try:
            if self._gs_provider is not None and _GTKSOURCE_AVAILABLE:
                gs_mod.detach_from_views(self.window, self._gs_provider, self._gs_attached)
        except Exception:
            pass
        self._gs_provider = None
        self._disconnect_completion_forward()
        for obj, handler_id in self._signal_ids:
            try:
                obj.disconnect(handler_id)  # type: ignore[attr-defined]
            except Exception:
                pass
        self._signal_ids.clear()
        try:
            self.roslyn.stop()
        except Exception:
            pass
        try:
            self.dap.close()
        except Exception:
            pass
        for widget_name, accessor in (
            ("explorer", lambda: self.window.get_side_panel()),
            ("testpanel", lambda: self.window.get_side_panel()),
            ("output", lambda: self.window.get_bottom_panel()),
            ("debugpanel", lambda: self.window.get_bottom_panel()),
        ):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            panel = self._safe(accessor)
            if panel is not None:
                _remove_from_panel(panel, widget)
            try:
                widget.destroy()
            except Exception:
                pass
            setattr(self, widget_name, None)
        if self.completion_popup is not None:
            try:
                self.completion_popup.destroy()
            except Exception:
                pass
            self.completion_popup = None

    def do_update_state(self) -> None:
        return

    def _hide_documents_panel(self) -> None:
        """Remove xed's built-in open-documents list from the side panel.

        Soft-only: anything unexpected aborts silently and the list stays.
        Restored by _restore_documents_panel on deactivate.
        """
        try:
            if getattr(self, "_hidden_docs", None) is not None:
                return
            settings = getattr(self, "settings", None)
            try:
                enabled = bool(settings.get("hide_documents_panel")) if settings else True
            except Exception:
                enabled = True
            if not enabled:
                return
            side = self._safe(lambda: self.window.get_side_panel())
            if side is None:
                return
            owned = tuple(
                w for w in (
                    getattr(self, "explorer", None),
                    getattr(self, "testpanel", None),
                    getattr(self, "output", None),
                    getattr(self, "debugpanel", None),
                )
                if w is not None
            )
            found = _find_documents_widget(side, skip=owned)
            if found is None:
                return
            try:
                removed = bool(side.remove_item(found))
            except Exception:
                removed = False
            if not removed:
                try:
                    side.remove(found)
                    removed = True
                except Exception as e:
                    debug(f"documents panel remove failed: {e!r}")
                    return
            self._hidden_docs = found
            debug("documents panel hidden")
        except Exception as e:
            debug(f"documents panel hide failed: {e!r}")

    def _close_untouched_starter_doc(self) -> None:
        """Close xed's blank starter doc (single untouched, location-less tab)."""
        try:
            settings = getattr(self, "settings", None)
            if settings is not None and not bool(settings.get("close_untitled_on_startup")):
                return
        except Exception:
            pass
        try:
            docs = list(self.window.get_documents())
        except Exception:
            return
        if len(docs) != 1:
            return
        doc = docs[0]
        try:
            if not doc.is_untouched() or doc_path(doc) is not None:
                return
        except Exception:
            return
        try:
            tab = self.window.get_active_tab()
        except Exception:
            tab = None
        if tab is None:
            return
        try:
            self.window.close_tab(tab)
            debug("closed untouched starter doc")
        except Exception as e:
            debug(f"starter doc close failed: {e!r}")

    def _restore_documents_panel(self) -> None:
        widget, self._hidden_docs = getattr(self, "_hidden_docs", None), None
        if widget is None:
            return
        try:
            side = self._safe(lambda: self.window.get_side_panel())
            if side is None:
                return
            try:
                side.add_item(widget, "Documents", "text-x-generic")
            except Exception:
                try:
                    side.add(widget)
                except Exception as e:
                    debug(f"documents panel restore failed: {e!r}")
        except Exception as e:
            debug(f"documents panel restore failed: {e!r}")

    def _report_startup_deps(self) -> None:
        try:
            settings = getattr(self, "settings", None)
            try:
                dotnet = str(settings.get("dotnet_executable")) if settings else "dotnet"
            except Exception:
                dotnet = "dotnet"
            try:
                roslyn_server = str(settings.get("roslyn_server")) if settings else "~/.dotnet/tools/roslyn-language-server"
            except Exception:
                roslyn_server = "~/.dotnet/tools/roslyn-language-server"
            try:
                netcoredbg_path = str(settings.get("netcoredbg_path")) if settings else "netcoredbg"
            except Exception:
                netcoredbg_path = "netcoredbg"
            issues = deps_mod.check_all(
                dotnet=dotnet or "dotnet",
                roslyn_server=roslyn_server,
                netcoredbg_path=netcoredbg_path,
            )
        except Exception as e:
            try:
                error(f"startup check failed: {e!r}")
            except Exception:
                pass
            return
        for issue in issues:
            try:
                error(f"startup check: {issue.log_line()}")
            except Exception:
                pass
        if issues and self.output is not None:
            try:
                hard = [i for i in issues if not i.warn_only]
                if hard:
                    self.output.append("C# startup check: missing " + ", ".join(i.name for i in hard) + "\n")
            except Exception:
                pass

    # -- helpers -----------------------------------------------------
    @staticmethod
    def _safe(fn):
        try:
            return fn()
        except Exception as e:
            debug(f"window accessor failed: {e!r}")
            return None

    def _connect(self, obj, signal: str, callback) -> None:
        try:
            handler_id = obj.connect(signal, callback)
            self._signal_ids.append((obj, handler_id))
        except Exception as e:
            debug(f"connect {signal} failed: {e!r}")

    def _active_path(self) -> str | None:
        doc = self._safe(lambda: self.window.get_active_document())
        if doc is None:
            return None
        return doc_path(doc)

    def _open_doc_dir(self) -> str | None:
        """Directory of any open document with a path (even if not active)."""
        try:
            docs = self._safe(lambda: list(self.window.get_documents())) or []
        except Exception:
            return None
        for doc in docs:
            try:
                path = doc_path(doc)
            except Exception:
                continue
            if path:
                try:
                    return os.path.dirname(path) or None
                except Exception:
                    return None
        return None

    @staticmethod
    def _startup_dir() -> str | None:
        """xed's working directory (where it was launched).

        With no document open there is no active path, so discovery would
        otherwise start at $HOME and miss a nearby .sln/.slnx. The process
        cwd reflects the launch directory for terminal launches; the home
        and crawl guards downstream keep menu launches safe.
        """
        try:
            cwd = os.getcwd()
        except Exception:
            return None
        try:
            return cwd if os.path.isdir(cwd) else None
        except Exception:
            return None

    def _find_doc(self, path: str):
        try:
            for doc in self.window.get_documents():
                if doc_path(doc) == path:
                    return doc
        except Exception as e:
            debug(f"_find_doc failed: {e!r}")
        return None

    def _iter_csharp_docs(self):
        try:
            docs = self.window.get_documents()
        except Exception:
            return
        for doc in docs:
            try:
                if is_csharp_doc(doc):
                    yield doc_path(doc), doc
            except Exception:
                continue

    def _schedule_refresh(self) -> None:
        if self._refresh_source is not None:
            try:
                GLib.source_remove(self._refresh_source)
            except Exception:
                pass
        try:
            self._refresh_source = GLib.timeout_add(250, self._refresh_cb)
        except Exception:
            self._refresh_cb()

    def _refresh_cb(self) -> bool:
        self._refresh_source = None
        try:
            self._refresh_solution()
        except Exception as e:
            debug(f"refresh failed: {e!r}")
        # Safety net: xed may (re)add its documents list after activation.
        self._hide_documents_panel()
        return False

    # -- solution ----------------------------------------------------
    def _dotnet(self) -> str:
        configured = str(self.settings.get("dotnet_executable") or "dotnet")
        resolved = dotnet_cli.resolve_dotnet(configured)
        return resolved or configured

    def _refresh_solution(self) -> None:
        if self.completion_popup is not None:
            try:
                self.completion_popup.dismiss()
            except Exception:
                pass
        active = self._active_path()
        start = (
            self._workspace_override
            or active
            or self._open_doc_dir()
            or self._startup_dir()
            or os.path.expanduser("~")
        )
        try:
            cwd = os.getcwd()
        except Exception:
            cwd = "?"
        debug(f"refresh solution from {start} (active={active} cwd={cwd})")
        dotnet = self._dotnet()
        self._model = solution_mod.load_solution(start, dotnet)
        try:
            self._solution_files = solution_mod.solution_files(self._model)
        except Exception as e:
            debug(f"solution file index failed: {e!r}")
            self._solution_files = []
        if self.explorer is not None:
            self.explorer.set_model(self._model)
        if self.output is not None:
            if self._model.path:
                self.output.set_status(f"{os.path.basename(self._model.path)} — {len(self._model.projects)} projects")
            else:
                self.output.set_status("No .sln/.slnx found — showing nearby .csproj files")
        for path, _doc in self._iter_csharp_docs():
            self._sync_doc(path)
        if self._model.path or self._model.projects:
            self._ensure_roslyn()
        else:
            self._warn_completion_once(
                "no-solution",
                "no .sln/.slnx or .csproj found; Roslyn not started so completion is unavailable.",
                "No solution found — completion unavailable.",
            )

    # -- roslyn ------------------------------------------------------
    def _ensure_roslyn(self) -> None:
        if self._model is None:
            return
        if getattr(self.roslyn, "state", "") in ("starting", "ready"):
            return
        if solution_mod.is_home_root(self._model.root_dir):
            message = (f"Roslyn not started: workspace root is {self._model.root_dir}. "
                       "Open the solution folder directly (starting it on your home "
                       "directory makes the server crawl symlinks like Wine "
                       "dosdevices/z: into /proc, where it crashes).")
            try:
                error(message)
            except Exception:
                pass
            if self.output is not None:
                self.output.append(message + "\n")
                self.output.set_status("Roslyn not started — open the solution folder.")
            return
        configured = str(self.settings.get("roslyn_server") or "~/.dotnet/tools/roslyn-language-server")
        argv = roslyn_mod.resolve_server_command(configured)
        if argv is None:
            try:
                error(f"Roslyn server not found: {configured}. "
                      "Install: dotnet tool install --global roslyn-language-server")
            except Exception:
                pass
            if self.output is not None:
                self.output.append(f"Roslyn server not found: {configured}\n")
                self.output.append("Install: dotnet tool install --global roslyn-language-server\n")
            return
        try:
            log_dir = os.path.join(GLib.get_user_cache_dir(), "xed", "xed-csharp", "roslyn-logs")
        except Exception:
            log_dir = ""
        try:
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
        except OSError:
            log_dir = ""
        debug(f"roslyn ensure: root={self._model.root_dir} sln={self._model.path} "
              f"state={getattr(self.roslyn, 'state', '?')} argv0={argv[0] if argv else None}")
        ok = self.roslyn.start(
            self._model.path,
            self._model.root_dir,
            argv,
            log_dir=log_dir or None,
            log_level=str(self.settings.get("roslyn_log_level") or "Information"),
            stderr_log_path=os.path.join(log_dir, "roslyn-stderr.log") if log_dir else None,
        )
        debug(f"roslyn ensure: start returned {ok}")
        if not ok:
            try:
                error("Roslyn failed to start (binary missing or spawn failed).")
            except Exception:
                pass
            if self.output is not None:
                self.output.append("Roslyn failed to start.\n")
            return
        if self.output is not None:
            self.output.append(f"Roslyn starting: {' '.join(argv)}\n")

    def _on_roslyn_error(self, message: str) -> None:
        try:
            error(message.splitlines()[0] if message else "Roslyn server error")
        except Exception:
            pass
        if self.output is not None:
            self.output.append(f"\n{message}\n")
            self.output.set_status("Roslyn server died — see Output. Refresh to restart.")

    def _on_roslyn_ready(self) -> None:
        try:
            self._completion_warned = ""
        except Exception:
            pass
        synced = 0
        debug(f"roslyn ready: syncing open docs (open_docs={len(getattr(self.roslyn, 'open_docs', {}))})")
        try:
            for path, _doc in self._iter_csharp_docs():
                try:
                    self._sync_doc(path)
                    synced += 1
                except Exception as e:
                    debug(f"ready sync failed for {path}: {e!r}")
        except Exception as e:
            debug(f"ready sync sweep failed: {e!r}")
        debug(f"roslyn ready: synced {synced} doc(s)")
        if self.output is not None:
            try:
                self.output.set_status(f"Roslyn ready — {synced} C# file(s) synced.")
            except Exception:
                pass

    def _sync_doc(self, path: str) -> None:
        state = getattr(self.roslyn, "state", "")
        if state != "ready":
            debug(f"sync skip {path}: roslyn {state!r}")
            return
        if not path.endswith(".cs"):
            return
        doc = self._find_doc(path)
        if doc is None:
            debug(f"sync skip {path}: no open buffer")
            return
        text = buffer_text(doc)
        version = self._doc_versions.get(path, 0) + 1
        self._doc_versions[path] = version
        try:
            known = any(
                path in uri or uri.endswith(os.path.basename(path)) for uri in self.roslyn.open_docs
            )
        except Exception:
            known = False
        if known:
            debug(f"sync did_change {path} v{version} ({len(text)} chars)")
            self.roslyn.did_change(path, version, text)
        else:
            debug(f"sync did_open {path} v{version} ({len(text)} chars)")
            self.roslyn.did_open(path, "csharp", version, text)

    def _on_doc_saved(self, path: str) -> None:
        if not path.endswith(".cs"):
            return
        doc = self._find_doc(path)
        text = buffer_text(doc) if doc is not None else ""
        try:
            self.roslyn.did_save(path, text)
        except Exception as e:
            debug(f"did_save failed: {e!r}")
        if bool(self.settings.get("format_on_save")):
            self._format_doc_path(path)

    def _on_doc_closed(self, path: str) -> None:
        try:
            self.roslyn.did_close(path)
        except Exception:
            pass
        try:
            uri = roslyn_mod.file_uri(path)
            self.diagnostics.pop(uri, None)
            self._refresh_problems()
        except Exception:
            pass
        self._doc_versions.pop(path, None)

    # -- diagnostics -------------------------------------------------
    def _on_diagnostics(self, uri: str, raw: list) -> None:
        items = intel.normalize_diagnostics(uri, raw)
        self.diagnostics[uri] = items
        total_errors = sum(1 for v in self.diagnostics.values() for d in v if d.severity == 1)
        total_warns = sum(1 for v in self.diagnostics.values() for d in v if d.severity == 2)
        if self.output is not None:
            self.output.set_status(f"C#: {total_errors} errors, {total_warns} warnings")
        self._refresh_problems()
        for path, doc in self._iter_csharp_docs():
            try:
                if roslyn_mod.file_uri(path) == uri:
                    self._render_diagnostics(doc, items)
            except Exception as e:
                debug(f"diagnostics render failed: {e!r}")

    def _refresh_problems(self) -> None:
        if self.output is None:
            return
        rows: list[tuple[str, str, int, str, str]] = []
        for uri, items in self.diagnostics.items():
            for diag in items:
                rows.append(
                    (
                        intel.SEVERITY_LABEL.get(diag.severity, "?"),
                        os.path.basename(diag.path),
                        diag.line + 1,
                        diag.message,
                        diag.path,
                    )
                )
        rows.sort(key=lambda r: (r[1], r[2]))
        self.output.set_problems(rows)

    def _ensure_diag_tags(self, doc) -> dict[int, object]:
        tags: dict[int, object] = {}
        try:
            table = doc.get_tag_table()
        except Exception:
            return tags
        specs = {
            1: ("underline", getattr(Pango.Underline, "ERROR", Pango.Underline.SINGLE)),
            2: ("underline", Pango.Underline.SINGLE),
            3: ("underline", Pango.Underline.SINGLE),
        }
        for severity, tag_name in DIAG_TAG_NAMES.items():
            tag = None
            try:
                tag = table.lookup(tag_name)
            except Exception:
                tag = None
            if tag is None:
                try:
                    prop, value = specs[severity]
                    tag = doc.create_tag(tag_name, **{prop: value})
                    if severity == 1:
                        try:
                            rgba = Gdk.RGBA()
                            if rgba.parse("#e01b24"):
                                tag.set_property("underline-rgba", rgba)
                        except Exception:
                            pass
                    elif severity == 2:
                        try:
                            rgba = Gdk.RGBA()
                            if rgba.parse("#e5a50a"):
                                tag.set_property("underline-rgba", rgba)
                        except Exception:
                            pass
                except Exception as e:
                    debug(f"diag tag create failed: {e!r}")
                    continue
            tags[severity] = tag
        return tags

    def _render_diagnostics(self, doc, items: list) -> None:
        try:
            start, end = doc.get_bounds()
        except Exception:
            return
        tags = self._ensure_diag_tags(doc)
        for tag in tags.values():
            try:
                doc.remove_tag(tag, start, end)
            except Exception:
                pass
        try:
            doc.remove_source_marks(DIAG_MARK_CATEGORY, start, end)
        except Exception:
            pass
        for diag in items:
            tag = tags.get(diag.severity)
            try:
                it = doc.get_iter_at_line(diag.line)
                it.forward_chars(diag.character)
                it_end = doc.get_iter_at_line(diag.line)
                it_end.forward_to_line_end()
                if it_end.get_offset() <= it.get_offset():
                    continue
                if tag is not None:
                    doc.apply_tag(tag, it, it_end)
                try:
                    doc.create_source_mark(None, DIAG_MARK_CATEGORY, it)
                except Exception:
                    pass
            except Exception:
                continue
        self._configure_marks(doc)

    def _configure_marks(self, doc) -> None:
        """Enable gutter marks on views showing this doc (once per view)."""
        if not _GTKSOURCE_AVAILABLE:
            return
        try:
            views = self.window.get_views()
        except Exception:
            return
        for view in views:
            try:
                if view.get_buffer() is not doc:
                    continue
                if hash(view) in self._mark_views_configured:
                    continue
                view.set_show_line_marks(True)
                for category, color in (
                    (DIAG_MARK_CATEGORY, "#e01b24"),
                    (BP_MARK_CATEGORY, "#a51d2d"),
                    (FRAME_MARK_CATEGORY, "#1c71d8"),
                ):
                    try:
                        attrs = GtkSource.MarkAttributes()
                        rgba = Gdk.RGBA()
                        if rgba.parse(color):
                            attrs.set_background(rgba)
                        view.set_mark_attributes(category, attrs, 10)
                    except Exception as e:
                        debug(f"mark attributes {category} failed: {e!r}")
                self._mark_views_configured.add(hash(view))
            except Exception:
                continue

    # -- completion --------------------------------------------------
    def _roslyn_ready(self) -> bool:
        return getattr(self.roslyn, "state", "") == "ready"

    # -- GtkSource framework completion (preferred, wordcompletion-style)
    def _use_framework(self) -> bool:
        try:
            return bool(_GTKSOURCE_AVAILABLE and self._gs_provider is not None)
        except Exception:
            return False

    def _setup_framework_completion(self) -> None:
        if not _GTKSOURCE_AVAILABLE:
            return
        try:
            if self._gs_provider is None:
                self._gs_provider = gs_mod.RoslynCompletionProvider(
                    is_ready=self._roslyn_ready,
                    resolve_path=self._gs_resolve_path,
                    send_request=self._gs_send_request,
                    flush_doc=self._flush_completion_doc,
                )
            if self.tracker is not None:
                self.tracker.framework_completion = True
            self._ensure_gs_providers()
            self._connect(self.window, "tab-added", lambda *_a: self._ensure_gs_providers())
            self._connect(
                self.window, "active-tab-changed", lambda *_a: self._ensure_gs_providers()
            )
        except Exception as e:
            debug(f"framework completion setup failed: {e!r}")
            self._gs_provider = None

    def _ensure_gs_providers(self) -> None:
        if not self._use_framework():
            return
        try:
            gs_mod.attach_to_views(self.window, self._gs_provider, self._gs_attached)
        except Exception as e:
            debug(f"completion provider attach failed: {e!r}")

    def _warn_completion_once(self, key: str, message: str, status: str = "") -> None:
        if self._completion_warned == key:
            return
        self._completion_warned = key
        try:
            error(f"completion unavailable: {message}")
        except Exception:
            pass
        if status and self.output is not None:
            try:
                self.output.set_status(status)
            except Exception:
                pass

    def _gs_resolve_path(self, buf) -> str | None:
        """Map a buffer to its .cs path (None for anything else)."""
        try:
            direct = doc_path(buf)
            if direct and direct.endswith(".cs"):
                return direct
        except Exception:
            pass
        try:
            for doc in self.window.get_documents():
                try:
                    same = doc is buf
                    if not same:
                        try:
                            same = hash(doc) == hash(buf)
                        except Exception:
                            same = False
                    if not same:
                        try:
                            same = doc_path(doc) == doc_path(buf) and doc_path(doc) is not None
                        except Exception:
                            same = False
                    if same:
                        path = doc_path(doc)
                        return path if (path and path.endswith(".cs")) else None
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _gs_send_request(self, method: str, params: dict, callback):
        try:
            request_id = self.roslyn.request(method, params, callback)
        except Exception as e:
            debug(f"framework completion request failed: {e!r}")
            return None
        if request_id is None:
            self._warn_completion_once(
                f"send-{getattr(self.roslyn, 'state', '?')}",
                f"{method} not sent: Roslyn server is {getattr(self.roslyn, 'state', '?')!r}.",
                "Roslyn not running — completion unavailable. Refresh to restart.",
            )
        return request_id

    def _flush_completion_doc(self, path: str) -> None:
        """Synchronously push the buffer to Roslyn before a completion query.

        didChange is normally debounced 400ms; VSCode sends the latest
        text before completing. Best-effort: missing doc/server is fine.
        """
        try:
            if getattr(self.roslyn, "state", "") != "ready":
                return
            doc = self._find_doc(path)
            if doc is None:
                return
            text = buffer_text(doc)
            version = self._doc_versions.get(path, 0) + 1
            self._doc_versions[path] = version
            try:
                known = any(
                    path in uri or uri.endswith(os.path.basename(path))
                    for uri in self.roslyn.open_docs
                )
            except Exception:
                known = False
            if known:
                self.roslyn.did_change(path, version, text)
            else:
                self.roslyn.did_open(path, "csharp", version, text)
        except Exception as e:
            debug(f"completion flush failed: {e!r}")

    def _show_framework_completion(self) -> bool:
        """Force the GtkSource popup open (explicit invoke, VSCode Ctrl+Space)."""
        try:
            if not self._use_framework():
                self._warn_completion_once(
                    "no-framework",
                    "GtkSource completion unavailable; install gir1.2-gtksource-4.",
                    "Completion unavailable (no GtkSource).",
                )
                return False
            if not self._roslyn_ready():
                self._warn_completion_once(
                    f"not-ready-{getattr(self.roslyn, 'state', '?')}",
                    f"Roslyn server is {getattr(self.roslyn, 'state', '?')!r}; invoke ignored.",
                    "Roslyn not ready — completion unavailable yet.",
                )
                return False
            view = self._safe(lambda: self.window.get_active_view())
            if view is None:
                return False
            opened = bool(gs_mod.show_completion(view, self._gs_provider))
            debug(f"completion show: opened={opened}")
            if not opened:
                self._warn_completion_once(
                    "show-failed",
                    "GtkSource completion.start() refused the request.",
                    "Completion popup would not open.",
                )
            return opened
        except Exception as e:
            debug(f"completion show failed: {e!r}")
            return False

    def _completion_visible(self) -> bool:
        try:
            return bool(self.completion_popup is not None and self.completion_popup.get_visible())
        except Exception:
            return False

    def _on_completion_request(self, _tracker, path: str, line: int, char: int, trigger: str) -> None:
        debug(f"completion-request: path={path} line={line} char={char} trigger={trigger} "
              f"ready={self._roslyn_ready()} framework={self._use_framework()}")
        if not self._roslyn_ready():
            self._warn_completion_once(
                f"not-ready-{getattr(self.roslyn, 'state', '?')}",
                f"Roslyn server is {getattr(self.roslyn, 'state', '?')!r}; completion skipped for {path}.",
                "Roslyn not ready — completion unavailable yet.",
            )
            return
        try:
            self._completion_warned = ""
        except Exception:
            pass
        if self._use_framework():
            # GtkSource interactive activation already populated on every
            # keystroke; the tracker no longer emits auto triggers in this
            # mode. Only explicit invokes arrive here (fallback key
            # bindings / menus): force the popup open at the cursor.
            if trigger == "invoke":
                self._show_framework_completion()
            return
        doc = self._find_doc(path)
        if doc is None:
            return
        if self.completion_popup is None:
            return
        # Live filtering: the list is already up and the user typed another
        # word char -> just narrow locally, no new LSP round-trip.
        if self._completion_visible() and trigger.startswith("auto:"):
            try:
                self._refilter_completion()
            except Exception as e:
                debug(f"completion refilter failed: {e!r}")
            return
        # Single-char auto triggers only pop a NEW list up once the prefix
        # is meaningful; a visible list is handled above.
        if trigger.startswith("auto:"):
            if len(trigger[len("auto:"):]) < 2:
                return
            trigger_kind, trigger_char = 1, None
        else:
            trigger_kind = 1 if trigger == "invoke" else 2
            trigger_char = trigger if len(trigger) == 1 else None
        params = intel.position_params(path, line, char)
        params["context"] = {
            "triggerKind": trigger_kind,
            "triggerCharacter": trigger_char,
        }
        self._pending_completion = {"path": path, "line": line, "char": char}
        self.roslyn.request("textDocument/completion", params, self._on_completion_response)

    def _on_completion_response(self, message: dict) -> None:
        pending, self._pending_completion = self._pending_completion, None
        if pending is None or self.completion_popup is None:
            debug(f"fallback completion: dropped (pending={pending is not None}, "
                  f"popup={self.completion_popup is not None})")
            return
        if message.get("error"):
            debug(f"fallback completion error: {message.get('error')}")
            return
        path = pending["path"]
        doc = self._find_doc(path)
        if doc is None:
            debug(f"fallback completion: no buffer for {path}")
            return
        text = buffer_text(doc)
        # The buffer may have moved while Roslyn answered; parse against the
        # request offset but filter against what is typed NOW.
        offset = intel.position_to_offset(text, pending["line"], pending["char"])
        items = intel.parse_completion(message, text, offset)
        debug(f"fallback completion: {len(items)} items for {path}")
        if not items:
            return
        try:
            cur_offset = cursor_offset(doc)
            prefix, _start = intel.prefix_at(text, cur_offset)
            cur_line, cur_char = intel.offset_to_position(text, cur_offset)
        except Exception:
            prefix, cur_line, cur_char = "", pending["line"], pending["char"]
        view = self._safe(lambda: self.window.get_active_view())
        if view is None:
            return
        self.completion_popup.set_items(items, prefix)
        if not self.completion_popup.has_items():
            return  # typed past every match while waiting: stay hidden
        self.completion_popup.show_at_view(view, cur_line, cur_char)
        self._hook_completion_forward(view)
        self._pending_completion = {"path": path}

    def _refilter_completion(self) -> None:
        """Narrow the visible list to the identifier at the cursor."""
        popup = self.completion_popup
        if popup is None or not self._completion_visible():
            return
        pending = self._pending_completion or {}
        path = pending.get("path") or self._active_path()
        if not path:
            return
        doc = self._find_doc(path)
        if doc is None:
            self._dismiss_completion()
            return
        try:
            text = buffer_text(doc)
            prefix, _start = intel.prefix_at(text, cursor_offset(doc))
        except Exception:
            return
        # Cursor left the word (space, ')', cursor move, ...) -> dismiss,
        # exactly like other editors. Commit chars are handled pre-insert
        # in _forward_completion_key so they never reach this branch.
        if not prefix:
            self._dismiss_completion()
            return
        popup.update_filter(prefix)
        if not popup.has_items():
            # Keep the popup up but uncommittable while nothing matches;
            # further typing may match again, Escape/space dismisses.
            pass

    def _apply_completion(self, item) -> None:
        pending = self._pending_completion or {}
        path = pending.get("path") or self._active_path()
        if not path:
            return
        doc = self._find_doc(path)
        if doc is None:
            return
        # Replace the CURRENT word prefix, not the stale range from request
        # time: the user may have typed more characters while filtering.
        try:
            text = buffer_text(doc)
            cur = cursor_offset(doc)
            _prefix, start = intel.prefix_at(text, cur)
        except Exception:
            start, cur = max(0, item.replace_start), max(0, item.replace_end)
        try:
            doc.begin_user_action()
            start_iter = doc.get_iter_at_offset(max(0, start))
            end_iter = doc.get_iter_at_offset(max(0, cur))
            doc.delete(start_iter, end_iter)
            at = doc.get_iter_at_offset(max(0, start))
            doc.insert(at, item.insert_text)
            suffix = intel.completion_suffix(getattr(item, "kind", 0), item.insert_text)
            if suffix:
                try:
                    ahead = at.copy()
                    ahead.forward_char()
                    if ahead.get_offset() > at.get_offset():
                        existing = doc.get_text(at, ahead, True)
                    else:
                        existing = ""
                except Exception:
                    existing = ""
                if existing != suffix:
                    doc.insert(at, suffix)
                    if suffix == "(":
                        try:
                            doc.insert(at, ")")
                            doc.place_cursor(
                                doc.get_iter_at_offset(at.get_offset() - 1)
                            )
                        except Exception as e:
                            debug(f"completion pair insert failed: {e!r}")
            doc.end_user_action()
        except Exception as e:
            debug(f"completion apply failed: {e!r}")
            try:
                doc.end_user_action()
            except Exception:
                pass
        self._dismiss_completion()

    def _dismiss_completion(self) -> None:
        popup, self._pending_completion = self.completion_popup, None
        self._disconnect_completion_forward()
        if popup is not None:
            try:
                # disconnect first so the hide() emission cannot recurse.
                popup.hide()
            except Exception:
                pass

    def _clear_pending_completion(self) -> None:
        self._pending_completion = None
        self._disconnect_completion_forward()

    def _hook_completion_forward(self, view) -> None:
        """Forward navigation keys from the editor view to a visible popup.

        Guarantees keyboard navigation even when the window manager refuses
        focus to the popup (common on Wayland, occasional on X11).
        """
        self._disconnect_completion_forward()
        try:
            handler_id = view.connect("key-press-event", self._forward_completion_key)
            self._completion_forward = (view, handler_id)
        except Exception as e:
            debug(f"completion forward hook failed: {e!r}")

    def _disconnect_completion_forward(self) -> None:
        hook, self._completion_forward = self._completion_forward, None
        if hook is None:
            return
        view, handler_id = hook
        try:
            view.disconnect(handler_id)
        except Exception:
            pass

    def _schedule_refilter(self) -> None:
        """Refilter after the pending keystroke is inserted/deleted."""
        try:
            GLib.idle_add(self._refilter_completion)
        except Exception:
            try:
                self._refilter_completion()
            except Exception:
                pass

    def _forward_completion_key(self, _view, event) -> bool:
        """Editor-view key handling while the popup is visible.

        The editor keeps focus; this runs pre-insert on key-press:
        navigation is consumed, commit chars accept-then-insert (return
        False), plain text falls through and refilters afterwards, and
        cursor-moving / boundary keys dismiss.
        """
        popup = self.completion_popup
        if popup is None:
            return False
        try:
            visible = popup.get_visible()
        except Exception:
            visible = False
        if not visible:
            return False
        try:
            name = Gdk.keyval_name(event.keyval) or ""
        except Exception:
            return False
        if name in NAV_KEYS:
            try:
                consumed = bool(popup.handle_nav_key(name))
                if name == "Escape":
                    self._clear_pending_completion()
                elif name in ("Return", "KP_Enter", "Tab"):
                    # activate_selected() emits item-activated ->
                    # _apply_completion -> _dismiss_completion.
                    pass
                return consumed
            except Exception:
                return False
        # Commit characters: accept the current item first, then let the
        # keystroke insert normally (so '.' chains into member access).
        try:
            typed = Gdk.keyval_to_unicode(event.keyval)
            char = chr(typed) if typed else ""
        except Exception:
            char = ""
        if char in COMMIT_CHARS:
            try:
                if popup.has_items():
                    popup.activate_selected()
                else:
                    self._dismiss_completion()
            except Exception:
                pass
            return False
        if name in ("BackSpace", "Delete", "KP_Delete"):
            self._schedule_refilter()
            return False
        if name in ("Left", "KP_Left", "Right", "KP_Right",
                    "Home", "KP_Home", "End", "KP_End"):
            # Cursor moves -> completion no longer applies.
            self._dismiss_completion()
            return False
        if char and intel.is_identifier_char(char):
            # Let it insert; views.py key-release will refilter, but also
            # cover the case where key-release is missed.
            self._schedule_refilter()
            return False
        if char:
            # Punctuation/space/etc ends the session (commit already
            # handled above). Let it insert, then hide.
            try:
                GLib.idle_add(self._dismiss_completion)
            except Exception:
                pass
            return False
        return False

    # -- navigation / hover ------------------------------------------
    def _jump_to(self, path: str, line0: int, char0: int = 0) -> None:
        try:
            location = Gio.File.new_for_path(path)
        except Exception as e:
            debug(f"jump: bad path {path}: {e!r}")
            return
        existing = None
        try:
            existing = self.window.get_tab_from_location(location)
        except Exception:
            existing = None
        try:
            if existing is not None:
                self.window.set_active_tab(existing)
            else:
                # Xed signature: (location, encoding, line_pos, create, jump_to).
                self.window.create_tab_from_location(
                    location, None, max(0, line0), True, True
                )
        except Exception as e:
            debug(f"jump open failed: {e!r}")
            if self.output is not None:
                self.output.append(f"Cannot open {path}: {e}\n")
            return

        def _go() -> bool:
            doc = self._find_doc(path)
            if doc is None:
                return False
            try:
                doc.goto_line(max(0, line0))
            except Exception:
                try:
                    doc.place_cursor(doc.get_iter_at_line(max(0, line0)))
                except Exception:
                    return False
            try:
                view = self.window.get_active_view()
                if view is not None:
                    view.scroll_to_cursor()
                    view.grab_focus()
            except Exception:
                pass
            return False

        try:
            GLib.idle_add(_go)
        except Exception:
            _go()

    def _open_file(self, path: str) -> None:
        self._jump_to(path, 0, 0)

    def _open_solution_folder(self) -> None:
        try:
            dialog = Gtk.FileChooserDialog(
                title="Open Solution Folder",
                action=Gtk.FileChooserAction.SELECT_FOLDER,
            )
            try:
                dialog.set_transient_for(self.window)
                dialog.set_modal(True)
            except Exception as e:
                debug(f"folder chooser transient failed: {e!r}")
            dialog.add_buttons(
                "_Cancel", Gtk.ResponseType.CANCEL,
                "_Open", Gtk.ResponseType.ACCEPT,
            )
        except Exception as e:
            debug(f"folder chooser create failed: {e!r}")
            return
        try:
            folder = dialog.get_filename() if dialog.run() == Gtk.ResponseType.ACCEPT else None
        except Exception as e:
            debug(f"folder chooser failed: {e!r}")
            folder = None
        finally:
            try:
                dialog.destroy()
            except Exception:
                pass
        if not folder:
            return
        sln = solution_mod.find_solution(folder)
        if sln is None:
            message = f"No .sln/.slnx found under {folder}"
            try:
                error(message)
            except Exception:
                pass
            if self.output is not None:
                self.output.append(message + "\n")
                self.output.set_status(message)
            return
        self._workspace_override = os.path.dirname(sln)
        debug(f"workspace override -> {self._workspace_override}")
        self._schedule_refresh()
        first_cs = self._first_cs_under(os.path.dirname(sln))
        if first_cs:
            self._jump_to(first_cs, 0, 0)
        elif self.output is not None:
            self.output.set_status(f"{os.path.basename(sln)} selected — no .cs files found.")

    @staticmethod
    def _first_cs_under(root: str) -> str | None:
        try:
            nodes = solution_mod.project_tree(root)
        except Exception:
            return None
        stack = list(nodes)
        while stack:
            node = stack.pop(0)
            if node.is_dir:
                stack = list(node.children) + stack
            elif node.path.endswith(".cs"):
                return node.path
        return None

    def _show_fuzzy_finder(self) -> None:
        files = list(getattr(self, "_solution_files", None) or [])
        if not files:
            debug("fuzzy: index empty, refreshing synchronously")
            try:
                self._refresh_solution()
            except Exception as e:
                debug(f"fuzzy refresh failed: {e!r}")
            files = list(getattr(self, "_solution_files", None) or [])
        debug(f"fuzzy: {len(files)} file(s) indexed")
        if not files:
            self._open_solution_folder()
            return
        if FuzzyFinderDialog is None:
            debug("fuzzy finder unavailable (no GTK)")
            return
        root = ""
        try:
            root = (self._model.root_dir if self._model else "") or ""
        except Exception:
            root = ""
        items: list[tuple[str, str]] = []
        for path in files:
            try:
                display = os.path.relpath(path, root) if root else path
            except Exception:
                display = path
            items.append((display, path))
        try:
            dialog = FuzzyFinderDialog(parent=self.window)
        except Exception as e:
            debug(f"fuzzy dialog create failed: {e!r}")
            return
        dialog.set_files(items)
        dialog.connect("open-file", lambda _w, p: (self._jump_to(p, 0, 0), dialog.destroy()))
        try:
            dialog.run()
        finally:
            try:
                dialog.destroy()
            except Exception:
                pass

    def _on_goto_definition(self, _tracker, path: str, line: int, char: int) -> None:
        if not self._roslyn_ready():
            return
        self.roslyn.request(
            "textDocument/definition",
            intel.position_params(path, line, char),
            self._on_definition_response,
        )

    def _on_definition_response(self, message: dict) -> None:
        targets = intel.parse_locations(message)
        if not targets:
            if self.output is not None:
                self.output.set_status("No definition found.")
            return
        first = targets[0]
        self._jump_to(first.path, first.line, first.character)
        if len(targets) > 1 and self.output is not None:
            self.output.set_problems(
                [("definition", os.path.basename(t.path), t.line + 1, t.path, t.path) for t in targets]
            )
            self.output.show_problems()

    def _on_find_references(self, _tracker, path: str, line: int, char: int) -> None:
        if not self._roslyn_ready():
            return
        params = intel.position_params(path, line, char)
        params["context"] = {"includeDeclaration": True}
        self.roslyn.request("textDocument/references", params, self._on_references_response)

    def _on_references_response(self, message: dict) -> None:
        targets = intel.parse_locations(message)
        if self.output is None:
            return
        if not targets:
            self.output.set_status("No references found.")
            return
        self.output.set_problems(
            [("reference", os.path.basename(t.path), t.line + 1, t.path, t.path) for t in targets]
        )
        self.output.show_problems()
        self.output.set_status(f"{len(targets)} reference(s).")

    def _on_hover_request(self, _tracker, path: str, line: int, char: int) -> None:
        if not self._roslyn_ready() or self.tracker is None:
            return
        self.roslyn.request(
            "textDocument/hover",
            intel.position_params(path, line, char),
            lambda message: self.tracker.show_hover_text(intel.parse_hover(message)),
        )

    # -- formatting / code actions -----------------------------------
    def _format_doc_path(self, path: str) -> None:
        if not self._roslyn_ready():
            return
        doc = self._find_doc(path)
        if doc is None:
            return
        params = {
            "textDocument": {"uri": roslyn_mod.file_uri(path)},
            "options": {"tabSize": 4, "insertSpaces": True},
        }
        self.roslyn.request("textDocument/formatting", params, lambda m: self._on_format_response(path, m))

    def _on_format_response(self, path: str, message: dict) -> None:
        doc = self._find_doc(path)
        if doc is None:
            return
        edits = (message or {}).get("result") or []
        if not edits:
            if self.output is not None:
                self.output.set_status("Already formatted.")
            return
        ops = intel.text_edits_to_ops(edits, buffer_text(doc))
        if not ops:
            return
        try:
            doc.begin_user_action()
            for op in ops:
                start = doc.get_iter_at_offset(max(0, op.start))
                end = doc.get_iter_at_offset(max(0, op.end))
                doc.delete(start, end)
                doc.insert(doc.get_iter_at_offset(max(0, op.start)), op.new_text)
            doc.end_user_action()
            if self.output is not None:
                self.output.set_status("Document formatted.")
        except Exception as e:
            debug(f"format apply failed: {e!r}")
            try:
                doc.end_user_action()
            except Exception:
                pass

    def _on_code_action_request(self, _tracker, path: str, line: int, char: int) -> None:
        if not self._roslyn_ready():
            return
        uri = roslyn_mod.file_uri(path)
        diags_raw = []
        for diag in self.diagnostics.get(uri, []):
            if diag.line == line:
                diags_raw.append(
                    {
                        "range": {
                            "start": {"line": diag.line, "character": diag.character},
                            "end": {"line": diag.line, "character": diag.character},
                        },
                        "severity": diag.severity,
                        "message": diag.message,
                    }
                )
        params = intel.position_params(path, line, char)
        params["context"] = {"diagnostics": diags_raw}
        self.roslyn.request("textDocument/codeAction", params, lambda m: self._on_code_actions(path, m))

    def _on_code_actions(self, path: str, message: dict) -> None:
        actions = intel.parse_code_actions(message)
        if not actions:
            if self.output is not None:
                self.output.set_status("No quick fixes available.")
            return
        menu = Gtk.Menu()
        for action in actions[:12]:
            item = Gtk.MenuItem.new_with_label(action.title)
            item.connect("activate", lambda _i, a=action: self._apply_code_action(path, a))
            menu.append(item)
        menu.show_all()
        try:
            menu.popup_at_pointer(None)
        except Exception as e:
            debug(f"code action menu failed: {e!r}")

    def _apply_code_action(self, path: str, action) -> None:
        if action.edit:
            self._apply_workspace_edit(action.edit)
        elif action.needs_resolve:
            self.roslyn.request(
                "codeAction/resolve", {"title": action.title, "data": action.data, "kind": action.kind},
                lambda m: self._apply_resolved_action(path, m),
            )
        elif action.command:
            cmd = action.command
            self.roslyn.request(
                "workspace/executeCommand",
                {"command": cmd.get("command", ""), "arguments": cmd.get("arguments", [])},
                lambda m: self._status_from_command(m),
            )
        else:
            if self.output is not None:
                self.output.set_status(f"No edit for: {action.title}")

    def _apply_resolved_action(self, path: str, message: dict) -> None:
        result = (message or {}).get("result") or {}
        edit = result.get("edit")
        if edit:
            self._apply_workspace_edit(edit)
        else:
            command = result.get("command")
            if command:
                self.roslyn.request(
                    "workspace/executeCommand",
                    {"command": command.get("command", ""), "arguments": command.get("arguments", [])},
                    lambda m: self._status_from_command(m),
                )

    def _status_from_command(self, message: dict) -> None:
        if self.output is None:
            return
        if (message or {}).get("error"):
            self.output.set_status(f"Command failed: {(message.get('error') or {}).get('message', '?')}")
        else:
            self.output.set_status("Command applied.")

    def _apply_workspace_edit(self, edit: dict) -> None:
        texts: dict[str, str] = {}
        try:
            for doc in self.window.get_documents():
                p = doc_path(doc)
                if p:
                    texts[roslyn_mod.file_uri(p)] = buffer_text(doc)
        except Exception:
            pass
        ops_by_uri = intel.workspace_edit_to_ops(edit, texts)
        applied = 0
        for uri, ops in ops_by_uri.items():
            if not ops:
                continue
            fpath = uri[7:] if uri.startswith("file://") else uri
            doc = self._find_doc(fpath)
            try:
                if doc is not None:
                    doc.begin_user_action()
                    for op in ops:
                        start = doc.get_iter_at_offset(max(0, op.start))
                        end = doc.get_iter_at_offset(max(0, op.end))
                        doc.delete(start, end)
                        doc.insert(doc.get_iter_at_offset(max(0, op.start)), op.new_text)
                    doc.end_user_action()
                    applied += 1
                elif fpath and os.path.isfile(fpath):
                    with open(fpath, "r", encoding="utf-8") as f:
                        current = f.read()
                    new_text = intel.apply_ops_to_text(current, ops)
                    with open(fpath, "w", encoding="utf-8") as f:
                        f.write(new_text)
                    applied += 1
            except Exception as e:
                debug(f"workspace edit apply failed for {fpath}: {e!r}")
                try:
                    if doc is not None:
                        doc.end_user_action()
                except Exception:
                    pass
        if self.output is not None:
            self.output.set_status(f"Applied edits to {applied} file(s).")

    # -- build / run / test actions ----------------------------------
    def _run_stream(self, argv: list[str], cwd: str, label: str) -> None:
        if self.output is None:
            return
        self.output.append(f"\n$ {' '.join(argv)}\n")
        self.output.set_status(label + "…")

        def on_line(_stream: str, text: str) -> None:
            assert self.output is not None
            self.output.append(text)

        def on_done(returncode: int) -> None:
            def _done() -> None:
                assert self.output is not None
                self.output.append(f"\n(exit {returncode})\n")
                self.output.set_status(f"{label}: exit {returncode}")
                if "Build" in label or "Restore" in label:
                    self._schedule_refresh()

            GLib.idle_add(_done)

        dotnet_cli.run_streaming(argv, cwd, on_line, on_done)

    def _build_solution(self) -> None:
        if not self._model:
            return
        target = self._model.path or self._model.root_dir
        self._run_stream([self._dotnet(), "build", target], self._model.root_dir, "Build")

    def _build_project(self, project: str) -> None:
        root = self._model.root_dir if self._model else os.path.dirname(project)
        self._run_stream([self._dotnet(), "build", project], root, "Build project")

    def _run_project(self, project: str) -> None:
        root = self._model.root_dir if self._model else os.path.dirname(project)
        self._run_stream([self._dotnet(), "run", "--project", project], root, "Run")

    def _restore(self) -> None:
        if not self._model:
            return
        target = self._model.path or self._model.root_dir
        self._run_stream([self._dotnet(), "restore", target], self._model.root_dir, "Restore")

    # -- test explorer -----------------------------------------------
    def _test_projects(self) -> list:
        if not self._model:
            return []
        return [p for p in self._model.projects if p.is_test_project] or list(self._model.projects)

    def _refresh_tests(self) -> None:
        if self.testpanel is None or self._discovering_tests:
            return
        projects = self._test_projects()
        if not projects:
            self.testpanel.set_status("No projects in solution.")
            return
        self._discovering_tests = True
        self.testpanel.set_projects([(p.name, p.path) for p in projects])
        dotnet = self._dotnet()

        def _worker() -> None:
            results: dict[str, list[str]] = {}
            for project in projects:
                try:
                    results[project.path] = testing_mod.list_tests(dotnet, project.path)
                except Exception as e:
                    debug(f"test discovery failed for {project.path}: {e!r}")
                    results[project.path] = []

            def _done() -> bool:
                self._discovering_tests = False
                if self.testpanel is not None:
                    self.testpanel.set_tests(results)
                return False

            GLib.idle_add(_done)

        threading.Thread(target=_worker, name="xedcsharp-test-discover", daemon=True).start()

    def _run_test_project(self, project: str, fqn: str | None = None) -> None:
        if self.output is None or self.testpanel is None:
            return
        root = self._model.root_dir if self._model else os.path.dirname(project)
        argv = [self._dotnet(), "test", project, "--nologo", "-v", "n"]
        if fqn:
            argv += ["--filter", f"FullyQualifiedName={fqn}"]
        label = f"Test {os.path.basename(project)}{f':{fqn}' if fqn else ''}"
        self.testpanel.mark_running(project, fqn)
        self.output.append(f"\n$ {' '.join(argv)}\n")
        self.output.set_status(label + "…")
        lines: list[str] = []

        def on_line(_stream: str, text: str) -> None:
            lines.append(text)
            assert self.output is not None
            self.output.append(text)

        def on_done(returncode: int) -> None:
            def _done() -> bool:
                run = testing_mod.parse_test_output("".join(lines), project)
                outcomes = {c.name: c.outcome for c in run.cases}
                if self.testpanel is not None:
                    if outcomes:
                        self.testpanel.apply_results(project, outcomes)
                    else:
                        summary = f"exit {returncode}"
                        if run.total:
                            summary = f"{run.passed} passed, {run.failed} failed, {run.skipped} skipped"
                        self.testpanel.set_status(f"{os.path.basename(project)}: {summary}")
                assert self.output is not None
                self.output.append(f"\n(exit {returncode})\n")
                self.output.set_status(f"{label}: exit {returncode}")
                return False

            GLib.idle_add(_done)

        dotnet_cli.run_streaming(argv, root, on_line, on_done)

    def _run_all_tests(self) -> None:
        projects = [p.path for p in self._test_projects()]
        if not projects:
            return

        def _chain(index: int) -> None:
            if index >= len(projects):
                return
            project = projects[index]
            root = self._model.root_dir if self._model else os.path.dirname(project)
            argv = [self._dotnet(), "test", project, "--nologo", "-v", "n"]
            if self.output is not None:
                self.output.append(f"\n$ {' '.join(argv)}\n")
            if self.testpanel is not None:
                self.testpanel.mark_running(project)
            lines: list[str] = []

            def on_line(_stream: str, text: str) -> None:
                lines.append(text)
                if self.output is not None:
                    self.output.append(text)

            def on_done(_rc: int) -> None:
                def _done() -> bool:
                    run = testing_mod.parse_test_output("".join(lines), project)
                    if self.testpanel is not None:
                        outcomes = {c.name: c.outcome for c in run.cases}
                        if outcomes:
                            self.testpanel.apply_results(project, outcomes)
                    _chain(index + 1)
                    return False

                GLib.idle_add(_done)

            dotnet_cli.run_streaming(argv, root, on_line, on_done)

        _chain(0)

    # -- breakpoints -------------------------------------------------
    def _toggle_breakpoint(self, path: str, line0: int) -> None:
        present = self.breakpoints.toggle(path, line0 + 1)
        debug(f"breakpoint {path}:{line0 + 1} -> {present}")
        doc = self._find_doc(path)
        if doc is not None:
            self._render_breakpoints(doc)
        if self.debugpanel is not None:
            self.debugpanel.set_breakpoints(self.breakpoints.all())
            self.debugpanel.set_status(
                f"Breakpoint {'set' if present else 'cleared'} at {os.path.basename(path)}:{line0 + 1}"
            )

    def _breakpoints_clear(self) -> None:
        self.breakpoints.clear_all()
        for _path, doc in self._iter_csharp_docs():
            self._clear_marks(doc, BP_MARK_CATEGORY)
        if self.debugpanel is not None:
            self.debugpanel.set_breakpoints({})

    def _clear_marks(self, doc, category: str) -> None:
        try:
            start, end = doc.get_bounds()
            doc.remove_source_marks(category, start, end)
        except Exception:
            pass

    def _render_breakpoints(self, doc) -> None:
        path = doc_path(doc)
        if not path:
            return
        self._clear_marks(doc, BP_MARK_CATEGORY)
        for line1 in self.breakpoints.get(path):
            try:
                it = doc.get_iter_at_line(max(0, line1 - 1))
                doc.create_source_mark(None, BP_MARK_CATEGORY, it)
            except Exception:
                continue
        self._configure_marks(doc)

    # -- debugging ---------------------------------------------------
    def _pick_startup_project(self, preferred: str | None = None):
        if preferred:
            for p in (self._model.projects if self._model else []):
                if p.path == preferred:
                    return p
        projects = list(self._model.projects) if self._model else []
        if not projects:
            return None
        active = self._active_path()
        if active:
            for p in projects:
                try:
                    if os.path.commonpath([active, os.path.dirname(p.path)]) == os.path.dirname(p.path):
                        if p.output_type.lower() == "exe":
                            return p
                except ValueError:
                    continue
            for p in projects:
                try:
                    if os.path.commonpath([active, os.path.dirname(p.path)]) == os.path.dirname(p.path):
                        return p
                except ValueError:
                    continue
        for p in projects:
            if p.output_type.lower() == "exe":
                return p
        return projects[0]

    def _debug_project(self, project: str | None) -> None:
        if self.debugpanel is None or self.output is None:
            return
        if getattr(self.dap, "state", "") not in ("stopped", "error"):
            self.debugpanel.set_status("A debug session is already running (Stop first).")
            return
        target = self._pick_startup_project(project)
        if target is None:
            self.output.append("No project to debug.\n")
            return
        dotnet = self._dotnet()
        tfm = (target.target_frameworks or [""])[0]
        self.debugpanel.set_status(f"Building {target.name}…")
        self.output.append(f"\n$ {dotnet} build {target.path} (for debugging)\n")

        def _worker() -> None:
            if not debugging_mod.ensure_built(dotnet, target.path):
                GLib.idle_add(lambda: self._debug_build_failed(target.path))
                return
            dll = debugging_mod.build_dll_path(target.path, "Debug", tfm)
            GLib.idle_add(lambda: self._debug_launch(target, dll))

        threading.Thread(target=_worker, name="xedcsharp-debug-build", daemon=True).start()

    def _debug_build_failed(self, project: str) -> bool:
        if self.debugpanel is not None:
            self.debugpanel.set_status(f"Build failed for {os.path.basename(project)} — not debugging.")
        if self.output is not None:
            self.output.append("Build failed; debug session aborted.\n")
        return False

    def _debug_launch(self, target, dll: str) -> bool:
        assert self.debugpanel is not None and self.output is not None
        if not dll or not os.path.isfile(dll):
            self.debugpanel.set_status(f"Built DLL not found ({dll or '?'}). Build the Debug configuration first.")
            self.output.append(f"Debug DLL not found: {dll}\n")
            return False
        configured = str(self.settings.get("netcoredbg_path") or "netcoredbg")
        netcoredbg = debugging_mod.find_netcoredbg(configured)
        if netcoredbg is None:
            self.debugpanel.set_status("netcoredbg not found.")
            self.output.append(debugging_mod.INSTALL_HINT + "\n")
            return False
        if not self.dap.connect([netcoredbg, "--interpreter=vscode"]):
            self.debugpanel.set_status("Could not start netcoredbg.")
            return False
        self._dap_project = target.path
        self._dap_thread = None
        self.debugpanel.set_status(f"Debugging {target.name}…")
        self.output.append(f"$ {netcoredbg} --interpreter=vscode -- {self._dotnet()} {dll}\n")
        cwd = os.path.dirname(target.path)
        args = str(self.settings.get("debug_args") or "")
        stop_at_entry = bool(self.settings.get("stop_at_entry"))
        self.dap.send_request("initialize", dap_mod.initialize_args(), self._on_dap_initialized)
        self._pending_launch = (dll, cwd, args, stop_at_entry)
        return False

    def _on_dap_initialized(self, message: dict) -> None:
        if not (message or {}).get("success", False):
            if self.debugpanel is not None:
                self.debugpanel.set_status("Debugger initialize failed.")
            try:
                self.dap.close()
            except Exception:
                pass
            return
        pending = getattr(self, "_pending_launch", None)
        if not pending:
            return
        dll, cwd, args, stop_at_entry = pending
        self.dap.send_request(
            "launch", dap_mod.launch_args(dll, cwd, args, stop_at_entry), self._on_dap_launched
        )

    def _on_dap_launched(self, message: dict) -> None:
        if not (message or {}).get("success", False):
            err = ((message or {}).get("message") or "launch failed")
            if self.debugpanel is not None:
                self.debugpanel.set_status(f"Launch failed: {err}")
            if self.output is not None:
                self.output.append(f"Launch failed: {err}\n")
            try:
                self.dap.close()
            except Exception:
                pass

    def _on_dap_event(self, event: str, body: dict) -> None:
        if self.debugpanel is None:
            return
        if event == "initialized":
            for path, lines in self.breakpoints.all().items():
                self.dap.send_request("setBreakpoints", dap_mod.set_breakpoints_args(path, lines), None)
            self.dap.send_request("configurationDone", {}, None)
            self.debugpanel.set_status("Running…")
        elif event == "stopped":
            self.debugpanel.set_status(dap_mod.summarize_stopped(body))
            try:
                self._dap_thread = int(body.get("threadId", 0)) or None
            except (TypeError, ValueError):
                self._dap_thread = None
            self._dap_fetch_stack()
        elif event == "continued":
            self._dap_thread = None
            self.debugpanel.clear_runtime()
            self.debugpanel.set_status("Running…")
            self._clear_frame_marks()
        elif event in ("terminated", "exited"):
            self.debugpanel.set_status(f"Debug session {event}.")
            if self.output is not None:
                self.output.append(f"\n(debug session {event})\n")
            try:
                self.dap.close()
            except Exception:
                pass
            self._dap_thread = None
            self.debugpanel.clear_runtime()
            self._clear_frame_marks()
        elif event == "output":
            text = body.get("output", "")
            if text and self.output is not None:
                self.output.append(text if text.endswith("\n") else text + "\n")

    def _dap_fetch_stack(self) -> None:
        if self._dap_thread is None:
            self.dap.send_request("threads", {}, self._on_dap_threads_for_stack)
        else:
            self.dap.send_request(
                "stackTrace",
                {"threadId": self._dap_thread, "startFrame": 0, "levels": 20},
                self._on_dap_stack,
            )

    def _on_dap_threads_for_stack(self, message: dict) -> None:
        threads = dap_mod.parse_threads((message or {}).get("body") or {})
        if not threads:
            return
        try:
            self._dap_thread = int(threads[0].get("id", 0)) or None
        except (TypeError, ValueError):
            self._dap_thread = None
        if self._dap_thread is not None:
            self._dap_fetch_stack()

    def _on_dap_stack(self, message: dict) -> None:
        frames = dap_mod.parse_stack_frames((message or {}).get("body") or {})
        if self.debugpanel is not None:
            self.debugpanel.set_stack(frames)
        if frames:
            top = frames[0]
            source = top.get("source") or {}
            fpath = source.get("path", "")
            line1 = int(top.get("line", 0) or 0)
            if fpath and os.path.isfile(fpath):
                self._jump_to(fpath, max(0, line1 - 1), 0)
                self._mark_frame(fpath, max(0, line1 - 1))
            try:
                frame_id = int(top.get("id", 0))
            except (TypeError, ValueError):
                frame_id = 0
            self.dap.send_request("scopes", {"frameId": frame_id}, self._on_dap_scopes)
        else:
            if self.debugpanel is not None:
                self.debugpanel.set_variables([])

    def _on_dap_scopes(self, message: dict) -> None:
        scopes = dap_mod.parse_scopes((message or {}).get("body") or {})
        if not scopes:
            if self.debugpanel is not None:
                self.debugpanel.set_variables([])
            return
        pending = {"count": len(scopes), "groups": []}

        def _make_cb(scope_name: str):
            def _cb(response: dict) -> None:
                variables = dap_mod.parse_variables((response or {}).get("body") or {})
                pending["groups"].append((scope_name, [dap_mod.format_variable(v) for v in variables]))
                pending["count"] -= 1
                if pending["count"] <= 0 and self.debugpanel is not None:
                    ordered = sorted(pending["groups"], key=lambda g: g[0])
                    self.debugpanel.set_variables(ordered)

            return _cb

        for scope in scopes:
            try:
                ref = int(scope.get("variablesReference", 0))
            except (TypeError, ValueError):
                ref = 0
            name = str(scope.get("name", "Scope"))
            if ref > 0:
                self.dap.send_request("variables", {"variablesReference": ref}, _make_cb(name))
            else:
                pending["count"] -= 1
        if pending["count"] <= 0 and self.debugpanel is not None:
            self.debugpanel.set_variables(sorted(pending["groups"], key=lambda g: g[0]))

    def _mark_frame(self, path: str, line0: int) -> None:
        doc = self._find_doc(path)
        if doc is None:
            return
        self._clear_frame_marks()
        try:
            it = doc.get_iter_at_line(max(0, line0))
            doc.create_source_mark(None, FRAME_MARK_CATEGORY, it)
        except Exception:
            pass
        self._configure_marks(doc)

    def _clear_frame_marks(self) -> None:
        for _path, doc in self._iter_csharp_docs():
            self._clear_marks(doc, FRAME_MARK_CATEGORY)

    def _dap_simple(self, command: str) -> None:
        if getattr(self.dap, "state", "") in ("stopped", "error", "connecting"):
            if self.debugpanel is not None:
                self.debugpanel.set_status("No active debug session.")
            return
        args: dict = {}
        if command in ("continue", "next", "stepIn", "stepOut"):
            if self._dap_thread is None:
                if self.debugpanel is not None:
                    self.debugpanel.set_status("No stopped thread yet.")
                return
            args = {"threadId": self._dap_thread}
        self.dap.send_request(command, args, None)
        if self.debugpanel is not None and command == "continue":
            self.debugpanel.set_status("Running…")

    def _dap_step(self, command: str) -> None:
        self._dap_simple(command)

    def _debug_stop(self) -> None:
        try:
            self.dap.close()
        except Exception:
            pass
        self._dap_thread = None
        if self.debugpanel is not None:
            self.debugpanel.set_status("Not debugging.")
            self.debugpanel.clear_runtime()
        self._clear_frame_marks()
