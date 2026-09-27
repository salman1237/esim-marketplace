"""Referral rewards and promo credit.

The rule that has to hold no matter what: reward credit can buy an eSIM but
can never leave as cash. That is tested from both ends - a promo-funded
purchase works, and a withdrawal can never draw on promo credit, including
through the refund of a promo-funded order.
"""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.kyc import KYCStatus, KYCSubmission
from app.models.merchant import MerchantProfile, MerchantStatus
from app.models.order import Order
from app.models.referral import ReferralEvent, ReferralReward, ReferralRewardStatus
from app.models.wallet import LedgerRefType, Wallet, WalletLedgerEntry, WalletType
from conftest import create_test_product, fund_wallet, register_and_login, wait_for_order

pytestmark = pytest.mark.asyncio

ALL_ON = {
    "is_enabled": True,
    "events": {
        "JOINING": {"referrer": "2.00", "referred": "1.00", "enabled": True},
        "FIRST_PURCHASE": {"referrer": "3.00", "referred": "0", "enabled": True},
        "NEW_MERCHANT": {"referrer": "5.00", "referred": "0", "enabled": True},
    },
    "max_rewarded_referrals": None,
}


async def _super_admin(client, promote_role, name="refadmin"):
    admin = await register_and_login(client, name)
    await promote_role(admin["user_id"], "SUPER_ADMIN")
    return admin


async def _set_settings(client, admin, payload=None):
    res = await client.put("/api/v1/admin/referral-settings", json=payload or ALL_ON, headers=admin["headers"])
    assert res.status_code == 200, res.text
    return res.json()


async def _reset_settings(client, admin):
    await client.put(
        "/api/v1/admin/referral-settings",
        json={"is_enabled": False, "events": {}, "max_rewarded_referrals": None},
        headers=admin["headers"],
    )


async def _balances(db_session, user_id: str) -> dict:
    res = await db_session.execute(select(Wallet).where(Wallet.user_id == user_id))
    out = {}
    for wallet in res.scalars().all():
        await db_session.refresh(wallet)
        out[wallet.wallet_type.value] = Decimal(str(wallet.balance))
    return out


async def _register_with_code(client, code: str, name="refnew"):
    import uuid as _uuid
    suffix = _uuid.uuid4().hex[:8]
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{name}_{suffix}@example.com", "username": f"{name}_{suffix}",
            "password": "TestPass123!", "referral_code": code,
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    return {
        "token": data["access_token"],
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
        "user_id": data["user_id"],
        "username": data["username"],
    }


async def test_every_account_gets_a_code_and_a_share_link(client, db_session):
    user = await register_and_login(client, "ref")
    res = await client.get("/api/v1/referrals/me", headers=user["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["code"] and len(body["code"]) == 8
    assert body["share_url"].endswith(f"?ref={body['code']}")
    # No 0/O/1/I/L - these get read off a screen and typed by hand.
    assert not set(body["code"]) & set("01OIL")
    assert body["referred_count"] == 0


async def test_joining_reward_credits_both_sides_as_promo_credit(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    await _set_settings(client, admin)

    referrer = await register_and_login(client, "refA")
    code = (await client.get("/api/v1/referrals/me", headers=referrer["headers"])).json()["code"]

    invited = await _register_with_code(client, code)

    # Referrer got 2.00, the invited user 1.00 - both in the REWARD wallet.
    assert (await _balances(db_session, referrer["user_id"]))["REWARD"] == Decimal("2.0000")
    invited_balances = await _balances(db_session, invited["user_id"])
    assert invited_balances["REWARD"] == Decimal("1.0000")
    assert invited_balances["DEFAULT"] == Decimal("0.0000")

    summary = (await client.get("/api/v1/referrals/me", headers=referrer["headers"])).json()
    assert summary["referred_count"] == 1
    assert Decimal(summary["total_earned"]) == Decimal("2.00")
    assert Decimal(summary["promo_balance"]) == Decimal("2.0000")
    assert summary["referred"][0]["username"] == invited["username"]

    invited_summary = (await client.get("/api/v1/referrals/me", headers=invited["headers"])).json()
    assert invited_summary["referred_by"] == referrer["username"]
    assert invited_summary["can_claim"] is False

    await _reset_settings(client, admin)


async def test_nothing_is_paid_while_the_programme_is_off(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    await _reset_settings(client, admin)

    referrer = await register_and_login(client, "refoff")
    code = (await client.get("/api/v1/referrals/me", headers=referrer["headers"])).json()["code"]
    invited = await _register_with_code(client, code)

    # The referral link is still recorded - only the money is off.
    assert (await _balances(db_session, referrer["user_id"])).get("REWARD", Decimal("0")) == Decimal("0.0000")
    invited_summary = (await client.get("/api/v1/referrals/me", headers=invited["headers"])).json()
    assert invited_summary["referred_by"] == referrer["username"]


async def test_an_unknown_code_never_blocks_registration(client, db_session):
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "badcode_ref@example.com", "username": "badcode_ref",
            "password": "TestPass123!", "referral_code": "ZZZZZZZZ",
        },
    )
    assert res.status_code == 200, res.text
    summary = (await client.get(
        "/api/v1/referrals/me", headers={"Authorization": f"Bearer {res.json()['access_token']}"}
    )).json()
    assert summary["referred_by"] is None
    assert summary["can_claim"] is True


async def test_first_purchase_reward_pays_once_on_delivery(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    await _set_settings(client, admin)

    referrer = await register_and_login(client, "refB")
    code = (await client.get("/api/v1/referrals/me", headers=referrer["headers"])).json()["code"]
    invited = await _register_with_code(client, code)
    await fund_wallet(db_session, invited["user_id"], Decimal("100"))

    product = await create_test_product(db_session, price=Decimal("10.00"))
    first = await client.post(
        "/api/v1/orders/checkout", json={"product_id": product.id, "payment_method": "WALLET"},
        headers=invited["headers"],
    )
    settled = await wait_for_order(client, first.json()["id"], invited["headers"])
    assert settled["status"] == "COMPLETED"

    # 2.00 joining + 3.00 first purchase.
    assert (await _balances(db_session, referrer["user_id"]))["REWARD"] == Decimal("5.0000")

    # A second purchase pays nothing more.
    second = await client.post(
        "/api/v1/orders/checkout", json={"product_id": product.id, "payment_method": "WALLET"},
        headers=invited["headers"],
    )
    await wait_for_order(client, second.json()["id"], invited["headers"])
    assert (await _balances(db_session, referrer["user_id"]))["REWARD"] == Decimal("5.0000")

    rewards = (await db_session.execute(
        select(ReferralReward).where(ReferralReward.referred_id == invited["user_id"])
    )).scalars().all()
    assert {r.event for r in rewards} == {ReferralEvent.JOINING, ReferralEvent.FIRST_PURCHASE}

    await _reset_settings(client, admin)


async def test_first_purchase_reward_is_reversed_when_the_order_is_refunded(client, db_session, promote_role, mock_vivape):
    admin = await _super_admin(client, promote_role)
    await _set_settings(client, admin)

    referrer = await register_and_login(client, "refC")
    code = (await client.get("/api/v1/referrals/me", headers=referrer["headers"])).json()["code"]
    invited = await _register_with_code(client, code)
    await fund_wallet(db_session, invited["user_id"], Decimal("100"))
    product = await create_test_product(db_session, price=Decimal("10.00"))

    # Deliver, so the first-purchase reward is granted...
    ok = await client.post(
        "/api/v1/orders/checkout", json={"product_id": product.id, "payment_method": "WALLET"},
        headers=invited["headers"],
    )
    await wait_for_order(client, ok.json()["id"], invited["headers"])
    assert (await _balances(db_session, referrer["user_id"]))["REWARD"] == Decimal("5.0000")

    # ...then reverse that reward directly, as a refund of that order would.
    order_id = ok.json()["id"]
    from app.services import referral_svc
    reward = await referral_svc.reverse_for_order(db_session, order_id, "order refunded")
    await db_session.commit()
    assert reward is not None
    assert reward.status == ReferralRewardStatus.REVERSED
    # Back to the 2.00 joining reward only.
    assert (await _balances(db_session, referrer["user_id"]))["REWARD"] == Decimal("2.0000")

    await _reset_settings(client, admin)


async def test_reversal_takes_back_only_what_is_left_unspent(client, db_session, promote_role):
    """A reward already spent on an eSIM can't be clawed back into a negative
    balance - we recover what remains and no more."""
    admin = await _super_admin(client, promote_role)
    await _set_settings(client, admin)

    referrer = await register_and_login(client, "refD")
    code = (await client.get("/api/v1/referrals/me", headers=referrer["headers"])).json()["code"]
    invited = await _register_with_code(client, code)
    await fund_wallet(db_session, invited["user_id"], Decimal("50"))
    product = await create_test_product(db_session, price=Decimal("10.00"))

    delivered = await client.post(
        "/api/v1/orders/checkout", json={"product_id": product.id, "payment_method": "WALLET"},
        headers=invited["headers"],
    )
    await wait_for_order(client, delivered.json()["id"], invited["headers"])
    assert (await _balances(db_session, referrer["user_id"]))["REWARD"] == Decimal("5.0000")

    # The referrer spends 4.00 of their 5.00 promo credit (a 4.00 eSIM).
    cheap = await create_test_product(db_session, price=Decimal("4.00"))
    spent = await client.post(
        "/api/v1/orders/checkout", json={"product_id": cheap.id, "payment_method": "WALLET"},
        headers=referrer["headers"],
    )
    assert spent.status_code == 202, spent.text
    await wait_for_order(client, spent.json()["id"], referrer["headers"])
    assert (await _balances(db_session, referrer["user_id"]))["REWARD"] == Decimal("1.0000")

    from app.services import referral_svc
    await referral_svc.reverse_for_order(db_session, delivered.json()["id"], "order refunded")
    await db_session.commit()
    # Only the 1.00 still there could be recovered - never negative.
    assert (await _balances(db_session, referrer["user_id"]))["REWARD"] == Decimal("0.0000")

    await _reset_settings(client, admin)


async def test_promo_credit_buys_an_esim_and_is_spent_before_cash(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    await _set_settings(client, admin)

    referrer = await register_and_login(client, "refE")
    code = (await client.get("/api/v1/referrals/me", headers=referrer["headers"])).json()["code"]
    invited = await _register_with_code(client, code)  # gets 1.00 promo
    await fund_wallet(db_session, invited["user_id"], Decimal("20"))

    product = await create_test_product(db_session, price=Decimal("10.00"))
    res = await client.post(
        "/api/v1/orders/checkout", json={"product_id": product.id, "payment_method": "WALLET"},
        headers=invited["headers"],
    )
    assert res.status_code == 202, res.text
    await wait_for_order(client, res.json()["id"], invited["headers"])

    balances = await _balances(db_session, invited["user_id"])
    # The 1.00 promo went first, so only 9.00 came off the main wallet.
    assert balances["REWARD"] == Decimal("0.0000")
    assert balances["DEFAULT"] == Decimal("11.0000")

    order = (await db_session.execute(select(Order).where(Order.id == res.json()["id"]))).scalar_one()
    await db_session.refresh(order)
    assert Decimal(str(order.reward_amount_used)) == Decimal("1.0000")

    # Both legs are on the ledger, each against its own wallet.
    entries = (await db_session.execute(
        select(WalletLedgerEntry, Wallet.wallet_type)
        .join(Wallet, WalletLedgerEntry.wallet_id == Wallet.id)
        .where(WalletLedgerEntry.reference_id == order.id)
    )).all()
    by_wallet = {wallet_type: Decimal(str(e.amount)) for e, wallet_type in entries}
    assert by_wallet[WalletType.REWARD] == Decimal("1.0000")
    assert by_wallet[WalletType.DEFAULT] == Decimal("9.0000")

    await _reset_settings(client, admin)


async def test_an_order_can_be_paid_entirely_from_promo_credit(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    await _set_settings(client, admin, {
        "is_enabled": True,
        "events": {"JOINING": {"referrer": "0", "referred": "12.00", "enabled": True}},
        "max_rewarded_referrals": None,
    })

    referrer = await register_and_login(client, "refF")
    code = (await client.get("/api/v1/referrals/me", headers=referrer["headers"])).json()["code"]
    invited = await _register_with_code(client, code)  # 12.00 promo, no cash

    product = await create_test_product(db_session, price=Decimal("10.00"))
    res = await client.post(
        "/api/v1/orders/checkout", json={"product_id": product.id, "payment_method": "WALLET"},
        headers=invited["headers"],
    )
    assert res.status_code == 202, res.text
    settled = await wait_for_order(client, res.json()["id"], invited["headers"])
    assert settled["status"] == "COMPLETED"

    balances = await _balances(db_session, invited["user_id"])
    assert balances["REWARD"] == Decimal("2.0000")
    assert balances["DEFAULT"] == Decimal("0.0000")

    await _reset_settings(client, admin)


async def test_promo_credit_can_never_be_withdrawn(client, db_session, promote_role):
    """The load-bearing rule: promo credit spends on eSIMs but is not cash."""
    admin = await _super_admin(client, promote_role)
    await _set_settings(client, admin, {
        "is_enabled": True,
        "events": {"JOINING": {"referrer": "0", "referred": "30.00", "enabled": True}},
        "max_rewarded_referrals": None,
    })

    referrer = await register_and_login(client, "refG")
    code = (await client.get("/api/v1/referrals/me", headers=referrer["headers"])).json()["code"]
    invited = await _register_with_code(client, code)  # 30.00 promo, no cash

    # KYC + a payout account, so nothing else can be the reason it's refused.
    db_session.add(KYCSubmission(
        user_id=invited["user_id"], nid_number="1234567890",
        document_front_filename="front.png", status=KYCStatus.APPROVED,
    ))
    await db_session.commit()
    account = await client.post(
        "/api/v1/withdrawals/accounts",
        json={"account_type": "MOBILE", "bank_name": "bKash", "holder_name": "Test", "account_number": "01712345678"},
        headers=invited["headers"],
    )
    assert account.status_code == 200, account.text

    config = (await client.get("/api/v1/withdrawals/config", headers=invited["headers"])).json()
    # The withdrawal page counts only the main wallet, which is empty.
    assert Decimal(config["balance"]) == Decimal("0.0000")
    assert config["can_withdraw"] is False

    res = await client.post(
        "/api/v1/withdrawals",
        json={"amount": "10", "bank_account_id": account.json()["id"]},
        headers=invited["headers"],
    )
    assert res.status_code == 400
    assert "balance" in res.json()["detail"].lower()
    # The promo credit is untouched.
    assert (await _balances(db_session, invited["user_id"]))["REWARD"] == Decimal("30.0000")

    await _reset_settings(client, admin)


async def test_refunding_a_promo_funded_order_returns_promo_to_promo(client, db_session, promote_role, mock_vivape):
    """The leak this guards: refunding the whole amount to the main wallet
    would turn non-withdrawable credit into withdrawable cash."""
    admin = await _super_admin(client, promote_role)
    await _set_settings(client, admin, {
        "is_enabled": True,
        "events": {"JOINING": {"referrer": "0", "referred": "6.00", "enabled": True}},
        "max_rewarded_referrals": None,
    })

    referrer = await register_and_login(client, "refH")
    code = (await client.get("/api/v1/referrals/me", headers=referrer["headers"])).json()["code"]
    invited = await _register_with_code(client, code)  # 6.00 promo
    await fund_wallet(db_session, invited["user_id"], Decimal("10"))

    product = await create_test_product(db_session, price=Decimal("10.00"))
    mock_vivape.create_transaction.side_effect = Exception("VivaPe down")
    res = await client.post(
        "/api/v1/orders/checkout", json={"product_id": product.id, "payment_method": "WALLET"},
        headers=invited["headers"],
    )
    assert res.status_code == 202, res.text
    settled = await wait_for_order(client, res.json()["id"], invited["headers"])
    assert settled["status"] == "FAILED"

    # 6.00 promo + 4.00 cash paid, so 6.00 promo + 4.00 cash refunded.
    balances = await _balances(db_session, invited["user_id"])
    assert balances["REWARD"] == Decimal("6.0000")
    assert balances["DEFAULT"] == Decimal("10.0000")

    refunds = (await db_session.execute(
        select(WalletLedgerEntry, Wallet.wallet_type)
        .join(Wallet, WalletLedgerEntry.wallet_id == Wallet.id)
        .where(
            WalletLedgerEntry.reference_id == res.json()["id"],
            WalletLedgerEntry.reference_type == LedgerRefType.REFUND,
        )
    )).all()
    split = {wallet_type: Decimal(str(e.amount)) for e, wallet_type in refunds}
    assert split == {WalletType.REWARD: Decimal("6.0000"), WalletType.DEFAULT: Decimal("4.0000")}

    await _reset_settings(client, admin)


async def test_new_merchant_reward_on_approval(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    await _set_settings(client, admin)

    referrer = await register_and_login(client, "refI")
    code = (await client.get("/api/v1/referrals/me", headers=referrer["headers"])).json()["code"]
    invited = await _register_with_code(client, code)

    apply_res = await client.post(
        "/api/v1/auth/apply-merchant",
        json={"business_name": "Referred Travel", "contact_phone": "+8801700000000"},
        headers=invited["headers"],
    )
    assert apply_res.status_code == 200, apply_res.text

    profile = (await db_session.execute(
        select(MerchantProfile).where(MerchantProfile.user_id == invited["user_id"])
    )).scalar_one()
    approve = await client.post(f"/api/v1/admin/merchants/{profile.id}/approve", headers=admin["headers"])
    assert approve.status_code == 200, approve.text

    # 2.00 joining + 5.00 new partner.
    assert (await _balances(db_session, referrer["user_id"]))["REWARD"] == Decimal("7.0000")

    await _reset_settings(client, admin)


async def test_self_referral_is_refused(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    await _set_settings(client, admin)

    user = await register_and_login(client, "refself")
    code = (await client.get("/api/v1/referrals/me", headers=user["headers"])).json()["code"]

    res = await client.post("/api/v1/referrals/claim", json={"code": code}, headers=user["headers"])
    assert res.status_code == 400
    assert "yourself" in res.json()["detail"]
    assert (await _balances(db_session, user["user_id"])).get("REWARD", Decimal("0")) == Decimal("0.0000")

    await _reset_settings(client, admin)


async def test_claiming_a_code_after_signup_then_never_again(client, db_session, promote_role):
    """Google sign-up has nowhere to type a code, so it can be added later -
    but only before the first eSIM, and only once."""
    admin = await _super_admin(client, promote_role)
    await _set_settings(client, admin)

    referrer = await register_and_login(client, "refJ")
    code = (await client.get("/api/v1/referrals/me", headers=referrer["headers"])).json()["code"]
    late = await register_and_login(client, "reflate")

    claimed = await client.post("/api/v1/referrals/claim", json={"code": code}, headers=late["headers"])
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["referred_by"] == referrer["username"]
    assert (await _balances(db_session, late["user_id"]))["REWARD"] == Decimal("1.0000")
    assert (await _balances(db_session, referrer["user_id"]))["REWARD"] == Decimal("2.0000")

    second = await client.post("/api/v1/referrals/claim", json={"code": code}, headers=late["headers"])
    assert second.status_code == 400
    assert "already has a referrer" in second.json()["detail"]

    await _reset_settings(client, admin)


async def test_a_code_cannot_be_claimed_after_a_delivered_purchase(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    await _set_settings(client, admin)

    referrer = await register_and_login(client, "refK")
    code = (await client.get("/api/v1/referrals/me", headers=referrer["headers"])).json()["code"]
    established = await register_and_login(client, "refold")
    await fund_wallet(db_session, established["user_id"], Decimal("50"))

    product = await create_test_product(db_session, price=Decimal("10.00"))
    bought = await client.post(
        "/api/v1/orders/checkout", json={"product_id": product.id, "payment_method": "WALLET"},
        headers=established["headers"],
    )
    await wait_for_order(client, bought.json()["id"], established["headers"])

    res = await client.post("/api/v1/referrals/claim", json={"code": code}, headers=established["headers"])
    assert res.status_code == 400
    assert "before your first eSIM" in res.json()["detail"]

    await _reset_settings(client, admin)


async def test_referrer_cap_stops_farming_but_still_welcomes_the_newcomer(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    await _set_settings(client, admin, {
        "is_enabled": True,
        "events": {"JOINING": {"referrer": "2.00", "referred": "1.00", "enabled": True}},
        "max_rewarded_referrals": 1,
    })

    referrer = await register_and_login(client, "refL")
    code = (await client.get("/api/v1/referrals/me", headers=referrer["headers"])).json()["code"]

    first = await _register_with_code(client, code)
    second = await _register_with_code(client, code)

    # Referrer paid for the first only; both newcomers still got their credit.
    assert (await _balances(db_session, referrer["user_id"]))["REWARD"] == Decimal("2.0000")
    assert (await _balances(db_session, first["user_id"]))["REWARD"] == Decimal("1.0000")
    assert (await _balances(db_session, second["user_id"]))["REWARD"] == Decimal("1.0000")

    await _reset_settings(client, admin)


async def test_validate_endpoint_is_public_and_thin(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    await _set_settings(client, admin)

    referrer = await register_and_login(client, "refM")
    code = (await client.get("/api/v1/referrals/me", headers=referrer["headers"])).json()["code"]

    ok = await client.get(f"/api/v1/referrals/validate?code={code.lower()}")
    assert ok.status_code == 200, ok.text
    assert ok.json()["valid"] is True
    assert ok.json()["referrer_username"] == referrer["username"]
    assert Decimal(ok.json()["joining_reward"]) == Decimal("1.00")

    bad = await client.get("/api/v1/referrals/validate?code=NOPE1234")
    assert bad.status_code == 200
    assert bad.json()["valid"] is False
    assert "referrer_username" not in bad.json()

    await _reset_settings(client, admin)


async def test_settings_are_admin_gated(client, db_session, promote_role):
    user = await register_and_login(client, "refuser")
    assert (await client.get("/api/v1/admin/referral-settings", headers=user["headers"])).status_code == 403
    assert (await client.put(
        "/api/v1/admin/referral-settings", json=ALL_ON, headers=user["headers"]
    )).status_code == 403
    assert (await client.get("/api/v1/admin/referrals", headers=user["headers"])).status_code == 403

    # Plain admins can look but not change the amounts.
    plain = await register_and_login(client, "refplainadmin")
    await promote_role(plain["user_id"], "ADMIN")
    assert (await client.get("/api/v1/admin/referral-settings", headers=plain["headers"])).status_code == 200
    assert (await client.put(
        "/api/v1/admin/referral-settings", json=ALL_ON, headers=plain["headers"]
    )).status_code == 403


async def test_admin_report_and_finance_separate_promo_from_cash(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    await _set_settings(client, admin)

    referrer = await register_and_login(client, "refN")
    code = (await client.get("/api/v1/referrals/me", headers=referrer["headers"])).json()["code"]
    await _register_with_code(client, code)

    report = await client.get("/api/v1/admin/referrals", headers=admin["headers"])
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["totals"]["rewards"] >= 1
    assert Decimal(body["totals"]["promo_credit_outstanding"]) >= Decimal("3.00")
    assert any(l["username"] == referrer["username"] for l in body["leaders"])
    assert body["rewards"][0]["event"] in ("JOINING", "FIRST_PURCHASE", "NEW_MERCHANT")

    finance = (await client.get("/api/v1/admin/finance/summary", headers=admin["headers"])).json()
    liabilities = finance["liabilities"]
    assert Decimal(liabilities["promo_credit"]) >= Decimal("3.00")
    # Promo credit is a liability in eSIMs, not in cash.
    assert Decimal(liabilities["cash_owed"]) == Decimal(liabilities["total"]) - Decimal(liabilities["promo_credit"])
    assert Decimal(finance["wallets"]["reward_credit_granted"]) >= Decimal("3.00")

    await _reset_settings(client, admin)


async def test_reward_settings_reject_absurd_amounts(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    res = await client.put(
        "/api/v1/admin/referral-settings",
        json={
            "is_enabled": True,
            "events": {"JOINING": {"referrer": "50000", "referred": "0", "enabled": True}},
            "max_rewarded_referrals": None,
        },
        headers=admin["headers"],
    )
    assert res.status_code == 400
    assert "cannot exceed" in res.json()["detail"]
