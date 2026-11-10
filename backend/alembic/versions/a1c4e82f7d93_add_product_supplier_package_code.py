"""add products.supplier_package_code, for suppliers whose product id isn't an integer

supplier_product_id is Integer-typed, which fits VivaPe (its product ids are
plain integers) but not eSIM Access, whose packageCode is a string like
"TOPUP_CKH491". Retyping supplier_product_id itself was considered and
rejected: it's an indexed, actively-queried column on a live production
table (the catalog-sync circuit breaker reads it every cycle), and this
project has already paid once for a careless touch to that exact sync path
(see e2b7d4c91a53's own history). A new, purely additive nullable column
carries zero risk to the existing VivaPe path instead.

No backfill needed - existing (VivaPe) rows have no value for this column
and never will; it is only ever populated going forward, for rows synced
from a supplier whose product identifier is a string.

No new "which supplier platform" column: Product.supplier_reference
already serves that role for the admin-facing enable/disable toggle
(supplier_settings_svc.py) and the three VivaPe wholesaler names it
already holds ("esimgo_bundle"/"worldmove_esim"/"telna_esim") sit at the
exact same level as a new "esimaccess" value would - extending
ESIM_REFERENCES in catalog_parsing.py is a Python-only change, not a
schema one.

Revision ID: a1c4e82f7d93
Revises: f3a8e51c904d
Create Date: 2026-11-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c4e82f7d93'
down_revision: Union[str, None] = 'f3a8e51c904d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('supplier_package_code', sa.String(length=100), nullable=True))
    op.create_index('ix_products_supplier_package_code', 'products', ['supplier_package_code'])


def downgrade() -> None:
    op.drop_index('ix_products_supplier_package_code', table_name='products')
    op.drop_column('products', 'supplier_package_code')
