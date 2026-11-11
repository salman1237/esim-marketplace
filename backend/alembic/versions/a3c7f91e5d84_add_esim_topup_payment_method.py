"""add esim_topups.payment_method for gateway-paid top-ups

A top-up could previously only be paid from the wallet. Adding the
same wallet-vs-ShurjoPay choice the initial eSIM purchase already has
needs a way to tell which rail paid for a given EsimTopup row - reuses
the existing `paymentmethod` enum type (orders.payment_method), no new
enum values needed.

Revision ID: a3c7f91e5d84
Revises: f0a3d82b6c71
Create Date: 2026-11-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c7f91e5d84'
down_revision: Union[str, None] = 'f0a3d82b6c71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'esim_topups',
        sa.Column(
            'payment_method',
            sa.Enum('WALLET', 'SHURJOPAY', 'MANUAL_BANK', name='paymentmethod', create_type=False),
            nullable=False,
            server_default='WALLET',
        ),
    )


def downgrade() -> None:
    op.drop_column('esim_topups', 'payment_method')
