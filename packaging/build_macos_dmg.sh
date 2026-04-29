#!/usr/bin/env bash
# Build DJ MetaManager.app and a compressed .dmg from the PyInstaller output.
# Requirements: Python with project dependencies + PyInstaller (see requirements-dev.txt).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python3 -m pip install -q -r "$ROOT/requirements.txt" -r "$ROOT/requirements-dev.txt"

OUT_DIR="${OUT_DIR:-dist}"
APP_NAME="DJ MetaManager.app"
VOL_NAME="DJ MetaManager"
DMG_NAME="${DMG_NAME:-DJ_MetaManager_macos.dmg}"

# Avoid stale artefacts from older spec names beside the canonical .app bundle
rm -rf "$OUT_DIR/$APP_NAME" "$OUT_DIR/DJMetaManager" "$OUT_DIR/launch_gui" "${OUT_DIR}/launch_gui.app" 2>/dev/null || true

pyinstaller --noconfirm --clean --distpath "$OUT_DIR" packaging/dj-mm.spec

if [[ ! -d "$OUT_DIR/$APP_NAME" ]]; then
  echo "Expected $OUT_DIR/$APP_NAME after build" >&2
  exit 1
fi

RELEASE_DIR="${RELEASE_DIR:-build/releases}"
mkdir -p "$RELEASE_DIR"
DMG_PATH="$RELEASE_DIR/$DMG_NAME"

hdiutil create -volname "$VOL_NAME" -srcfolder "$OUT_DIR/$APP_NAME" -ov -format UDZO "$DMG_PATH"

echo "Built: $OUT_DIR/$APP_NAME"
echo "DMG:   $DMG_PATH"
