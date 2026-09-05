"""Minimal Debug Adapter Protocol client for Samsung netcoredbg.

DAP uses the same Content-Length framing as LSP, so the transport layer is
reused from lsp_transport. Only stdlib + lsp_transport here (no GTK), which
keeps request builders and event parsing headless-testable.

Typical session (driven by __init__.py):
  connect(argv) -> initialize -> launch -> [initialized event] ->
  setBreakpoints -> configurationDone -> threads/stopped loop ->
  stackTrace -> scopes -> variables; terminated/exited -> close.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional

from .logging_util import debug
from .lsp_transport import LspTransport, PendingRequests


# ---------------------------------------------------------------------------
# Pure request builders
# ---------------------------------------------------------------------------

def initialize_args(adapter_id: str = "xed-csharp") -> dict:
    return {
        "clientID": "xed",
        "clientName": "xed-csharp",
        "adapterID": adapter_id,
        "pathFormat": "path",
        "linesStartAt1": True,
        "columnsStartAt1": True,
        "supportsVariableType": True,
        "supportsRunInTerminalRequest": False,
    }


def launch_args(dll: str, cwd: str, args: str = "", stop_at_entry: bool = False) -> dict:
    argv = [a for a in args.split() if a] if args else []
    return {
        "request": "launch",
        "program": dll,
        "args": argv,
        "cwd": cwd,
        "stopAtEntry": stop_at_entry,
        "console": "internalConsole",
        "internalConsoleOptions": "openOnSessionStart",
    }


def set_breakpoints_args(path: str, lines_1based: List[int]) -> dict:
    return {
        "source": {"name": path.split("/")[-1], "path": path},
        "breakpoints": [{"line": n} for n in sorted(lines_1based)],
        "sourceModified": False,
    }


# ---------------------------------------------------------------------------
# Pure event/response parsing helpers
# ---------------------------------------------------------------------------

def summarize_stopped(body: dict) -> str:
    reason = body.get("reason", "stopped")
    thread = body.get("threadId", "?")
    text = body.get("description") or body.get("text") or ""
    return f"stopped ({reason}) thread {thread} {text}".strip()


def parse_threads(body: Any) -> List[dict]:
    return body.get("threads", []) if isinstance(body, dict) else []


def parse_stack_frames(body: Any) -> List[dict]:
    return body.get("stackFrames", []) if isinstance(body, dict) else []


def parse_scopes(body: Any) -> List[dict]:
    return body.get("scopes", []) if isinstance(body, dict) else []


def parse_variables(body: Any) -> List[dict]:
    return body.get("variables", []) if isinstance(body, dict) else []


def format_variable(var: dict) -> str:
    name = var.get("name", "?")
    value = var.get("value", "")
    vtype = var.get("type", "")
    if vtype:
        return f"{name}: {vtype} = {value}"
    return f"{name} = {value}"


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class DapSession:
    """Owns a netcoredbg process speaking DAP over stdio."""

    def __init__(
        self,
        on_event: Optional[Callable[[str, dict], None]] = None,
        ui_dispatch: Optional[Callable[[Callable[[], None]], None]] = None,
    ) -> None:
        self.on_event = on_event
        self.ui_dispatch = ui_dispatch or (lambda fn: fn())
        self.transport: Optional[LspTransport] = None
        self.pending = PendingRequests()
        self._seq = 0
        self._seq_lock = threading.Lock()
        self._lock = threading.Lock()
        self.state = "stopped"
        self.capabilities: dict = {}

    def _next_seq(self) -> int:
        with self._seq_lock:
            self._seq += 1
            return self._seq

    # -- lifecycle ---------------------------------------------------
    def connect(self, argv: List[str]) -> bool:
        with self._lock:
            if self.transport is not None:
                return True
            try:
                self.transport = LspTransport(argv, self._on_message)
                self.transport.start()
            except FileNotFoundError:
                debug(f"DapSession: binary missing: {argv[0]!r}")
                self.transport = None
                self.state = "error"
                return False
            self.state = "connecting"
            return True

    def close(self) -> None:
        with self._lock:
            transport, self.transport = self.transport, None
            self.pending.clear()
            self.state = "stopped"
        if transport is not None:
            try:
                self._send_raw({"seq": self._next_seq(), "type": "request", "command": "disconnect", "arguments": {"restart": False}})
            except Exception:
                pass
            transport.stop()

    # -- protocol ----------------------------------------------------
    def _send_raw(self, message: dict) -> None:
        if self.transport is None:
            debug("DapSession: no transport, dropping message")
            return
        self.transport.send(message)

    def send_request(self, command: str, arguments: Optional[dict], callback=None) -> Optional[int]:
        if self.transport is None:
            debug(f"DapSession.request {command}: not connected")
            return None
        seq = self._next_seq()
        if callback is not None:
            self.pending.add(seq, callback)
        self._send_raw(
            {"seq": seq, "type": "request", "command": command, "arguments": arguments or {}}
        )
        return seq

    def _on_message(self, message: dict) -> None:
        msg_type = message.get("type", "")
        if msg_type == "response":
            try:
                seq = int(message.get("request_seq", -1))
            except (TypeError, ValueError):
                return
            callback = self.pending.pop(seq)
            if message.get("command") == "initialize" and message.get("success"):
                self.capabilities = (message.get("body") or {})
                with self._lock:
                    if self.state == "connecting":
                        self.state = "ready"
            if callback is not None:
                self.ui_dispatch(lambda: callback(message))
        elif msg_type == "event":
            event = message.get("event", "")
            body = message.get("body") or {}
            debug(f"DAP event: {event}")
            if self.on_event is not None:
                cb = self.on_event
                self.ui_dispatch(lambda: cb(event, body))
        else:
            debug(f"DAP unknown message type: {msg_type!r}")
