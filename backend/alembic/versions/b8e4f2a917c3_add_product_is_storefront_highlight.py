"""add products.is_storefront_highlight for the storefront's featured Global card

Separate from is_featured, which is already used as a per-country
"recommended pick" (235 products as of 2026-11-18, effectively one per
destination) and so cannot identify a single storefront-wide "Global"
package. This lets an admin pick which product(s) GET /catalog/featured
returns. Defaults every existing row to false.

Revision ID: b8e4f2a917c3
Revises: a3c7f91e5d84
Create Date: 2026-11-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e4f2a917c3'
down_revision: Union[str, None] = 'a3c7f91e5d84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('is_storefront_highlight', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('products', 'is_storefront_highlight')
