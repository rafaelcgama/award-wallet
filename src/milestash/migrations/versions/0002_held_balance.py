"""Hold back a balance that fell by more than half until you say whether it's right

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("loyalty_accounts") as table:
        table.add_column(sa.Column("held_balance", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("loyalty_accounts") as table:
        table.drop_column("held_balance")
