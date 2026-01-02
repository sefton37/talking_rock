#!/usr/bin/env bash
# Build an AppImage for ReOS
# Requires: appimagetool, linuxdeploy
#
# Usage: ./scripts/build-appimage.sh
#
# Output: dist/ReOS-x86_64.AppImage

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$ROOT_DIR/build/appimage"
APPDIR="$BUILD_DIR/ReOS.AppDir"
OUTPUT_DIR="$ROOT_DIR/dist"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

info() { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# Check dependencies
check_deps() {
    local missing=()

    command -v appimagetool >/dev/null 2>&1 || missing+=("appimagetool")
    command -v python3.12 >/dev/null 2>&1 || missing+=("python3.12")

    if [ ${#missing[@]} -ne 0 ]; then
        error "Missing dependencies: ${missing[*]}"
    fi
}

# Download appimagetool if not available
ensure_appimagetool() {
    if ! command -v appimagetool >/dev/null 2>&1; then
        info "Downloading appimagetool..."
        local tool_url="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
        curl -Lo /tmp/appimagetool "$tool_url"
        chmod +x /tmp/appimagetool
        export PATH="/tmp:$PATH"
    fi
}

# Build the Tauri app if not already built
build_tauri() {
    local binary="$ROOT_DIR/apps/reos-tauri/src-tauri/target/release/reos_tauri"
    if [ ! -f "$binary" ]; then
        info "Building Tauri application..."
        cd "$ROOT_DIR/apps/reos-tauri"
        npm run tauri:build
    else
        info "Using existing Tauri build: $binary"
    fi
}

# Create AppDir structure
create_appdir() {
    info "Creating AppDir structure..."

    rm -rf "$APPDIR"
    mkdir -p "$APPDIR/usr/bin"
    mkdir -p "$APPDIR/usr/lib/python3.12"
    mkdir -p "$APPDIR/usr/share/applications"
    mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
    mkdir -p "$APPDIR/usr/share/man/man1"

    # Copy Tauri binary
    cp "$ROOT_DIR/apps/reos-tauri/src-tauri/target/release/reos_tauri" \
       "$APPDIR/usr/bin/reos-desktop"

    # Copy Python package
    info "Installing Python package..."
    python3.12 -m pip install --target="$APPDIR/usr/lib/python3.12/site-packages" \
        -e "$ROOT_DIR" --no-deps --ignore-installed

    # Copy dependencies
    python3.12 -m pip install --target="$APPDIR/usr/lib/python3.12/site-packages" \
        fastapi httpx uvicorn pydantic typer rich --ignore-installed

    # Create wrapper script for CLI
    cat > "$APPDIR/usr/bin/reos" << 'WRAPPER'
#!/bin/bash
APPDIR="$(dirname "$(dirname "$(readlink -f "$0")")")"
export PYTHONPATH="$APPDIR/usr/lib/python3.12/site-packages:$PYTHONPATH"
exec python3 -m reos.cli "$@"
WRAPPER
    chmod +x "$APPDIR/usr/bin/reos"

    # Desktop file
    cp "$ROOT_DIR/dist/reos.desktop" "$APPDIR/usr/share/applications/"
    cp "$ROOT_DIR/dist/reos.desktop" "$APPDIR/"

    # Icon (create a placeholder if not exists)
    if [ -f "$ROOT_DIR/dist/reos.png" ]; then
        cp "$ROOT_DIR/dist/reos.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/"
        cp "$ROOT_DIR/dist/reos.png" "$APPDIR/reos.png"
    else
        # Create a simple placeholder icon
        info "Creating placeholder icon..."
        convert -size 256x256 xc:transparent \
            -fill '#4A90D9' -draw "circle 128,128 128,20" \
            -fill white -font Helvetica -pointsize 120 \
            -gravity center -annotate 0 "R" \
            "$APPDIR/reos.png" 2>/dev/null || \
        echo "Warning: Could not create icon (install imagemagick)"
    fi

    # Man page
    cp "$ROOT_DIR/dist/reos.1" "$APPDIR/usr/share/man/man1/"

    # AppRun script
    cat > "$APPDIR/AppRun" << 'APPRUN'
#!/bin/bash
APPDIR="$(dirname "$(readlink -f "$0")")"
export PATH="$APPDIR/usr/bin:$PATH"
export LD_LIBRARY_PATH="$APPDIR/usr/lib:$LD_LIBRARY_PATH"
export PYTHONPATH="$APPDIR/usr/lib/python3.12/site-packages:$PYTHONPATH"
export XDG_DATA_DIRS="$APPDIR/usr/share:${XDG_DATA_DIRS:-/usr/share}"

# Determine what to run
if [ "$1" = "--cli" ] || [ "$1" = "cli" ]; then
    shift
    exec "$APPDIR/usr/bin/reos" "$@"
else
    exec "$APPDIR/usr/bin/reos-desktop" "$@"
fi
APPRUN
    chmod +x "$APPDIR/AppRun"
}

# Build the AppImage
build_appimage() {
    info "Building AppImage..."

    mkdir -p "$OUTPUT_DIR"

    ARCH=x86_64 appimagetool "$APPDIR" "$OUTPUT_DIR/ReOS-x86_64.AppImage"

    success "AppImage created: $OUTPUT_DIR/ReOS-x86_64.AppImage"
}

# Main
main() {
    info "Building ReOS AppImage..."

    check_deps
    ensure_appimagetool
    build_tauri
    create_appdir
    build_appimage

    success "Build complete!"
    echo ""
    echo "To run:"
    echo "  chmod +x $OUTPUT_DIR/ReOS-x86_64.AppImage"
    echo "  $OUTPUT_DIR/ReOS-x86_64.AppImage"
    echo ""
    echo "For CLI mode:"
    echo "  $OUTPUT_DIR/ReOS-x86_64.AppImage --cli status"
}

main "$@"
