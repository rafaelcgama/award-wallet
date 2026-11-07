"""The Windows app's own parts. The ones that only work things out run everywhere; the ones that
ask Windows itself run on Windows, which GitHub's Windows check does for every pull request."""

import os
import re
import sys
import uuid
from pathlib import Path

import pytest

from award_wallet import desktop, fetching, system, windows

on_windows = pytest.mark.skipif(sys.platform != "win32", reason="asks Windows itself")


@pytest.mark.parametrize(
    ("build", "version"),
    [(26200, "19.0.0"), (26100, "19.0.0"), (22631, "15.0.0"), (22000, "14.0.0"), (19045, "10.0.0"), (9600, "0.0.0")],
)
def test_sites_hear_the_windows_version_chrome_tells_them(build, version):
    # Windows 11 is 13 or more: Chrome gives sites Windows' own version number, not its name.
    assert windows.platform_version(build) == version


def test_the_installed_chromes_version_is_its_newest_folder(monkeypatch, tmp_path):
    application = tmp_path / "Google" / "Chrome" / "Application"
    for name in ("141.0.7390.55", "142.0.7444.60", "SetupMetrics", "142.0.7444.9"):
        (application / name).mkdir(parents=True)
    (application / "143.0.0.1").write_text("not a folder", encoding="utf-8")
    (application / "chrome.exe").write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nothing here"))
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path))
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path / "nothing here either"))
    assert windows.chrome_version() == "142.0.7444.60"
    (application / "chrome.exe").unlink()
    assert windows.chrome_version() is None


def test_windows_chrome_tells_sites_it_is_chrome_on_windows(monkeypatch):
    monkeypatch.delenv("AW_BROWSER_PATH", raising=False)
    monkeypatch.setattr(system, "on_windows", lambda: True)
    monkeypatch.setattr(windows, "chrome_version", lambda: "142.0.7444.60")
    assert fetching.chrome_user_agent() == (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/142.0.0.0 Safari/537.36"
    )
    monkeypatch.setattr(windows, "chrome_version", lambda: None)
    assert fetching.chrome_user_agent() is None


def test_windows_chrome_gives_sites_the_real_windows_details(monkeypatch):
    monkeypatch.setattr(system, "on_windows", lambda: True)
    monkeypatch.setattr(windows, "build_number", lambda: 26100)
    monkeypatch.setattr(fetching.platform, "machine", lambda: "AMD64")
    hints = fetching._client_hints()
    assert (hints["platform"], hints["platformVersion"], hints["architecture"]) == ("Windows", "19.0.0", "x86")
    monkeypatch.setattr(fetching.platform, "machine", lambda: "ARM64")
    assert fetching._client_hints()["architecture"] == "arm"


def test_the_screen_a_site_sees_matches_windows_display_scale(monkeypatch):
    # A 2560x1440 screen at 150%: pages measure it as 1707x960, with 1.5 pixels to each unit.
    monkeypatch.setattr(system, "on_windows", lambda: True)
    monkeypatch.setattr(windows, "screen", lambda: (1707, 960, 1.5))
    monkeypatch.delenv("AW_BROWSER_PATH", raising=False)
    monkeypatch.setattr(windows, "chrome_version", lambda: None)
    args = fetching._launch_options()["args"]
    assert "--screen-info={0,0 2560x1440 devicePixelRatio=1.5}" in args
    assert "--window-size=1200,760" in args


def test_a_screen_windows_wont_describe_is_left_to_chrome(monkeypatch):
    def broken():
        raise OSError("no screen")

    monkeypatch.setattr(system, "on_windows", lambda: True)
    monkeypatch.setattr(windows, "screen", broken)
    assert fetching.this_screen() is None


# Asking Windows itself -------------------------------------------------------------------------


@on_windows
def test_only_one_copy_runs_at_a_time(monkeypatch):
    import ctypes

    # A name of its own, so an Award Wallet open on this PC doesn't count.
    monkeypatch.setattr(windows, "MUTEX_NAME", f"AwardWalletTest-{uuid.uuid4()}")
    monkeypatch.setattr(windows, "_mutex", None)
    assert windows.claim_single_instance()
    try:
        assert not windows.claim_single_instance()
    finally:
        ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(windows._mutex))


@on_windows
def test_bringing_back_a_window_that_isnt_there_does_nothing():
    windows.show_running_copy(f"Award Wallet {uuid.uuid4()}")


@on_windows
def test_windows_describes_this_pc():
    assert windows.build_number() >= 17763
    assert windows.platform_version(windows.build_number()) != "0.0.0"
    screen = windows.screen()
    # A PC without a screen, like some servers, gives none.
    if screen is not None:
        width, height, scale = screen
        assert width > 0 and height > 0 and scale >= 1


@on_windows
def test_the_data_folder_is_in_local_app_data():
    assert desktop.data_dir() == Path(os.environ["LOCALAPPDATA"]) / "Award Wallet"


needs_chrome = pytest.mark.skipif(
    sys.platform != "win32" or (windows.chrome_version() if sys.platform == "win32" else None) is None,
    reason="needs Google Chrome installed on Windows",
)


@needs_chrome
def test_the_installed_chromes_version_is_found():
    assert re.fullmatch(r"\d+\.\d+\.\d+\.\d+", windows.chrome_version())


@needs_chrome
def test_the_hidden_chrome_is_the_installed_google_chrome_and_says_so(monkeypatch, tmp_path):
    # The way the app starts it, rather than the tests' AW_BROWSER_PATH.
    monkeypatch.delenv("AW_BROWSER_PATH", raising=False)
    playwright, context = fetching.browser_launcher(tmp_path / "profile")
    try:
        page = context.pages[0] if context.pages else context.new_page()
        agent = page.evaluate("navigator.userAgent")
        platform = page.evaluate("navigator.userAgentData.platform")
    finally:
        context.close()
        playwright.stop()
    assert "Windows NT 10.0; Win64; x64" in agent and "Headless" not in agent
    assert f"Chrome/{windows.chrome_version().split('.')[0]}.0.0.0" in agent
    assert platform == "Windows"
