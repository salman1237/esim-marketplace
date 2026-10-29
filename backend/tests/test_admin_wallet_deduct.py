"""Taking money back out of a customer wallet.

The mirror of the existing recharge, and deliberately not its equal:
adding balance can be undone by deducting it, but deducting is the half
that can leave a customer unable to buy something they have already paid
for, so it is super-admin only and must never overdraw.
"""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.wallet import Wallet, WalletType
from conftest import register_and_login

pytestmark = pytest.mark.asyncio


async def _admin(client, promote_role, role="SUPER_ADMIN", name="walletadmin"):
    admin = await register_and_login(client, name)
    await promote_role(admin["user_id"], role)
    return admin


async def _balance(db_session, user_id) -> Decimal:
    wallet = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.DEFAULT)
    )).scalar_one()
    return Decimal(str(wallet.balance))


async def test_super_admin_can_deduct_and_the_balance_drops(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    customer = await register_and_login(client, "deductcust")

    await client.post(f"/api/v1/admin/customers/{customer['user_id']}/wallet/recharge",
                      json={"amount": "20.00"}, headers=admin["headers"])
    res = await client.post(f"/api/v1/admin/customers/{customer['user_id']}/wallet/deduct",
                            json={"amount": "7.50", "description": "charged twice"},
                            headers=admin["headers"])
    assert res.status_code == 200, res.text
    assert res.json()["new_balance"] == pytest.approx(12.5)
    assert await _balance(db_session, customer["user_id"]) == Decimal("12.5000")


async def test_a_deduction_larger_than_the_balance_is_refused(client, db_session, promote_role):
    """Not clamped to zero and not allowed to go negative: a negative
    wallet is a state nothing else in the ledger knows how to handle."""
    admin = await _admin(client, promote_role, name="overdrawadmin")
    customer = await register_and_login(client, "overdrawcust")
    await client.post(f"/api/v1/admin/customers/{customer['user_id']}/wallet/recharge",
                      json={"amount": "5.00"}, headers=admin["headers"])

    res = await client.post(f"/api/v1/admin/customers/{customer['user_id']}/wallet/deduct",
                            json={"amount": "50.00"}, headers=admin["headers"])
    assert res.status_code == 400
    assert "balance" in res.json()["detail"].lower()
    assert await _balance(db_session, customer["user_id"]) == Decimal("5.0000")


async def test_a_plain_admin_cannot_deduct(client, db_session, promote_role):
    admin = await _admin(client, promote_role, role="ADMIN", name="plainwalletadmin")
    customer = await register_and_login(client, "plaindeductcust")
    await client.post(f"/api/v1/admin/customers/{customer['user_id']}/wallet/recharge",
                      json={"amount": "10.00"}, headers=admin["headers"])

    res = await client.post(f"/api/v1/admin/customers/{customer['user_id']}/wallet/deduct",
                            json={"amount": "1.00"}, headers=admin["headers"])
    assert res.status_code == 403
    assert await _balance(db_session, customer["user_id"]) == Decimal("10.0000")


async def test_a_refund_is_recorded_as_a_refund_not_an_adjustment(client, db_session, promote_role):
    """Same movement of money, different event - a customer reading their
    ledger should see why it happened."""
    from app.models.wallet import WalletLedgerEntry, LedgerRefType

    admin = await _admin(client, promote_role, name="refundadmin")
    customer = await register_and_login(client, "refundcust")
    await client.post(f"/api/v1/admin/customers/{customer['user_id']}/wallet/recharge",
                      json={"amount": "30.00"}, headers=admin["headers"])

    await client.post(f"/api/v1/admin/customers/{customer['user_id']}/wallet/deduct",
                      json={"amount": "4.00", "reason": "REFUND"}, headers=admin["headers"])

    wallet = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == customer["user_id"], Wallet.wallet_type == WalletType.DEFAULT)
    )).scalar_one()
    entries = (await db_session.execute(
        select(WalletLedgerEntry).where(WalletLedgerEntry.wallet_id == wallet.id)
    )).scalars().all()
    assert any(e.reference_type == LedgerRefType.REFUND for e in entries)


async def test_the_deduction_is_audit_logged(client, db_session, promote_role):
    admin = await _admin(client, promote_role, name="auditdeductadmin")
    customer = await register_and_login(client, "auditdeductcust")
    await client.post(f"/api/v1/admin/customers/{customer['user_id']}/wallet/recharge",
                      json={"amount": "9.00"}, headers=admin["headers"])
    await client.post(f"/api/v1/admin/customers/{customer['user_id']}/wallet/deduct",
                      json={"amount": "2.00"}, headers=admin["headers"])

    res = await client.get("/api/v1/admin/audit-logs", headers=admin["headers"])
    body = res.json()
    rows = body["items"] if isinstance(body, dict) else body
    assert "ADMIN_DEDUCT_CUSTOMER_WALLET" in [r["action"] for r in rows]


async def test_admin_can_read_the_balance_before_touching_it(client, db_session, promote_role):
    admin = await _admin(client, promote_role, role="ADMIN", name="balancereader")
    customer = await register_and_login(client, "balancecust")
    await client.post(f"/api/v1/admin/customers/{customer['user_id']}/wallet/recharge",
                      json={"amount": "15.00"}, headers=admin["headers"])

    res = await client.get(f"/api/v1/admin/customers/{customer['user_id']}/wallet", headers=admin["headers"])
    assert res.status_code == 200
    body = res.json()
    default = [w for w in body["wallets"] if w["wallet_type"] == "DEFAULT"][0]
    assert default["balance"] == pytest.approx(15.0)
    assert body["email"] == customer["email"]
