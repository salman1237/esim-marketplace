"""add agent profiles, the merchant-agent mapping and agent commission on orders

Phase 4: agents earn a percentage of the price of everything their merchants
sell, on top of the merchant's own commission. Order.agent_id and
Order.agent_commission_amount snapshot who was paid and how much, so moving a
merchant to a different agent later never rewrites a past sale.

The AGENT role is added for accounts that are only agents; agent capability
itself comes from an APPROVED agent_profiles row, which a MERCHANT can also
hold - the client's rule that an agent can also be a merchant.

Revision ID: b5f19c8d40a2
Revises: a7d24e6c1f38
Create Date: 2026-09-27 15:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5f19c8d40a2'
down_revision: Union[str, None] = 'a7d24e6c1f38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE can't run inside a transaction block on older
    # PostgreSQL versions, and autogenerate doesn't detect enum value changes.
    # Done first: the agent_profiles table below is useless without the role.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'AGENT'")
        op.execute("ALTER TYPE ledgerreftype ADD VALUE IF NOT EXISTS 'AGENT_COMMISSION_EARNED'")

    op.create_table(
        'agent_profiles',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('company_name', sa.String(length=255), nullable=False),
        sa.Column('contact_phone', sa.String(length=50), nullable=False),
        sa.Column('agent_code', sa.String(length=16), nullable=False),
        sa.Column('commission_rate_pct', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column(
            'status',
            sa.Enum('PENDING', 'APPROVED', 'REJECTED', 'SUSPENDED', name='agentstatus'),
            nullable=False,
        ),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('reviewed_by_id', sa.String(length=36), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
    op.create_index(op.f('ix_agent_profiles_agent_code'), 'agent_profiles', ['agent_code'], unique=True)
    op.create_index(op.f('ix_agent_profiles_status'), 'agent_profiles', ['status'], unique=False)

    op.add_column('merchant_profiles', sa.Column('agent_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_merchant_profiles_agent_id'), 'merchant_profiles', ['agent_id'], unique=False)
    op.create_foreign_key(
        'fk_merchant_profiles_agent_id', 'merchant_profiles', 'users', ['agent_id'], ['id'], ondelete='SET NULL'
    )

    op.add_column('orders', sa.Column('agent_id', sa.String(length=36), nullable=True))
    op.add_column(
        'orders',
        sa.Column('agent_commission_amount', sa.Numeric(precision=18, scale=4), server_default='0', nullable=False),
    )
    op.create_index(op.f('ix_orders_agent_id'), 'orders', ['agent_id'], unique=False)
    op.create_foreign_key('fk_orders_agent_id', 'orders', 'users', ['agent_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_orders_agent_id', 'orders', type_='foreignkey')
    op.drop_index(op.f('ix_orders_agent_id'), table_name='orders')
    op.drop_column('orders', 'agent_commission_amount')
    op.drop_column('orders', 'agent_id')
    op.drop_constraint('fk_merchant_profiles_agent_id', 'merchant_profiles', type_='foreignkey')
    op.drop_index(op.f('ix_merchant_profiles_agent_id'), table_name='merchant_profiles')
    op.drop_column('merchant_profiles', 'agent_id')
    op.drop_index(op.f('ix_agent_profiles_status'), table_name='agent_profiles')
    op.drop_index(op.f('ix_agent_profiles_agent_code'), table_name='agent_profiles')
    op.drop_table('agent_profiles')
    sa.Enum(name='agentstatus').drop(op.get_bind(), checkfirst=True)
    # PostgreSQL can't drop a value from an enum type, so the AGENT role and
    # the agent-commission reference type are left in place; both are harmless
    # once nothing uses them.
