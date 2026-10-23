"""add products.is_featured for admin-picked recommended packages

Lets a Super Admin/Admin mark a package as "recommended" for its
destination - shown first and badged on the explore page. Defaults every
existing row to false, so nothing is highlighted until an admin picks one.

Revision ID: d9a3c6f21b84
Revises: c7f2b8a40e91
Create Date: 2026-10-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9a3c6f21b84'
down_revision: Union[str, None] = 'c7f2b8a40e91'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('is_featured', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('products', 'is_featured')
