"""add esim_profiles.trip_feedback_sent_at for the post-trip reminder email

Marks that the "how was your eSIM" reminder has already gone out for this
profile, so the scheduled sweep (anything that expired in roughly the last
day) never emails the same customer twice for the same trip.

Revision ID: c7f2b8a40e91
Revises: b1e4a92f7c60
Create Date: 2026-10-23 00:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7f2b8a40e91'
down_revision: Union[str, None] = 'b1e4a92f7c60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('esim_profiles', sa.Column('trip_feedback_sent_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('esim_profiles', 'trip_feedback_sent_at')
