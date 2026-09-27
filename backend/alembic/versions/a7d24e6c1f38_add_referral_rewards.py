"""add referral codes, referral_rewards, and the promo-credit share on orders

Phase 3: referral rewards paid as promo credit into the REWARD wallet.
Order.reward_amount_used records how much of an order came out of that wallet,
so a refund goes back to the wallets that paid instead of turning
non-withdrawable credit into withdrawable cash.

Revision ID: a7d24e6c1f38
Revises: f3c8d21a97b4
Create Date: 2026-09-27 12:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d24e6c1f38'
down_revision: Union[str, None] = 'f3c8d21a97b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('referral_code', sa.String(length=16), nullable=True))
    op.add_column('users', sa.Column('referred_by_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_users_referral_code'), 'users', ['referral_code'], unique=True)
    op.create_index(op.f('ix_users_referred_by_id'), 'users', ['referred_by_id'], unique=False)
    op.create_foreign_key(
        'fk_users_referred_by_id', 'users', 'users', ['referred_by_id'], ['id'], ondelete='SET NULL'
    )

    op.create_table(
        'referral_rewards',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('referrer_id', sa.String(length=36), nullable=False),
        sa.Column('referred_id', sa.String(length=36), nullable=False),
        sa.Column(
            'event',
            sa.Enum('JOINING', 'FIRST_PURCHASE', 'NEW_MERCHANT', name='referralevent'),
            nullable=False,
        ),
        sa.Column('referrer_amount', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('referred_amount', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('order_id', sa.String(length=36), nullable=True),
        sa.Column(
            'status',
            sa.Enum('GRANTED', 'REVERSED', name='referralrewardstatus'),
            nullable=False,
        ),
        sa.Column('reversal_reason', sa.Text(), nullable=True),
        sa.Column('reversed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['referred_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['referrer_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('referred_id', 'event', name='uq_referral_reward_once_per_event'),
    )
    op.create_index(op.f('ix_referral_rewards_created_at'), 'referral_rewards', ['created_at'], unique=False)
    op.create_index(op.f('ix_referral_rewards_order_id'), 'referral_rewards', ['order_id'], unique=False)
    op.create_index(op.f('ix_referral_rewards_referred_id'), 'referral_rewards', ['referred_id'], unique=False)
    op.create_index(op.f('ix_referral_rewards_referrer_id'), 'referral_rewards', ['referrer_id'], unique=False)
    op.create_index(op.f('ix_referral_rewards_status'), 'referral_rewards', ['status'], unique=False)

    op.add_column(
        'orders',
        sa.Column('reward_amount_used', sa.Numeric(precision=18, scale=4), server_default='0', nullable=False),
    )

    # ALTER TYPE ... ADD VALUE can't run inside a transaction block on older
    # PostgreSQL versions, and autogenerate doesn't detect enum value changes.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE ledgerreftype ADD VALUE IF NOT EXISTS 'REWARD_EARNED'")
        op.execute("ALTER TYPE ledgerreftype ADD VALUE IF NOT EXISTS 'REWARD_REVERSED'")


def downgrade() -> None:
    op.drop_column('orders', 'reward_amount_used')
    op.drop_index(op.f('ix_referral_rewards_status'), table_name='referral_rewards')
    op.drop_index(op.f('ix_referral_rewards_referrer_id'), table_name='referral_rewards')
    op.drop_index(op.f('ix_referral_rewards_referred_id'), table_name='referral_rewards')
    op.drop_index(op.f('ix_referral_rewards_order_id'), table_name='referral_rewards')
    op.drop_index(op.f('ix_referral_rewards_created_at'), table_name='referral_rewards')
    op.drop_table('referral_rewards')
    sa.Enum(name='referralrewardstatus').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='referralevent').drop(op.get_bind(), checkfirst=True)
    op.drop_constraint('fk_users_referred_by_id', 'users', type_='foreignkey')
    op.drop_index(op.f('ix_users_referred_by_id'), table_name='users')
    op.drop_index(op.f('ix_users_referral_code'), table_name='users')
    op.drop_column('users', 'referred_by_id')
    op.drop_column('users', 'referral_code')
    # PostgreSQL can't drop a value from an enum type; the two reward
    # reference types are harmless if unused, so they are left in place.
