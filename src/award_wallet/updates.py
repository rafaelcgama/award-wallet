"""Checks GitHub Releases for a newer version of the app."""

import hashlib
import hmac
import json
import logging
import logging.handlers
import os
import plistlib
import re
import shlex
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

import certifi

from award_wallet import __version__, system

log = logging.getLogger(__name__)

# Far more than the app's download: one that grows past this isn't the app.
MAX_DOWNLOAD = 1024 * 1024 * 1024


class UpdateCheckFailed(Exception):
    """The release list couldn't be read; the message is safe to show."""


@dataclass(frozen=True)
class Release:
    version: str
    page_url: str
    # This computer's download attached to the release, when there is one: the Mac's .dmg or the
    # Windows Setup.exe.
    download_url: str | None
    # Its SHA-256, which GitHub works out when the release is published. A download that doesn't
    # match it is thrown away.
    download_sha256: str | None = None


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


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to another https address, so nobody on the way can swap a file."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https":
            raise urllib.error.URLError(f"won't follow a redirect away from https, to {urlsplit(newurl).scheme}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(request: urllib.request.Request, timeout: float):
    # The Mac app's bundled Python has no access to the system certificates, so bring our own.
    context = ssl.create_default_context(cafile=certifi.where())
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), _HttpsOnly())
    return opener.open(request, timeout=timeout)


def _on_github(url: object, repo: str, kind: str) -> bool:
    """Whether url is in this repository's releases on GitHub: its "download" files or its "tag"
    pages. Nothing else is ever downloaded or linked to."""
    if not isinstance(url, str):
        return False
    parts = urlsplit(url)
    prefix = f"/{repo}/releases/{kind}/"
    if (parts.scheme, parts.netloc) != ("https", "github.com") or parts.query or parts.fragment:
        return False
    if not parts.path.startswith(prefix):
        return False
    rest = [unquote(segment) for segment in parts.path.removeprefix(prefix).split("/")]
    return all(segment not in ("", ".", "..") and not set(segment) & set("/\\") for segment in rest)


def download_ending() -> str:
    """How this computer's download ends its name in a release: Award-Wallet-v1.2.3.dmg for a Mac,
    Award-Wallet-v1.2.3-Setup.exe for Windows."""
    return "-Setup.exe" if system.on_windows() else ".dmg"


def _app_download(data: dict, repo: str) -> tuple[str | None, str | None]:
    """The release's download for this computer, and its SHA-256 when GitHub lists one."""
    assets = data.get("assets")
    for asset in assets if isinstance(assets, list) else []:
        if not isinstance(asset, dict) or not str(asset.get("name", "")).endswith(download_ending()):
            continue
        url = asset.get("browser_download_url")
        if not _on_github(url, repo, "download"):
            log.warning("Ignored a release download outside %s's releases", repo)
            continue
        digest = asset.get("digest")
        found = re.fullmatch(r"sha256:([0-9a-f]{64})", digest) if isinstance(digest, str) else None
        return url, found.group(1) if found else None
    return None, None


def latest_release(repo: str, timeout: float = 10) -> Release:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"AwardWallet/{__version__}"},
    )
    try:
        with _open(request, timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateCheckFailed(
                f"No published releases found for {repo}. If the repository is private, "
                "updates can't be checked automatically."
            ) from None
        raise UpdateCheckFailed(f"GitHub answered with an error ({exc.code}). Try again later.") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise UpdateCheckFailed("Couldn't reach GitHub. Check your internet connection.") from None

    try:
        version = data["tag_name"]
        parse_version(version)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise UpdateCheckFailed("The latest release has no version number.") from None
    page_url = data.get("html_url")
    download_url, download_sha256 = _app_download(data, repo)
    return Release(
        version=version.lstrip("v"),
        page_url=page_url if _on_github(page_url, repo, "tag") else "",
        download_url=download_url,
        download_sha256=download_sha256,
    )


# Installing an update on a Mac -----------------------------------------------------------------

# Runs after the app quits: puts the new app in place, keeping the old one until the copy is
# complete, and reopens it. The new app comes from the downloaded .dmg, or, when moving the app
# into Applications, from the running copy itself.
_INSTALLER = """#!/bin/bash
# Written by Award Wallet to install itself once it has quit.
set -u
# The app keeps its own files private; an installed app is readable like any other.
umask 022
# Wait for the app to quit, for two minutes at most: never replace an app that's still running.
waited=0
while kill -0 {pid} 2>/dev/null; do
  sleep 0.3
  waited=$((waited + 1))
  if [ "$waited" -gt 400 ]; then echo "Award Wallet didn't quit, so nothing was installed"; exit 1; fi
done
new={source}
mount=""
if [ -n {dmg} ]; then
  mount="$(mktemp -d)"
  if hdiutil attach -nobrowse -readonly -quiet -mountpoint "$mount" {dmg}; then
    new="$(find "$mount" -maxdepth 1 -name '*.app' | head -1)"
  else
    new=""
  fi
fi
if [ -n "$new" ] && [ -d "$new" ]; then
  mkdir -p "$(dirname {app})"
  rm -rf {app}.old
  # Only copy once the old app is out of the way: copying over it would mix the two versions.
  if [ ! -e {app}.old ] && {{ [ ! -e {app} ] || mv {app} {app}.old; }}; then
    # A copy downloaded with a browser is marked as from the internet, which makes macOS ask again
    # before opening it; this one came from the app itself, so it's copied without that mark.
    # Never change the new app once it's in place (removing the mark afterwards, say): macOS counts
    # that as modifying another app, blocks it and says Award Wallet "was prevented from modifying
    # apps on your Mac".
    if ditto --noqtn "$new" {app}; then
      rm -rf {app}.old
      echo "Installed $new as {app}"
    else
      echo "Couldn't copy $new, so the app is left as it was"
      rm -rf {app}
      if [ -e {app}.old ]; then mv {app}.old {app}; fi
    fi
  else
    echo "Couldn't move the old app aside, so it's left as it was"
  fi
else
  echo "Nothing to install"
fi
if [ -n "$mount" ]; then hdiutil detach -quiet "$mount"; fi
if [ -n {dmg} ]; then rm -f {dmg}; fi
if [ -d {app} ]; then open {app}; else open {running}; fi
"""

# Where Mac apps live. The app installs itself into the one it's in, or into /Applications when it
# was opened from somewhere else, like the .dmg or Downloads, so it always ends up where you look.
APPLICATIONS = (Path("/Applications"), Path.home() / "Applications")


def running_app_bundle() -> Path | None:
    """The .app this code runs from, or None when it isn't a packaged Mac app."""
    if not system.on_mac() or not getattr(sys, "frozen", False):
        return None
    for parent in Path(sys.executable).resolve().parents:
        if parent.suffix == ".app":
            return parent
    return None


def in_applications(app: Path) -> bool:
    return app.parent in APPLICATIONS


def _can_write(folder: Path) -> bool:
    return os.access(folder, os.W_OK)


def install_target(app: Path) -> Path:
    """Where an update (or a move) puts the app."""
    if in_applications(app):
        return app
    system = APPLICATIONS[0]
    if _can_write(system):
        return system / app.name
    return APPLICATIONS[1] / app.name


def bundle_version(app: Path) -> str | None:
    """The version of the app at app, from its Info.plist, or None when there's no app there."""
    try:
        with (app / "Contents" / "Info.plist").open("rb") as plist:
            version = plistlib.load(plist).get("CFBundleShortVersionString")
        parse_version(version)
    except (OSError, ValueError, TypeError, AttributeError, plistlib.InvalidFileException):
        return None
    return version


def where_it_runs(app: Path) -> str:
    """Where the app was opened from, in words, for when it's not in Applications."""
    if str(app).startswith("/Volumes/"):
        return "the disk image (.dmg)"
    if "/AppTranslocation/" in str(app):
        return "a temporary copy macOS made of it"
    home = Path.home()
    folder = app.parent
    return f"~/{folder.relative_to(home)}" if folder.is_relative_to(home) else str(folder)


def download(
    url: str,
    destination: Path,
    *,
    sha256: str,
    timeout: float = 60,
    progress: Callable[[int, int | None], None] | None = None,
) -> None:
    """Save url to destination, calling progress(bytes so far, total bytes or None) as it goes.

    The file must have the SHA-256 GitHub gave for it, so a file changed on the way is never
    installed: it's deleted instead."""
    request = urllib.request.Request(url, headers={"User-Agent": f"AwardWallet/{__version__}"})
    digest = hashlib.sha256()
    try:
        with _open(request, timeout) as response, destination.open("wb") as out:
            length = (getattr(response, "headers", None) or {}).get("Content-Length")
            total = int(length) if length and str(length).isdigit() else None
            done = 0
            while chunk := response.read(256 * 1024):
                done += len(chunk)
                if done > MAX_DOWNLOAD:
                    raise UpdateCheckFailed("The download is far bigger than the app, so it was stopped.")
                digest.update(chunk)
                out.write(chunk)
                if progress:
                    progress(done, total)
        if not hmac.compare_digest(digest.hexdigest(), sha256.lower()):
            log.warning("The downloaded update doesn't match its release's SHA-256; it was deleted")
            raise UpdateCheckFailed("The download didn't match the release, so nothing was installed. Try again.")
    except UpdateCheckFailed:
        destination.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, TimeoutError, OSError):
        destination.unlink(missing_ok=True)
        raise UpdateCheckFailed("Couldn't download the update. Check your internet connection.") from None


def installer_script(*, app: Path, running: Path, pid: int, dmg: Path | None = None, source: Path | None = None) -> str:
    """The script that puts the new app at app once process pid has quit: from dmg when given,
    otherwise from source (a copy of the app itself)."""

    def quoted(path: Path | None) -> str:
        return shlex.quote(str(path)) if path else "''"

    return _INSTALLER.format(pid=pid, dmg=quoted(dmg), source=quoted(source), app=quoted(app), running=quoted(running))


def _installer_log() -> Path | None:
    """install.log next to the app's own log (in Diagnostics), so an install that went wrong leaves
    a trace where the rest of the troubleshooting information is."""
    for handler in logging.getLogger().handlers:
        # The app's rolling log (see desktop.start_logging), not some other file a library logs to.
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            return Path(handler.baseFilename).with_name("install.log")
    return None


def _run_installer(script_text: str, folder: Path) -> None:
    script = folder / "install.sh"
    script.write_text(script_text, encoding="utf-8")
    script.chmod(0o700)
    log_path = _installer_log() or folder / "install.log"
    with log_path.open("a", encoding="utf-8") as output:
        output.write(f"\n{datetime.now():%Y-%m-%d %H:%M:%S} Award Wallet {__version__} hands over to {script}\n")
        output.flush()
        subprocess.Popen(
            ["/bin/bash", "-x", str(script)],
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )


# Installing an update on Windows ---------------------------------------------------------------


def installed_windows_app() -> Path | None:
    """The folder of the Windows app this code runs from, or None when it isn't a packaged one."""
    if not system.on_windows() or not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve().parent


def installed_app() -> Path | None:
    """The packaged app this code runs from, which can update itself: the Mac's .app or the
    Windows app's folder. None when running from the code, like in development."""
    return running_app_bundle() or installed_windows_app()


def setup_command(setup: Path, log_path: Path) -> list[str]:
    """Runs the downloaded Setup with no window or questions. It waits for the app to quit, puts
    the new version where the old one was and opens it (see packaging/windows/award_wallet.iss)."""
    return [str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOCANCEL", f"/LOG={log_path}"]


def _run_setup(setup: Path) -> None:
    # Setup's own log replaces the last one in Diagnostics, where an install that went wrong
    # leaves its trace.
    log_path = _installer_log() or setup.with_name("install.log")
    log.info("Award Wallet %s hands over to %s", __version__, setup.name)
    # On its own, so it carries on once the app has quit.
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(setup_command(setup, log_path), creationflags=flags, close_fds=True)


def remove_old_downloads(older_than: float = 3600) -> None:
    """Delete updates an earlier launch downloaded: Windows' Setup can't delete itself, so its
    folder stays behind once it's done."""
    cutoff = time.time() - older_than
    try:
        folders = list(Path(tempfile.gettempdir()).glob("award-wallet-update-*"))
    except OSError:
        return
    for folder in folders:
        try:
            if folder.is_dir() and folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            continue


def start_move(app: Path) -> Path:
    """Copy the running app into Applications once it quits, and open it there. Returns where.

    When Applications already has this version or a newer one (this copy is a stale one, left in
    Downloads, say), that one is kept and opened instead."""
    target = install_target(app)
    installed = bundle_version(target)
    source = None if installed and not is_newer(__version__, installed) else app
    folder = Path(tempfile.mkdtemp(prefix="award-wallet-move-"))
    _run_installer(installer_script(app=target, running=app, pid=os.getpid(), source=source), folder)
    return target


@dataclass(frozen=True)
class Progress:
    """Where an update stands, for the window's progress bar."""

    # "idle", "downloading", "installing" (the app is about to quit and reopen) or "failed".
    state: str = "idle"
    version: str = ""
    done: int = 0
    total: int | None = None
    error: str = ""

    @property
    def percent(self) -> int | None:
        if self.state == "installing":
            return 100
        if not self.total:
            return None
        return min(99, self.done * 100 // self.total)


class Updater:
    """Downloads and installs one update in the background, so the window can show its progress:
    click, it downloads, the app quits, replaces itself and reopens."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._progress = Progress()

    def progress(self) -> Progress:
        with self._lock:
            return self._progress

    def _set(self, **changes) -> None:
        with self._lock:
            self._progress = replace(self._progress, **changes)

    def start(self, release: Release, app: Path, when_installing: Callable[[], None]) -> bool:
        """Start installing release over app; when_installing is called once the new version is
        downloaded and ready (the app should quit then). False if an update is already going."""
        with self._lock:
            if self._progress.state in ("downloading", "installing"):
                return False
            self._progress = Progress(state="downloading", version=release.version)
        threading.Thread(
            target=self._install, args=(release, app, when_installing), name="award-wallet-update", daemon=True
        ).start()
        return True

    def _install(self, release: Release, app: Path, when_installing: Callable[[], None]) -> None:
        try:
            if not release.download_url:
                computer = "Windows" if system.on_windows() else "Mac"
                raise UpdateCheckFailed(f"This release has no {computer} app attached yet. Try again in a few minutes.")
            if not release.download_sha256:
                # Without it, a changed file couldn't be told apart from the real one.
                raise UpdateCheckFailed("GitHub hasn't listed this release's checksum yet. Try again in a few minutes.")
            folder = Path(tempfile.mkdtemp(prefix="award-wallet-update-"))
            downloaded = folder / ("Award-Wallet-Setup.exe" if system.on_windows() else "update.dmg")
            download(
                release.download_url,
                downloaded,
                sha256=release.download_sha256,
                progress=lambda done, total: self._set(done=done, total=total),
            )
            if system.on_windows():
                _run_setup(downloaded)
            else:
                target = install_target(app)
                _run_installer(installer_script(app=target, running=app, pid=os.getpid(), dmg=downloaded), folder)
        except UpdateCheckFailed as exc:
            self._set(state="failed", error=str(exc))
            return
        except Exception:
            log.exception("Installing the update failed")
            self._set(state="failed", error="Couldn't install the update. Try again.")
            return
        log.info("Update %s downloaded; quitting to install it", release.version)
        self._set(state="installing")
        when_installing()
