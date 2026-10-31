#!/usr/bin/env bash
# Publishes a new version: bumps the version, commits, tags and pushes. GitHub then builds the
# Mac app and attaches it to a release, and the installed app offers it as an update.
#   bash release.sh          # 0.3.0 -> 0.3.1
#   bash release.sh 0.4.0    # a specific version
set -euo pipefail
cd "$(dirname "$0")"

current="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)"
if [[ $# -ge 1 ]]; then
  next="$1"
else
  IFS=. read -r major minor patch <<<"$current"
  next="$major.$minor.$((patch + 1))"
fi

if [[ "$(git branch --show-current)" != "main" ]]; then
  echo "Switch to main first (git switch main)." >&2
  exit 1
fi

echo "==> Releasing $current -> $next"
perl -pi -e "s/^version = \"\Q$current\E\"/version = \"$next\"/" pyproject.toml
perl -pi -e "s/__version__ = \"\Q$current\E\"/__version__ = \"$next\"/" src/award_wallet/__init__.py
perl -0pi -e "s/## \[Unreleased\]\n/## [Unreleased]\n\n## [$next] - $(date +%Y-%m-%d)\n/" CHANGELOG.md
uv lock -q

git add -A
git commit -m "Release v$next"
git tag "v$next"
git push origin main "v$next"

echo
echo "Pushed v$next. GitHub is building the app (about 10 minutes):"
echo "  https://github.com/$(git remote get-url origin | sed -E 's#.*github.com[:/](.*)\.git#\1#; s#.*github.com[:/](.*)#\1#')/actions"
echo "When it's done, choose Award Wallet > Check for Updates… in the app."
