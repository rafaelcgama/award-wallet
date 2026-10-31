#!/usr/bin/env bash
# Builds Award Wallet.app and "Award Wallet.dmg" in build/. GitHub runs this for each release;
# to build one yourself on a Mac, run from this folder:
#   bash build_dmg.sh
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="Award Wallet"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)"

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

echo
echo "Done: build/$APP_NAME.dmg"
if [[ -z "${CI:-}" ]]; then open build; fi
