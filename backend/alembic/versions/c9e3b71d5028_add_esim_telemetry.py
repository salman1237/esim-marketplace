"""add esim_telemetry and activated_at, for live eSIM status

Live data usage, install state and carrier provisioning history from VivaPe,
cached per eSIM so the status page still renders when the supplier is down.

Also adds esim_profiles.activated_at. Validity runs from FIRST ACTIVATION, not
from purchase - confirmed against VivaPe's own status page - so both
activated_at and expires_at are now filled in from telemetry once the customer
installs, instead of being computed at provisioning time. Existing rows keep
whatever expires_at they were given; no backfill.

Revision ID: c9e3b71d5028
Revises: b5f19c8d40a2
Create Date: 2026-09-27 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9e3b71d5028'
down_revision: Union[str, None] = 'b5f19c8d40a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('esim_profiles', sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'esim_telemetry',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('esim_profile_id', sa.String(length=36), nullable=False),
        sa.Column('data_used_bytes', sa.BigInteger(), nullable=False),
        sa.Column('data_used_mb', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('status_text', sa.String(length=60), nullable=True),
        sa.Column('is_installed', sa.Boolean(), nullable=False),
        sa.Column('device_model', sa.String(length=120), nullable=True),
        sa.Column('eid', sa.String(length=64), nullable=True),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('history', sa.JSON(), nullable=True),
        sa.Column('daily_breakdown', sa.JSON(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_forced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('fetch_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['esim_profile_id'], ['esim_profiles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    # One row per eSIM, enforced by the unique index the model declares. A
    # separate UniqueConstraint here as well would show up as schema drift.
    op.create_index(op.f('ix_esim_telemetry_esim_profile_id'), 'esim_telemetry', ['esim_profile_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_esim_telemetry_esim_profile_id'), table_name='esim_telemetry')
    op.drop_table('esim_telemetry')
    op.drop_column('esim_profiles', 'activated_at')
