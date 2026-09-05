"""Language-intelligence glue: diagnostics + LSP request/response helpers.

Rendering: diagnostics are surfaced as (a) editor underline tags + gutter
marks (GtkSource.Buffer APIs, guarded), (b) a clickable Problems list, and
(c) a status summary. The pure helpers in this module (positions, parsing,
edit computation) are headless-testable; GTK application lives in views.py
and __init__.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .logging_util import debug
from .roslyn import file_uri


@dataclass
class Diagnostic:
    uri: str
    path: str
    line: int  # 0-based
    character: int
    severity: int  # 1=error 2=warning 3=info 4=hint
    message: str
    code: str = ""


SEVERITY_LABEL = {1: "error", 2: "warning", 3: "info", 4: "hint"}


def normalize_diagnostics(uri: str, raw: list) -> List[Diagnostic]:
    out: List[Diagnostic] = []
    path = uri[7:] if uri.startswith("file://") else uri
    for item in raw:
        try:
            rng = item.get("range", {}).get("start", {})
            line = max(0, int(rng.get("line", 0)))
            char = max(0, int(rng.get("character", 0)))
            severity = int(item.get("severity", 3))
            message = str(item.get("message", "")).strip().splitlines()[0][:500]
            code = item.get("code", "")
            if isinstance(code, dict):
                code = str(code.get("value", ""))
            out.append(Diagnostic(uri, path, line, char, severity, message, str(code)))
        except Exception as e:
            debug(f"normalize_diagnostics skip: {e!r}")
            continue
    return out


def summarize(diagnostics: List[Diagnostic]) -> str:
    errors = sum(1 for d in diagnostics if d.severity == 1)
    warnings = sum(1 for d in diagnostics if d.severity == 2)
    if errors == 0 and warnings == 0:
        return f"{len(diagnostics)} diagnostics"
    return f"{errors} errors, {warnings} warnings"


def position_params(path: str, line: int, character: int) -> dict:
    """Build textDocumentPositionParams (xed lines are 0-based like LSP)."""
    return {
        "textDocument": {"uri": file_uri(path)},
        "position": {"line": max(0, line), "character": max(0, character)},
    }


def diagnostics_by_file(store: Dict[str, List[Diagnostic]]) -> Dict[str, int]:
    return {uri: len(items) for uri, items in store.items()}


def xy_of(result) -> Tuple[int, int]:
    """Extract (x, y) from GI coordinate calls with unstable arity.

    Gtk coordinate methods disagree: most return (x, y), but
    Gdk.Window.get_origin() returns (ok, x, y). Take the last two so both
    shapes (and any future success-flag prefix) work.
    """
    try:
        seq = tuple(result)
    except TypeError as e:
        raise ValueError(f"not a coordinate tuple: {result!r}") from e
    if len(seq) < 2:
        raise ValueError(f"not a coordinate tuple: {result!r}")
    return int(seq[-2]), int(seq[-1])


# ---------------------------------------------------------------------------
# Positions / offsets (LSP is 0-based UTF-16; xed buffer iters are 0-based
# lines. For offsets we treat text as a plain Python string, which matches
# for ASCII and is close enough for trigger/completion bookkeeping.)
# ---------------------------------------------------------------------------

def offset_to_position(text: str, offset: int) -> Tuple[int, int]:
    """Convert a char offset into an (line, character) pair (both 0-based)."""
    offset = max(0, min(offset, len(text)))
    line = text.count("\n", 0, offset)
    line_start = text.rfind("\n", 0, offset) + 1
    return line, offset - line_start


def position_to_offset(text: str, line: int, character: int) -> int:
    """Convert a 0-based (line, character) pair into a char offset."""
    lines = text.split("\n")
    line = max(0, min(line, len(lines) - 1))
    character = max(0, min(character, len(lines[line])))
    return sum(len(lines[i]) + 1 for i in range(line)) + character


_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def word_range_at(text: str, offset: int) -> Tuple[int, int]:
    """Return (start, end) offsets of the identifier surrounding offset."""
    for match in _WORD_RE.finditer(text):
        if match.start() <= offset <= match.end():
            return match.start(), match.end()
    return offset, offset


def line_start_offset(text: str, line: int) -> int:
    return position_to_offset(text, line, 0)


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------

@dataclass
class CompletionItem:
    label: str
    detail: str = ""
    documentation: str = ""
    insert_text: str = ""
    replace_start: int = 0
    replace_end: int = 0
    kind: int = 0


def _markdown_to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("value", ""))
    if isinstance(value, list):
        return "\n".join(_markdown_to_text(v) for v in value)
    return str(value)


def parse_completion(
    response: dict, text: str, offset: int, max_items: int = 50
) -> List[CompletionItem]:
    """Parse a textDocument/completion response into UI items.

    The replace range defaults to the identifier at the cursor; an LSP
    textEdit (if present and intersecting the cursor) overrides it.
    """
    result = response.get("result") if isinstance(response, dict) else None
    if result is None:
        return []
    raw_items = result.get("items", result) if isinstance(result, dict) else result
    if not isinstance(raw_items, list):
        return []
    fallback_start, fallback_end = word_range_at(text, offset)
    items: List[CompletionItem] = []
    for raw in raw_items[:max_items]:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label", ""))
        if not label:
            continue
        detail = str(raw.get("detail", "") or "")
        documentation = _markdown_to_text(raw.get("documentation"))[:1000]
        insert_text = str(raw.get("insertText", "") or raw.get("textEdit", {}).get("newText", "") or label)
        start, end = fallback_start, fallback_end
        text_edit = raw.get("textEdit") or {}
        edit_range = text_edit.get("range") or text_edit.get("insert", {}).get("range")
        if isinstance(edit_range, dict):
            try:
                s = edit_range.get("start", {})
                e = edit_range.get("end", {})
                start = position_to_offset(text, int(s.get("line", 0)), int(s.get("character", 0)))
                end = position_to_offset(text, int(e.get("line", 0)), int(e.get("character", 0)))
            except (TypeError, ValueError):
                pass
        try:
            kind = int(raw.get("kind", 0))
        except (TypeError, ValueError):
            kind = 0
        items.append(
            CompletionItem(
                label=label,
                detail=detail,
                documentation=documentation,
                insert_text=insert_text,
                replace_start=start,
                replace_end=end,
                kind=kind,
            )
        )
    return items


def should_trigger_completion(typed_char: str) -> bool:
    return typed_char in (".", "(", "<")


def is_identifier_char(char: str) -> bool:
    """True for chars that extend a C# identifier (letters, digits, _)."""
    return bool(char) and (char == "_" or char.isalnum())


def prefix_at(text: str, offset: int) -> tuple[str, int]:
    """Return (prefix, start_offset) of the identifier ending at offset.

    The prefix is the trailing [A-Za-z0-9_] run immediately before the
    cursor. Non-identifier chars (including '.') terminate it, so after
    ``Console.Wri`` with the cursor at the end the prefix is ``Wri``.
    """
    offset = max(0, min(offset, len(text)))
    start = offset
    while start > 0 and (text[start - 1] == "_" or text[start - 1].isalnum()):
        start -= 1
    return text[start:offset], start


def filter_completion(
    items: list["CompletionItem"], prefix: str
) -> list["CompletionItem"]:
    """Filter items by what the user has typed (case-insensitive).

    Ranking (stable within each group, preserving Roslyn's relevance order):
      1. labels starting with the prefix
      2. labels containing the prefix elsewhere
    An empty prefix returns every item.
    """
    if not prefix:
        return list(items)
    lowered = prefix.lower()
    starts, contains = [], []
    for item in items:
        label = (item.label or "").lower()
        if label.startswith(lowered):
            starts.append(item)
        elif lowered in label:
            contains.append(item)
    return starts + contains


# ---------------------------------------------------------------------------
# Hover / locations
# ---------------------------------------------------------------------------

def parse_hover(response: dict, max_len: int = 1500) -> str:
    """Extract plain text from a textDocument/hover response."""
    result = (response or {}).get("result") or {}
    contents = result.get("contents")
    if contents is None:
        return ""
    if isinstance(contents, dict) and "value" in contents:
        text = _markdown_to_text(contents)
    elif isinstance(contents, list):
        text = "\n".join(_markdown_to_text(c) for c in contents)
    else:
        text = _markdown_to_text(contents)
    # Strip markdown fences for tooltip display.
    text = re.sub(r"```[a-zA-Z#]*\n?", "", text)
    return text.strip()[:max_len]


@dataclass
class NavTarget:
    uri: str
    path: str
    line: int  # 0-based
    character: int = 0


def _nav_from_lsp_range(uri: str, loc_range: dict) -> NavTarget:
    path = uri[7:] if uri.startswith("file://") else uri
    start = (loc_range or {}).get("start", {})
    try:
        line = max(0, int(start.get("line", 0)))
        char = max(0, int(start.get("character", 0)))
    except (TypeError, ValueError):
        line, char = 0, 0
    return NavTarget(uri=uri, path=path, line=line, character=char)


def parse_locations(response: dict) -> List[NavTarget]:
    """Parse definition/references responses (Location | Location[] | LocationLink[])."""
    result = (response or {}).get("result")
    if result is None:
        return []
    raw_list = result if isinstance(result, list) else [result]
    targets: List[NavTarget] = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        uri = raw.get("uri") or raw.get("targetUri", "")
        loc_range = raw.get("range") or raw.get("targetRange") or {}
        # LocationLink points at targetSelectionRange for the symbol itself.
        sel = raw.get("targetSelectionRange")
        if sel:
            loc_range = sel
        if uri:
            targets.append(_nav_from_lsp_range(uri, loc_range))
    return targets


# ---------------------------------------------------------------------------
# Edits (formatting, code actions)
# ---------------------------------------------------------------------------

@dataclass
class EditOp:
    """A single text replacement computed from LSP edits (offsets into the
    original document text)."""

    start: int
    end: int
    new_text: str


def text_edits_to_ops(text_edits: list, text: str) -> List[EditOp]:
    """Convert LSP TextEdit[] into offset ops sorted for safe application."""
    ops: List[EditOp] = []
    for edit in text_edits or []:
        try:
            rng = edit["range"]
            start = position_to_offset(text, int(rng["start"]["line"]), int(rng["start"]["character"]))
            end = position_to_offset(text, int(rng["end"]["line"]), int(rng["end"]["character"]))
            ops.append(EditOp(start, end, str(edit.get("newText", ""))))
        except (KeyError, TypeError, ValueError) as e:
            debug(f"text_edits_to_ops skip: {e!r}")
            continue
    # Apply from the end so earlier offsets stay valid.
    ops.sort(key=lambda op: (op.start, op.end), reverse=True)
    return ops


def apply_ops_to_text(text: str, ops: List[EditOp]) -> str:
    for op in ops:
        text = text[: op.start] + op.new_text + text[op.end :]
    return text


def workspace_edit_to_ops(workspace_edit: dict, current_text_by_uri: dict) -> Dict[str, List[EditOp]]:
    """Convert an LSP WorkspaceEdit into per-uri op lists.

    Supports both `changes` (uri -> TextEdit[]) and `documentChanges`
    (TextDocumentEdit[]). Unknown shapes are skipped with a debug log.
    """
    out: Dict[str, List[EditOp]] = {}
    if not isinstance(workspace_edit, dict):
        return out
    changes = workspace_edit.get("changes") or {}
    for uri, edits in changes.items():
        text = current_text_by_uri.get(uri, "")
        out[uri] = text_edits_to_ops(edits, text)
    for doc_change in workspace_edit.get("documentChanges") or []:
        if not isinstance(doc_change, dict):
            continue
        if doc_change.get("kind") == "rename":
            debug("workspace_edit rename not supported, skipping")
            continue
        doc = doc_change.get("textDocument", {})
        uri = doc.get("uri", "")
        if not uri:
            continue
        text = current_text_by_uri.get(uri, "")
        out[uri] = text_edits_to_ops(doc_change.get("edits", []), text)
    return out


@dataclass
class CodeAction:
    title: str
    kind: str = ""
    edit: Optional[dict] = None
    command: Optional[dict] = None
    data: Optional[dict] = None
    needs_resolve: bool = False


def parse_code_actions(response: dict) -> List[CodeAction]:
    result = (response or {}).get("result") or []
    actions: List[CodeAction] = []
    for raw in result:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title", ""))
        if not title:
            continue
        actions.append(
            CodeAction(
                title=title,
                kind=str(raw.get("kind", "") or ""),
                edit=raw.get("edit"),
                command=raw.get("command"),
                data=raw.get("data"),
                needs_resolve=bool(raw.get("data") and not raw.get("edit")),
            )
        )
    # Prefer quickfixes/refactors over informational actions.
    order = {"quickfix": 0, "refactor": 1}
    actions.sort(key=lambda a: order.get((a.kind or "").split(".")[0], 9))
    return actions
