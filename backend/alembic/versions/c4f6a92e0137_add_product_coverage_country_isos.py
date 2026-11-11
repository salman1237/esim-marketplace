"""add products.coverage_country_isos for regional eSIM Access packages

A regional/multi-country eSIM Access package is synced under a single
pseudo-Country (keyed on eSIM Access's locationCode - see migration
b2d5f93a8e61 and catalog_sync_svc.py's sync_esimaccess_catalog), which
loses the actual list of countries that package covers. The raw
packageInfoList response does carry that list in its own `location`
field (a comma-separated ISO2 string, e.g. "NO,RS,DE" - confirmed in
catalog_parsing.py's _esimaccess_location), it's just never stored
anywhere today. Needed so the storefront can show "Covers: Norway,
Serbia, Germany" on a regional package instead of nothing.

NULL for every non-regional row (fixed-data or single-country Day Pass)
and every VivaPe row - `coverage_networks` already exists but holds an
unrelated value (ipExport, the exit-IP distinction) for those rows, so
this is a new column rather than a repurposing of it.

Revision ID: c4f6a92e0137
Revises: b2d5f93a8e61
Create Date: 2026-11-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f6a92e0137'
down_revision: Union[str, None] = 'b2d5f93a8e61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('coverage_country_isos', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('products', 'coverage_country_isos')
