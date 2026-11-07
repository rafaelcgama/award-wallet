# Award Wallet

An app for Mac and Windows that shows all your airline miles and credit card points in one place.
It signs in to each program for you, reads the balance, and keeps the history, so you don't have
to visit every site. Programs so far: American AAdvantage, Delta SkyMiles, United MileagePlus,
Chase Ultimate Rewards, Capital One Miles and American Express Membership Rewards.

It's a personal app: everything stays on your computer, nothing runs in the background, and
nothing sits in the menu bar or next to the clock. Closing the window quits it.

## Install on a Mac

You need a Mac with an Apple chip (M1 or newer) and **Google Chrome**, which the app uses to sign
in to the programs' websites. Download the app, or build it yourself.

### Download it

1. Download the newest `Award-Wallet-vX.Y.Z.dmg` from the repository's **Releases** page.
2. Open it and drag **Award Wallet** onto **Applications**. (Opened straight from the .dmg, it
   offers to move itself there.)
3. The first time only: the app isn't signed with a paid Apple developer certificate, so macOS
   says it "could not verify" Award Wallet. Click **Done**, then either run
   `xattr -dr com.apple.quarantine "/Applications/Award Wallet.app"` in Terminal, or go to
   **System Settings → Privacy & Security** and click **Open Anyway**.

### Build it yourself

No programming needed: you paste two lines into Terminal and wait a few minutes. A copy you build
on your own Mac opens without the "could not verify" warning.

1. **Get the code.** On this repository's GitHub page, click the green **Code** button, then
   **Download ZIP**. In your **Downloads** folder, double-click `award-wallet-main.zip` if your
   browser didn't unzip it already. You now have a folder named `award-wallet-main`.
2. **Open Terminal.** Press ⌘ Space, type `Terminal` and press Return.
3. **Install uv**, a free tool that downloads what the build needs, like Python. Paste this line
   into Terminal and press Return:

   ```sh
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

4. **Build the app.** Paste this line and press Return:

   ```sh
   cd ~/Downloads/award-wallet-main && bash build_dmg.sh
   ```

   If macOS asks whether Terminal may access files in your Downloads folder, click **Allow**.
   The build downloads what it needs, runs the app's tests and packs the app. When it says
   `Done: build/Award Wallet.dmg`, a Finder window opens on the `build` folder.
5. **Install it.** Double-click **Award Wallet.dmg**, drag **Award Wallet** onto
   **Applications**, then eject the disk image (the ⏏ next to it in Finder's sidebar). The
   `award-wallet-main` folder and the .zip can go to the Trash.

**Update now** works in a copy you built, too: it installs the newest release.

If something goes wrong:

- **"uv is missing"**: step 3 didn't finish. Do it again, then quit Terminal (⌘ Q), open it again
  and repeat step 4.
- **"no such file or directory"**: the folder has another name or isn't in Downloads. Type `cd `
  (with a space after it), drag the folder from Finder onto the Terminal window and press Return.
  Then paste `bash build_dmg.sh` and press Return.
- **It stops at "Running tests"**: something in this copy of the code doesn't work on your Mac.
  Copy what Terminal shows into a new issue on the repository's **Issues** page.
- **On an Intel Mac** it stops while installing `cryptography`: that library is only published
  ready to use for Apple chips, so the build needs a Mac with an Apple chip.

## Install on Windows

You need Windows 10 (version 1809 or newer) or Windows 11 and **Google Chrome**, which the app
uses to sign in to the programs' websites. Download the app, or build it yourself.

### Download it

1. Download the newest `Award-Wallet-vX.Y.Z-Setup.exe` from the repository's **Releases** page.
2. Open it. The first time only: Setup isn't signed with a paid code-signing certificate, so
   Windows says "Windows protected your PC". Click **More info**, then **Run anyway**.
3. Setup installs Award Wallet for you alone, with no administrator password, adds it to the
   Start menu and opens it. Tick **Create a desktop shortcut** in Setup if you want one.

If Windows says **Smart App Control** blocked Setup, that PC only runs signed apps, and Award
Wallet isn't signed: it can't be installed there unless Smart App Control is turned off in
**Windows Security → App & browser control**.

### Build it yourself

No programming needed: you paste a few lines into PowerShell and wait a few minutes.

1. **Get the code.** On this repository's GitHub page, click the green **Code** button, then
   **Download ZIP**, and save it in your **Downloads** folder.
2. **Open PowerShell.** Press the Windows key, type `PowerShell` and press Enter.
3. **Install uv**, a free tool that downloads what the build needs, like Python. Paste this line
   into PowerShell and press Enter, then close PowerShell and open it again:

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

4. **Install Inno Setup**, the free tool that makes the installer:

   ```powershell
   winget install --exact --id JRSoftware.InnoSetup
   ```

5. **Build the app.** Paste these lines and press Enter:

   ```powershell
   Expand-Archive ~\Downloads\award-wallet-main.zip ~\Downloads -Force
   cd ~\Downloads\award-wallet-main
   powershell -ExecutionPolicy Bypass -File build_windows.ps1
   ```

   The build downloads what it needs, runs the app's tests, packs the app and checks that it
   starts. It ends with `Done: build\Award-Wallet-Setup.exe`.
6. **Install it.** Run `build\Award-Wallet-Setup.exe` (type `start build\Award-Wallet-Setup.exe`
   and press Enter). The `award-wallet-main` folder and the .zip can go to the Recycle Bin.

If it stops with **"uv is missing"** or **"Inno Setup is missing"**, do step 3 or 4 again, then
close PowerShell, open it again and repeat step 5 from its `cd` line. If it stops at **"Running
tests"**, copy what PowerShell shows into a new issue on the repository's **Issues** page.

## Using it

- **Link a program** with its username and password. The app signs in and fetches the balance
  out of sight. Each program has its own Chrome profile, kept by the app, so the site remembers
  this computer the way it remembers your own Chrome and stops asking.
- **Balances refresh by themselves** every time you open the app, three programs at a time.
  **Refresh now** does it on demand, and **Refresh** on a program's page does just that one.
  Chrome works invisibly, with no window, tab, Dock icon or taskbar button, and types the saved
  login one key at a time, like a person.
- **Needs your sign-in** means a site wants something only you can give, like a code by text,
  usually only the first time. Click **Sign in** on the program, even while others refresh: the
  site's page shows right in Award Wallet, with a note saying what the site wants. The app types
  your saved login; you click and type on the page like in a browser to finish, like entering the
  code. It's the same hidden Chrome that does the refreshes, so the site gets to know that browser,
  and from then on refreshes run out of sight again. **Stop** ends the sign-in; nothing else
  opens, ever.
- **Check your login** means the site turned down the saved username or password. Click
  **Sign in** and sign in yourself on the site's page, and the app keeps the login that works; or
  save it again. The app never retries a rejected login by itself, so your account doesn't get
  locked.
- **Check the balance** means a refresh read less than half of what the program had, and at
  least 1,000 fewer. That could be points you used, or some other number on the site's page, so it
  stays out of the history until you say: the program's page offers to keep the new balance or the
  one before. If you didn't use them, look at your account on the program's site.
- **Fetch failed** means a refresh couldn't read the balance, and the program says why. If the
  site couldn't be reached, the next refresh tries again. If the app couldn't find your points on
  the site's page, the site may have changed it: a screenshot of the page goes into Diagnostics, so
  the app can be fixed.
- **Rename a program** by double-clicking its name on the program's page: type the new name and
  press Return, or Esc to leave it as it was. Its card shows the new name. A program starts with
  its own name, like AAdvantage, and an empty name goes back to it.
- **History** keeps each change in your balance with its date, one entry a day at most, so you can
  see when points came in or went out.
- **When miles expire:** American's balance page says when your miles expire, and the app reads
  that date on each refresh and shows it on the program's card. From 90 days before, that line
  turns into an alert with a countdown and what to do: earn or spend any miles and the date moves
  24 months out. The other programs' points don't expire, and their cards say why.
- **Enter a balance by hand** on a program's page when you didn't save a login for it, or to add
  when points expire, which most sites don't show. You can add how many points expire and on what
  date (or just the date, if the whole balance expires then), and the program's card shows the
  next expiration. Refreshes keep it until the date passes.
- **Use miles** (or **Use points**) under a balance opens the program's own site in your browser,
  to use them.
- **Transfer partners** on a Chase, Amex or Capital One program's page lists the airlines and
  hotels its points move to, and at what ratio. It stays folded until you click it.
- **Change saved login** is on the program's page. A new password keeps the site's memory of this
  computer; a different username starts fresh, so the site may ask to confirm it's you again.
- **Remove saved login** goes back to entering the balance by hand, and **Remove program** also
  deletes its history. Both delete the program's Chrome profile; your account with the program
  isn't affected.

What changed in each version is in [CHANGELOG.md](CHANGELOG.md).

## Updating

The app checks for a new version each time it opens and shows a banner when there is one. Click
**Update now**: a progress bar follows the download, then the app closes, replaces itself and
reopens on its own. Your programs and logins are kept. **Help → About Award Wallet** shows your
version and checks again. If an update ever goes wrong, `install.log` in Diagnostics says what
happened.

On Windows, the app downloads the new version's Setup, which installs it where the old one was
without asking anything, and opens it. Windows doesn't warn again: that was only for the Setup
you downloaded yourself.

On a Mac, the app replaces itself in your Applications folder. Opened from anywhere else (the
.dmg, or Downloads), it shows **Move to Applications**, which puts it there and reopens it from
there. Then eject the .dmg or delete the other copy, so you don't open an old one by mistake.

If macOS says Award Wallet "was prevented from modifying apps on your Mac" while it updates, close
the notice and leave Award Wallet switched off under **System Settings → Privacy & Security → App
Management**. The update installs anyway, and switching it on would let the app change or delete
any app on your Mac.

## Your data

Everything lives in one folder: `~/Library/Application Support/Award Wallet` on a Mac, and
`%LOCALAPPDATA%\Award Wallet` on Windows (paste that into File Explorer's address bar to open it).

| | What it holds |
| --- | --- |
| `settings.env` | Your encryption keys. Back it up: without it, saved logins can't be decrypted. |
| `award_wallet.db` | Your programs and balance history. |
| `Browser/` | Each program's Chrome profile: the site's cookies, which keep it signed in and remember this computer. Deleting one makes that site ask for a security code again. |
| `Diagnostics/` | A log of what the app did and screenshots of pages where a fetch failed. Safe to send when something needs fixing: the screenshots black out every box, so nothing typed shows (cover account numbers the page itself shows). **Help → Show Diagnostics in Finder** (**in File Explorer** on Windows) opens it. |

To uninstall on a Mac, drag the app to the Trash. On Windows, go to **Settings → Apps → Installed
apps**, click the **⋯** next to Award Wallet and choose **Uninstall**. Either way your data stays;
to remove it too, delete that folder.

**Security.**
- Program logins are encrypted with AES-256-GCM before they're saved, and each one is tied to its
  account. They're only ever sent to the program's own website.
- The sites' cookies stay in each program's Chrome profile, which Chrome encrypts the same way it
  protects your own Chrome's cookies: with your Mac's Keychain, or on Windows with your Windows
  account.
- Only you can open the app's folder or read what the app writes. (On Windows, the folder is in
  your own AppData, which other people on the PC can't open.)
- The app's pages are served only to its own window on your computer. Each launch makes a new secret
  that signs the window in for that launch only, the app only answers on 127.0.0.1, every form
  carries a token, and requests from other websites are turned away.
- The pages run only the app's own scripts, can't be shown inside another site and aren't kept on
  disk.
- While you sign in, the pictures of the site's page stay in the app's memory and are gone when
  the sign-in ends. Only the app's own window can see them, and only clicks, scrolls, keys and
  text reach the site's page from it, each one checked first. Nothing you type there is logged.
- Updates come only from this repository's releases on GitHub, over HTTPS, and must match the
  SHA-256 GitHub lists for them, or nothing is installed.

## How it's built

Python 3.12. FastAPI serves server-rendered pages (Jinja) to a native window (pywebview), SQLite
holds the data (SQLAlchemy, Alembic for schema changes), and Playwright drives Chrome to fetch
balances. PyInstaller packages it as a Mac .app, and as a Windows app that Inno Setup wraps in
Setup.exe. The same code runs on both; what differs is asked in `system.py`, and the Windows
specifics are in `windows.py`.

```
src/award_wallet/
  desktop.py     the app: window, menus, data folder, log file, the build's self-test
  system.py      which computer it runs on, and what it calls things (Finder or File Explorer)
  windows.py     Windows only: one copy at a time, the screen, Chrome's version
  fetching.py    signs in with Chrome, in each program's own profile, and reads a balance
  sign_in_view.py  carries a sign-in's page to the window, and your clicks and keys back
  providers/     one module per program: where its balance page is and how to read it
  services/      accounts, balances, background refresh
  updates.py     Check for Updates, one-click install (.dmg or Setup.exe), Move to Applications
  web/           pages, templates, CSS and scripts; security.py locks the pages to the window
  models.py      tables: loyalty accounts, balance snapshots, expiration lots
  migrations/    database schema versions
  security/      the encryption vault
packaging/       app icons, the PyInstaller entry point, and windows/award_wallet.iss (the installer)
build_dmg.sh     builds the Mac app; build_windows.ps1 builds the Windows app and Setup.exe
tests/           pytest suite, including fakebank.py, a pretend bank to test signing in
```

### Adding a program

Create a module in `src/award_wallet/providers/`, subclass `Provider`, decorate it with
`@register`, and import it in `providers/__init__.py`. Set `balance_url` (the page that shows the
balance once signed in), then either `balance_labels` (the words shown with the balance, like
"Ultimate Rewards points": the reader takes the number in the same box) or `balance_patterns`
(regular expressions that find it in the page's text). Labels are the better choice when a page
shows more than one balance. If the page says when the balance expires, `expiration_patterns`
find the date by the words around it, like "Miles expire on Jan 3, 2028", never by where it sits
in the page. Wrap a label in `alone()` when look-alikes sit nearby, like "Pending
Miles" next to "Available Miles": then only a box whose whole text is the label counts. The
sign-in itself is generic. Never rename a provider's `key`: it's stored in the database.

`program` is the program's own name, like "AAdvantage": a program has that name when it's linked,
and goes back to it when its name is cleared. `unit` ("miles" or "points") and `rewards_url` make
its **Use miles** button. For a bank's points, `transfer_partners` lists the airlines and hotels
they move to, each a `TransferPartner` with its ratio, like "1:1", and a note when the ratio
depends on the card. Banks change these a few times a year, so a comment above the list says when
it was last checked.

## Development

You need [uv](https://docs.astral.sh/uv/): `curl -LsSf https://astral.sh/uv/install.sh | sh`, or
`brew install uv` if you use Homebrew. Run `make` to list the shortcuts:

| Command | What it does |
| --- | --- |
| `make setup` | Install everything into `.venv` (once) |
| `make app` | Run the app from the current branch's code, with your real data, without installing it |
| `make test` / `make lint` / `make format` | Tests, style checks, style fixes |
| `make check` | Lint and tests, the same as CI |
| `make dmg` | Build `build/Award Wallet.dmg` locally |

After editing `models.py`, add a migration (it uses a scratch database, never your data):

```sh
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe the change"
```

`tests/test_migrations.py` fails if `models.py` changes without a matching migration.

On Windows there's no `make`: `uv sync --extra desktop` installs everything,
`uv run python -m award_wallet.desktop` runs the app from the code, `uv run pytest` runs the
tests, and `powershell -ExecutionPolicy Bypass -File build_windows.ps1` builds
`build\Award-Wallet-Setup.exe`. Every build checks that the packed app starts: it runs it with
`--self-test`, which serves the pages from a new, empty data folder and starts the hidden Chrome,
never touching your data.

Some tests need a browser: the ones that sign in to a pretend bank, read balances off pages, or
run the app's own scripts, like the expiration countdown and renaming a program. CI installs
Chromium for them and sets `AW_REQUIRE_BROWSER`, so a missing browser fails the run instead of
skipping them. On your computer they're skipped unless `AW_BROWSER_PATH` names a Chrome or Chromium to
use. `tests/test_windows.py` asks Windows itself, so most of it runs only on Windows.

### Branches and releases

- `main` is what the installed app updates from, so every change goes on its own branch with a
  pull request. CI runs lint and every test on it, the browser ones included, which takes about
  10 minutes. It also runs every test on Windows with Google Chrome, then builds Setup.exe and
  keeps it with the run for 30 days: on the pull request, open the **windows** check's details,
  then **Summary → Artifacts → Award-Wallet-Setup** (a .zip with Setup.exe inside) to try it
  before merging.
- To try a branch before merging: `git fetch && git switch <branch> && make app`.
  `git switch main` goes back.
- Each pull request that changes the app bumps the version in `pyproject.toml` and
  `src/award_wallet/__init__.py` (a test checks they match), runs `uv lock` so `uv.lock` has the
  new version too (CI fails otherwise), and adds a `CHANGELOG.md` entry.
- Every pull request also updates this README when it changes anything the README describes.
- Merging into `main` with a new version publishes it: the release workflow builds the .dmg on a
  Mac runner and Setup.exe on a Windows runner (a few minutes, under **Actions**) and attaches
  both to one GitHub release, and the installed apps offer it. If either build fails, nothing is
  released until it's fixed or the run's **Re-run failed jobs** succeeds. Merging without a
  version bump releases nothing.
- When pull requests build on each other, merge them in order with **Create a merge commit**.
  Squashing makes each later one conflict on the version number. Merged in a row, a version in
  between may get no release of its own, because a release run still waiting when a newer merge
  arrives is cancelled; the newest always gets one.
