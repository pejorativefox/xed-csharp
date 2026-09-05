#!/usr/bin/env bash
# Install xed-csharp into the user plugins directory.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_DIR="${XED_PLUGIN_DIR:-$HOME/.local/share/xed/plugins}"
STYLE_DIR="${XED_STYLE_DIR:-$HOME/.local/share/xed/styles}"

mkdir -p "$DEST_DIR"
cp "$SRC_DIR/xedcsharp.plugin" "$DEST_DIR/"
rm -rf "$DEST_DIR/xedcsharp"
cp -r "$SRC_DIR/xedcsharp" "$DEST_DIR/"
rm -rf "$DEST_DIR/xedcsharp/__pycache__"

mkdir -p "$STYLE_DIR"
cp "$SRC_DIR"/styles/*.xml "$STYLE_DIR/"

BIN_DIR="${XED_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$BIN_DIR"
cp "$SRC_DIR/xed-open" "$BIN_DIR/"
chmod +x "$BIN_DIR/xed-open"

echo "Installed xed-csharp to $DEST_DIR"
echo "Installed color schemes to $STYLE_DIR"
echo "Installed xed-open to $BIN_DIR (usage: xed-open 'file.cs[:line[:col]]')"
echo "Fully quit xed first (File -> Quit all windows), then run:"
echo "  XED_DEBUG_CSHARP=1 xed"
echo "Then enable: Edit -> Preferences -> Plugins -> C# DevKit for xed"
echo "Marker log (proves load/activate): /tmp/xedcsharp-$(id -u).log"
