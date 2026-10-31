# Award Wallet

One dashboard for all your airline miles and loyalty points. Each program shows its balance,
when it was last updated and when points expire, so you don't have to sign in to every site.

It runs on your own computer. Programs supported so far: United MileagePlus, Chase Ultimate
Rewards and Capital One Miles.

## The Mac app

Build it once on your Mac, from this folder:

```sh
bash build_dmg.sh
```

That makes `build/Award Wallet.dmg`. Open it and drag Award Wallet into Applications. After that,
start it like any app: it opens in its own window, straight to your points, with no Terminal and
no sign-in screen. The first build also moves your data from the Terminal version into the app.

The app keeps its data in `~/Library/Application Support/Award Wallet`: `settings.env` holds
your keys (back it up) and `award_wallet.db` holds everything else. It only answers to this Mac,
and each launch gets a new secret that the window uses to sign you in.

Rebuild with the same command after updating the code.

## Run it from Terminal (development)

You need [uv](https://docs.astral.sh/uv/), which also installs the right Python for you:

```sh
brew install uv          # or: curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then, from this folder:

```sh
cd ~/Projects/award-wallet
uv sync                  # install dependencies into .venv
uv run award-wallet init # create .env with your secret keys (once)
uv run award-wallet serve
```

Open <http://127.0.0.1:8000>, create an account and link your programs. Stop the app with Ctrl+C.

## Where your data lives

Everything stays in this folder on your computer:

| File | What it holds |
| --- | --- |
| `.env` | Your secret keys. Back it up somewhere safe: without it, saved logins can't be decrypted. |
| `data/award_wallet.db` | The database: accounts, programs, balance history. |

Both are listed in `.gitignore`, so they never end up in git.

## Security

- **Program logins are encrypted** with AES-256-GCM before they're saved, using the key in
  `.env`. Each encrypted login is tied to its owner and account, so it can't be copied onto
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

## How it's built

Python 3.12, FastAPI, SQLAlchemy and Alembic, with server-rendered Jinja pages and no
JavaScript build step.

```
src/award_wallet/
  models.py      tables: users, loyalty accounts, balance snapshots, expiration lots
  providers/     one module per program (united.py, chase.py, capital_one.py)
  services/      the core logic, separate from the web layer
  security/      password hashing and the encryption vault
  web/           routes, templates and CSS
  migrations/    database schema versions (Alembic)
  cli.py         the award-wallet command
tests/           pytest suite
```

Balances are stored as snapshots, so history is kept and the newest snapshot is the current
balance. A snapshot can carry several expiration lots for programs whose points expire in batches.

### Adding a program

Create a module in `src/award_wallet/providers/`, subclass `Provider`, decorate it with
`@register`, and import it in `providers/__init__.py`. The `key` is stored in the database, so
never rename it. Automatic fetching plugs in through `Provider.fetch`.

### Development

```sh
uv run pytest                                          # run the tests
uv run uvicorn award_wallet.web:create_app --factory --reload --port 8000  # auto-reload
uv run alembic revision --autogenerate -m "describe the change"            # after editing models.py
```

`tests/test_migrations.py` fails if `models.py` changes without a matching migration.

## Roadmap

1. ~~Foundation: accounts, encrypted logins, manual balances~~ (done)
2. Automatic balance fetching for United, Chase and Capital One
3. Dashboard refresh: "refresh all", a daily automatic refresh, and upcoming expirations
