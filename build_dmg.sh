#!/usr/bin/env bash
# Builds Award Wallet.app and "Award Wallet.dmg" in build/. Run it on your Mac from this folder:
#   ./build_dmg.sh
# The first time, it also moves your existing data (.env and data/award_wallet.db) into the
# app's data folder, so your programs and saved logins come along.
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="Award Wallet"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)"
DATA_DIR="$HOME/Library/Application Support/$APP_NAME"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "Build this on a Mac: a .app and .dmg can only be made on macOS." >&2
  exit 1
fi
if ! command -v uv >/dev/null; then
  echo "uv is missing. Install it with: brew install uv" >&2
  exit 1
fi

echo "==> Installing dependencies"
uv sync --extra desktop

if [[ "${SKIP_TESTS:-0}" != "1" ]]; then
  echo "==> Running tests"
  uv run pytest
fi

echo "==> Building $APP_NAME.app $VERSION"
rm -rf build/dist build/work
uv run pyinstaller --noconfirm --clean --windowed \
  --name "$APP_NAME" \
  --osx-bundle-identifier com.rafaelcgama.awardwallet \
  --icon "$PWD/packaging/AppIcon.icns" \
  --collect-data award_wallet \
  --add-data "$PWD/src/award_wallet/migrations:award_wallet/migrations" \
  --collect-submodules award_wallet \
  --collect-submodules uvicorn \
  --distpath build/dist --workpath build/work --specpath build \
  packaging/award_wallet_app.py

# Show the real version in Finder and About, then re-sign since the Info.plist changed.
PLIST="build/dist/$APP_NAME.app/Contents/Info.plist"
plutil -replace CFBundleShortVersionString -string "$VERSION" "$PLIST"
plutil -replace CFBundleVersion -string "$VERSION" "$PLIST"
codesign --force --deep --sign - "build/dist/$APP_NAME.app"

echo "==> Packing $APP_NAME.dmg"
rm -rf build/dmg "build/$APP_NAME.dmg"
mkdir -p build/dmg
cp -R "build/dist/$APP_NAME.app" build/dmg/
ln -s /Applications build/dmg/Applications
hdiutil create -quiet -volname "$APP_NAME" -srcfolder build/dmg -ov -format UDZO "build/$APP_NAME.dmg"

if [[ -n "${CI:-}" ]]; then exit 0; fi

# Carry over data from the Terminal version, once. Existing app data is never overwritten.
if [[ -f .env && ! -f "$DATA_DIR/settings.env" ]]; then
  echo "==> Moving your existing data into the app"
  mkdir -p "$DATA_DIR" && chmod 700 "$DATA_DIR"
  cp .env "$DATA_DIR/settings.env" && chmod 600 "$DATA_DIR/settings.env"
  # The -wal and -shm files hold recent changes that SQLite hasn't merged yet.
  for f in data/award_wallet.db data/award_wallet.db-wal data/award_wallet.db-shm; do
    if [[ -f "$f" ]]; then cp "$f" "$DATA_DIR/"; fi
  done
fi

echo
echo "Done: build/$APP_NAME.dmg"
echo "Open it and drag $APP_NAME into Applications."
open build
