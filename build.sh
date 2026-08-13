#!/usr/bin/env bash
# Build DJ MetaManager.app and install to /Applications.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

APP_NAME="DJ MetaManager.app"
DIST_DIR="dist"

echo "Installing dependencies..."
pip3 install -q -r requirements.txt pyinstaller

echo "Building $APP_NAME..."
rm -rf "$DIST_DIR/$APP_NAME" "$DIST_DIR/DJMetaManager" build/DJMetaManager 2>/dev/null || true
pyinstaller --noconfirm --clean --distpath "$DIST_DIR" packaging/dj-mm.spec

if [[ ! -d "$DIST_DIR/$APP_NAME" ]]; then
  echo "ERROR: Build failed -- $DIST_DIR/$APP_NAME not found" >&2
  exit 1
fi

echo "Installing to /Applications..."
rm -rf "/Applications/$APP_NAME"
cp -R "$DIST_DIR/$APP_NAME" "/Applications/$APP_NAME"

echo "Done. $APP_NAME installed to /Applications."
