#!/usr/bin/env bash
# Build distribution ZIPs for itch.io release.
#
# Output:
#   dist/dynamic_color_palette-<version>-<branch>.zip
#   dist/dynamic_color_palette_godot_shader-<version>-<branch>.zip

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
DIST="$ROOT/dist"

# Version from bl_info in __init__.py
VERSION=$(grep -oP '"version":\s+\(\K\d+,\s*\d+,\s*\d+(?=\))' \
    "$ROOT/dynamic_color_palette/__init__.py" | tr -d ' ' | tr ',' '.')

# Current git branch
BRANCH=$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)

SUFFIX="-${VERSION}-${BRANCH}"

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
echo "Building dist ZIPs (v${VERSION}, branch: ${BRANCH})..."
echo ""

build_zip \
    "dist/dynamic_color_palette${SUFFIX}.zip" \
    "$ROOT/dynamic_color_palette" \
    "$DIST/dynamic_color_palette${SUFFIX}.zip"

echo ""

build_zip \
    "dist/dynamic_color_palette_godot_shader${SUFFIX}.zip" \
    "$ROOT/godot_4_shader" \
    "$DIST/dynamic_color_palette_godot_shader${SUFFIX}.zip"

echo ""
echo "Done."
