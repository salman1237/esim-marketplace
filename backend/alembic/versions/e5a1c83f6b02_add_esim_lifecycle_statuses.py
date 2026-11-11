"""add SUSPENDED/REVOKED/CANCELLED to esimstatus for eSIM Access lifecycle actions

Needed for the new admin suspend/unsuspend/revoke/cancel actions (esim/
suspend, esim/unsuspend, esim/revoke, esim/cancel - eSIM Access only,
reference doc §4.4), which set ESIMProfile.status to reflect a
deliberate staff action distinct from the live install/usage state
ESIMTelemetry already tracks.

Revision ID: e5a1c83f6b02
Revises: d8e4b6f21a09
Create Date: 2026-11-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e5a1c83f6b02'
down_revision: Union[str, None] = 'd8e4b6f21a09'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE can't run inside a transaction block on older
    # PostgreSQL versions, and autogenerate doesn't detect enum value changes.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE esimstatus ADD VALUE IF NOT EXISTS 'SUSPENDED'")
        op.execute("ALTER TYPE esimstatus ADD VALUE IF NOT EXISTS 'REVOKED'")
        op.execute("ALTER TYPE esimstatus ADD VALUE IF NOT EXISTS 'CANCELLED'")


def downgrade() -> None:
    # PostgreSQL can't drop a value from an enum type. The value is harmless
    # if unused, so it is left in place.
    pass
