"""add countries.popular_order for admin-managed home page ordering

Lets a Super Admin control the order destinations appear in the home page's
Popular Destinations row, not just which ones appear. Defaults every
existing row to 0 so today's name-sorted order is preserved until an admin
reorders something.

Revision ID: b1e4a92f7c60
Revises: a4d81c6e29f7
Create Date: 2026-10-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1e4a92f7c60'
down_revision: Union[str, None] = 'a4d81c6e29f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('countries', sa.Column('popular_order', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('countries', 'popular_order')
