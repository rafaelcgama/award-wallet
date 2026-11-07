#!/usr/bin/env bash
# Builds Milestash.app and "Milestash.dmg" in build/. GitHub runs this for each release;
# to build one yourself on a Mac, run from this folder (the README's "Build it yourself" walks
# through it):
#   bash build_dmg.sh
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="Milestash"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "Build this on a Mac: a .app and .dmg can only be made on macOS." >&2
  exit 1
fi
if ! command -v uv >/dev/null && [[ -x "$HOME/.local/bin/uv" ]]; then
  # uv's installer puts it here, and a Terminal window opened before the install doesn't look there.
  PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v uv >/dev/null; then
  echo "uv is missing. Install it with this line, then open a new Terminal window and try again:" >&2
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

echo "==> Installing dependencies"
uv sync --locked --extra desktop

if [[ "${SKIP_TESTS:-0}" != "1" ]]; then
  echo "==> Running tests"
  uv run pytest
fi

echo "==> Building $APP_NAME.app $VERSION"
rm -rf build/dist build/work
uv run pyinstaller --noconfirm --clean --windowed \
  --name "$APP_NAME" \
  --osx-bundle-identifier com.rafaelcgama.milestash \
  --icon "$PWD/packaging/AppIcon.icns" \
  --collect-data milestash \
  --add-data "$PWD/src/milestash/migrations:milestash/migrations" \
  --collect-submodules milestash \
  --collect-submodules uvicorn \
  --distpath build/dist --workpath build/work --specpath build \
  packaging/milestash_app.py

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
# The folder the .dmg was made from has a shortcut to /Applications, which editors and backup tools
# would wander into (PyCharm offered to "npm install" inside other apps there). Its job is done.
rm -rf build/dmg

echo
echo "Done: build/$APP_NAME.dmg"
if [[ -z "${CI:-}" ]]; then open build; fi
