"""What the Windows app asks of Windows itself: that only one copy runs, how big the screen is, and
the details about this PC that Chrome gives sites. Only called on Windows, except for the parts
that just work things out (platform_version, chrome_version), which tests check anywhere."""

import ctypes
import os
import re
import sys
from pathlib import Path

# The app holds this while it runs. Setup (packaging/windows/milestash.iss) waits for it to go
# before it replaces the app, so the two names must stay the same.
MUTEX_NAME = "Milestash"
_ERROR_ALREADY_EXISTS = 183
_SW_RESTORE = 9
_DESKTOPVERTRES = 117
_DESKTOPHORZRES = 118

# Held until the app quits: Windows lets go of a mutex when the last handle to it closes.
_mutex = None

# The first build of each Windows release, and the version Chrome tells sites it is (the
# Sec-CH-UA-Platform-Version client hint): Windows' own interface version, not its name, so
# Windows 11 is 13 or more. Newer builds than the first row tell the first row's.
_PLATFORM_VERSIONS = (
    (26100, "19.0.0"),  # Windows 11 24H2 and later
    (22621, "15.0.0"),  # Windows 11 22H2 and 23H2
    (22000, "14.0.0"),  # Windows 11 21H2
    (19041, "10.0.0"),  # Windows 10 2004 to 22H2
    (18362, "8.0.0"),
    (17763, "7.0.0"),
    (17134, "6.0.0"),
    (16299, "5.0.0"),
    (15063, "4.0.0"),
    (14393, "3.0.0"),
    (10586, "2.0.0"),
    (10240, "1.0.0"),
)
_CHROME_VERSION = re.compile(r"\d+(?:\.\d+){3}")


def claim_single_instance() -> bool:
    """Whether this is the only copy of the app running. The first copy holds a named mutex until
    it quits; a second one finds it taken."""
    global _mutex
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        # Windows didn't say: a second copy is better than one that won't open.
        return True
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _mutex = handle
    return True


def show_running_copy(title: str) -> None:
    """Bring the running copy's window to the front, and back up if it was minimized. It's the
    Windows Forms window with the app's name, so a folder window of the same name isn't."""
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    each_window = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [each_window, wintypes.LPARAM]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    found = []

    def check(window, _) -> bool:
        text = ctypes.create_unicode_buffer(256)
        kind = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(window, text, 256)
        user32.GetClassNameW(window, kind, 256)
        if text.value == title and kind.value.startswith("WindowsForms"):
            found.append(window)
        return True

    user32.EnumWindows(each_window(check), 0)
    for window in found:
        if user32.IsIconic(window):
            user32.ShowWindow(window, _SW_RESTORE)
        user32.SetForegroundWindow(window)


def screen() -> tuple[int, int, float] | None:
    """The main screen: its width and height in the units pages measure in, and how many pixels
    make one of them (1.5 with Windows' display scale at 150%). None if Windows doesn't say."""
    import winreg
    from ctypes import wintypes

    try:
        user32 = ctypes.WinDLL("user32")
        gdi32 = ctypes.WinDLL("gdi32")
        user32.GetDC.argtypes = [wintypes.HWND]
        user32.GetDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
        context = user32.GetDC(None)
        try:
            # The screen's real size in pixels, whatever scaling Windows applies to this app.
            width = gdi32.GetDeviceCaps(context, _DESKTOPHORZRES)
            height = gdi32.GetDeviceCaps(context, _DESKTOPVERTRES)
        finally:
            user32.ReleaseDC(None, context)
    except OSError:
        return None
    dpi = 96
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop\WindowMetrics") as key:
            dpi = int(winreg.QueryValueEx(key, "AppliedDPI")[0])
    except (OSError, ValueError):
        pass
    if width <= 0 or height <= 0 or dpi <= 0:
        return None
    scale = round(dpi / 96, 2)
    return round(width / scale), round(height / scale), scale


def build_number() -> int:
    """This Windows' build number, like 26100."""
    return sys.getwindowsversion().build


def platform_version(build: int) -> str:
    """What Chrome on a PC with this Windows build tells sites its Windows version is."""
    for first, version in _PLATFORM_VERSIONS:
        if build >= first:
            return version
    return "0.0.0"


def chrome_version() -> str | None:
    """The version of the installed Google Chrome, which names a folder next to chrome.exe. Looks
    where Playwright looks for it: installed for you alone first, then for everyone."""
    for variable in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        root = os.environ.get(variable)
        folder = Path(root) / "Google" / "Chrome" / "Application" if root else None
        if folder is None or not (folder / "chrome.exe").is_file():
            continue
        versions = [entry.name for entry in folder.iterdir() if _CHROME_VERSION.fullmatch(entry.name)]
        versions = [name for name in versions if (folder / name).is_dir()]
        return max(versions, key=lambda name: tuple(int(part) for part in name.split("."))) if versions else None
    return None
