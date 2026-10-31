"""Checks GitHub Releases for a newer version of the app."""

import json
import os
import re
import shlex
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import certifi

from award_wallet import __version__


class UpdateCheckFailed(Exception):
    """The release list couldn't be read; the message is safe to show."""


@dataclass(frozen=True)
class Release:
    version: str
    page_url: str
    # The .dmg attached to the release, when there is one.
    download_url: str | None


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.3' -> (1, 2, 3). Anything after the numbers (like '-beta') is ignored."""
    match = re.match(r"v?(\d+(?:\.\d+)*)", text.strip())
    if not match:
        raise ValueError(f"Not a version: {text!r}")
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(candidate: str, current: str = __version__) -> bool:
    def padded(version: tuple[int, ...]) -> tuple[int, ...]:
        return version + (0,) * (4 - len(version))

    return padded(parse_version(candidate)) > padded(parse_version(current))


def latest_release(repo: str, timeout: float = 10) -> Release:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"AwardWallet/{__version__}"},
    )
    # The Mac app's bundled Python has no access to the system certificates, so bring our own.
    context = ssl.create_default_context(cafile=certifi.where())
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateCheckFailed(
                f"No published releases found for {repo}. If the repository is private, "
                "updates can't be checked automatically."
            ) from None
        raise UpdateCheckFailed(f"GitHub answered with an error ({exc.code}). Try again later.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise UpdateCheckFailed("Couldn't reach GitHub. Check your internet connection.") from None

    try:
        version = data["tag_name"]
        parse_version(version)
    except (KeyError, TypeError, ValueError):
        raise UpdateCheckFailed("The latest release has no version number.") from None
    dmgs = [asset for asset in data.get("assets", []) if asset.get("name", "").endswith(".dmg")]
    download_url = dmgs[0].get("browser_download_url") if dmgs else None
    return Release(version=version.lstrip("v"), page_url=data.get("html_url", ""), download_url=download_url)


# Installing an update (the Mac app only) ------------------------------------------------------

_INSTALLER = """#!/bin/bash
# Written by Award Wallet to install an update once the app has quit.
set -u
while kill -0 {pid} 2>/dev/null; do sleep 0.3; done
mount="$(mktemp -d)"
if hdiutil attach -nobrowse -readonly -quiet -mountpoint "$mount" {dmg}; then
  new="$(find "$mount" -maxdepth 1 -name '*.app' | head -1)"
  if [ -n "$new" ]; then
    rm -rf {app}.old
    mv {app} {app}.old
    if ditto "$new" {app}; then rm -rf {app}.old; else rm -rf {app}; mv {app}.old {app}; fi
  fi
  hdiutil detach -quiet "$mount"
fi
rm -f {dmg}
open {app}
"""


def running_app_bundle() -> Path | None:
    """The .app this code runs from, or None when it isn't a packaged Mac app."""
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    for parent in Path(sys.executable).resolve().parents:
        if parent.suffix == ".app":
            return parent
    return None


def download(url: str, destination: Path, timeout: float = 60) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": f"AwardWallet/{__version__}"})
    context = ssl.create_default_context(cafile=certifi.where())
    try:
        with (
            urllib.request.urlopen(request, timeout=timeout, context=context) as response,
            destination.open("wb") as out,
        ):
            shutil.copyfileobj(response, out)
    except (urllib.error.URLError, TimeoutError, OSError):
        destination.unlink(missing_ok=True)
        raise UpdateCheckFailed("Couldn't download the update. Check your internet connection.") from None


def installer_script(dmg: Path, app: Path, pid: int) -> str:
    return _INSTALLER.format(pid=pid, dmg=shlex.quote(str(dmg)), app=shlex.quote(str(app)))


def start_install(release: Release, app: Path) -> None:
    """Download the release and hand over to a script that swaps the app once we quit."""
    if not release.download_url:
        raise UpdateCheckFailed("This release has no Mac app attached yet. Try again in a few minutes.")
    folder = Path(tempfile.mkdtemp(prefix="award-wallet-update-"))
    dmg = folder / "update.dmg"
    download(release.download_url, dmg)
    script = folder / "install.sh"
    script.write_text(installer_script(dmg, app, os.getpid()))
    script.chmod(0o700)
    subprocess.Popen(["/bin/bash", str(script)], start_new_session=True, close_fds=True)
