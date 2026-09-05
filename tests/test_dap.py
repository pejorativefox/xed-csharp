"""Unit tests for DAP helpers and the breakpoint store (headless)."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins", "xedcsharp"))

from xedcsharp import dap
from xedcsharp.breakpoints import BreakpointStore


def test_initialize_args_shape():
    args = dap.initialize_args()
    assert args["linesStartAt1"] is True
    assert args["pathFormat"] == "path"


def test_launch_args_shape():
    args = dap.launch_args("/proj/bin/Debug/net10.0/App.dll", "/proj", "--foo bar", True)
    assert args["program"].endswith("App.dll")
    assert args["args"] == ["--foo", "bar"]
    assert args["cwd"] == "/proj"
    assert args["stopAtEntry"] is True


def test_set_breakpoints_args_sorted():
    args = dap.set_breakpoints_args("/a/File.cs", [10, 3])
    assert [b["line"] for b in args["breakpoints"]] == [3, 10]
    assert args["source"]["path"] == "/a/File.cs"


def test_summarize_stopped():
    text = dap.summarize_stopped({"reason": "breakpoint", "threadId": 1})
    assert "breakpoint" in text and "1" in text


def test_parse_helpers_tolerant():
    assert dap.parse_threads({}) == []
    assert dap.parse_stack_frames(None) == []
    assert dap.parse_scopes("nope") == []
    assert dap.parse_variables({}) == []
    assert dap.format_variable({"name": "x", "value": "5", "type": "int"}) == "x: int = 5"
    assert dap.format_variable({"name": "y", "value": "null"}) == "y = null"


def test_dap_session_request_without_transport():
    session = dap.DapSession()
    assert session.send_request("threads", {}, None) is None
    session.close()  # must not raise


def test_dap_session_response_routing():
    received = []
    events = []
    session = dap.DapSession(on_event=lambda e, b: events.append((e, b)))
    seq = session._next_seq()
    session.pending.add(seq, lambda m: received.append(m))
    session._on_message({"type": "response", "request_seq": seq, "success": True,
                         "command": "threads", "body": {}})
    assert len(received) == 1
    session._on_message({"type": "event", "event": "stopped", "body": {"reason": "step"}})
    assert events == [("stopped", {"reason": "step"})]
    session._on_message({"type": "mystery"})  # must not raise


def test_breakpoint_store_toggle_and_persist():
    with tempfile.TemporaryDirectory() as tmp:
        store = BreakpointStore(os.path.join(tmp, "bp.ini"))
        assert store.toggle("/a/F.cs", 10) is True
        assert store.toggle("/a/F.cs", 4) is True
        assert store.get("/a/F.cs") == [4, 10]
        assert store.toggle("/a/F.cs", 10) is False
        assert store.get("/a/F.cs") == [4]
        store2 = BreakpointStore(os.path.join(tmp, "bp.ini"))
        assert store2.get("/a/F.cs") == [4]
        store2.clear_file("/a/F.cs")
        assert store2.get("/a/F.cs") == []
        store2.toggle("/b/G.cs", 1)
        store2.clear_all()
        assert store2.all() == {}
