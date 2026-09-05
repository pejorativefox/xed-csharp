"""Roslyn completion via GtkSource's built-in framework (the wordcompletion way).

The bundled wordcompletion plugin builds no popup at all: it registers a
GtkSourceCompletionProvider and the editor's own completion window handles
focus, filtering, navigation and commit. This module does the same for
Roslyn items, which fixes the focus-stealing class of bugs structurally:
our code never creates, maps or focuses a window.

Custom CompletionPopup (completion.py) remains as a fallback for builds
without GtkSource.
"""

from __future__ import annotations

import threading
import time

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("GtkSource", "4")
    from gi.repository import GObject, GtkSource  # type: ignore

    _AVAILABLE = True
except Exception:  # headless unit tests / missing typelib
    GObject = None  # type: ignore
    GtkSource = None  # type: ignore
    _AVAILABLE = False

from . import intelligence as intel
from .logging_util import debug

#: Block populate() at most this long waiting for Roslyn. Local stdio LSP
#: usually answers in milliseconds; on timeout we show the cached list and
#: the late response warms the cache for the next keystroke.
FETCH_TIMEOUT_S = 0.35

#: Cap proposals per populate so huge namespaces stay snappy; the
#: framework filters as the user types.
MAX_PROPOSALS = 80


class _RoslynProposalBase:
    """Proposal logic; mixed into the GtkSource type when available."""

    def __init__(self, label: str, insert_text: str, info: str = "") -> None:
        super().__init__(label=label, text=label, info=info or "")
        self.insert_text = insert_text


if _AVAILABLE:
    # Mixin first: its __init__ must win MRO over the Gtk/GObject ones,
    # and its super().__init__() chains into them correctly.
    class RoslynProposal(_RoslynProposalBase, GtkSource.CompletionItem):  # type: ignore[misc]
        """A framework proposal carrying the exact text to insert."""
else:
    # Import-safe fallback: never instantiated without GtkSource, but the
    # module must load (a conditional base of `object` would crash with
    # "duplicate base class" if written inline in the class statement).
    class RoslynProposal(_RoslynProposalBase):  # type: ignore[no-redef]
        """A framework proposal carrying the exact text to insert."""


def _is_word_char(char: str) -> bool:
    return bool(char) and (char == "_" or char.isalnum())


def word_start_offset(text: str, offset: int) -> int:
    """Pure helper: start offset of the identifier ending at offset."""
    _prefix, start = intel.prefix_at(text, offset)
    return start


class _RoslynCompletionProviderBase:
    """Provider logic; mixed into the GObject/iface types when available."""

    __gsignals__ = {}  # type: ignore[misc]

    """GtkSource completion provider backed by Roslyn textDocument/completion.

    Callbacks (wired by the plugin, kept off GTK so they stay testable):
      is_ready() -> bool
      resolve_path(buffer) -> str | None (None for non-C# buffers)
      send_request(method, params, callback) -> id | None
    """

    def __init__(self, is_ready, resolve_path, send_request) -> None:
        super().__init__()
        self._is_ready = is_ready
        self._resolve_path = resolve_path
        self._send_request = send_request
        self._lock = threading.Lock()
        self._cache: list = []
        self._cache_key = None
        self._cache_time = 0.0
        self._late: list[tuple] = []  # timed-out responses, drained next populate

    # -- GtkSource interface -----------------------------------------
    def do_get_name(self):  # noqa: N802
        return "xed-csharp-roslyn"

    def do_get_activation(self):  # noqa: N802
        return (
            GtkSource.CompletionActivation.INTERACTIVE
            | GtkSource.CompletionActivation.USER_REQUESTED
        )

    def do_get_interactive_delay(self):  # noqa: N802
        return 150

    def do_get_priority(self):  # noqa: N802
        # Rank above the plain word-completion provider.
        return 10

    def _buffer_path(self, context):
        try:
            _ok, it = context.get_iter()
        except Exception:
            return None, None
        try:
            buf = it.get_buffer()
        except Exception:
            return None, None
        try:
            path = self._resolve_path(buf)
        except Exception:
            return None, None
        return buf, path

    def do_match(self, context):  # noqa: N802
        try:
            if not self._is_ready():
                return False
            buf, path = self._buffer_path(context)
            if not path:
                return False
            try:
                activation = context.get_activation()
                if activation & GtkSource.CompletionActivation.USER_REQUESTED:
                    return True
            except Exception:
                pass
            # Interactive: only complete inside words or right after a
            # member-access trigger, not after spaces/punctuation.
            try:
                _ok, it = context.get_iter()
                probe = it.copy()
                if probe.backward_char():
                    return _is_word_char(probe.get_char()) or probe.get_char() in ".(<"
                return False
            except Exception:
                return True
        except Exception:
            return False

    def do_populate(self, context):  # noqa: N802
        try:
            _ok, it = context.get_iter()
            buf = it.get_buffer()
            path = self._resolve_path(buf)
            if not path or not self._is_ready():
                context.add_proposals(self, [], True)
                return
            text = self._buffer_text(buf)
            offset = it.get_offset()
            line, char = intel.offset_to_position(text, offset)
            items = self.fetch_sync(path, line, char, text, offset)
            proposals = [
                RoslynProposal(
                    label=item.label,
                    insert_text=item.insert_text or item.label,
                    info=(item.documentation or item.detail or "")[:1000],
                )
                for item in items[:MAX_PROPOSALS]
            ]
            context.add_proposals(self, proposals, True)
        except Exception as e:
            debug(f"roslyn populate failed: {e!r}")
            try:
                context.add_proposals(self, [], True)
            except Exception:
                pass

    def do_get_start_iter(self, context, _proposal, it):  # noqa: N802
        """Word start for framework filtering + default replacement."""
        try:
            start = it.copy()
            while start.backward_char():
                if not _is_word_char(start.get_char()):
                    start.forward_char()
                    break
            it.assign(start)
            return True
        except Exception:
            return False

    def do_activate_proposal(self, proposal, it):  # noqa: N802
        """Replace the current word with the proposal's insert text."""
        try:
            insert = getattr(proposal, "insert_text", "") or ""
            if not insert:
                return False
            buf = it.get_buffer()
            start = it.copy()
            while start.backward_char():
                if not _is_word_char(start.get_char()):
                    start.forward_char()
                    break
            buf.begin_user_action()
            try:
                buf.delete(start, it)
                buf.insert(start, insert)
            finally:
                buf.end_user_action()
            return True
        except Exception as e:
            debug(f"roslyn activate failed: {e!r}")
            return False

    # -- data ----------------------------------------------------------
    @staticmethod
    def _buffer_text(buf) -> str:
        try:
            start, end = buf.get_bounds()
            return buf.get_text(start, end, True)
        except Exception:
            return ""

    def note_response(self, key, message: dict, text: str, offset: int) -> None:
        """Parse + cache a completion response (GTK-free, any thread)."""
        try:
            items = intel.parse_completion(message or {}, text, offset)
        except Exception:
            items = []
        with self._lock:
            self._cache = list(items)
            self._cache_key = key
            self._cache_time = time.monotonic()

    def fetch_sync(
        self, path: str, line: int, char: int, text: str, offset: int,
        timeout: float = FETCH_TIMEOUT_S,
    ) -> list:
        """Return cached items, else block (<= timeout) for Roslyn.

        Late responses are parsed off-thread and stashed; the next
        populate drains them, so typing one more character shows fresh
        data with no extra request.
        """
        key = (path, line)
        with self._lock:
            matching = [items for (k, items) in self._late if k == key]
            self._late = [(k, items) for (k, items) in self._late if k != key]
            if matching:
                self._cache = list(matching[-1])
                self._cache_key = key
                self._cache_time = time.monotonic()
            if self._cache_key == key and self._cache:
                return list(self._cache)

        params = intel.position_params(path, line, char)
        params["context"] = {"triggerKind": 1, "triggerCharacter": None}

        event = threading.Event()
        box: dict = {}

        def _cb(message: dict) -> None:
            try:
                items = intel.parse_completion(message or {}, text, offset)
            except Exception:
                items = []
            with self._lock:
                if box.get("expired"):
                    self._late.append((key, items))
                else:
                    box["items"] = items
            event.set()

        try:
            request_id = self._send_request("textDocument/completion", params, _cb)
        except Exception as e:
            debug(f"roslyn completion send failed: {e!r}")
            request_id = None
        if request_id is None:
            with self._lock:
                return list(self._cache)

        if event.wait(timeout):
            items = box.get("items", [])
            with self._lock:
                self._cache = list(items)
                self._cache_key = key
                self._cache_time = time.monotonic()
            return list(items)

        with self._lock:
            box["expired"] = True
            return list(self._cache)


if _AVAILABLE:
    class RoslynCompletionProvider(  # type: ignore[misc,no-redef]
        _RoslynCompletionProviderBase, GObject.Object, GtkSource.CompletionProvider
    ):
        """GtkSource provider; see _RoslynCompletionProviderBase for logic."""
else:
    # Same duplicate-base-class hazard as RoslynProposal above: with no
    # GtkSource typelib the GObject/iface bases don't exist, so fall back
    # to the plain logic base (never instantiated in this configuration).
    class RoslynCompletionProvider(_RoslynCompletionProviderBase):  # type: ignore[no-redef]
        """GtkSource provider; see _RoslynCompletionProviderBase for logic."""


def attach_to_views(window, provider, attached: set) -> int:
    """Register the provider on every view once. Returns new attachments."""
    count = 0
    try:
        views = window.get_views()
    except Exception:
        return 0
    for view in views or []:
        try:
            key = hash(view)
        except Exception:
            continue
        if key in attached:
            continue
        try:
            completion = view.get_completion()
        except Exception:
            continue
        if completion is None:
            continue
        try:
            completion.add_provider(provider)
            attached.add(key)
            count += 1
        except Exception as e:
            debug(f"completion provider attach failed: {e!r}")
    return count


def detach_from_views(window, provider, attached: set) -> None:
    """Remove the provider wherever it was attached."""
    try:
        views = window.get_views()
    except Exception:
        views = []
    for view in views or []:
        try:
            if hash(view) not in attached:
                continue
            view.get_completion().remove_provider(provider)
        except Exception:
            pass
    attached.clear()
