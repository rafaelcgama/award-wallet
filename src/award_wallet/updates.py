"""Checks GitHub Releases for a newer version of the app."""

import json
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass

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
