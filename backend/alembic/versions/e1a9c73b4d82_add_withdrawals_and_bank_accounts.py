"""add bank_accounts and withdrawal_requests, plus withdrawal ledger ref types

Phase 1 of the payout work: users save a payout account, request a
withdrawal (which holds the balance immediately), and an admin marks it paid
with the conversion rate frozen onto the request.

Revision ID: e1a9c73b4d82
Revises: c2f4b8e1d7a3
Create Date: 2026-09-26 10:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1a9c73b4d82'
down_revision: Union[str, None] = 'c2f4b8e1d7a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bank_accounts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('account_type', sa.Enum('BANK', 'MOBILE', name='payoutaccounttype'), nullable=False),
        sa.Column('bank_name', sa.String(length=120), nullable=False),
        sa.Column('holder_name', sa.String(length=160), nullable=False),
        sa.Column('account_number', sa.String(length=64), nullable=False),
        sa.Column('branch_name', sa.String(length=160), nullable=True),
        sa.Column('routing_number', sa.String(length=64), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_bank_accounts_user_id'), 'bank_accounts', ['user_id'], unique=False)

    op.create_table(
        'withdrawal_requests',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('reference_no', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('amount', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('fee_amount', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('net_amount', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('note_category', sa.String(length=40), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('bank_account_id', sa.String(length=36), nullable=True),
        sa.Column('account_snapshot', sa.JSON(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('PENDING', 'PAID', 'REJECTED', 'CANCELLED', name='withdrawalstatus'),
            nullable=False,
        ),
        sa.Column('payout_currency', sa.String(length=3), nullable=False),
        sa.Column('conversion_rate', sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column('payout_amount', sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column('payment_reference', sa.String(length=120), nullable=True),
        sa.Column('proof_filename', sa.String(length=255), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('reviewed_by_id', sa.String(length=36), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['bank_account_id'], ['bank_accounts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_withdrawal_requests_created_at'), 'withdrawal_requests', ['created_at'], unique=False)
    op.create_index(op.f('ix_withdrawal_requests_reference_no'), 'withdrawal_requests', ['reference_no'], unique=True)
    op.create_index(op.f('ix_withdrawal_requests_status'), 'withdrawal_requests', ['status'], unique=False)
    op.create_index(op.f('ix_withdrawal_requests_user_id'), 'withdrawal_requests', ['user_id'], unique=False)

    # ALTER TYPE ... ADD VALUE can't run inside a transaction block on older
    # PostgreSQL versions, and autogenerate doesn't detect enum value changes.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE ledgerreftype ADD VALUE IF NOT EXISTS 'WITHDRAWAL_HOLD'")
        op.execute("ALTER TYPE ledgerreftype ADD VALUE IF NOT EXISTS 'WITHDRAWAL_REVERSED'")


def downgrade() -> None:
    op.drop_index(op.f('ix_withdrawal_requests_user_id'), table_name='withdrawal_requests')
    op.drop_index(op.f('ix_withdrawal_requests_status'), table_name='withdrawal_requests')
    op.drop_index(op.f('ix_withdrawal_requests_reference_no'), table_name='withdrawal_requests')
    op.drop_index(op.f('ix_withdrawal_requests_created_at'), table_name='withdrawal_requests')
    op.drop_table('withdrawal_requests')
    op.drop_index(op.f('ix_bank_accounts_user_id'), table_name='bank_accounts')
    op.drop_table('bank_accounts')
    sa.Enum(name='withdrawalstatus').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='payoutaccounttype').drop(op.get_bind(), checkfirst=True)
    # PostgreSQL can't drop a value from an enum type; the two withdrawal
    # reference types are harmless if unused, so they are left in place.
