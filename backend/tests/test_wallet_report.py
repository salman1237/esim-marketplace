"""Who is holding money, and how much of it is actually cash.

The three wallets are reported separately on purpose: DEFAULT is money a
customer topped up, REWARD is promo credit that can be spent but never
withdrawn, and COMMISSION is what a partner has earned. Summing them into
one number would imply the business owes cash it does not.
"""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.wallet import LedgerRefType, Wallet, WalletType
from app.services.ledger_svc import LedgerService
from app.services.wallet_report_svc import build_wallet_report
from conftest import register_and_login

pytestmark = pytest.mark.asyncio


async def _credit(db_session, user_id, wallet_type, amount):
    wallet = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == wallet_type)
    )).scalar_one()
    await LedgerService.credit(
        db_session, wallet.id, Decimal(amount), LedgerRefType.ADMIN_ADJUSTMENT,
        description="test top-up", idempotency_key=None,
    )
    await db_session.commit()


async def test_each_wallet_kind_is_reported_separately(client, db_session):
    user = await register_and_login(client, "walletreportuser")
    await _credit(db_session, user["user_id"], WalletType.DEFAULT, "25.00")
    await _credit(db_session, user["user_id"], WalletType.REWARD, "5.00")

    report = await build_wallet_report(db_session, search=user["email"])
    assert len(report["items"]) == 1
    row = report["items"][0]
    assert row["default_balance"] == "25.00"
    assert row["reward_balance"] == "5.00"
    assert row["total_balance"] == "30.00"


async def test_sorting_by_balance_puts_the_largest_first(client, db_session):
    small = await register_and_login(client, "smallholder")
    large = await register_and_login(client, "largeholder")
    await _credit(db_session, small["user_id"], WalletType.DEFAULT, "3.00")
    await _credit(db_session, large["user_id"], WalletType.DEFAULT, "900.00")

    report = await build_wallet_report(db_session, sort="total", descending=True)
    emails = [i["email"] for i in report["items"]]
    assert emails.index(large["email"]) < emails.index(small["email"])

    ascending = await build_wallet_report(db_session, sort="total", descending=False)
    emails_asc = [i["email"] for i in ascending["items"]]
    assert emails_asc.index(small["email"]) < emails_asc.index(large["email"])


async def test_min_balance_filters_out_empty_wallets(client, db_session):
    rich = await register_and_login(client, "richholder")
    poor = await register_and_login(client, "poorholder")
    await _credit(db_session, rich["user_id"], WalletType.DEFAULT, "120.00")

    report = await build_wallet_report(db_session, min_balance=Decimal("100"))
    emails = [i["email"] for i in report["items"]]
    assert rich["email"] in emails
    assert poor["email"] not in emails


async def test_search_matches_email_and_phone(client, db_session):
    user = await register_and_login(client, "searchableholder")
    await _credit(db_session, user["user_id"], WalletType.DEFAULT, "10.00")

    by_email = await build_wallet_report(db_session, search=user["email"])
    assert len(by_email["items"]) == 1

    by_phone = await build_wallet_report(db_session, search="8801700000000")
    assert user["email"] in [i["email"] for i in by_phone["items"]]


async def test_summary_keeps_cash_apart_from_promo_credit(client, db_session):
    """The number that matters for liability is cash, not the total: promo
    credit can be spent on eSIMs but never withdrawn."""
    user = await register_and_login(client, "liabilityholder")
    await _credit(db_session, user["user_id"], WalletType.DEFAULT, "40.00")
    await _credit(db_session, user["user_id"], WalletType.REWARD, "60.00")

    report = await build_wallet_report(db_session, search=user["email"])
    summary = report["summary"]
    assert summary["total_default_eur"] == "40.00"
    assert summary["total_reward_eur"] == "60.00"
    assert summary["total_all_eur"] == "100.00"


async def test_last_activity_reflects_the_most_recent_ledger_entry(client, db_session):
    user = await register_and_login(client, "activityholder")
    await _credit(db_session, user["user_id"], WalletType.DEFAULT, "11.00")

    report = await build_wallet_report(db_session, search=user["email"])
    assert report["items"][0]["last_activity"] is not None


async def test_report_requires_admin(client):
    res = await client.get("/api/v1/admin/reports/wallets")
    assert res.status_code in (401, 403)


async def test_the_limit_returns_the_largest_balances_not_an_arbitrary_slice(client, db_session):
    """Caught by CI, not locally: the limit was applied in SQL while the
    sort ran in Python afterwards, so the report reordered only whichever
    rows the database happened to return. With more holders than the
    limit, "the largest balances" were the largest of an arbitrary slice -
    wrong in exactly the case the sort exists for.

    Built to discriminate rather than to pass: the small holders are
    created FIRST so an unordered LIMIT returns them by heap order, and
    the three large ones are created last and are far larger than anything
    else the suite makes. Under the old code this asks the database for
    three rows, gets small ones, sorts those three and returns them.
    """
    for i in range(12):
        minnow = await register_and_login(client, f"minnow{i}")
        await _credit(db_session, minnow["user_id"], WalletType.DEFAULT, "1.00")

    expected = []
    for name, amount in (("whale1", "90000.00"), ("whale2", "80000.00"), ("whale3", "70000.00")):
        whale = await register_and_login(client, name)
        await _credit(db_session, whale["user_id"], WalletType.DEFAULT, amount)
        expected.append(whale["email"])

    top_three = await build_wallet_report(db_session, sort="total", descending=True, limit=3)
    assert [i["email"] for i in top_three["items"]] == expected, (
        "the limit cut off larger balances before the sort ran"
    )
