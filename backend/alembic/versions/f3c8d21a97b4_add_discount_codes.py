"""add discount codes, redemptions, and the discount fields on orders

Phase 2: one code per order (enforced by the unique constraint on
discount_redemptions.order_id). Order.total_amount stays "what the customer
was charged", so it is stored net of the discount and Order.discount_amount
records what came off - profit and commission both follow from that without
any further adjustment.

Revision ID: f3c8d21a97b4
Revises: e1a9c73b4d82
Create Date: 2026-09-27 09:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3c8d21a97b4'
down_revision: Union[str, None] = 'e1a9c73b4d82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'discount_codes',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('code', sa.String(length=40), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('discount_type', sa.Enum('PERCENT', 'FIXED', name='discounttype'), nullable=False),
        sa.Column('value', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('max_discount_amount', sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column('min_order_amount', sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('max_uses', sa.Integer(), nullable=True),
        sa.Column('max_uses_per_user', sa.Integer(), nullable=True),
        sa.Column('first_order_only', sa.Boolean(), nullable=False),
        sa.Column('scope', sa.Enum('ALL', 'COUNTRY', 'PRODUCT', name='discountscope'), nullable=False),
        sa.Column('country_id', sa.Integer(), nullable=True),
        sa.Column('product_id', sa.String(length=36), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_by_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['country_id'], ['countries.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_discount_codes_code'), 'discount_codes', ['code'], unique=True)

    op.create_table(
        'discount_redemptions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('discount_code_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('order_id', sa.String(length=36), nullable=False),
        sa.Column('discount_amount', sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['discount_code_id'], ['discount_codes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('order_id', name='uq_discount_redemption_order'),
    )
    op.create_index(op.f('ix_discount_redemptions_created_at'), 'discount_redemptions', ['created_at'], unique=False)
    op.create_index(op.f('ix_discount_redemptions_discount_code_id'), 'discount_redemptions', ['discount_code_id'], unique=False)
    op.create_index(op.f('ix_discount_redemptions_user_id'), 'discount_redemptions', ['user_id'], unique=False)

    op.add_column('orders', sa.Column('discount_code_id', sa.String(length=36), nullable=True))
    # server_default keeps the NOT NULL valid for orders placed before this.
    op.add_column('orders', sa.Column('discount_amount', sa.Numeric(precision=18, scale=4), server_default='0', nullable=False))
    op.create_foreign_key(
        'fk_orders_discount_code_id', 'orders', 'discount_codes', ['discount_code_id'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('fk_orders_discount_code_id', 'orders', type_='foreignkey')
    op.drop_column('orders', 'discount_amount')
    op.drop_column('orders', 'discount_code_id')
    op.drop_index(op.f('ix_discount_redemptions_user_id'), table_name='discount_redemptions')
    op.drop_index(op.f('ix_discount_redemptions_discount_code_id'), table_name='discount_redemptions')
    op.drop_index(op.f('ix_discount_redemptions_created_at'), table_name='discount_redemptions')
    op.drop_table('discount_redemptions')
    op.drop_index(op.f('ix_discount_codes_code'), table_name='discount_codes')
    op.drop_table('discount_codes')
    sa.Enum(name='discountscope').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='discounttype').drop(op.get_bind(), checkfirst=True)
