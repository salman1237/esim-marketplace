"""add the agent bonus taken from merchant commission, and its approval queue

An agent can take 0-10 percentage points out of a merchant's commission. The
live value is merchant_profiles.agent_bonus_pct; agent_bonus_requests is the
approval queue in front of it, because nothing an agent asks for takes effect
until an admin approves it.

orders.agent_bonus_amount is kept apart from agent_commission_amount because
the two cost different things: the agent's own percentage comes out of our
margin, the bonus comes out of the merchant's share.

Revision ID: f7c2e91b30d5
Revises: d2a71f4e63b9
Create Date: 2026-09-28 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7c2e91b30d5'
down_revision: Union[str, None] = 'd2a71f4e63b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'merchant_profiles',
        sa.Column('agent_bonus_pct', sa.Numeric(precision=5, scale=2), server_default='0', nullable=False),
    )
    op.add_column(
        'orders',
        sa.Column('agent_bonus_amount', sa.Numeric(precision=18, scale=4), server_default='0', nullable=False),
    )

    op.create_table(
        'agent_bonus_requests',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('agent_id', sa.String(length=36), nullable=False),
        sa.Column('merchant_profile_id', sa.String(length=36), nullable=False),
        sa.Column('current_pct', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('requested_pct', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('merchant_rate_pct', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column(
            'status',
            sa.Enum('PENDING', 'APPROVED', 'REJECTED', name='agentbonusstatus'),
            nullable=False,
        ),
        sa.Column('decision_note', sa.Text(), nullable=True),
        sa.Column('reviewed_by_id', sa.String(length=36), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['merchant_profile_id'], ['merchant_profiles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_agent_bonus_requests_agent_id'), 'agent_bonus_requests', ['agent_id'], unique=False)
    op.create_index(op.f('ix_agent_bonus_requests_created_at'), 'agent_bonus_requests', ['created_at'], unique=False)
    op.create_index(
        op.f('ix_agent_bonus_requests_merchant_profile_id'), 'agent_bonus_requests', ['merchant_profile_id'], unique=False
    )
    op.create_index(op.f('ix_agent_bonus_requests_status'), 'agent_bonus_requests', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_agent_bonus_requests_status'), table_name='agent_bonus_requests')
    op.drop_index(op.f('ix_agent_bonus_requests_merchant_profile_id'), table_name='agent_bonus_requests')
    op.drop_index(op.f('ix_agent_bonus_requests_created_at'), table_name='agent_bonus_requests')
    op.drop_index(op.f('ix_agent_bonus_requests_agent_id'), table_name='agent_bonus_requests')
    op.drop_table('agent_bonus_requests')
    sa.Enum(name='agentbonusstatus').drop(op.get_bind(), checkfirst=True)
    op.drop_column('orders', 'agent_bonus_amount')
    op.drop_column('merchant_profiles', 'agent_bonus_pct')
