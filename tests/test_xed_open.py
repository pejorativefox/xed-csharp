"""Unit tests for the xed-open helper script."""

import os


def _open_module():
    from importlib.machinery import SourceFileLoader

    path = os.path.join(os.path.dirname(__file__), "..", "xed-open")
    return SourceFileLoader("xed_open", path).load_module()


def test_parse_location_colon_forms():
    xed_open = _open_module()
    assert xed_open.parse_location("a.cs") == ("a.cs", None, None)
    assert xed_open.parse_location("a.cs:25") == ("a.cs", 25, None)
    assert xed_open.parse_location("a.cs:25:17") == ("a.cs", 25, 17)
    assert xed_open.parse_location("src/A B.cs:3") == ("src/A B.cs", 3, None)


def test_parse_location_msbuild_forms():
    xed_open = _open_module()
    assert xed_open.parse_location("a.cs(25)") == ("a.cs", 25, None)
    assert xed_open.parse_location("a.cs(25,17)") == ("a.cs", 25, 17)
    assert xed_open.parse_location("a.cs(25:17)") == ("a.cs", 25, 17)


def test_open_location_missing_file():
    xed_open = _open_module()
    assert xed_open.open_location("/no/such/file.cs", 3) == 2
    assert xed_open.open_location("", None) == 2
