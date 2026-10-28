"""add products.last_seen_in_feed_at, replacing updated_at as the retirement signal

The retirement sweep decided "the supplier dropped this product" from
updated_at going stale, on the assumption that re-syncing a product always
advances it. It does not: SQLAlchemy compares values at flush time, so
assigning a product the same price/data it already had produces no UPDATE
and no onupdate, leaving updated_at frozen. Products still present in the
feed went stale and were deactivated by the sweep at the end of the very
run that had just seen them (production, 23-28 Oct 2026: ~1430 of 1473
products deactivated on a ~16h cycle).

Backfilled from updated_at, which is the best evidence available for when
each product was last known good: products in the feed get a real value on
the next sync, while anything genuinely retired stays stale and remains
eligible for deactivation, so the safety net keeps working.

Revision ID: e2b7d4c91a53
Revises: d9a3c6f21b84
Create Date: 2026-10-28 06:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2b7d4c91a53'
down_revision: Union[str, None] = 'd9a3c6f21b84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('last_seen_in_feed_at', sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE products SET last_seen_in_feed_at = updated_at "
        "WHERE supplier_product_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column('products', 'last_seen_in_feed_at')
