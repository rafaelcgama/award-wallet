import sqlalchemy as sa
from alembic import command

from milestash.db import alembic_config, upgrade_database


def test_migrations_match_the_models(tmp_path):
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    upgrade_database(url)
    # Fails if a model changed without a matching migration.
    command.check(alembic_config(url))


def test_migrations_downgrade_cleanly(tmp_path):
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    upgrade_database(url)
    command.downgrade(alembic_config(url), "base")
    upgrade_database(url)


def test_programs_named_after_their_company_get_the_programs_own_name(tmp_path):
    url = f"sqlite:///{tmp_path / 'linked.db'}"
    command.upgrade(alembic_config(url), "0002")
    engine = sa.create_engine(url)
    now = "2026-11-07 12:00:00"
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO users VALUES ('me', 'me@example.com', 'Me', 'x', :now)"), {"now": now})
        for account, provider, label in (
            ("a", "american", "American Airlines"),
            ("b", "united", "United Airlines"),
            ("c", "chase", "Sapphire Preferred"),
            ("d", "delta", "SkyMiles"),
        ):
            connection.execute(
                sa.text(
                    "INSERT INTO loyalty_accounts (id, user_id, provider, label, sync_status, created_at, updated_at)"
                    " VALUES (:id, 'me', :provider, :label, 'ok', :now, :now)"
                ),
                {"id": account, "provider": provider, "label": label, "now": now},
            )
    upgrade_database(url)
    with engine.connect() as connection:
        labels = dict(connection.execute(sa.text("SELECT id, label FROM loyalty_accounts")).all())
    # A name you chose stays yours.
    assert labels == {"a": "AAdvantage", "b": "MileagePlus", "c": "Sapphire Preferred", "d": "SkyMiles"}
