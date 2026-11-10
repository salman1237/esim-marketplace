"""widen countries.iso2 for eSIM Access regional codes, add products.supplier_period_num for Day Pass variants

Two additive changes needed to sync eSIM Access's Day Pass and
multi-country/regional packages, which the original integration
deliberately excluded (see parse_esimaccess_package's original docstring)
pending exactly these two schema decisions.

1. countries.iso2 was String(10) - fine for every real ISO2 (2 chars) and
   every VivaPe country id so far, but eSIM Access's own stable regional
   identifiers (confirmed live: 42 distinct values, e.g. "EU-42" for
   Europe/42 countries, up to 14 chars - "SAAEQAKWOMBH-6") don't fit.
   Widened to String(20) for safe margin. A pure length increase on an
   existing VARCHAR column - no data loss, no rewrite of existing values,
   same category of risk as e2b7d4c91a53's own column add.

2. products.supplier_package_code already exists (a1c4e82f7d93) but a Day
   Pass's packageCode is the SAME for every duration a customer might buy
   (the catalog has one entry; periodNum is a parameter chosen at order
   time, confirmed in backend/docs/esimaccess_integration_reference.md
   section 4.2 and the Day Pass tiered-pricing formula already
   implemented in esimaccess_adapter.py). Syncing a Day Pass as several
   fixed-looking Product variants (e.g. a 7-day and a 30-day version of
   the same catalog entry, see catalog_parsing.py) means several Product
   rows legitimately share one supplier_package_code - distinguished only
   by which periodNum each variant represents. supplier_period_num is
   NULL for every fixed-data (dataType 1) row, exactly as before.

   A composite uniqueness guarantee is added alongside it:
   (supplier_package_code, COALESCE(supplier_period_num, -1)) must be
   unique among esimaccess rows - a plain UNIQUE(code, period_num) would
   not actually catch two duplicate fixed-data rows (both NULL
   period_num), since Postgres treats NULL as distinct from NULL in a
   unique constraint. The COALESCE sentinel closes that gap.

Revision ID: b2d5f93a8e61
Revises: a1c4e82f7d93
Create Date: 2026-11-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2d5f93a8e61'
down_revision: Union[str, None] = 'a1c4e82f7d93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('countries', 'iso2', type_=sa.String(length=20), existing_type=sa.String(length=10))

    op.add_column('products', sa.Column('supplier_period_num', sa.Integer(), nullable=True))

    op.execute(
        "CREATE UNIQUE INDEX ix_products_esimaccess_code_period "
        "ON products (supplier_package_code, COALESCE(supplier_period_num, -1)) "
        "WHERE supplier_reference = 'esimaccess'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_esimaccess_code_period")
    op.drop_column('products', 'supplier_period_num')
    op.alter_column('countries', 'iso2', type_=sa.String(length=10), existing_type=sa.String(length=20))
