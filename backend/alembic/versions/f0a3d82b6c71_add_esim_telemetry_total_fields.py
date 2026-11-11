"""add total_volume_bytes/total_duration_days to esim_telemetry

A top-up changes an eSIM Access eSIM's REAL total data/validity - the
product's own data_amount_gb/validity_days are frozen at the moment of
the original purchase and never move, confirmed live: a real 1GB/7Days
purchase topped up once became "Total data: 2GB" / "Total time: 14
Days" in eSIM Access's own account (console.esimaccess.com,
2026-11-12), while our own storefront kept showing "0.00 MB left of
1024.00 MB" / "7 days" - the stale, pre-top-up numbers. esim/query's
own totalVolume/totalDuration are the authoritative current totals;
this column pair caches them per eSIM so the storefront can show the
real total instead of recomputing from Product every time.

Revision ID: f0a3d82b6c71
Revises: e5a1c83f6b02
Create Date: 2026-11-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f0a3d82b6c71'
down_revision: Union[str, None] = 'e5a1c83f6b02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('esim_telemetry', sa.Column('total_volume_bytes', sa.BigInteger(), nullable=True))
    op.add_column('esim_telemetry', sa.Column('total_duration_days', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('esim_telemetry', 'total_duration_days')
    op.drop_column('esim_telemetry', 'total_volume_bytes')
