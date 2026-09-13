"""add cost snapshot to orders for the sales profit report

orders.cost_amount records the supplier cost at the moment of purchase, so a
later change to a product's cost or to the global selling profit % never
rewrites past profit.

Revision ID: c2f4b8e1d7a3
Revises: 9e4c7d2a1b35
Create Date: 2026-09-13 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2f4b8e1d7a3'
down_revision: Union[str, None] = '9e4c7d2a1b35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('cost_amount', sa.Numeric(precision=18, scale=4), nullable=True))
    # Orders placed before this had no cost recorded. The product's current
    # supplier cost is the closest record available - VivaPe costs rarely
    # change - so existing orders are backfilled from it.
    op.execute(
        "UPDATE orders SET cost_amount = products.cost_price "
        "FROM products WHERE orders.product_id = products.id AND orders.cost_amount IS NULL"
    )


def downgrade() -> None:
    op.drop_column('orders', 'cost_amount')
