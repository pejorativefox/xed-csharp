"""Roslyn completion via GtkSource's built-in framework (the wordcompletion way).

The bundled wordcompletion plugin builds no popup at all: it registers a
GtkSourceCompletionProvider and the editor's own completion window handles
focus, filtering, navigation and commit. This module does the same for
Roslyn items, which fixes the focus-stealing class of bugs structurally:
our code never creates, maps or focuses a window.

VSCode-parity notes (GtkSource4 constraints):

* ``do_populate`` never blocks: it returns the cached list immediately
  (or an empty unfinished list) and completes the in-flight request via
  ``context.add_proposals(..., True)`` when Roslyn answers.
* Trigger ownership belongs to the framework (interactive + user
  requested). The plugin must NOT prefetch on every keystroke; it only
  forces ``completion.start()`` on explicit ``Ctrl+Space``.
* Filtering while typing is done by the framework against each
  proposal's ``text`` (``filterText`` or label). The cache is reused
  while the user extends the same prefix (VSCode behaviour for complete
  lists) and re-queried after trigger characters or when the server
  reported ``isIncomplete``.
* Replacement uses the LSP ``textEdit`` range carried per proposal,
  not a generic word scan.

Custom CompletionPopup (completion.py) remains as a frozen fallback for
builds without GtkSource.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

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

#: GtkSource4 ``populate`` is synchronous, so this module never blocks it:
#: a fast local Roslyn usually answers in milliseconds and the async
#: completion lands while the popup is open. No main-loop wait here.
FETCH_TIMEOUT_S = 0.35  # legacy ``fetch_sync`` shim only; populate is async.

#: Cap proposals per populate so huge namespaces stay snappy; the
#: framework filters as the user types. Large enough to keep Roslyn's
#: relevance order intact (VSCode shows hundreds virtualized).
MAX_PROPOSALS = 300

#: How long a complete list may be reused while the user extends the same
#: prefix on the same line (framework filters locally, like VSCode).
CACHE_TTL_S = 10.0

#: Interactive delay (ms). VSCode feels instant; the previous 150ms felt
#: laggy. The framework still throttles while typing.
INTERACTIVE_DELAY_MS = 75

#: Characters that request a fresh member list (LSP TriggerCharacter).
TRIGGER_CHARACTERS = (".", "(", "<")


class _RoslynProposalBase:
    """Proposal logic; mixed into the GtkSource type when available."""

    def __init__(
        self,
        label: str,
        insert_text: str,
        info: str = "",
        filter_text: str = "",
        markup: str = "",
        icon_name: str = "",
        replace_start: int = 0,
        replace_end: int = 0,
        insert_start: int = 0,
        insert_end: int = 0,
        additional_edits: list | None = None,
        commit_chars: list | None = None,
        preselect: bool = False,
        kind: int = 0,
    ) -> None:
        # GtkSource filters on ``text`` and shows ``label``/``markup``.
        text = filter_text or label
        try:
            super().__init__(label=label, text=text, info=info or "")  # type: ignore[call-arg]
        except TypeError:
            # Fallback base (no GtkSource): plain object init.
            try:
                super().__init__()  # type: ignore[call-arg]
            except TypeError:
                pass
            self.label_text = label
            self.filter_text_value = text
            self.info_text = info or ""
        if markup:
            try:
                self.set_property("markup", markup)  # type: ignore[attr-defined]
            except Exception:
                pass
        if icon_name:
            try:
                self.set_property("icon-name", icon_name)  # type: ignore[attr-defined]
            except Exception:
                pass
        self.insert_text = insert_text
        self.filter_text = filter_text or label
        self.replace_start = replace_start
        self.replace_end = replace_end
        self.insert_start = insert_start
        self.insert_end = insert_end
        self.additional_edits = list(additional_edits or [])
        self.commit_chars = list(commit_chars or [])
        self.preselect = bool(preselect)
        self.kind = kind


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


def _escape_markup(text: str) -> str:
    try:
        from gi.repository import GLib  # type: ignore

        return GLib.markup_escape_text(text or "")
    except Exception:
        return (text or "").replace("&", "&amp;").replace("<", "&lt;")


def proposal_markup(label: str, detail: str) -> str:
    """VSCode-like row: ``label`` + muted ``detail`` (framework aligns)."""
    if detail:
        return f"{_escape_markup(label)}  <span alpha=\"55%\" size=\"smaller\">{_escape_markup(detail.strip()[:120])}</span>"
    return _escape_markup(label)


def trigger_context(
    text: str, offset: int, user_requested: bool, is_retrigger: bool = False
) -> tuple[int, str | None]:
    """LSP completion context for a populate (pure, testable).

    Returns ``(triggerKind, triggerCharacter)``: 1=Invoked, 2=
    TriggerCharacter, 3=TriggerForIncompleteCompletions (VSCode
    re-query while the user extends an incomplete list).
    """
    if is_retrigger:
        return 3, None
    if user_requested:
        return 1, None
    if 0 < offset <= len(text):
        char = text[offset - 1]
        if char in TRIGGER_CHARACTERS:
            return 2, char
    return 1, None


@dataclass
class _CacheEntry:
    items: list = field(default_factory=list)
    is_incomplete: bool = False
    path: str = ""
    line: int = 0
    char: int = 0
    offset: int = 0
    prefix: str = ""
    time: float = 0.0


def cache_valid(
    entry: _CacheEntry | None,
    path: str,
    line: int,
    prefix: str,
    now: float | None = None,
) -> bool:
    """Whether a cached list may back a populate without re-querying.

    VSCode reuses a *complete* list while the user extends the same
    prefix on the same line (local fuzzy filter). Anything else —
    line change, trigger character (prefix reset), expiry, or
    ``isIncomplete`` — needs a fresh request.
    """
    if entry is None or not entry.items:
        return False
    if entry.path != path or entry.line != line:
        return False
    if entry.is_incomplete:
        return False
    try:
        age = (time.monotonic() if now is None else now) - entry.time
    except Exception:
        age = 0.0
    if age > CACHE_TTL_S:
        return False
    # Extending the same prefix reuses; anything else re-queries.
    # Empty current prefix right after '.' must NOT reuse the previous
    # word list (member list differs).
    if prefix and entry.prefix and not prefix.startswith(entry.prefix):
        return False
    if not prefix and entry.prefix:
        return False
    return True


class _RoslynCompletionProviderBase:
    """Provider logic; mixed into the GObject/iface types when available."""

    __gsignals__ = {}  # type: ignore[misc]

    """GtkSource completion provider backed by Roslyn textDocument/completion.

    Callbacks (wired by the plugin, kept off GTK so they stay testable):
      is_ready() -> bool
      resolve_path(buffer) -> str | None (None for non-C# buffers)
      send_request(method, params, callback) -> id | None
      flush_doc(path) -> None (best-effort synchronous didChange flush)
    """

    def __init__(self, is_ready, resolve_path, send_request, flush_doc=None) -> None:
        super().__init__()
        self._is_ready = is_ready
        self._resolve_path = resolve_path
        self._send_request = send_request
        self._flush_doc = flush_doc
        self._lock = threading.Lock()
        self._cache: dict[str, _CacheEntry] = {}
        self._seq = 0
        # Legacy compat (fetch_sync/note_response tests + prefetch path).
        self._legacy_items: list = []
        self._legacy_key = None
        self._legacy_time = 0.0
        self._late: list[tuple] = []

    # -- GtkSource interface -----------------------------------------
    def do_get_name(self):  # noqa: N802
        return "xed-csharp-roslyn"

    def do_get_activation(self):  # noqa: N802
        return (
            GtkSource.CompletionActivation.INTERACTIVE  # type: ignore[union-attr]
            | GtkSource.CompletionActivation.USER_REQUESTED  # type: ignore[union-attr]
        )

    def do_get_interactive_delay(self):  # noqa: N802
        return INTERACTIVE_DELAY_MS

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

    def _is_user_requested(self, context) -> bool:
        try:
            activation = context.get_activation()
            return bool(activation & GtkSource.CompletionActivation.USER_REQUESTED)  # type: ignore[union-attr]
        except Exception:
            return False

    def do_match(self, context):  # noqa: N802
        # VSCode shows completion while typing anywhere in C#; the
        # framework already throttles via the interactive delay, so stay
        # permissive here. Gating on the previous char (old behaviour)
        # suppressed the popup on first chars and after keywords.
        try:
            if not self._is_ready():
                return False
            _buf, path = self._buffer_path(context)
            return bool(path)
        except Exception:
            return False

    def _proposals_for(self, items: list) -> list:
        out = []
        for item in items[:MAX_PROPOSALS]:
            try:
                out.append(
                    RoslynProposal(
                        label=item.label,
                        insert_text=item.insert_text or item.label,
                        info=intel.completion_info_text(item),
                        filter_text=intel.completion_filter_text(item),
                        markup=proposal_markup(item.label, item.detail),
                        icon_name=intel.completion_icon_name(item.kind),
                        replace_start=item.replace_start,
                        replace_end=item.replace_end,
                        insert_start=item.insert_start,
                        insert_end=item.insert_end,
                        additional_edits=item.additional_edits,
                        commit_chars=item.commit_chars,
                        preselect=item.preselect,
                        kind=item.kind,
                    )
                )
            except Exception as e:
                debug(f"roslyn proposal build failed: {e!r}")
                continue
        return out

    def do_populate(self, context):  # noqa: N802
        # Never block the main loop (VSCode is fully async). Serve the
        # cache synchronously; complete the request on this same context
        # when Roslyn answers.
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
            prefix, _start = intel.prefix_at(text, offset)
            user_requested = self._is_user_requested(context)
            with self._lock:
                entry = self._cache.get(path)
                hit = cache_valid(entry, path, line, prefix)
                items = list(entry.items) if (hit and entry is not None) else []
                retrigger = bool(entry is not None and entry.is_incomplete)
                self._seq += 1
                seq = self._seq
            if hit:
                context.add_proposals(self, self._proposals_for(items), True)
                if retrigger:
                    # Incomplete list: VSCode re-queries in the background
                    # while keeping the current rows visible.
                    self._request_async(
                        context, seq, path, line, char, text, offset,
                        user_requested, is_retrigger=True,
                    )
                return
            if self._flush_doc is not None:
                try:
                    self._flush_doc(path)
                except Exception:
                    pass
            # No usable cache: show nothing yet but keep the context open;
            # the async answer completes it (no freeze, no stale flash).
            context.add_proposals(self, [], False)
            self._request_async(
                context, seq, path, line, char, text, offset,
                user_requested, is_retrigger=retrigger,
            )
        except Exception as e:
            debug(f"roslyn populate failed: {e!r}")
            try:
                context.add_proposals(self, [], True)
            except Exception:
                pass

    def _request_async(
        self, context, seq: int, path: str, line: int, char: int,
        text: str, offset: int, user_requested: bool, is_retrigger: bool = False,
    ) -> None:
        kind, trigger_char = trigger_context(text, offset, user_requested, is_retrigger)
        params = intel.position_params(path, line, char)
        params["context"] = {"triggerKind": kind, "triggerCharacter": trigger_char}
        prefix, _s = intel.prefix_at(text, offset)

        def _cb(message: dict) -> None:
            try:
                items = intel.parse_completion(message or {}, text, offset)
                incomplete = intel.completion_is_incomplete(message or {})
            except Exception:
                items, incomplete = [], False
            with self._lock:
                if seq < self._seq and not is_retrigger:
                    # Superseded by a newer populate; keep cache fresh but
                    # don't touch the stale context.
                    self._cache[path] = _CacheEntry(
                        items=list(items), is_incomplete=incomplete,
                        path=path, line=line, char=char, offset=offset,
                        prefix=prefix, time=time.monotonic(),
                    )
                    return
                self._cache[path] = _CacheEntry(
                    items=list(items), is_incomplete=incomplete,
                    path=path, line=line, char=char, offset=offset,
                    prefix=prefix, time=time.monotonic(),
                )
                # Legacy shim state for fetch_sync callers.
                self._legacy_items = list(items)
                self._legacy_key = (path, line)
                self._legacy_time = time.monotonic()
            # Complete the still-open context, unless the cursor has since
            # moved to another line (then the framework already populated
            # anew and this delivery would be stale).
            try:
                try:
                    _ok, cur = context.get_iter()
                    cur_text = self._buffer_text(cur.get_buffer())
                    cur_line, _c = intel.offset_to_position(cur_text, cur.get_offset())
                    if cur_line != line:
                        return
                except Exception:
                    pass
                context.add_proposals(self, self._proposals_for(items), True)
            except Exception as e:
                debug(f"roslyn async complete failed: {e!r}")

        try:
            request_id = self._send_request("textDocument/completion", params, _cb)
        except Exception as e:
            debug(f"roslyn completion send failed: {e!r}")
            request_id = None
        if request_id is None:
            try:
                context.add_proposals(self, [], True)
            except Exception:
                pass

    def _stored_range_start(self, proposal, text: str, cur: int) -> int | None:
        """Stored edit start when plausible, else None (word-scan fallback).

        Manually built proposals carry the (0, 0) default — never trust an
        empty range, or ``Console.Wri`` would collapse to the file start.
        """
        try:
            start_off = getattr(proposal, "replace_start", None)
            end_off = getattr(proposal, "replace_end", None)
            if not isinstance(start_off, int) or not isinstance(end_off, int):
                return None
            if end_off <= start_off:
                return None
            if 0 <= start_off <= cur <= len(text):
                return start_off
        except Exception:
            pass
        return None

    def do_get_start_iter(self, context, proposal, it):  # noqa: N802
        """Per-proposal start iter (VSCode textEdit-aware)."""
        try:
            if proposal is not None:
                try:
                    buf = it.get_buffer()
                    text = self._buffer_text(buf)
                    cur = it.get_offset()
                    start_off = self._stored_range_start(proposal, text, cur)
                    if start_off is None:
                        # Fall back to the insert range when it is set.
                        ins_s = getattr(proposal, "insert_start", None)
                        ins_e = getattr(proposal, "insert_end", None)
                        if (
                            isinstance(ins_s, int)
                            and isinstance(ins_e, int)
                            and ins_e > ins_s
                            and 0 <= ins_s <= cur <= len(text)
                        ):
                            between = text[ins_s:cur]
                            if not between or all(
                                c == "_" or c.isalnum() for c in between
                            ):
                                start_off = ins_s
                    if start_off is not None:
                        it.assign(buf.get_iter_at_offset(start_off))
                        return True
                except Exception:
                    pass
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
        """Apply the LSP textEdit range exactly (VSCode semantics)."""
        try:
            insert = getattr(proposal, "insert_text", "") or ""
            if not insert:
                return False
            buf = it.get_buffer()
            end = it.copy()
            try:
                text = self._buffer_text(buf)
                cur = end.get_offset()
                start_off = self._stored_range_start(proposal, text, cur)
                if start_off is not None:
                    start = buf.get_iter_at_offset(start_off)
                else:
                    raise ValueError("no stored range")
            except Exception:
                start = end.copy()
                while start.backward_char():
                    if not _is_word_char(start.get_char()):
                        start.forward_char()
                        break
            buf.begin_user_action()
            try:
                buf.delete(start, end)
                buf.insert(start, insert)
                # Same-document additionalTextEdits (e.g. brace
                # adjustments). Applied after the main edit by line/char
                # so top-of-file inserts keep their position.
                for edit in getattr(proposal, "additional_edits", None) or []:
                    try:
                        rng = (edit or {}).get("range") or {}
                        s = rng.get("start", {})
                        e = rng.get("end", {})
                        s_it = buf.get_iter_at_line_offset(
                            max(0, int(s.get("line", 0))), max(0, int(s.get("character", 0)))
                        )
                        e_it = buf.get_iter_at_line_offset(
                            max(0, int(e.get("line", 0))), max(0, int(e.get("character", 0)))
                        )
                        if e_it.compare(s_it) < 0:
                            continue
                        # Skip edits overlapping the just-applied region.
                        buf.delete(s_it, e_it)
                        buf.insert(
                            buf.get_iter_at_line_offset(
                                max(0, int(s.get("line", 0))),
                                max(0, int(s.get("character", 0))),
                            ),
                            str((edit or {}).get("newText", "")),
                        )
                    except Exception:
                        continue
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
            incomplete = intel.completion_is_incomplete(message or {})
        except Exception:
            items, incomplete = [], False
        prefix, _s = intel.prefix_at(text, offset)
        try:
            line, char = intel.offset_to_position(text, offset)
        except Exception:
            line, char = 0, 0
        path = key[0] if isinstance(key, tuple) and key else str(key or "")
        with self._lock:
            self._cache[path] = _CacheEntry(
                items=list(items), is_incomplete=incomplete, path=path,
                line=line, char=char, offset=offset, prefix=prefix,
                time=time.monotonic(),
            )
            self._legacy_items = list(items)
            self._legacy_key = key
            self._legacy_time = time.monotonic()

    def fetch_sync(
        self, path: str, line: int, char: int, text: str, offset: int,
        timeout: float = FETCH_TIMEOUT_S,
    ) -> list:
        """Legacy blocking fetch (deprecated: populate is async now).

        Kept for unit tests and the non-framework fallback path. New
        code should rely on ``do_populate`` + cache instead.
        """
        prefix, _s = intel.prefix_at(text, offset)
        with self._lock:
            entry = self._cache.get(path)
            if cache_valid(entry, path, line, prefix) and entry is not None:
                return list(entry.items)
            if self._legacy_key == (path, line) and self._legacy_items:
                return list(self._legacy_items)

        params = intel.position_params(path, line, char)
        params["context"] = {"triggerKind": 1, "triggerCharacter": None}

        event = threading.Event()
        box: dict = {}

        def _cb(message: dict) -> None:
            try:
                items = intel.parse_completion(message or {}, text, offset)
                incomplete = intel.completion_is_incomplete(message or {})
            except Exception:
                items, incomplete = [], False
            with self._lock:
                if box.get("expired"):
                    self._late.append(((path, line), items))
                else:
                    box["items"] = items
                self._cache[path] = _CacheEntry(
                    items=list(items), is_incomplete=incomplete, path=path,
                    line=line, char=char, offset=offset, prefix=prefix,
                    time=time.monotonic(),
                )
                self._legacy_items = list(items)
                self._legacy_key = (path, line)
                self._legacy_time = time.monotonic()
            event.set()

        try:
            request_id = self._send_request("textDocument/completion", params, _cb)
        except Exception as e:
            debug(f"roslyn completion send failed: {e!r}")
            request_id = None
        if request_id is None:
            with self._lock:
                return list(self._legacy_items)

        if event.wait(timeout):
            return list(box.get("items", []))

        with self._lock:
            box["expired"] = True
            return list(self._legacy_items)


if _AVAILABLE:
    class RoslynCompletionProvider(  # type: ignore[misc,no-redef,attr-defined]
        _RoslynCompletionProviderBase, GObject.Object, GtkSource.CompletionProvider  # type: ignore[attr-defined]
    ):
        """GtkSource provider; see _RoslynCompletionProviderBase for logic."""
else:
    # Same duplicate-base-class hazard as RoslynProposal above: with no
    # GtkSource typelib the GObject/iface bases don't exist, so fall back
    # to the plain logic base (never instantiated in this configuration).
    class RoslynCompletionProvider(_RoslynCompletionProviderBase):  # type: ignore[no-redef]
        """GtkSource provider; see _RoslynCompletionProviderBase for logic."""


def show_completion(view, provider=None) -> bool:
    """Force the framework popup open (VSCode Ctrl+Space).

    Starts USER_REQUESTED completion at the cursor. Returns True when
    the request was issued; the provider's populate supplies the rows
    asynchronously.
    """
    try:
        completion = view.get_completion()
    except Exception:
        return False
    if completion is None:
        return False
    try:
        buf = view.get_buffer()
        mark = buf.get_insert()
        it = buf.get_iter_at_mark(mark)
    except Exception:
        return False
    try:
        context = completion.create_context(it)
    except Exception:
        return False
    try:
        if provider is None:
            return bool(completion.start([], context))
        return bool(completion.start([provider], context))
    except TypeError:
        # Older bindings: start() takes no explicit provider list.
        try:
            return bool(completion.start(context))
        except Exception as e:
            debug(f"completion show failed: {e!r}")
            return False
    except Exception as e:
        debug(f"completion show failed: {e!r}")
        return False


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
