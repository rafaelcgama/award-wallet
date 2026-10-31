from alembic import command

from award_wallet.db import alembic_config, upgrade_database


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
