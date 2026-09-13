"""switch base currency from USD to EUR

VivaPe - the only supplier - prices in euro, and catalog costs were always
stored exactly as VivaPe reports them: the amounts were euro all along and
only the label said USD. Decided with the client: relabel, don't convert.
Every stored amount (wallet balances, ledger, product prices, orders,
commission) keeps its number; only the currency code changes.

Exchange rates were stored as "1 USD = X". They are rebased to "1 EUR = X"
by dividing by EUR's effective rate, so display and top-up conversion stay
correct.

Revision ID: 9e4c7d2a1b35
Revises: 3b8d6a1f2c90
Create Date: 2026-09-13 16:00:00.000000

"""
from decimal import Decimal
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9e4c7d2a1b35'
down_revision: Union[str, None] = '3b8d6a1f2c90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 1 USD in EUR, used only if the database has no EUR rate at all.
FALLBACK_EUR_PER_USD = Decimal("0.863")

RELABELLED_COLUMNS = (
    ("wallets", "currency"),
    ("products", "currency"),
    ("orders", "currency"),
    ("users", "preferred_currency"),
)


def _relabel(src: str, dst: str) -> None:
    for table, column in RELABELLED_COLUMNS:
        op.execute(sa.text(f"UPDATE {table} SET {column} = :dst WHERE {column} = :src").bindparams(src=src, dst=dst))
    # platform_settings.value is JSON, so the stored value is the JSON string '"USD"'.
    op.execute(
        sa.text(
            "UPDATE platform_settings SET value = CAST(:dst AS json) "
            "WHERE key = 'default_currency' AND CAST(value AS text) = :src"
        ).bindparams(dst=f'"{dst}"', src=f'"{src}"')
    )


def _rebase_rates(old_base: str, new_base: str, fallback_factor: Decimal) -> None:
    """Rates are "1 old_base = X". Divide every rate by new_base's effective
    rate to get "1 new_base = X"; new_base itself becomes exactly 1."""
    bind = op.get_bind()
    row = bind.execute(
        sa.text("SELECT rate_to_base, manual_rate, is_manual_override FROM currency_rates WHERE currency_code = :c"),
        {"c": new_base},
    ).first()

    effective = None
    if row is not None:
        effective = row.manual_rate if (row.is_manual_override and row.manual_rate) else row.rate_to_base
    factor = Decimal(str(effective)) if effective and Decimal(str(effective)) > 0 else fallback_factor

    bind.execute(
        sa.text("UPDATE currency_rates SET rate_to_base = rate_to_base / :f, manual_rate = manual_rate / :f"),
        {"f": factor},
    )

    if row is not None:
        bind.execute(
            sa.text(
                "UPDATE currency_rates SET rate_to_base = 1, manual_rate = NULL, "
                "is_manual_override = false, source = 'AUTO_API' WHERE currency_code = :c"
            ),
            {"c": new_base},
        )
    else:
        bind.execute(
            sa.text(
                "INSERT INTO currency_rates (currency_code, rate_to_base, is_manual_override, source, updated_at) "
                "VALUES (:c, 1, false, 'AUTO_API', now())"
            ),
            {"c": new_base},
        )

    # The old base must stay convertible (e.g. visitors who display USD).
    has_old = bind.execute(
        sa.text("SELECT 1 FROM currency_rates WHERE currency_code = :c"), {"c": old_base}
    ).first()
    if not has_old:
        bind.execute(
            sa.text(
                "INSERT INTO currency_rates (currency_code, rate_to_base, is_manual_override, source, updated_at) "
                "VALUES (:c, :r, false, 'AUTO_API', now())"
            ),
            {"c": old_base, "r": Decimal("1") / factor},
        )


def upgrade() -> None:
    _relabel("USD", "EUR")
    _rebase_rates(old_base="USD", new_base="EUR", fallback_factor=FALLBACK_EUR_PER_USD)


def downgrade() -> None:
    _relabel("EUR", "USD")
    _rebase_rates(old_base="EUR", new_base="USD", fallback_factor=Decimal("1") / FALLBACK_EUR_PER_USD)
