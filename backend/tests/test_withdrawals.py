"""Withdrawal flow: eligibility gates, the balance hold, payout and reversal.

The hold is the part worth guarding hardest - if a request doesn't take the
money out of the wallet immediately, a user can request a payout and spend
the same balance on an eSIM before an admin reviews it.
"""
import io
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.kyc import KYCStatus, KYCSubmission
from app.models.wallet import LedgerRefType, Wallet, WalletType
from app.models.withdrawal import WithdrawalRequest, WithdrawalStatus
from conftest import create_test_product, fund_wallet, register_and_login

ACCOUNT = {
    "account_type": "MOBILE",
    "bank_name": "bKash",
    "holder_name": "Test Holder",
    "account_number": "01712345678",
}
PROOF = ("proof.png", io.BytesIO(b"\x89PNG\r\n\x1a\nfake"), "image/png")


async def _approve_kyc(db_session, user_id: str):
    db_session.add(KYCSubmission(
        user_id=user_id, nid_number="1234567890",
        document_front_filename="front.png", status=KYCStatus.APPROVED,
    ))
    await db_session.commit()


async def _balance(db_session, user_id: str) -> Decimal:
    res = await db_session.execute(
        select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.DEFAULT)
    )
    wallet = res.scalar_one()
    await db_session.refresh(wallet)
    return Decimal(str(wallet.balance))


async def _ready_user(client, db_session, balance: Decimal = Decimal("100")):
    """A KYC-approved, funded user with one saved payout account."""
    user = await register_and_login(client, "wd")
    await _approve_kyc(db_session, user["user_id"])
    await fund_wallet(db_session, user["user_id"], balance)
    res = await client.post("/api/v1/withdrawals/accounts", json=ACCOUNT, headers=user["headers"])
    assert res.status_code == 200, res.text
    user["account_id"] = res.json()["id"]
    return user


async def _admin(client, promote_role):
    admin = await register_and_login(client, "wdadmin")
    await promote_role(admin["user_id"], "SUPER_ADMIN")
    return admin


@pytest.mark.asyncio
async def test_config_lists_blockers_before_kyc_or_account(client, db_session):
    user = await register_and_login(client, "wd")
    res = await client.get("/api/v1/withdrawals/config", headers=user["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["can_withdraw"] is False
    blockers = " ".join(body["blockers"]).lower()
    assert "kyc" in blockers
    assert "account" in blockers
    assert body["base_currency"] == "EUR"


@pytest.mark.asyncio
async def test_withdrawal_blocked_without_kyc(client, db_session):
    user = await register_and_login(client, "wd")
    await fund_wallet(db_session, user["user_id"], Decimal("100"))
    account = await client.post("/api/v1/withdrawals/accounts", json=ACCOUNT, headers=user["headers"])
    res = await client.post(
        "/api/v1/withdrawals",
        json={"amount": "20", "bank_account_id": account.json()["id"]},
        headers=user["headers"],
    )
    assert res.status_code == 400
    assert "kyc" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_withdrawal_blocked_without_saved_account(client, db_session):
    user = await register_and_login(client, "wd")
    await _approve_kyc(db_session, user["user_id"])
    await fund_wallet(db_session, user["user_id"], Decimal("100"))
    res = await client.post(
        "/api/v1/withdrawals",
        json={"amount": "20", "bank_account_id": "not-a-real-account"},
        headers=user["headers"],
    )
    assert res.status_code == 400
    assert "saved payout account" in res.json()["detail"]


@pytest.mark.asyncio
async def test_request_holds_the_balance_immediately(client, db_session):
    user = await _ready_user(client, db_session, Decimal("100"))
    res = await client.post(
        "/api/v1/withdrawals",
        json={"amount": "40", "bank_account_id": user["account_id"], "note_category": "commission"},
        headers=user["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "PENDING"
    assert body["reference_no"].startswith("WDR-")
    assert Decimal(body["net_amount"]) == Decimal("40.0000")  # default fee is zero
    assert await _balance(db_session, user["user_id"]) == Decimal("60.0000")


@pytest.mark.asyncio
async def test_held_balance_cannot_be_spent_or_withdrawn_twice(client, db_session):
    user = await _ready_user(client, db_session, Decimal("50"))
    first = await client.post(
        "/api/v1/withdrawals",
        json={"amount": "40", "bank_account_id": user["account_id"]},
        headers=user["headers"],
    )
    assert first.status_code == 200, first.text

    # The same money a second time - the hold has already taken it.
    second = await client.post(
        "/api/v1/withdrawals",
        json={"amount": "40", "bank_account_id": user["account_id"]},
        headers=user["headers"],
    )
    assert second.status_code == 400
    assert "balance" in second.json()["detail"].lower()

    # And it can't be spent on an eSIM either.
    product = await create_test_product(db_session, price=Decimal("30.00"))
    checkout = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET"},
        headers=user["headers"],
    )
    assert checkout.status_code == 400, checkout.text


@pytest.mark.asyncio
async def test_amount_must_respect_configured_limits(client, db_session, promote_role):
    admin = await _admin(client, promote_role)
    settings_res = await client.put(
        "/api/v1/admin/withdrawal-settings",
        json={
            "min_amount": "10", "max_amount": "50", "fee_type": "flat", "fee_value": "1",
            "payout_currency": "BDT", "processing_time": "2 business days", "is_enabled": True,
        },
        headers=admin["headers"],
    )
    assert settings_res.status_code == 200, settings_res.text

    user = await _ready_user(client, db_session, Decimal("200"))
    too_small = await client.post(
        "/api/v1/withdrawals", json={"amount": "5", "bank_account_id": user["account_id"]}, headers=user["headers"]
    )
    assert too_small.status_code == 400
    assert "minimum" in too_small.json()["detail"].lower()

    too_big = await client.post(
        "/api/v1/withdrawals", json={"amount": "80", "bank_account_id": user["account_id"]}, headers=user["headers"]
    )
    assert too_big.status_code == 400
    assert "maximum" in too_big.json()["detail"].lower()

    ok = await client.post(
        "/api/v1/withdrawals", json={"amount": "20", "bank_account_id": user["account_id"]}, headers=user["headers"]
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert Decimal(body["fee_amount"]) == Decimal("1.0000")
    assert Decimal(body["net_amount"]) == Decimal("19.0000")
    # The gross amount leaves the wallet, fee included.
    assert await _balance(db_session, user["user_id"]) == Decimal("180.0000")

    # Restore the defaults so later tests in this session see a clean config.
    await client.put(
        "/api/v1/admin/withdrawal-settings",
        json={
            "min_amount": "5", "max_amount": "1000", "fee_type": "flat", "fee_value": "0",
            "payout_currency": "BDT", "processing_time": "1-3 business days", "is_enabled": True,
        },
        headers=admin["headers"],
    )


@pytest.mark.asyncio
async def test_reject_returns_the_full_amount(client, db_session, promote_role):
    user = await _ready_user(client, db_session, Decimal("100"))
    created = await client.post(
        "/api/v1/withdrawals", json={"amount": "30", "bank_account_id": user["account_id"]}, headers=user["headers"]
    )
    withdrawal_id = created.json()["id"]
    assert await _balance(db_session, user["user_id"]) == Decimal("70.0000")

    admin = await _admin(client, promote_role)
    res = await client.post(
        f"/api/v1/admin/withdrawals/{withdrawal_id}/reject?reason=Name+mismatch", headers=admin["headers"]
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "REJECTED"
    assert await _balance(db_session, user["user_id"]) == Decimal("100.0000")

    # Rejecting twice must not credit the balance again.
    again = await client.post(f"/api/v1/admin/withdrawals/{withdrawal_id}/reject", headers=admin["headers"])
    assert again.status_code == 400
    assert await _balance(db_session, user["user_id"]) == Decimal("100.0000")


@pytest.mark.asyncio
async def test_user_can_cancel_and_get_the_money_back(client, db_session):
    user = await _ready_user(client, db_session, Decimal("60"))
    created = await client.post(
        "/api/v1/withdrawals", json={"amount": "25", "bank_account_id": user["account_id"]}, headers=user["headers"]
    )
    withdrawal_id = created.json()["id"]
    res = await client.post(f"/api/v1/withdrawals/{withdrawal_id}/cancel", headers=user["headers"])
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "CANCELLED"
    assert await _balance(db_session, user["user_id"]) == Decimal("60.0000")


@pytest.mark.asyncio
async def test_approval_freezes_the_rate_and_records_the_payout(client, db_session, promote_role):
    user = await _ready_user(client, db_session, Decimal("100"))
    created = await client.post(
        "/api/v1/withdrawals", json={"amount": "20", "bank_account_id": user["account_id"]}, headers=user["headers"]
    )
    withdrawal_id = created.json()["id"]

    admin = await _admin(client, promote_role)
    res = await client.post(
        f"/api/v1/admin/withdrawals/{withdrawal_id}/approve",
        data={"payment_reference": "BKASH-TRX-99881"},
        files={"proof": PROOF},
        headers=admin["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "PAID"
    assert body["payment_reference"] == "BKASH-TRX-99881"
    assert body["has_proof"] is True
    assert body["payout_currency"] == "BDT"

    rate = Decimal(body["conversion_rate"])
    assert rate > 0
    # net × rate, to four places - the figure the receipt and the email show.
    assert Decimal(body["payout_amount"]) == (Decimal(body["net_amount"]) * rate).quantize(Decimal("0.0001"))

    # Paying does NOT move the balance again: the hold already took it.
    assert await _balance(db_session, user["user_id"]) == Decimal("80.0000")

    # The rate stays put even if the stored rates change afterwards.
    stored = (await db_session.execute(
        select(WithdrawalRequest).where(WithdrawalRequest.id == withdrawal_id)
    )).scalar_one()
    await db_session.refresh(stored)
    assert Decimal(str(stored.conversion_rate)) == rate.quantize(Decimal("0.000001"))
    assert stored.status == WithdrawalStatus.PAID


@pytest.mark.asyncio
async def test_approval_requires_a_proof_file(client, db_session, promote_role):
    user = await _ready_user(client, db_session, Decimal("40"))
    created = await client.post(
        "/api/v1/withdrawals", json={"amount": "15", "bank_account_id": user["account_id"]}, headers=user["headers"]
    )
    admin = await _admin(client, promote_role)
    res = await client.post(
        f"/api/v1/admin/withdrawals/{created.json()['id']}/approve",
        data={"payment_reference": "REF-1"},
        headers=admin["headers"],
    )
    assert res.status_code == 422  # proof is a required form file


@pytest.mark.asyncio
async def test_a_paid_withdrawal_cannot_be_rejected(client, db_session, promote_role):
    user = await _ready_user(client, db_session, Decimal("40"))
    created = await client.post(
        "/api/v1/withdrawals", json={"amount": "15", "bank_account_id": user["account_id"]}, headers=user["headers"]
    )
    withdrawal_id = created.json()["id"]
    admin = await _admin(client, promote_role)
    await client.post(
        f"/api/v1/admin/withdrawals/{withdrawal_id}/approve",
        data={"payment_reference": "REF-2"}, files={"proof": PROOF}, headers=admin["headers"],
    )
    res = await client.post(f"/api/v1/admin/withdrawals/{withdrawal_id}/reject", headers=admin["headers"])
    assert res.status_code == 400
    assert await _balance(db_session, user["user_id"]) == Decimal("25.0000")


@pytest.mark.asyncio
async def test_queue_and_settings_are_admin_only(client, db_session):
    user = await register_and_login(client, "wd")
    assert (await client.get("/api/v1/admin/withdrawals", headers=user["headers"])).status_code == 403
    assert (await client.get("/api/v1/admin/withdrawal-settings", headers=user["headers"])).status_code == 403
    assert (await client.put(
        "/api/v1/admin/withdrawal-settings",
        json={"min_amount": "1", "max_amount": "2"},
        headers=user["headers"],
    )).status_code == 403


@pytest.mark.asyncio
async def test_others_withdrawals_are_not_visible(client, db_session):
    owner = await _ready_user(client, db_session, Decimal("40"))
    created = await client.post(
        "/api/v1/withdrawals", json={"amount": "15", "bank_account_id": owner["account_id"]}, headers=owner["headers"]
    )
    stranger = await register_and_login(client, "wdother")
    res = await client.get(f"/api/v1/withdrawals/{created.json()['id']}", headers=stranger["headers"])
    assert res.status_code == 404
    assert (await client.get("/api/v1/withdrawals", headers=stranger["headers"])).json() == []


@pytest.mark.asyncio
async def test_account_with_a_pending_withdrawal_cannot_be_deleted(client, db_session):
    user = await _ready_user(client, db_session, Decimal("40"))
    await client.post(
        "/api/v1/withdrawals", json={"amount": "15", "bank_account_id": user["account_id"]}, headers=user["headers"]
    )
    res = await client.delete(f"/api/v1/withdrawals/accounts/{user['account_id']}", headers=user["headers"])
    assert res.status_code == 400
    assert "awaiting review" in res.json()["detail"]


@pytest.mark.asyncio
async def test_payout_details_are_snapshotted_onto_the_request(client, db_session):
    """Editing or removing the account afterwards must not rewrite history."""
    user = await _ready_user(client, db_session, Decimal("60"))
    created = await client.post(
        "/api/v1/withdrawals", json={"amount": "20", "bank_account_id": user["account_id"]}, headers=user["headers"]
    )
    snapshot = created.json()["account"]
    assert snapshot["bank_name"] == "bKash"
    assert snapshot["account_number"] == ACCOUNT["account_number"]

    await client.post(f"/api/v1/withdrawals/{created.json()['id']}/cancel", headers=user["headers"])
    await client.delete(f"/api/v1/withdrawals/accounts/{user['account_id']}", headers=user["headers"])

    after = await client.get(f"/api/v1/withdrawals/{created.json()['id']}", headers=user["headers"])
    assert after.json()["account"]["account_number"] == ACCOUNT["account_number"]


@pytest.mark.asyncio
async def test_ledger_stays_balanced_and_tagged(client, db_session, promote_role):
    """The wallet balance must still equal the sum of its own ledger entries
    after a hold and a reversal. Funded through the ledger here rather than
    with conftest's fund_wallet, which writes the balance directly and would
    leave the wallet legitimately out of step with its entries."""
    from app.models.wallet import LedgerTxType, WalletLedgerEntry
    from app.services.ledger_svc import LedgerService

    user = await register_and_login(client, "wd")
    await _approve_kyc(db_session, user["user_id"])
    wallet = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == user["user_id"], Wallet.wallet_type == WalletType.DEFAULT)
    )).scalar_one()
    await LedgerService.credit(
        db_session, wallet.id, Decimal("80"), LedgerRefType.ADMIN_ADJUSTMENT, description="test funding"
    )
    await db_session.commit()
    account = await client.post("/api/v1/withdrawals/accounts", json=ACCOUNT, headers=user["headers"])

    created = await client.post(
        "/api/v1/withdrawals", json={"amount": "30", "bank_account_id": account.json()["id"]}, headers=user["headers"]
    )
    admin = await _admin(client, promote_role)
    await client.post(
        f"/api/v1/admin/withdrawals/{created.json()['id']}/reject?reason=test", headers=admin["headers"]
    )

    entries = (await db_session.execute(
        select(WalletLedgerEntry).where(WalletLedgerEntry.wallet_id == wallet.id)
    )).scalars().all()
    net = sum(
        (e.amount if e.tx_type == LedgerTxType.CREDIT else -e.amount) for e in entries
    )
    assert Decimal(str(net)) == await _balance(db_session, user["user_id"]) == Decimal("80.0000")

    kinds = {e.reference_type for e in entries if e.reference_id == created.json()["id"]}
    assert kinds == {LedgerRefType.WITHDRAWAL_HOLD, LedgerRefType.WITHDRAWAL_REVERSED}


@pytest.mark.asyncio
async def test_finance_summary_reports_pending_payables(client, db_session, promote_role):
    user = await _ready_user(client, db_session, Decimal("90"))
    await client.post(
        "/api/v1/withdrawals", json={"amount": "35", "bank_account_id": user["account_id"]}, headers=user["headers"]
    )
    admin = await _admin(client, promote_role)
    res = await client.get("/api/v1/admin/finance/summary", headers=admin["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert Decimal(body["liabilities"]["pending_withdrawals"]["payable"]) >= Decimal("35.00")
    assert Decimal(body["wallets"]["withdrawals_held"]) >= Decimal("35.00")
    assert body["withdrawals"]["by_status"]["PENDING"]["requests"] >= 1


@pytest.mark.asyncio
async def test_first_account_becomes_default_and_can_be_switched(client, db_session):
    user = await register_and_login(client, "wd")
    first = await client.post("/api/v1/withdrawals/accounts", json=ACCOUNT, headers=user["headers"])
    assert first.json()["is_default"] is True

    second = await client.post(
        "/api/v1/withdrawals/accounts",
        json={**ACCOUNT, "bank_name": "City Bank", "account_type": "BANK", "account_number": "998877665544"},
        headers=user["headers"],
    )
    assert second.json()["is_default"] is False

    await client.post(f"/api/v1/withdrawals/accounts/{second.json()['id']}/default", headers=user["headers"])
    accounts = (await client.get("/api/v1/withdrawals/accounts", headers=user["headers"])).json()
    defaults = {a["bank_name"]: a["is_default"] for a in accounts}
    assert defaults == {"City Bank": True, "bKash": False}

    duplicate = await client.post("/api/v1/withdrawals/accounts", json=ACCOUNT, headers=user["headers"])
    assert duplicate.status_code == 400
