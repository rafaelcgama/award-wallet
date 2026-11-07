"""The few things that differ between the Mac app and the Windows app, asked in one place."""

import sys


def on_windows() -> bool:
    return sys.platform == "win32"


def on_mac() -> bool:
    return sys.platform == "darwin"


def file_browser() -> str:
    """What this computer calls the app that shows folders."""
    return "File Explorer" if on_windows() else "Finder"
