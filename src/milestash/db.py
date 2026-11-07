"""Database engine, sessions and migrations."""

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def ensure_sqlite_directory(url: URL) -> None:
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        # Private to your user: the database holds your (encrypted) logins.
        Path(url.database).parent.mkdir(mode=0o700, parents=True, exist_ok=True)


def create_db_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return create_engine(url, pool_pre_ping=True)

    ensure_sqlite_directory(url)
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_sqlite_features(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        # SQLite ignores foreign keys (and so ON DELETE CASCADE) unless asked.
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def alembic_config(database_url: str):
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    # Alembic's config treats % as interpolation, which URL-encoded passwords contain.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade_database(database_url: str) -> None:
    from alembic import command

    command.upgrade(alembic_config(database_url), "head")
