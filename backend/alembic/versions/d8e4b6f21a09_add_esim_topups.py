"""add esim_topups table and ESIM_TOPUP_PURCHASE ledger reference type

Topping up an already-delivered eSIM (eSIM Access's esim/topup) is a
wholly new capability - no VivaPe equivalent exists, and no existing
model represents it. EsimTopup is deliberately separate from Order/
ESIMProfile: it's a synchronous charge-then-call, never left PROCESSING
across requests the way an initial purchase's async provisioning can be.

Revision ID: d8e4b6f21a09
Revises: c4f6a92e0137
Create Date: 2026-11-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e4b6f21a09'
down_revision: Union[str, None] = 'c4f6a92e0137'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE can't run inside a transaction block on older
    # PostgreSQL versions, and autogenerate doesn't detect enum value changes.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE ledgerreftype ADD VALUE IF NOT EXISTS 'ESIM_TOPUP_PURCHASE'")

    # Not created explicitly here - op.create_table below creates it
    # itself from the Enum column (create_type defaults to True), and
    # calling .create() first made the type get created TWICE in the same
    # transaction ("type already exists"), crash-looping the app on boot
    # the one time this was deployed.
    esim_topup_status = sa.Enum('PENDING', 'COMPLETED', 'FAILED', name='esimtopupstatus')

    op.create_table(
        'esim_topups',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('esim_profile_id', sa.String(length=36), sa.ForeignKey('esim_profiles.id'), nullable=False),
        sa.Column('buyer_id', sa.String(length=36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('package_code', sa.String(length=100), nullable=False),
        sa.Column('title', sa.String(length=150), nullable=False),
        sa.Column('data_amount_gb', sa.Numeric(8, 2), nullable=False),
        sa.Column('validity_days', sa.Integer(), nullable=False),
        sa.Column('cost_price', sa.Numeric(18, 4), nullable=False),
        sa.Column('retail_price', sa.Numeric(18, 4), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('status', esim_topup_status, nullable=False, server_default='PENDING'),
        sa.Column('reward_amount_used', sa.Numeric(18, 4), nullable=False, server_default='0'),
        sa.Column('external_trx_id', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_esim_topups_esim_profile_id', 'esim_topups', ['esim_profile_id'])
    op.create_index('ix_esim_topups_buyer_id', 'esim_topups', ['buyer_id'])


def downgrade() -> None:
    op.drop_index('ix_esim_topups_buyer_id', table_name='esim_topups')
    op.drop_index('ix_esim_topups_esim_profile_id', table_name='esim_topups')
    op.drop_table('esim_topups')
    sa.Enum(name='esimtopupstatus').drop(op.get_bind(), checkfirst=True)
    # PostgreSQL can't drop a value from an enum type. The value is harmless
    # if unused, so it is left in place.
