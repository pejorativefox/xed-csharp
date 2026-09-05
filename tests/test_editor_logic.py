"""Unit tests for editor intelligence helpers (headless, no GTK)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xedcsharp import intelligence as intel


def test_offset_position_roundtrip():
    text = "class A {\n    void M() {}\n}\n"
    for offset in (0, 5, 9, 10, 20, len(text)):
        line, char = intel.offset_to_position(text, offset)
        assert intel.position_to_offset(text, line, char) == offset


def test_position_clamps():
    text = "ab\ncd"
    assert intel.position_to_offset(text, 99, 99) == len(text)
    assert intel.position_to_offset(text, -1, -5) == 0


def test_word_range():
    text = "var foo = bar.Baz();"
    start, end = intel.word_range_at(text, 5)
    assert text[start:end] == "foo"
    start, end = intel.word_range_at(text, 13)
    assert text[start:end] == "bar"
    # Cursor at end of a word still belongs to it (completion-friendly).
    start, end = intel.word_range_at(text, 3)
    assert text[start:end] == "var"
    # On a non-word char -> empty range at cursor.
    gap = text.index("=")
    start, end = intel.word_range_at(text, gap)
    assert start == end == gap


def test_parse_completion_items():
    text = "Console.Wri"
    offset = len(text)
    response = {
        "result": {
            "items": [
                {"label": "WriteLine", "detail": "void Console.WriteLine(...)",
                 "documentation": "Writes a line",
                 "textEdit": {"newText": "WriteLine",
                              "range": {"start": {"line": 0, "character": 8},
                                        "end": {"line": 0, "character": 11}}}},
                {"label": "Write", "kind": 2},
                {"no-label": True},
            ]
        }
    }
    items = intel.parse_completion(response, text, offset)
    assert [i.label for i in items] == ["WriteLine", "Write"]
    assert items[0].insert_text == "WriteLine"
    assert (items[0].replace_start, items[0].replace_end) == (8, 11)
    assert items[1].insert_text == "Write"  # falls back to label
    assert items[1].replace_start == 8 and items[1].replace_end == 11  # word fallback


def test_parse_completion_empty():
    assert intel.parse_completion({}, "x", 1) == []
    assert intel.parse_completion({"result": None}, "x", 1) == []


def test_trigger_chars():
    assert intel.should_trigger_completion(".")
    assert intel.should_trigger_completion("(")
    assert not intel.should_trigger_completion("a")
    assert not intel.should_trigger_completion(" ")


def test_prefix_at():
    text = "Console.Wri"
    prefix, start = intel.prefix_at(text, len(text))
    assert (prefix, start) == ("Wri", 8)
    # A dot terminates the prefix (member access starts a new word).
    prefix, start = intel.prefix_at("Console.", len("Console."))
    assert (prefix, start) == ("", 8)
    prefix, start = intel.prefix_at("", 0)
    assert (prefix, start) == ("", 0)


def test_is_identifier_char():
    assert intel.is_identifier_char("a")
    assert intel.is_identifier_char("Z")
    assert intel.is_identifier_char("5")
    assert intel.is_identifier_char("_")
    assert not intel.is_identifier_char(".")
    assert not intel.is_identifier_char(" ")
    assert not intel.is_identifier_char("")


def test_filter_completion_prefix_first():
    items = [
        intel.CompletionItem(label="WriteLine"),
        intel.CompletionItem(label="Write"),
        intel.CompletionItem(label="WriteAsync"),
        intel.CompletionItem(label="TextWriter"),
    ]
    assert [i.label for i in intel.filter_completion(items, "Wri")] == [
        "WriteLine", "Write", "WriteAsync", "TextWriter",
    ]
    # Substring matches follow prefix matches, case-insensitively.
    assert [i.label for i in intel.filter_completion(items, "writ")] == [
        "WriteLine", "Write", "WriteAsync", "TextWriter",
    ]
    assert intel.filter_completion(items, "") == items
    assert intel.filter_completion(items, "zzz") == []


def test_xy_of_two_tuple():
    assert intel.xy_of((10, 20)) == (10, 20)


def test_xy_of_origin_triple():
    # Gdk.Window.get_origin() returns (ok, x, y) — this unpack bug hid the
    # completion popup at cursor (0, 0) and logged "too many values".
    assert intel.xy_of((1, 30, 40)) == (30, 40)


def test_xy_of_rejects_short():
    for bad in ((5,), (), None, 7):
        try:
            intel.xy_of(bad)
        except ValueError:
            continue
        raise AssertionError(f"xy_of({bad!r}) should raise")


def test_parse_hover_markdown():
    response = {"result": {"contents": {"kind": "markdown",
                                        "value": "```csharp\nvoid M()\n```\nDoes things"}}}
    assert intel.parse_hover(response) == "void M()\nDoes things"
    assert intel.parse_hover({"result": {}}) == ""
    assert intel.parse_hover({}) == ""


def test_parse_locations_variants():
    single = {"result": {"uri": "file:///a.cs",
                         "range": {"start": {"line": 3, "character": 4}}}}
    targets = intel.parse_locations(single)
    assert len(targets) == 1 and targets[0].line == 3 and targets[0].path == "/a.cs"
    multi = {"result": [
        {"uri": "file:///a.cs", "range": {"start": {"line": 1, "character": 0}}},
        {"targetUri": "file:///b.cs",
         "targetRange": {"start": {"line": 9, "character": 2}},
         "targetSelectionRange": {"start": {"line": 9, "character": 6}}},
    ]}
    targets = intel.parse_locations(multi)
    assert len(targets) == 2
    assert targets[1].path == "/b.cs" and targets[1].character == 6
    assert intel.parse_locations({"result": None}) == []


def test_text_edits_apply_reverse_order():
    text = "aaa bbb ccc"
    edits = [
        {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}},
         "newText": "AAA"},
        {"range": {"start": {"line": 0, "character": 8}, "end": {"line": 0, "character": 11}},
         "newText": "CCC"},
    ]
    ops = intel.text_edits_to_ops(edits, text)
    assert intel.apply_ops_to_text(text, ops) == "AAA bbb CCC"


def test_workspace_edit_changes_and_document_changes():
    edit = {
        "changes": {
            "file:///a.cs": [
                {"range": {"start": {"line": 0, "character": 0},
                           "end": {"line": 0, "character": 1}}, "newText": "X"}
            ]
        },
        "documentChanges": [
            {"textDocument": {"uri": "file:///b.cs"},
             "edits": [{"range": {"start": {"line": 0, "character": 0},
                                  "end": {"line": 0, "character": 1}}, "newText": "Y"}]},
            {"kind": "rename", "oldUri": "file:///c.cs", "newUri": "file:///d.cs"},
        ],
    }
    ops = intel.workspace_edit_to_ops(edit, {"file:///a.cs": "abc", "file:///b.cs": "def"})
    assert intel.apply_ops_to_text("abc", ops["file:///a.cs"]) == "Xbc"
    assert intel.apply_ops_to_text("def", ops["file:///b.cs"]) == "Yef"


def test_parse_code_actions_sorted():
    response = {"result": [
        {"title": "Add using", "kind": "quickfix", "edit": {}},
        {"title": "Rename", "kind": "refactor.rename", "data": {"x": 1}},
        {"title": "Info only", "kind": "info"},
        {"title": ""},
    ]}
    actions = intel.parse_code_actions(response)
    assert [a.title for a in actions] == ["Add using", "Rename", "Info only"]
    assert actions[1].needs_resolve is True
    assert actions[0].needs_resolve is False
