import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from milestash import __version__, system, updates
from milestash.web import create_app

# The Mac app's installer is a shell script that works with Mac paths like /Applications: its tests
# run on Macs and Linux, not on Windows, which has its own installer (see the _Windows tests).
mac_installer = pytest.mark.skipif(sys.platform == "win32", reason="the Mac installer's paths and shell")


class _window:
    """The app window, already signed in with its launch token."""

    def __init__(self, settings):
        desktop = settings.model_copy(update={"desktop_token": SecretStr("t")})
        self.client = TestClient(create_app(desktop), base_url="http://127.0.0.1")

    def __enter__(self):
        self.client.__enter__()
        self.client.get("/?token=t")
        return self.client

    def __exit__(self, *exc):
        return self.client.__exit__(*exc)


def test_version_matches_package_metadata():
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == __version__


@pytest.mark.parametrize(
    ("candidate", "current", "newer"),
    [
        ("v0.3.0", "0.2.0", True),
        ("0.2.1", "0.2.0", True),
        ("0.2", "0.2.0", False),
        ("v0.1.9", "0.2.0", False),
        ("1.0.0-beta", "0.9", True),
    ],
)
def test_version_comparison(candidate, current, newer):
    assert updates.is_newer(candidate, current) is newer


def test_about_page_shows_version(settings):
    with _window(settings) as window:
        page = window.get("/about")
        assert page.status_code == 200
        assert f"Version {__version__}" in page.text
        assert "Check for updates" in page.text


def test_about_page_leaves_out_the_data_folder(settings, tmp_path):
    with _window(settings) as window:
        page = window.get("/about")
    assert "Your data is kept" not in page.text
    assert str(tmp_path.resolve()) not in page.text


def _fake_github(monkeypatch, payload=None, error=None):
    def answer(request, timeout):
        if error:
            raise error
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(updates, "_open", answer)


RELEASES = "https://github.com/rafaelcgama/milestash/releases"
DMG = f"{RELEASES}/download/v99.0.0/Milestash-v99.0.0.dmg"
DMG_SHA256 = hashlib.sha256(b"dmg").hexdigest()
SETUP = f"{RELEASES}/download/v99.0.0/Milestash-v99.0.0-Setup.exe"
SETUP_SHA256 = hashlib.sha256(b"setup").hexdigest()
# The download for the computer the tests run on.
DOWNLOAD, DOWNLOAD_SHA256 = (SETUP, SETUP_SHA256) if sys.platform == "win32" else (DMG, DMG_SHA256)


def _release_payload(**changes) -> dict:
    """A release as GitHub lists it, with the Mac and the Windows app; changes apply to both."""
    assets = [
        {"name": "Milestash-v99.0.0.dmg", "browser_download_url": DMG, "digest": f"sha256:{DMG_SHA256}"},
        {"name": "Milestash-v99.0.0-Setup.exe", "browser_download_url": SETUP, "digest": f"sha256:{SETUP_SHA256}"},
    ]
    return {
        "tag_name": "v99.0.0",
        "html_url": f"{RELEASES}/tag/v99.0.0",
        "assets": [{**asset, **changes} for asset in assets],
    }


def test_newer_release_offers_download(settings, monkeypatch):
    _fake_github(monkeypatch, _release_payload())
    with _window(settings) as window:
        page = window.get("/about?check=1")
        assert "Version 99.0.0 is available" in page.text
        assert DOWNLOAD in page.text


def test_a_release_names_its_download_and_checksum(monkeypatch):
    _fake_github(monkeypatch, _release_payload())
    release = updates.latest_release("rafaelcgama/milestash")
    assert (release.download_url, release.download_sha256) == (DOWNLOAD, DOWNLOAD_SHA256)
    assert release.page_url == f"{RELEASES}/tag/v99.0.0"


@pytest.mark.parametrize(("on_windows", "app"), [(False, (DMG, DMG_SHA256)), (True, (SETUP, SETUP_SHA256))])
def test_each_computer_downloads_its_own_app(monkeypatch, on_windows, app):
    monkeypatch.setattr(system, "on_windows", lambda: on_windows)
    _fake_github(monkeypatch, _release_payload())
    release = updates.latest_release("rafaelcgama/milestash")
    assert (release.download_url, release.download_sha256) == app


@pytest.mark.parametrize(("on_windows", "name"), [(False, "Milestash.dmg"), (True, "Milestash-Setup.exe")])
def test_downloads_named_without_the_version_are_found_too(monkeypatch, on_windows, name):
    # From 0.14.1 on, every release names its files the same, so the README can link to the newest.
    monkeypatch.setattr(system, "on_windows", lambda: on_windows)
    payload = _release_payload()
    for asset, fixed in zip(payload["assets"], ("Milestash.dmg", "Milestash-Setup.exe"), strict=True):
        asset["name"], asset["browser_download_url"] = fixed, f"{RELEASES}/download/v99.0.0/{fixed}"
    _fake_github(monkeypatch, payload)
    assert updates.latest_release("rafaelcgama/milestash").download_url == f"{RELEASES}/download/v99.0.0/{name}"


def test_the_readme_links_to_the_files_every_release_has(monkeypatch):
    # The README's download links fetch the newest release's files by name: release.yml has to
    # publish exactly those names, and each computer's app has to recognize its own.
    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    for on_windows, name in ((False, "Milestash.dmg"), (True, "Milestash-Setup.exe")):
        monkeypatch.setattr(system, "on_windows", lambda on_windows=on_windows: on_windows)
        assert f"{RELEASES}/latest/download/{name}" in readme
        assert f"path: build/{name}\n" in workflow
        assert name.endswith(updates.download_ending())


def test_windows_never_downloads_the_mac_app(monkeypatch):
    # Say the release is out but its Setup isn't attached yet.
    monkeypatch.setattr(system, "on_windows", lambda: True)
    mac_only = _release_payload()
    mac_only["assets"] = mac_only["assets"][:1]
    _fake_github(monkeypatch, mac_only)
    assert updates.latest_release("rafaelcgama/milestash").download_url is None


@pytest.mark.parametrize(
    "elsewhere",
    [
        "https://example.com/aw.dmg",
        "http://github.com/rafaelcgama/milestash/releases/download/v99.0.0/aw.dmg",
        "https://github.com/someone-else/milestash/releases/download/v99.0.0/aw.dmg",
        "https://github.com/rafaelcgama/milestash/releases/download/../../../../x/y/releases/download/v1/aw.dmg",
        "https://github.com/rafaelcgama/milestash/releases/download/v99.0.0/%2e%2e/aw.dmg",
        "https://github.com.example.com/rafaelcgama/milestash/releases/download/v99.0.0/aw.dmg",
    ],
)
def test_nothing_is_downloaded_from_outside_the_apps_own_releases(monkeypatch, elsewhere):
    _fake_github(monkeypatch, _release_payload(browser_download_url=elsewhere))
    assert updates.latest_release("rafaelcgama/milestash").download_url is None


def test_current_release_says_up_to_date(settings, monkeypatch):
    _fake_github(monkeypatch, {"tag_name": f"v{__version__}", "html_url": "", "assets": []})
    with _window(settings) as window:
        assert "You have the latest version" in window.get("/about?check=1").text


def test_failed_check_is_explained(settings, monkeypatch):
    _fake_github(monkeypatch, error=urllib.error.URLError("offline"))
    with _window(settings) as window:
        assert "Couldn&#39;t reach GitHub" in window.get("/about?check=1").text
    _fake_github(monkeypatch, error=urllib.error.HTTPError("u", 404, "nf", {}, None))
    with _window(settings) as window:
        assert "No published releases" in window.get("/about?check=1").text


class _Installed:
    """The installed app, as the update code sees it: its quit hook, and where it runs."""

    def __init__(self, monkeypatch):
        self.quit_calls = 0
        # Quit right away instead of after the "Installing" page has shown for a moment.
        monkeypatch.setattr(
            "milestash.web.routes.about.threading.Timer",
            lambda delay, fn: type("T", (), {"start": lambda self: fn()})(),
        )

    def attach(self, window) -> None:
        window.app.state.quit_app = self.quit

    def quit(self) -> None:
        self.quit_calls += 1


class _Mac(_Installed):
    """The installed Mac app, and the installer scripts it starts."""

    def __init__(self, monkeypatch, app: Path):
        super().__init__(monkeypatch)
        self.installers: list[str] = []
        monkeypatch.setattr(system, "on_windows", lambda: False)
        monkeypatch.setattr(updates, "running_app_bundle", lambda: app)
        monkeypatch.setattr(updates, "_run_installer", lambda text, folder: self.installers.append(text))


class _Windows(_Installed):
    """The installed Windows app, and the Setups it runs."""

    def __init__(self, monkeypatch, folder: Path):
        super().__init__(monkeypatch)
        self.setups: list[Path] = []
        monkeypatch.setattr(system, "on_windows", lambda: True)
        monkeypatch.setattr(updates, "running_app_bundle", lambda: None)
        monkeypatch.setattr(updates, "installed_windows_app", lambda: folder)
        monkeypatch.setattr(updates, "_run_setup", self.setups.append)


def _token(page: str) -> str:
    return page.split('name="csrf_token" value="')[1].split('"')[0]


def _wait_for(window, **expected) -> dict:
    """Poll the update's status, as the progress page does, until it shows what's expected."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = window.get("/update/status").json()
        if all(status[key] == value for key, value in expected.items()):
            return status
        time.sleep(0.02)
    raise AssertionError(f"the update never got to {expected}: {status}")


def _eventually(condition) -> None:
    deadline = time.monotonic() + 10
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.02)


@mac_installer
def test_update_now_is_one_click_with_progress(settings, monkeypatch, tmp_path):
    release = updates.Release("99.0.0", f"{RELEASES}/tag/v99.0.0", DMG, DMG_SHA256)
    monkeypatch.setattr(updates, "latest_release", lambda repo: release)
    mac = _Mac(monkeypatch, Path("/Applications/Milestash.app"))
    go_on = threading.Event()

    def download(url, destination, *, sha256, timeout=60, progress=None):
        assert sha256 == DMG_SHA256
        progress(40, 100)
        go_on.wait(10)
        progress(100, 100)
        destination.write_bytes(b"dmg")

    monkeypatch.setattr(updates, "download", download)
    with _window(settings) as window:
        mac.attach(window)
        window.app.state.available_update = release
        dashboard = window.get("/").text
        assert "Milestash 99.0.0 is available." in dashboard and "Update now" in dashboard
        # One click on the banner starts it: no second button on another page.
        page = window.post("/update", data={"csrf_token": _token(dashboard)})
        assert page.url.path == "/update"
        assert "Updating to 99.0.0" in page.text and "progressbar" in page.text
        _wait_for(window, state="downloading", percent=40)
        go_on.set()
        _wait_for(window, state="installing", percent=100)
        _eventually(lambda: mac.quit_calls == 1)
        # Clicking again while it installs doesn't start a second one.
        window.post("/update", data={"csrf_token": _token(dashboard)})
    [script] = mac.installers
    assert "mv /Applications/Milestash.app /Applications/Milestash.app.old" in script and "update.dmg" in script
    assert mac.quit_calls == 1


def test_update_now_on_windows_runs_the_new_setup(settings, monkeypatch, tmp_path):
    release = updates.Release("99.0.0", f"{RELEASES}/tag/v99.0.0", SETUP, SETUP_SHA256)
    monkeypatch.setattr(updates, "latest_release", lambda repo: release)
    pc = _Windows(monkeypatch, tmp_path / "Programs" / "Milestash")
    downloads = []

    def download(url, destination, *, sha256, timeout=60, progress=None):
        downloads.append((url, sha256))
        progress(100, 100)
        destination.write_bytes(b"setup")

    monkeypatch.setattr(updates, "download", download)
    with _window(settings) as window:
        pc.attach(window)
        window.app.state.available_update = release
        dashboard = window.get("/").text
        assert "Update now" in dashboard
        window.post("/update", data={"csrf_token": _token(dashboard)})
        _wait_for(window, state="installing", percent=100)
        _eventually(lambda: pc.quit_calls == 1)
    assert downloads == [(SETUP, SETUP_SHA256)]
    # The Setup it checked is the one it runs, and then the app quits so Setup can replace it.
    [setup] = pc.setups
    assert setup.name == "Milestash-Setup.exe" and setup.read_bytes() == b"setup"


def test_windows_setup_runs_on_its_own_with_no_questions(monkeypatch, tmp_path):
    import logging.handlers

    started = []
    monkeypatch.setattr(updates.subprocess, "Popen", lambda command, **options: started.append((command, options)))
    diagnostics = tmp_path / "Diagnostics"
    diagnostics.mkdir()
    handler = logging.handlers.RotatingFileHandler(diagnostics / "milestash.log", encoding="utf-8")
    logging.getLogger().addHandler(handler)
    try:
        updates._run_setup(tmp_path / "Milestash-Setup.exe")
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
    [(command, options)] = started
    # Setup's log goes next to the app's, where the rest of the troubleshooting information is.
    assert command == [
        str(tmp_path / "Milestash-Setup.exe"),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/NOCANCEL",
        f"/LOG={diagnostics / 'install.log'}",
    ]
    if sys.platform == "win32":
        # It carries on once the app has quit.
        assert options["creationflags"] & subprocess.DETACHED_PROCESS


def test_updates_downloaded_by_an_earlier_launch_are_cleared_away(monkeypatch, tmp_path):
    monkeypatch.setattr(updates.tempfile, "gettempdir", lambda: str(tmp_path))
    two_hours_ago = time.time() - 2 * 3600
    old = tmp_path / "milestash-update-old"
    old.mkdir()
    (old / "Milestash-Setup.exe").write_bytes(b"setup")
    os.utime(old, (two_hours_ago, two_hours_ago))
    # One downloading right now stays, and so does everything that isn't the app's.
    new = tmp_path / "milestash-update-new"
    new.mkdir()
    other = tmp_path / "someone-elses"
    other.mkdir()
    os.utime(other, (two_hours_ago, two_hours_ago))
    updates.remove_old_downloads()
    assert not old.exists() and new.exists() and other.exists()


def test_a_failed_download_says_why_and_offers_another_try(settings, monkeypatch):
    release = updates.Release("99.0.0", f"{RELEASES}/tag/v99.0.0", DMG, DMG_SHA256)
    monkeypatch.setattr(updates, "latest_release", lambda repo: release)
    mac = _Mac(monkeypatch, Path("/Applications/Milestash.app"))

    def offline(url, destination, *, sha256, timeout=60, progress=None):
        raise updates.UpdateCheckFailed("Couldn't download the update. Check your internet connection.")

    monkeypatch.setattr(updates, "download", offline)
    with _window(settings) as window:
        mac.attach(window)
        about = window.get("/about?check=1").text
        assert "Update to 99.0.0" in about
        window.post("/update", data={"csrf_token": _token(about)})
        assert "Couldn't download" in _wait_for(window, state="failed")["error"]
        page = window.get("/update").text
        assert "The update didn't finish" in page and "Try again" in page
    assert mac.quit_calls == 0 and mac.installers == []


@mac_installer
def test_an_app_opened_from_the_dmg_offers_to_move_into_applications(settings, monkeypatch):
    mac = _Mac(monkeypatch, Path("/Volumes/Milestash/Milestash.app"))
    monkeypatch.setattr(updates, "_can_write", lambda folder: True)
    monkeypatch.setattr(updates, "bundle_version", lambda app: None)
    with _window(settings) as window:
        mac.attach(window)
        dashboard = window.get("/").text
        assert "running from the disk image (.dmg), not your Applications folder" in dashboard
        page = window.post("/move-to-applications", data={"csrf_token": _token(dashboard)})
        assert "Moving to Applications" in page.text and "/Applications/Milestash.app" in page.text
        assert "eject the Milestash disk image" in page.text
    assert mac.quit_calls == 1
    [script] = mac.installers
    assert "new=/Volumes/Milestash/Milestash.app" in script


@mac_installer
def test_a_stale_copy_opens_the_newer_one_in_applications_instead(settings, monkeypatch):
    mac = _Mac(monkeypatch, Path.home() / "Downloads" / "Milestash.app")
    monkeypatch.setattr(updates, "_can_write", lambda folder: True)
    monkeypatch.setattr(updates, "bundle_version", lambda app: "99.0.0")
    with _window(settings) as window:
        mac.attach(window)
        dashboard = window.get("/").text
        assert "running from ~/Downloads" in dashboard
        page = window.post("/move-to-applications", data={"csrf_token": _token(dashboard)}).text
        assert "delete the copy in ~/Downloads" in page
    [script] = mac.installers
    assert "new=''" in script and "open /Applications/Milestash.app" in script


@mac_installer
def test_an_app_in_applications_offers_no_move(settings, monkeypatch):
    mac = _Mac(monkeypatch, Path("/Applications/Milestash.app"))
    with _window(settings) as window:
        mac.attach(window)
        assert "Move to Applications" not in window.get("/").text


@mac_installer
def test_updates_always_land_in_applications(monkeypatch):
    home = Path.home()
    assert updates.install_target(Path("/Applications/Milestash.app")) == Path("/Applications/Milestash.app")
    assert updates.install_target(home / "Applications/Milestash.app") == home / "Applications/Milestash.app"
    monkeypatch.setattr(updates, "_can_write", lambda folder: True)
    for elsewhere in ("/Volumes/Milestash/Milestash.app", f"{home}/Downloads/Milestash.app"):
        assert updates.install_target(Path(elsewhere)) == Path("/Applications/Milestash.app")
    monkeypatch.setattr(updates, "_can_write", lambda folder: False)
    assert updates.install_target(home / "Downloads/Milestash.app") == home / "Applications/Milestash.app"
    assert updates.where_it_runs(home / "Downloads/Milestash.app") == "~/Downloads"
    assert "temporary copy" in updates.where_it_runs(Path("/private/var/folders/x/AppTranslocation/y/d/A.app"))


class _Download(io.BytesIO):
    headers = {"Content-Length": str(600 * 1024)}


def test_download_reports_progress(monkeypatch, tmp_path):
    content = b"x" * 600 * 1024
    monkeypatch.setattr(updates, "_open", lambda request, timeout: _Download(content))
    seen = []
    updates.download(
        DMG, tmp_path / "aw.dmg", sha256=hashlib.sha256(content).hexdigest(), progress=lambda d, t: seen.append((d, t))
    )
    assert seen[-1] == (600 * 1024, 600 * 1024) and len(seen) == 3
    assert (tmp_path / "aw.dmg").stat().st_size == 600 * 1024


def test_a_download_that_doesnt_match_its_checksum_is_thrown_away(monkeypatch, tmp_path):
    # Say someone on the way swapped the file: it isn't the one GitHub published.
    monkeypatch.setattr(updates, "_open", lambda request, timeout: _Download(b"something else"))
    with pytest.raises(updates.UpdateCheckFailed, match="didn't match the release"):
        updates.download(DMG, tmp_path / "aw.dmg", sha256=DMG_SHA256)
    assert not (tmp_path / "aw.dmg").exists()


def test_a_download_far_bigger_than_the_app_is_stopped(monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "MAX_DOWNLOAD", 1000)
    monkeypatch.setattr(updates, "_open", lambda request, timeout: _Download(b"x" * 600 * 1024))
    with pytest.raises(updates.UpdateCheckFailed, match="far bigger"):
        updates.download(DMG, tmp_path / "aw.dmg", sha256=DMG_SHA256)
    assert not (tmp_path / "aw.dmg").exists()


def test_downloads_never_follow_a_redirect_off_https():
    request = urllib.request.Request(DMG)
    with pytest.raises(urllib.error.URLError):
        updates._HttpsOnly().redirect_request(request, None, 302, "Found", {}, "http://example.com/aw.dmg")
    assert updates._HttpsOnly().redirect_request(request, None, 302, "Found", {}, "https://example.com/aw.dmg")


def test_a_release_without_a_checksum_is_not_installed(settings, monkeypatch):
    release = updates.Release("99.0.0", f"{RELEASES}/tag/v99.0.0", DMG, None)
    monkeypatch.setattr(updates, "latest_release", lambda repo: release)
    mac = _Mac(monkeypatch, Path("/Applications/Milestash.app"))
    downloads = []
    monkeypatch.setattr(updates, "download", lambda *args, **kwargs: downloads.append(args))
    with _window(settings) as window:
        mac.attach(window)
        window.post("/update", data={"csrf_token": _token(window.get("/about?check=1").text)})
        assert "checksum" in _wait_for(window, state="failed")["error"]
    assert downloads == [] and mac.installers == [] and mac.quit_calls == 0


def test_a_page_that_breaks_says_so_and_logs_why(settings, monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise RuntimeError("something broke")

    desktop = settings.model_copy(update={"desktop_token": SecretStr("t")})
    with TestClient(create_app(desktop), base_url="http://127.0.0.1", raise_server_exceptions=False) as window:
        window.get("/?token=t")
        monkeypatch.setattr("milestash.web.routes.dashboard.summarize_accounts", broken)
        page = window.get("/")
    assert page.status_code == 500
    assert "Something went wrong on this page" in page.text and "Back to your points" in page.text
    [record] = [r for r in caplog.records if r.name == "milestash.web.app"]
    assert record.message == "GET / failed" and "something broke" in str(record.exc_info[1])


def test_web_version_only_links_to_the_download(settings, monkeypatch):
    release = updates.Release("99.0.0", "https://github.com/x/y", "https://example.com/aw.dmg")
    monkeypatch.setattr(updates, "latest_release", lambda repo: release)
    with _window(settings) as window:
        about = window.get("/about?check=1").text
        assert "Update to" not in about
        assert "https://example.com/aw.dmg" in about


# The installer script, run for real with stand-ins for the Mac's own tools ---------------------

_TOOLS = {
    # Mounting the .dmg shows the app that was put next to it.
    "hdiutil": 'if [ "$1" = attach ]; then cp -R "$7.contents/." "$6/"; else rm -rf "$3"; fi',
    "ditto": (
        '[ -f "$STUB_DIR/ditto-fails" ] && exit 1; '
        'while [ "${1#-}" != "$1" ]; do echo "$1" >> "$STUB_DIR/ditto-options"; shift; done; '
        'cp -R "$1" "$2"'
    ),
    # Like moving an app out of a folder you're not allowed to change.
    "mv": '[ -f "$STUB_DIR/mv-fails" ] && exit 1; exec /bin/mv "$@"',
    "xattr": 'echo "$@" >> "$STUB_DIR/xattr-ran"',
    "open": 'echo "$@" >> "$STUB_DIR/opened"',
}


def _app(path: Path, version: str) -> Path:
    (path / "Contents").mkdir(parents=True)
    (path / "Contents" / "version").write_text(version)
    return path


def _run(script: str, tmp_path: Path) -> list[str]:
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    for name, body in _TOOLS.items():
        (tools / name).write_text(f"#!/bin/bash\n{body}\n")
        (tools / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{tools}:{os.environ['PATH']}", "STUB_DIR": str(tmp_path)}
    subprocess.run(["/bin/bash", "-c", script], env=env, check=True, timeout=30)
    opened = tmp_path / "opened"
    return opened.read_text().split("\n")[:-1] if opened.exists() else []


def _quit_pid() -> int:
    """The id of a process that has already quit, like the app by the time the script runs."""
    child = subprocess.Popen(["true"])
    child.wait()
    return child.pid


@mac_installer
def test_installer_replaces_the_app_from_the_dmg_and_reopens_it(tmp_path):
    app = _app(tmp_path / "Applications" / "Milestash.app", "0.5.1")
    dmg = tmp_path / "update.dmg"
    dmg.write_bytes(b"dmg")
    _app(tmp_path / "update.dmg.contents" / "Milestash.app", "0.6.0")
    opened = _run(updates.installer_script(app=app, running=app, pid=_quit_pid(), dmg=dmg), tmp_path)
    assert (app / "Contents" / "version").read_text() == "0.6.0"
    assert not (tmp_path / "Applications" / "Milestash.app.old").exists() and not dmg.exists()
    assert opened == [str(app)]


@mac_installer
def test_installer_never_changes_the_new_app_once_it_is_in_place(tmp_path):
    # macOS blocks one app changing another that's already in place, like removing the internet
    # mark from its files, and says Milestash "was prevented from modifying apps on your Mac".
    # So the copy is made without the mark instead.
    app = _app(tmp_path / "Applications" / "Milestash.app", "0.5.1")
    dmg = tmp_path / "update.dmg"
    dmg.write_bytes(b"dmg")
    _app(tmp_path / "update.dmg.contents" / "Milestash.app", "0.6.0")
    _run(updates.installer_script(app=app, running=app, pid=_quit_pid(), dmg=dmg), tmp_path)
    assert (app / "Contents" / "version").read_text() == "0.6.0"
    assert (tmp_path / "ditto-options").read_text().split() == ["--noqtn"]
    assert not (tmp_path / "xattr-ran").exists()


@mac_installer
def test_installer_keeps_the_old_app_when_the_copy_fails(tmp_path):
    app = _app(tmp_path / "Applications" / "Milestash.app", "0.5.1")
    dmg = tmp_path / "update.dmg"
    dmg.write_bytes(b"dmg")
    _app(tmp_path / "update.dmg.contents" / "Milestash.app", "0.6.0")
    (tmp_path / "ditto-fails").touch()
    opened = _run(updates.installer_script(app=app, running=app, pid=_quit_pid(), dmg=dmg), tmp_path)
    assert (app / "Contents" / "version").read_text() == "0.5.1"
    assert opened == [str(app)]


@mac_installer
def test_installer_never_copies_over_an_app_it_couldnt_move_aside(tmp_path):
    app = _app(tmp_path / "Applications" / "Milestash.app", "0.5.1")
    dmg = tmp_path / "update.dmg"
    dmg.write_bytes(b"dmg")
    _app(tmp_path / "update.dmg.contents" / "Milestash.app", "0.6.0")
    (tmp_path / "mv-fails").touch()
    opened = _run(updates.installer_script(app=app, running=app, pid=_quit_pid(), dmg=dmg), tmp_path)
    assert sorted(path.name for path in (app / "Contents").iterdir()) == ["version"]
    assert (app / "Contents" / "version").read_text() == "0.5.1"
    assert opened == [str(app)]


@mac_installer
def test_the_installer_writes_what_it_did_next_to_the_app_log(tmp_path):
    import logging.handlers

    diagnostics = tmp_path / "Diagnostics"
    diagnostics.mkdir()
    handler = logging.handlers.RotatingFileHandler(diagnostics / "milestash.log")
    logging.getLogger().addHandler(handler)
    try:
        updates._run_installer("echo Installed it", tmp_path)
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
    log = diagnostics / "install.log"
    _eventually(lambda: "Installed it" in log.read_text())
    assert f"Milestash {__version__} hands over to" in log.read_text()


@mac_installer
def test_an_update_from_award_wallet_ends_up_named_milestash(tmp_path):
    # Award Wallet's own installer puts the new version where the old one was, under the old name...
    old = _app(tmp_path / "Applications" / "Award Wallet.app", "0.13.0")
    dmg = tmp_path / "update.dmg"
    dmg.write_bytes(b"dmg")
    _app(tmp_path / "update.dmg.contents" / "Milestash.app", "0.14.0")
    assert _run(updates.installer_script(app=old, running=old, pid=_quit_pid(), dmg=dmg), tmp_path) == [str(old)]
    assert (old / "Contents" / "version").read_text() == "0.14.0"
    # ...and the new version takes its name once it has quit, then opens again.
    (tmp_path / "opened").unlink()
    new = tmp_path / "Applications" / "Milestash.app"
    assert _run(updates.rename_script(app=old, pid=_quit_pid()), tmp_path) == [str(new)]
    assert (new / "Contents" / "version").read_text() == "0.14.0" and not old.exists()


@mac_installer
def test_an_app_that_cant_be_renamed_opens_under_its_old_name(tmp_path):
    old = _app(tmp_path / "Applications" / "Award Wallet.app", "0.14.0")
    (tmp_path / "mv-fails").touch()
    assert _run(updates.rename_script(app=old, pid=_quit_pid()), tmp_path) == [str(old)]
    assert (old / "Contents" / "version").read_text() == "0.14.0"


def test_only_award_wallet_in_applications_takes_the_new_name(monkeypatch, tmp_path):
    applications = tmp_path / "Applications"
    monkeypatch.setattr(updates, "APPLICATIONS", (applications, tmp_path / "home" / "Applications"))

    def running(app):
        monkeypatch.setattr(updates, "running_app_bundle", lambda: app)
        return updates.app_to_rename()

    assert running(None) is None
    assert running(applications / "Award Wallet.app") == applications / "Award Wallet.app"
    # A name you gave it yourself, a copy outside Applications, or a Milestash already there: left alone.
    assert running(applications / "My Miles.app") is None
    assert running(applications / "Milestash.app") is None
    assert running(tmp_path / "Downloads" / "Award Wallet.app") is None
    (applications / "Milestash.app").mkdir(parents=True)
    assert running(applications / "Award Wallet.app") is None


def test_bundle_version_reads_the_info_plist(tmp_path):
    import plistlib

    app = tmp_path / "Milestash.app"
    assert updates.bundle_version(app) is None
    (app / "Contents").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "0.6.0"}))
    assert updates.bundle_version(app) == "0.6.0"


@mac_installer
def test_installer_moves_the_app_into_applications(tmp_path):
    running = _app(tmp_path / "Downloads" / "Milestash.app", "0.6.0")
    target = tmp_path / "Applications" / "Milestash.app"
    opened = _run(updates.installer_script(app=target, running=running, pid=_quit_pid(), source=running), tmp_path)
    assert (target / "Contents" / "version").read_text() == "0.6.0"
    assert opened == [str(target)]
