#!/usr/bin/env bash
# Install every plugin in plugins/ into the user plugins directory.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_DIR="${XED_PLUGIN_DIR:-$HOME/.local/share/xed/plugins}"
STYLE_DIR="${XED_STYLE_DIR:-$HOME/.local/share/xed/styles}"

mkdir -p "$DEST_DIR"
shopt -s nullglob
for plugin in "$SRC_DIR"/plugins/*/; do
    [ -d "$plugin" ] || continue
    name="$(basename "$plugin")"
    # drop the legacy flat install (pre-subfolder layout) of this plugin only
    for desc in "$plugin"/*.plugin; do
        rm -f "$DEST_DIR/$(basename "$desc")"
    done
    for mod in "$plugin"*/; do
        [ -d "$mod" ] || continue
        rm -rf "$DEST_DIR/$(basename "$mod")"
    done
    # install the whole plugin folder: $DEST_DIR/<name>/{<name>.plugin,<name>/}
    rm -rf "$DEST_DIR/$name"
    cp -r "$plugin" "$DEST_DIR/"
    find "$DEST_DIR/$name" -type d -name '__pycache__' -prune -exec rm -rf {} +
    echo "Installed $name to $DEST_DIR/$name"
done

mkdir -p "$STYLE_DIR"
cp "$SRC_DIR"/styles/*.xml "$STYLE_DIR/"

BIN_DIR="${XED_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$BIN_DIR"
cp "$SRC_DIR/xed-open" "$BIN_DIR/"
chmod +x "$BIN_DIR/xed-open"

echo "Installed color schemes to $STYLE_DIR"
echo "Installed xed-open to $BIN_DIR (usage: xed-open 'file.cs[:line[:col]]')"
echo "Fully quit xed first (File -> Quit all windows), then run:"
echo "  XED_PLUGIN_DEBUG=1 xed"
echo "Then enable: Edit -> Preferences -> Plugins -> C# DevKit for xed"
echo "Marker log (proves load/activate): /tmp/xedcsharp-$(id -u).log"
