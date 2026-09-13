"""add COMMISSION_TRANSFER ledger reference type

Merchants can move earned commission into their main wallet from the
merchant dashboard; both ledger legs are tagged with this reference type.

Revision ID: 7c1e2f9a4b6d
Revises: d4bf8b516459
Create Date: 2026-09-13 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '7c1e2f9a4b6d'
down_revision: Union[str, None] = 'd4bf8b516459'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE can't run inside a transaction block on older
    # PostgreSQL versions, and autogenerate doesn't detect enum value changes.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE ledgerreftype ADD VALUE IF NOT EXISTS 'COMMISSION_TRANSFER'")


def downgrade() -> None:
    # PostgreSQL can't drop a value from an enum type. The value is harmless
    # if unused, so it is left in place.
    pass
