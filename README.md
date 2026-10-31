# Award Wallet

One dashboard for all your airline miles and loyalty points. Each program shows its balance,
when it was last updated and when points expire, so you don't have to sign in to every site.

It runs on your own computer. Programs supported so far: United MileagePlus, Chase Ultimate
Rewards and Capital One Miles.

## Install the app

Award Wallet is a Mac app. It opens in its own window and quits when you close the window:
nothing runs in the background and nothing sits in the menu bar.

### From a release (easiest)

1. Go to the repository's **Releases** page on GitHub and download the newest
   `Award-Wallet-vX.Y.Z.dmg`.
2. Open the .dmg and drag **Award Wallet** onto the **Applications** folder.
3. The first time only: the app isn't signed with an Apple developer certificate, so macOS asks
   before opening it. Right-click Award Wallet in Applications, choose **Open**, then **Open**
   again. If macOS still refuses, go to **System Settings → Privacy & Security** and click
   **Open Anyway** next to the Award Wallet message.
4. Link your programs from the dashboard. Your logins are encrypted and stay on your Mac.

Release builds come from GitHub's Apple Silicon Macs (M1 and newer). On an Intel Mac, build it
yourself as below.

### Build it yourself

You need [uv](https://docs.astral.sh/uv/) (`brew install uv`). Then:

```sh
git clone https://github.com/rafaelcgama/award-wallet.git
cd award-wallet
bash build_dmg.sh
```

That runs the tests, builds `build/Award Wallet.dmg` and opens the `build` folder. Continue from
step 2 above.

### Automatic balances

Award Wallet signs in to United, Chase and Capital One through **Google Chrome**, so install
Chrome if you don't have it. Link a program with its login and a Chrome window opens to sign in.
If the site asks for a security code, enter it in that window, once. The site then remembers
the browser, and from then on balances refresh quietly every time you open the app, or when you
click **Refresh now**.

If a site asks for a code again, or your password changes, the program shows **Needs your
sign-in**. Open it and click **Sign in** to repeat the one-time step. Award Wallet never retries
a rejected login in the background, so your account doesn't get locked.

When a fetch fails, a screenshot of the page is saved in
`~/Library/Application Support/Award Wallet/screenshots`, which helps fix the program's reader if
a site changes its layout.

### Updating

Award Wallet checks for a new version each time it opens and shows a banner when there is one.
Click **Update now** (or choose **Award Wallet → Check for Updates…**), then **Install**: the app
downloads the new version, closes, replaces itself and reopens. Your programs and logins are kept,
because they live outside the app. **Help → About Award Wallet** shows the version you have.

### Uninstalling

Drag Award Wallet from Applications to the Trash. To remove your data too, delete
`~/Library/Application Support/Award Wallet`.

## Where your data lives

The app keeps everything in `~/Library/Application Support/Award Wallet`:

| File | What it holds |
| --- | --- |
| `settings.env` | Your secret keys. Back it up somewhere safe: without it, saved logins can't be decrypted. |
| `award_wallet.db` | The database: programs, balance history. |

The window only accepts the app itself: each launch makes a new secret that signs the window in,
and the app only answers on 127.0.0.1.

When you run it from Terminal instead (see Development), the same two files are `.env` and
`data/award_wallet.db` in this folder. Both are in `.gitignore`, so they never end up in git. The
first `bash build_dmg.sh` copies them into the app's folder.

## Security

- **Program logins are encrypted** with AES-256-GCM before they're saved, using the key in
  `settings.env` (or `.env`). Each encrypted login is tied to its owner and account, so it can't be copied onto
  another row. Logins are never shown again after you save them.
- **Award Wallet passwords** are hashed with Argon2id.
- **Every form carries a token**, so other websites can't submit forms as you, and the session
  cookie is signed and `HttpOnly`.
- **It only listens on 127.0.0.1**, so other devices on your network can't reach it.
- **Each person sees only their own programs.** Friends and family can create their own accounts
  on the same Award Wallet. To stop new sign-ups, set `AW_ALLOW_SIGNUP=false` in `.env`.

### Rotating the encryption key

```sh
uv run award-wallet generate-key
```

Put the new entry first in `AW_ENCRYPTION_KEYS` and keep the old ones after it, separated by
commas. New logins use the first key, and older ones stay readable with the others.

## Settings

Set these in `.env` or as environment variables:

| Setting | Default | Meaning |
| --- | --- | --- |
| `AW_SECRET_KEY` | (required) | Signs the session cookie. |
| `AW_ENCRYPTION_KEYS` | (required) | `key_id:base64key` entries; the first one encrypts. |
| `AW_DATABASE_URL` | `sqlite:///data/award_wallet.db` | Any SQLAlchemy URL, e.g. Postgres when hosting. |
| `AW_ALLOW_SIGNUP` | `true` | Whether new people can create accounts. |
| `AW_HOST` / `AW_PORT` | `127.0.0.1` / `8000` | Where the app listens. |
| `AW_SECURE_COOKIES` | `false` | Turn on when serving over HTTPS. |
| `AW_AUTO_MIGRATE` | `true` | Apply database migrations on startup. |
| `AW_AUTO_FETCH` | `false` (on in the Mac app) | Sign in to program sites with Chrome to fetch balances. |
| `AW_UPDATE_REPO` | `rafaelcgama/award-wallet` | GitHub repository that Check for Updates looks at. |

## How it's built

Python 3.12, FastAPI, SQLAlchemy and Alembic, with server-rendered Jinja pages and no
JavaScript build step. The Mac app shows those pages in a native window with pywebview and is
packaged with PyInstaller.

```
src/award_wallet/
  models.py      tables: users, loyalty accounts, balance snapshots, expiration lots
  providers/     one module per program (united.py, chase.py, capital_one.py)
  services/      the core logic, separate from the web layer
  security/      password hashing and the encryption vault
  web/           routes, templates and CSS
  migrations/    database schema versions (Alembic)
  cli.py         the award-wallet command
  desktop.py     the Mac app: window, menus, data folder
  updates.py     Check for Updates (GitHub releases)
  fetching.py    signs in with Chrome (Playwright) and reads balances
packaging/       app icon and the PyInstaller entry point
tests/           pytest suite
```

Balances are stored as snapshots, so history is kept and the newest snapshot is the current
balance. A snapshot can carry several expiration lots for programs whose points expire in batches.

### Adding a program

Create a module in `src/award_wallet/providers/`, subclass `Provider`, decorate it with
`@register`, and import it in `providers/__init__.py`. The `key` is stored in the database, so
never rename it. For automatic fetching, set `balance_url` (the page that shows the balance) and
`balance_patterns` (regular expressions that find it in the page's text). The sign-in itself is
generic: `fetching.py` finds the username and password boxes, and `tests/fakebank.py` is a
pretend site for testing it.

## Development

You need [uv](https://docs.astral.sh/uv/), which also installs the right Python. Common tasks
have `make` shortcuts (run `make` to list them):

| Command | What it does |
| --- | --- |
| `make setup` | Install dependencies into `.venv`, including the Mac app extras |
| `make test` | Run the tests |
| `make lint` / `make format` | Check, or fix, style with ruff |
| `make check` | Lint and tests, the same as CI |
| `make app` | Open the app window straight from the code |
| `make run` | Serve the web version at <http://127.0.0.1:8000> with auto-reload |
| `make dmg` | Build `build/Award Wallet.dmg` |

To run the web version without make: `uv run award-wallet init` once (creates `.env`), then
`uv run award-wallet serve`. Stop it with Ctrl+C.

After editing `models.py`, add a migration:

```sh
uv run alembic revision --autogenerate -m "describe the change"
```

`tests/test_migrations.py` fails if `models.py` changes without a matching migration.

### Working with git

- `main` should always build and pass `make check`. CI (`.github/workflows/ci.yml`) runs it on
  every push and pull request.
- For anything bigger than a small fix, work on a branch (`git switch -c my-change`), then open a
  pull request.
- Note changes under **Unreleased** in `CHANGELOG.md` as you go.

### Making a release

From `main`, with your changes committed:

```sh
bash release.sh          # 0.3.0 -> 0.3.1, or: bash release.sh 0.4.0
```

It bumps the version in `pyproject.toml`, `src/award_wallet/__init__.py` and `CHANGELOG.md`,
commits, tags and pushes. The release workflow then builds the .dmg on a Mac runner (about ten
minutes, progress under the repo's **Actions** tab) and attaches it to a GitHub release, which
the installed app offers as an update.

Update checks read public releases. If the repository is private, the app says it can't check,
and you update by rebuilding. The repository it checks is set by `AW_UPDATE_REPO`.

## Roadmap

1. ~~Foundation: accounts, encrypted logins, manual balances~~ (done)
2. ~~Mac app~~ (done)
3. ~~Automatic balances for United, Chase and Capital One, refreshed on every launch~~ (done)
4. Upcoming expirations view

## License

MIT: see [LICENSE](LICENSE).
