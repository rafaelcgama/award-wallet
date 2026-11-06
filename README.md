# Award Wallet

A Mac app that shows all your airline miles and credit card points in one place. It signs in to
each program for you, reads the balance, and keeps the history, so you don't have to visit every
site. Programs so far: American AAdvantage, United MileagePlus, Chase Ultimate Rewards and
Capital One Miles.

It's a personal app: everything stays on your Mac, nothing runs in the background, and nothing
sits in the menu bar. Closing the window quits it.

## Install

1. Download the newest `Award-Wallet-vX.Y.Z.dmg` from the repository's **Releases** page.
2. Open it and drag **Award Wallet** onto **Applications**. (Opened straight from the .dmg, it
   offers to move itself there.)
3. The first time only: the app isn't signed with a paid Apple developer certificate, so macOS
   says it "could not verify" Award Wallet. Click **Done**, then either run
   `xattr -dr com.apple.quarantine "/Applications/Award Wallet.app"` in Terminal, or go to
   **System Settings → Privacy & Security** and click **Open Anyway**.

Release builds are for Apple Silicon Macs (M1 and newer). You also need **Google Chrome**, which
the app uses to sign in to the programs' websites.

## Using it

- **Link a program** with its username and password. The app signs in and fetches the balance
  out of sight. Each program has its own Chrome profile, kept by the app, so the site remembers
  this Mac the way it remembers your own Chrome and stops asking.
- **Balances refresh by themselves** every time you open the app, all programs at once. The
  **Refresh now** button does it on demand. Chrome works invisibly, with no window, tab or Dock
  icon, and types the saved login one key at a time, like a person.
- **Needs your sign-in** means a site wants something only you can give, like a code by text,
  usually only the first time. Click **Sign in** on the program: a Chrome window opens for just
  that, the program shows **Waiting for you** with a note saying what the site wants, and from
  then on refreshes run out of sight again. Nothing opens unless you click.
- **Check your login** means the site turned down the saved username or password. Click
  **Sign in** and sign in yourself in the window, and the app keeps the login that works; or save
  it again. The app never retries a rejected login by itself, so your account doesn't get locked.
- **History** keeps each change in your balance with its date, one entry a day at most, so you can
  see when points came in or went out.

## Updating

The app checks for a new version each time it opens and shows a banner when there is one. Click
**Update now**: a progress bar follows the download, then the app closes, replaces itself in your
Applications folder and reopens on its own. Your programs and logins are kept. **Help → About
Award Wallet** shows your version and checks again.

Opened from anywhere but Applications (the .dmg, or Downloads), the app shows **Move to
Applications**, which puts it there and reopens it from there. Then eject the .dmg or delete the
other copy, so you don't open an old one by mistake. If an update ever goes wrong, `install.log`
in Diagnostics says what happened.

## Your data

Everything lives in `~/Library/Application Support/Award Wallet`:

| | What it holds |
| --- | --- |
| `settings.env` | Your encryption keys. Back it up: without it, saved logins can't be decrypted. |
| `award_wallet.db` | Your programs and balance history. |
| `Browser/` | Each program's Chrome profile: the site's cookies, which keep it signed in and remember this Mac. Deleting one makes that site ask for a security code again. |
| `Diagnostics/` | A log of what the app did and screenshots of pages where a fetch failed. Safe to send when something needs fixing: the screenshots black out every box, so nothing typed shows (cover account numbers the page itself shows). **Help → Show Diagnostics in Finder** opens it. |

To uninstall, drag the app to the Trash; to remove your data too, delete that folder.

**Security.**
- Program logins are encrypted with AES-256-GCM before they're saved, and each one is tied to its
  account. They're only ever sent to the program's own website.
- The sites' cookies stay in each program's Chrome profile, which Chrome encrypts with your Mac's
  Keychain, the same way it protects your own Chrome's cookies.
- Only you can open the app's folder or read what the app writes.
- The app's pages are served only to its own window on your Mac. Each launch makes a new secret
  that signs the window in for that launch only, the app only answers on 127.0.0.1, every form
  carries a token, and requests from other websites are turned away.
- The pages run only the app's own scripts, can't be shown inside another site and aren't kept on
  disk.
- Updates come only from this repository's releases on GitHub, over HTTPS, and must match the
  SHA-256 GitHub lists for them, or nothing is installed.

## How it's built

Python 3.12. FastAPI serves server-rendered pages (Jinja) to a native window (pywebview), SQLite
holds the data (SQLAlchemy, Alembic for schema changes), and Playwright drives Chrome to fetch
balances. PyInstaller packages it as a .app.

```
src/award_wallet/
  desktop.py     the app: window, menus, data folder, log file
  fetching.py    signs in with Chrome, in each program's own profile, and reads a balance
  providers/     one module per program: where its balance page is and how to read it
  services/      accounts, balances, background refresh
  updates.py     Check for Updates, one-click install, Move to Applications
  web/           pages, templates, CSS and scripts; security.py locks the pages to the window
  models.py      tables: loyalty accounts, balance snapshots, expiration lots
  migrations/    database schema versions
  security/      the encryption vault
packaging/       app icon and the PyInstaller entry point
tests/           pytest suite, including fakebank.py, a pretend bank to test signing in
```

### Adding a program

Create a module in `src/award_wallet/providers/`, subclass `Provider`, decorate it with
`@register`, and import it in `providers/__init__.py`. Set `balance_url` (the page that shows the
balance once signed in), then either `balance_labels` (the words shown with the balance, like
"Ultimate Rewards points": the reader takes the number in the same box) or `balance_patterns`
(regular expressions that find it in the page's text). Labels are the better choice when a page
shows more than one balance. The sign-in itself is generic. Never rename a provider's `key`: it's
stored in the database.

## Development

You need [uv](https://docs.astral.sh/uv/) (`brew install uv`). Run `make` to list the shortcuts:

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

### Branches and releases

- `main` is what the installed app updates from, so every change goes on its own branch with a
  pull request. CI runs lint and tests on it.
- To try a branch before merging: `git fetch && git switch <branch> && make app`.
  `git switch main` goes back.
- Each pull request bumps the version in `pyproject.toml` and `src/award_wallet/__init__.py`
  (a test checks they match) and adds a `CHANGELOG.md` entry.
- Merging into `main` with a new version publishes it: the release workflow builds the .dmg on a
  Mac runner (a few minutes, under **Actions**) and attaches it to a GitHub release, and the
  installed app offers it. Merging without a version bump releases nothing.
