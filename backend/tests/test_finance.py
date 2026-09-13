import uuid
import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import select

from conftest import register_and_login, create_test_product
from app.models.audit import SupplierTransactionLog
from app.models.order import Order, OrderStatus, PaymentMethod
from app.models.wallet import Wallet, WalletType
from app.services.ledger_svc import LedgerService
from app.models.wallet import LedgerRefType

pytestmark = pytest.mark.asyncio


async def _super_admin(client, promote_role, name):
    sa = await register_and_login(client, name)
    await promote_role(sa["user_id"], "SUPER_ADMIN")
    return sa


async def _approved_merchant(client, admin_headers, name):
    user = await register_and_login(client, name)
    await client.post(
        "/api/v1/auth/apply-merchant",
        json={"business_name": f"{name} Travels", "contact_phone": "+1000000000"},
        headers=user["headers"],
    )
    queue = await client.get("/api/v1/admin/merchants/queue", headers=admin_headers)
    entry = next(m for m in queue.json() if m["user_id"] == user["user_id"])
    res = await client.post(f"/api/v1/admin/merchants/{entry['id']}/approve", headers=admin_headers)
    assert res.status_code == 200, res.text
    return user


async def _wallet(db_session, user_id, wallet_type=WalletType.DEFAULT):
    return (await db_session.execute(
        select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == wallet_type)
    )).scalar_one()


async def _order(db_session, buyer_id, product, status, trx_id=None, cost="5.0000", total="6.2500", reseller=False, age=timedelta(0)):
    order = Order(
        order_no=f"ORD-FIN-{uuid.uuid4().hex[:10].upper()}",
        buyer_id=buyer_id, beneficiary_id=buyer_id, product_id=product.id,
        total_amount=Decimal(total), cost_amount=Decimal(cost) if cost is not None else None,
        currency="EUR", payment_method=PaymentMethod.WALLET, status=status,
        is_reseller_order=reseller, external_trx_id=trx_id,
    )
    if age:
        order.updated_at = datetime.now(timezone.utc) - age
    db_session.add(order)
    await db_session.commit()
    return order


async def test_finance_reports_require_admin(client):
    user = await register_and_login(client, "finuser")
    for path in ("summary", "vivape", "vivape.csv", f"merchant-statement?user_id={user['user_id']}"):
        assert (await client.get(f"/api/v1/admin/finance/{path}", headers=user["headers"])).status_code == 403


async def test_vivape_reconciliation_flags_every_kind_of_mismatch(client, db_session, promote_role):
    sa = await _super_admin(client, promote_role, "finrecon")
    product = await create_test_product(db_session)
    tag = uuid.uuid4().hex[:8]

    ok = await _order(db_session, sa["user_id"], product, OrderStatus.COMPLETED, trx_id=f"ok-{tag}")
    failed = await _order(db_session, sa["user_id"], product, OrderStatus.FAILED, trx_id=f"failed-{tag}")
    no_trx = await _order(db_session, sa["user_id"], product, OrderStatus.COMPLETED)
    no_cost = await _order(db_session, sa["user_id"], product, OrderStatus.COMPLETED, trx_id=f"nocost-{tag}", cost=None)
    stuck = await _order(db_session, sa["user_id"], product, OrderStatus.PROCESSING, age=timedelta(hours=2))
    dup_a = await _order(db_session, sa["user_id"], product, OrderStatus.COMPLETED, trx_id=f"dup-{tag}")
    dup_b = await _order(db_session, sa["user_id"], product, OrderStatus.COMPLETED, trx_id=f"dup-{tag}")

    for trx in (f"ok-{tag}", f"orphan-{tag}"):
        db_session.add(SupplierTransactionLog(
            supplier_name="VIVAPE", endpoint="create-transaction", method="POST",
            request_payload={}, response_payload={"purchase_trx": {"id": trx}}, status_code=200, latency_ms=1,
        ))
    await db_session.commit()

    res = await client.get("/api/v1/admin/finance/vivape", headers=sa["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    ex = body["exceptions"]
    ids = lambda key: {o["order_id"] for o in ex[key]}

    assert body["ok"] is False
    assert failed.id in ids("charged_but_failed")
    assert no_trx.id in ids("completed_without_trx")
    assert no_cost.id in ids("completed_missing_cost")
    assert stuck.id in ids("stuck_in_progress")
    assert {dup_a.id, dup_b.id} <= ids("duplicate_trx_ids")
    assert f"orphan-{tag}" in {o["vivape_trx_id"] for o in ex["supplier_trx_without_order"]}
    assert f"ok-{tag}" not in {o["vivape_trx_id"] for o in ex["supplier_trx_without_order"]}
    assert ok.id not in ids("charged_but_failed") | ids("completed_without_trx")

    csv_res = await client.get("/api/v1/admin/finance/vivape.csv", headers=sa["headers"])
    assert csv_res.status_code == 200
    assert f"failed-{tag}" in csv_res.text and "VivaPe charge to recover" in csv_res.text
    assert no_trx.order_no not in csv_res.text  # only orders VivaPe charged for

    bad = await client.get("/api/v1/admin/finance/vivape?date_from=2026-09-10&date_to=2026-09-01", headers=sa["headers"])
    assert bad.status_code == 400


async def test_money_cycle_summary_and_ledger_integrity(client, db_session, promote_role):
    sa = await _super_admin(client, promote_role, "fincycle")
    customer = await register_and_login(client, "fincustomer")
    wallet = await _wallet(db_session, customer["user_id"])
    await LedgerService.credit(db_session, wallet.id, Decimal("40.0000"), LedgerRefType.DEPOSIT_MANUAL, ref_id="fin-test", description="test deposit")
    await db_session.commit()

    body = (await client.get("/api/v1/admin/finance/summary", headers=sa["headers"])).json()
    assert Decimal(body["money_in"]["manual_deposits"]) >= Decimal("40.00")
    assert Decimal(body["liabilities"]["total"]) >= Decimal("40.00")
    assert any(r["reference_type"] == "DEPOSIT_MANUAL" and r["holder"] == "customer" for r in body["ledger_breakdown"])
    assert customer["email"] if "email" in customer else True
    assert wallet.id not in {w["wallet_id"] for w in body["integrity"]["mismatched_wallets"]}

    # A balance changed without a ledger entry is exactly what the check exists to catch.
    broken_user = await register_and_login(client, "finbroken")
    broken = await _wallet(db_session, broken_user["user_id"])
    broken.balance = Decimal("12.3400")
    await db_session.commit()
    integrity = (await client.get("/api/v1/admin/finance/summary", headers=sa["headers"])).json()["integrity"]
    assert integrity["ok"] is False
    assert integrity["wallet_balance_mismatches"] >= 1


async def test_merchant_statement_adds_up_for_admin_and_merchant(client, db_session, promote_role):
    sa = await _super_admin(client, promote_role, "finstmtadmin")
    merchant = await _approved_merchant(client, sa["headers"], "finstmtmerchant")
    product = await create_test_product(db_session)

    wallet = await _wallet(db_session, merchant["user_id"])
    await LedgerService.credit(db_session, wallet.id, Decimal("100.0000"), LedgerRefType.DEPOSIT_GATEWAY, ref_id="fin-topup")
    await LedgerService.debit(db_session, wallet.id, Decimal("6.2500"), LedgerRefType.ORDER_PURCHASE, ref_id="fin-order")
    await db_session.commit()
    await _order(db_session, merchant["user_id"], product, OrderStatus.COMPLETED, trx_id=f"stmt-{uuid.uuid4().hex[:8]}", reseller=True)

    month = datetime.now(timezone.utc).strftime("%Y-%m")
    admin_view = await client.get(
        f"/api/v1/admin/finance/merchant-statement?user_id={merchant['user_id']}&month={month}", headers=sa["headers"]
    )
    assert admin_view.status_code == 200, admin_view.text
    stmt = admin_view.json()
    default = next(w for w in stmt["wallets"] if w["wallet_type"] == "DEFAULT")
    assert default["opening_balance"] == "0.00"
    assert default["credits"] == "100.00" and default["debits"] == "6.25"
    assert default["closing_balance"] == "93.75"
    assert stmt["consistent"] is True
    assert stmt["orders"]["completed"] == 1
    assert stmt["merchant"]["business_name"] == "finstmtmerchant Travels"

    own = await client.get(f"/api/v1/merchant/statement?month={month}", headers=merchant["headers"])
    assert own.status_code == 200
    assert own.json()["wallets"] == stmt["wallets"]

    csv_res = await client.get("/api/v1/merchant/statement.csv", headers=merchant["headers"])
    assert csv_res.status_code == 200
    assert "93.75" in csv_res.text and "-6.25" in csv_res.text

    # An earlier month has nothing yet, and a later one opens at the closing balance.
    next_month = (datetime.now(timezone.utc).replace(day=28) + timedelta(days=5)).strftime("%Y-%m")
    later = (await client.get(f"/api/v1/merchant/statement?month={next_month}", headers=merchant["headers"])).json()
    later_default = next(w for w in later["wallets"] if w["wallet_type"] == "DEFAULT")
    assert later_default["opening_balance"] == "93.75" and later_default["entries"] == []

    assert (await client.get("/api/v1/merchant/statement?month=2026-13", headers=merchant["headers"])).status_code == 400
    plain = await register_and_login(client, "finnotmerchant")
    assert (await client.get("/api/v1/merchant/statement", headers=plain["headers"])).status_code == 403
