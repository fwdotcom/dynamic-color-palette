#!/usr/bin/env bash
# Build distribution ZIPs for itch.io release.
#
# Output:
#   dist/zip/dynamic_color_palette.zip                  -- Blender addon (flat, __pycache__ excluded)
#   dist/zip/dynamic_color_palette_godot_shader.zip     -- Godot 4 shader

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
DIST="$ROOT/dist/zip"

build_zip() {
    local label="$1"
    local src="$2"
    local out="$3"

    rm -f "$out"

    local tmp
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' RETURN

    # Copy source tree, excluding __pycache__ and .pyc files
    rsync -a --exclude='__pycache__' --exclude='*.pyc' "$src/" "$tmp/"

    (cd "$tmp" && zip -qr "$out" .)

    local size_kb
    size_kb=$(( ($(stat -c%s "$out") + 1023) / 1024 ))
    echo "  $label  ($size_kb KB)"
    zipinfo -1 "$out" | sed 's/^/    /'
}

mkdir -p "$DIST"
echo ""
echo "Building dist ZIPs..."
echo ""

build_zip \
    "dist/zip/dynamic_color_palette.zip" \
    "$ROOT/dynamic_color_palette" \
    "$DIST/dynamic_color_palette.zip"

echo ""

build_zip \
    "dist/zip/dynamic_color_palette_godot_shader.zip" \
    "$ROOT/godot_4_shader" \
    "$DIST/dynamic_color_palette_godot_shader.zip"

echo ""
echo "Done."
