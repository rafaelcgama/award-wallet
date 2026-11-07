"""A program linked under its company's name shows the program's own name, like the others

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every program gets its own name when it's linked, like "AAdvantage". One linked under its
# company's name, like "American Airlines", gets that too. Written out here rather than read from
# the providers, so this step does the same thing whatever they say later.
COMPANY_TO_PROGRAM = {
    "american": ("American Airlines", "AAdvantage"),
    "amex": ("American Express", "Membership Rewards"),
    "capital_one": ("Capital One", "Capital One Miles"),
    "chase": ("Chase", "Ultimate Rewards"),
    "delta": ("Delta Air Lines", "SkyMiles"),
    "united": ("United Airlines", "MileagePlus"),
}


def upgrade() -> None:
    accounts = sa.table("loyalty_accounts", sa.column("provider", sa.String), sa.column("label", sa.String))
    for provider, (company, program) in COMPANY_TO_PROGRAM.items():
        op.execute(
            accounts.update().where(accounts.c.provider == provider, accounts.c.label == company).values(label=program)
        )


def downgrade() -> None:
    # Nothing to undo: the names are yours to change on the program's page.
    pass
