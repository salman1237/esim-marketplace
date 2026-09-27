"""The agent's bonus: a slice of a merchant's commission, approved by an admin
and invisible to the merchant.

Two things are load-bearing here. The money must split correctly - the
merchant's share shrinks by exactly what the agent gains, and our margin is
untouched. And the merchant must never be able to discover it, from any
endpoint they can reach.
"""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.agent import AgentProfile
from app.models.agent_bonus import AgentBonusRequest, AgentBonusStatus
from app.models.kyc import KYCStatus, KYCSubmission
from app.models.merchant import MerchantProfile, MerchantStatus
from app.models.order import Order
from app.models.wallet import Wallet, WalletType
from conftest import create_test_product, fund_wallet, register_and_login, wait_for_order

pytestmark = pytest.mark.asyncio


async def _super_admin(client, promote_role, name="bonusadmin"):
    admin = await register_and_login(client, name)
    await promote_role(admin["user_id"], "SUPER_ADMIN")
    return admin


async def _approved_agent(client, db_session, admin, name="bonusagent", rate="2.00"):
    user = await register_and_login(client, name)
    await client.post(
        "/api/v1/agent/apply",
        json={"company_name": f"{name} Group", "contact_phone": "+8801700000000"},
        headers=user["headers"],
    )
    profile = (await db_session.execute(
        select(AgentProfile).where(AgentProfile.user_id == user["user_id"])
    )).scalar_one()
    approved = await client.post(f"/api/v1/admin/agents/{profile.id}/approve", headers=admin["headers"])
    user["profile_id"] = profile.id
    user["code"] = approved.json()["agent_code"]
    await client.put(
        f"/api/v1/admin/agents/{profile.id}/commission", json={"rate_pct": rate}, headers=admin["headers"]
    )
    return user


async def _merchant(client, db_session, promote_role, name="bonusmerchant", rate="20.00", agent_code=None):
    user = await register_and_login(client, name)
    await client.post(
        "/api/v1/auth/apply-merchant",
        json={
            "business_name": f"{name} Tours", "contact_phone": "+8801700000000",
            **({"agent_code": agent_code} if agent_code else {}),
        },
        headers=user["headers"],
    )
    profile = (await db_session.execute(
        select(MerchantProfile).where(MerchantProfile.user_id == user["user_id"])
    )).scalar_one()
    profile.status = MerchantStatus.APPROVED
    profile.commission_rate_pct = Decimal(rate)
    await db_session.commit()
    await promote_role(user["user_id"], "MERCHANT")
    user["profile_id"] = profile.id
    return user


async def _set_bonus(client, db_session, admin, agent, merchant, pct):
    """Agent requests, admin approves - the only path that changes the rate."""
    asked = await client.post(
        "/api/v1/agent/bonus-requests",
        json={"merchant_profile_id": merchant["profile_id"], "requested_pct": pct},
        headers=agent["headers"],
    )
    assert asked.status_code == 200, asked.text
    request_id = asked.json()["request"]["id"]
    approved = await client.post(
        f"/api/v1/admin/agent-bonus-requests/{request_id}/approve", headers=admin["headers"]
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


async def _sell(client, db_session, merchant, price="100.00"):
    product = await create_test_product(db_session, price=Decimal(price))
    customer = await register_and_login(client, "bonusbuyer")
    await fund_wallet(db_session, merchant["user_id"], Decimal("500"))
    res = await client.post(
        "/api/v1/orders/checkout",
        json={
            "product_id": product.id, "payment_method": "WALLET",
            "is_buy_for_user": True, "beneficiary_email": customer["email"],
        },
        headers=merchant["headers"],
    )
    assert res.status_code == 202, res.text
    await wait_for_order(client, res.json()["id"], merchant["headers"])
    return res.json()["id"]


async def _commission_balance(db_session, user_id) -> Decimal:
    wallet = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.COMMISSION)
    )).scalar_one_or_none()
    if not wallet:
        return Decimal("0")
    await db_session.refresh(wallet)
    return Decimal(str(wallet.balance))


async def test_nothing_changes_until_an_admin_approves(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "bonusa1")
    merchant = await _merchant(client, db_session, promote_role, "bonusm1", rate="20.00", agent_code=agent["code"])

    asked = await client.post(
        "/api/v1/agent/bonus-requests",
        json={"merchant_profile_id": merchant["profile_id"], "requested_pct": "10", "reason": "Volume deal"},
        headers=agent["headers"],
    )
    assert asked.status_code == 200, asked.text

    # Still on zero while the request waits.
    profile = (await db_session.execute(
        select(MerchantProfile).where(MerchantProfile.id == merchant["profile_id"])
    )).scalar_one()
    await db_session.refresh(profile)
    assert Decimal(str(profile.agent_bonus_pct)) == Decimal("0")

    order_id = await _sell(client, db_session, merchant, price="100.00")
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    await db_session.refresh(order)
    assert Decimal(str(order.reseller_commission_amount)) == Decimal("20.0000")
    assert Decimal(str(order.agent_bonus_amount)) == Decimal("0")

    # A second request for the same partner is refused while one is pending.
    again = await client.post(
        "/api/v1/agent/bonus-requests",
        json={"merchant_profile_id": merchant["profile_id"], "requested_pct": "5"},
        headers=agent["headers"],
    )
    assert again.status_code == 400
    assert "already a request waiting" in again.json()["detail"]


async def test_an_approved_bonus_moves_the_slice_from_merchant_to_agent(client, db_session, promote_role):
    """The client's own example: 20% merchant, 10% bonus, merchant keeps 10%."""
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "bonusa2", rate="2.00")
    merchant = await _merchant(client, db_session, promote_role, "bonusm2", rate="20.00", agent_code=agent["code"])

    decision = await _set_bonus(client, db_session, admin, agent, merchant, "10")
    assert decision["merchant_keeps_pct"] == "10.00"
    assert decision["zeroes_merchant"] is False

    order_id = await _sell(client, db_session, merchant, price="100.00")
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    await db_session.refresh(order)

    # Merchant: 20% - 10% = 10 on a 100 sale.
    assert Decimal(str(order.reseller_commission_amount)) == Decimal("10.0000")
    # Agent: their own 2% of the price, plus the 10% slice.
    assert Decimal(str(order.agent_commission_amount)) == Decimal("2.0000")
    assert Decimal(str(order.agent_bonus_amount)) == Decimal("10.0000")

    assert await _commission_balance(db_session, merchant["user_id"]) == Decimal("10.0000")
    assert await _commission_balance(db_session, agent["user_id"]) == Decimal("12.0000")


async def test_the_bonus_costs_us_nothing(client, db_session, promote_role):
    """What the merchant loses is exactly what the agent gains, so our own
    margin is identical with and without a bonus."""
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "bonusa3", rate="2.00")

    plain = await _merchant(client, db_session, promote_role, "bonusm3a", rate="20.00", agent_code=agent["code"])
    bonused = await _merchant(client, db_session, promote_role, "bonusm3b", rate="20.00", agent_code=agent["code"])
    await _set_bonus(client, db_session, admin, agent, bonused, "10")

    plain_order = (await db_session.execute(
        select(Order).where(Order.id == await _sell(client, db_session, plain, price="100.00"))
    )).scalar_one()
    bonus_order = (await db_session.execute(
        select(Order).where(Order.id == await _sell(client, db_session, bonused, price="100.00"))
    )).scalar_one()
    await db_session.refresh(plain_order)
    await db_session.refresh(bonus_order)

    def total_paid_out(o):
        return (Decimal(str(o.reseller_commission_amount)) + Decimal(str(o.agent_commission_amount))
                + Decimal(str(o.agent_bonus_amount)))

    assert total_paid_out(plain_order) == total_paid_out(bonus_order) == Decimal("22.0000")


async def test_a_bonus_can_zero_a_merchant_but_never_go_negative(client, db_session, promote_role):
    """Most merchants are on 5%, and the range allows 10% - so the cap matters."""
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "bonusa4", rate="2.00")
    merchant = await _merchant(client, db_session, promote_role, "bonusm4", rate="5.00", agent_code=agent["code"])

    decision = await _set_bonus(client, db_session, admin, agent, merchant, "10")
    # The admin is told plainly what approving does.
    assert decision["merchant_keeps_pct"] == "0.00"
    assert decision["zeroes_merchant"] is True

    order_id = await _sell(client, db_session, merchant, price="100.00")
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    await db_session.refresh(order)

    assert Decimal(str(order.reseller_commission_amount)) == Decimal("0")
    # Capped at the merchant's own 5%, not the requested 10%.
    assert Decimal(str(order.agent_bonus_amount)) == Decimal("5.0000")
    assert await _commission_balance(db_session, merchant["user_id"]) == Decimal("0")


async def test_the_merchant_is_never_shown_the_deduction(client, db_session, promote_role):
    """Business confidentiality, checked on every endpoint a merchant reaches."""
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "bonusa5", rate="2.00")
    merchant = await _merchant(client, db_session, promote_role, "bonusm5", rate="20.00", agent_code=agent["code"])
    await _set_bonus(client, db_session, admin, agent, merchant, "10")

    overview = await client.get("/api/v1/merchant/overview", headers=merchant["headers"])
    assert overview.status_code == 200, overview.text
    body = overview.json()
    commission = body["commission"]

    # One number, and it is the net one they are actually paid.
    assert Decimal(commission["effective_rate_pct"]) == Decimal("10.00")
    assert Decimal(commission["flat_rate_pct"]) == Decimal("10.00")

    # Neither the pre-deduction rate nor the bonus appears anywhere in the
    # payload. Checked on keys and values rather than a substring search,
    # because the test fixture's own business name contains "bonus".
    import json

    def leaks(payload) -> list:
        found = []

        def walk(node, path=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    if any(word in k.lower() for word in ("agent", "bonus", "gross")):
                        found.append(f"{path}.{k}")
                    walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")
            elif path.endswith("_pct") and str(node) in ("20", "20.0", "20.00"):
                found.append(f"{path}={node}")

        walk(payload)
        return found

    assert leaks(body) == [], f"merchant overview leaks: {leaks(body)}"

    order_id = await _sell(client, db_session, merchant, price="100.00")
    detail = (await client.get(f"/api/v1/merchant/orders/{order_id}", headers=merchant["headers"])).json()
    assert Decimal(detail["commission_earned"]) == Decimal("10.0000")
    assert leaks(detail) == [], f"merchant order detail leaks: {leaks(detail)}"

    # The ledger line names the net rate, not the rate an admin set.
    ledger = (await client.get("/api/v1/wallets/ledger?wallet_type=COMMISSION", headers=merchant["headers"])).json()
    earned = [e for e in ledger if e["reference_type"] == "COMMISSION_EARNED"]
    assert earned, "no commission entry"
    assert "10.00%" in earned[0]["description"]
    # The rate is the parenthesised part; the order number legitimately
    # contains "2026", so match the rate specifically.
    assert "(20" not in earned[0]["description"]


async def test_the_partner_api_reports_the_net_rate_too(client, db_session, promote_role):
    from app.models.partner_api import ApiKey
    from conftest import partner_auth_headers

    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "bonusa6", rate="2.00")
    merchant = await _merchant(client, db_session, promote_role, "bonusm6", rate="20.00", agent_code=agent["code"])
    await _set_bonus(client, db_session, admin, agent, merchant, "10")

    key_res = await client.post(
        f"/api/v1/admin/merchants/{merchant['profile_id']}/api-key", headers=admin["headers"]
    )
    assert key_res.status_code == 200, key_res.text
    headers = await partner_auth_headers(client, key_res.json()["api_key"])

    me = await client.get("/api/v1/partner/me", headers=headers)
    assert me.status_code == 200, me.text
    assert Decimal(str(me.json()["commission_rate_pct"])) == Decimal("10.00")


async def test_suspending_the_agent_hands_the_full_rate_back(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "bonusa7", rate="2.00")
    merchant = await _merchant(client, db_session, promote_role, "bonusm7", rate="20.00", agent_code=agent["code"])
    await _set_bonus(client, db_session, admin, agent, merchant, "10")

    await client.post(
        f"/api/v1/admin/agents/{agent['profile_id']}/reject?reason=Under+review", headers=admin["headers"]
    )

    order_id = await _sell(client, db_session, merchant, price="100.00")
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    await db_session.refresh(order)
    # No approved agent, so no deduction and no agent earnings.
    assert Decimal(str(order.reseller_commission_amount)) == Decimal("20.0000")
    assert Decimal(str(order.agent_bonus_amount)) == Decimal("0")
    assert Decimal(str(order.agent_commission_amount)) == Decimal("0")


async def test_agents_can_only_touch_their_own_partners(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    mine = await _approved_agent(client, db_session, admin, "bonusa8")
    other = await _approved_agent(client, db_session, admin, "bonusa9")
    merchant = await _merchant(client, db_session, promote_role, "bonusm8", rate="20.00", agent_code=mine["code"])

    res = await client.post(
        "/api/v1/agent/bonus-requests",
        json={"merchant_profile_id": merchant["profile_id"], "requested_pct": "10"},
        headers=other["headers"],
    )
    assert res.status_code == 400
    assert "isn't mapped to you" in res.json()["detail"]


async def test_the_bonus_range_is_enforced(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "bonusa10")
    merchant = await _merchant(client, db_session, promote_role, "bonusm9", rate="20.00", agent_code=agent["code"])

    too_high = await client.post(
        "/api/v1/agent/bonus-requests",
        json={"merchant_profile_id": merchant["profile_id"], "requested_pct": "15"},
        headers=agent["headers"],
    )
    assert too_high.status_code == 422

    negative = await client.post(
        "/api/v1/agent/bonus-requests",
        json={"merchant_profile_id": merchant["profile_id"], "requested_pct": "-1"},
        headers=agent["headers"],
    )
    assert negative.status_code == 422

    same = await client.post(
        "/api/v1/agent/bonus-requests",
        json={"merchant_profile_id": merchant["profile_id"], "requested_pct": "0"},
        headers=agent["headers"],
    )
    assert same.status_code == 400
    assert "already on" in same.json()["detail"]


async def test_a_rejected_request_changes_nothing(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "bonusa11")
    merchant = await _merchant(client, db_session, promote_role, "bonusm10", rate="20.00", agent_code=agent["code"])

    asked = await client.post(
        "/api/v1/agent/bonus-requests",
        json={"merchant_profile_id": merchant["profile_id"], "requested_pct": "10"},
        headers=agent["headers"],
    )
    request_id = asked.json()["request"]["id"]
    rejected = await client.post(
        f"/api/v1/admin/agent-bonus-requests/{request_id}/reject",
        json={"note": "Too steep for this partner"}, headers=admin["headers"],
    )
    assert rejected.status_code == 200, rejected.text

    profile = (await db_session.execute(
        select(MerchantProfile).where(MerchantProfile.id == merchant["profile_id"])
    )).scalar_one()
    await db_session.refresh(profile)
    assert Decimal(str(profile.agent_bonus_pct)) == Decimal("0")

    # And deciding twice is refused.
    assert (await client.post(
        f"/api/v1/admin/agent-bonus-requests/{request_id}/approve", headers=admin["headers"]
    )).status_code == 400

    mine = (await client.get("/api/v1/agent/bonus-requests", headers=agent["headers"])).json()
    row = next(r for r in mine if r["id"] == request_id)
    assert row["status"] == "REJECTED"
    assert row["decision_note"] == "Too steep for this partner"
    # The agent sees the decision but not the partner's underlying rate.
    assert "merchant_rate_pct" not in row


async def test_the_admin_queue_shows_what_approving_would_do(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "bonusa12")
    merchant = await _merchant(client, db_session, promote_role, "bonusm11", rate="5.00", agent_code=agent["code"])
    await client.post(
        "/api/v1/agent/bonus-requests",
        json={"merchant_profile_id": merchant["profile_id"], "requested_pct": "10"},
        headers=agent["headers"],
    )

    queue = (await client.get("/api/v1/admin/agent-bonus-requests?status=PENDING", headers=admin["headers"])).json()
    row = next(r for r in queue if r["merchant_profile_id"] == merchant["profile_id"])
    assert row["merchant_rate_pct"] == "5.00"
    assert row["requested_pct"] == "10.00"
    assert row["resulting_merchant_pct"] == "0.00"
    assert row["zeroes_merchant"] is True
    assert row["agent"] == agent["username"]

    user = await register_and_login(client, "bonusnobody")
    assert (await client.get("/api/v1/admin/agent-bonus-requests", headers=user["headers"])).status_code == 403


async def test_the_agent_invite_link_carries_their_code(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "bonusa13")
    overview = (await client.get("/api/v1/agent/overview", headers=agent["headers"])).json()
    assert overview["agent"]["invite_url"].endswith(f"/reseller?agent={agent['code']}")
    assert overview["agent"]["max_bonus_pct"] == "10.00"


async def test_admin_can_send_a_user_back_through_kyc(client, db_session, promote_role):
    """And it must actually block withdrawals, or it means nothing."""
    admin = await _super_admin(client, promote_role)
    user = await register_and_login(client, "kycagain")
    db_session.add(KYCSubmission(
        user_id=user["user_id"], nid_number="1234567890",
        document_front_filename="front.png", status=KYCStatus.APPROVED,
    ))
    await fund_wallet(db_session, user["user_id"], Decimal("100"))
    await db_session.commit()

    account = await client.post(
        "/api/v1/withdrawals/accounts",
        json={"account_type": "MOBILE", "bank_name": "bKash", "holder_name": "Test", "account_number": "01712345678"},
        headers=user["headers"],
    )
    assert (await client.get("/api/v1/withdrawals/config", headers=user["headers"])).json()["can_withdraw"] is True

    res = await client.post(
        "/api/v1/admin/kyc/request-reverification",
        json={"user_id": user["user_id"], "reason": "Document expired"},
        headers=admin["headers"],
    )
    assert res.status_code == 200, res.text

    config = (await client.get("/api/v1/withdrawals/config", headers=user["headers"])).json()
    assert config["can_withdraw"] is False
    assert config["kyc_verified"] is False

    blocked = await client.post(
        "/api/v1/withdrawals",
        json={"amount": "20", "bank_account_id": account.json()["id"]},
        headers=user["headers"],
    )
    assert blocked.status_code == 400
    assert "kyc" in blocked.json()["detail"].lower()

    # The customer sees why, on the screen they already know.
    mine = (await client.get("/api/v1/kyc/me", headers=user["headers"])).json()
    assert mine["status"] == "REJECTED"
    assert mine["rejection_reason"] == "Document expired"

    # Resubmitting puts them back in the queue as normal.
    import io as _io
    resubmit = await client.post(
        "/api/v1/kyc/submit",
        data={"nid_number": "1234567890"},
        files={"document_front": ("id.png", _io.BytesIO(b"\x89PNG\r\n\x1a\nfake"), "image/png")},
        headers=user["headers"],
    )
    assert resubmit.status_code == 200, resubmit.text
    assert (await client.get("/api/v1/kyc/me", headers=user["headers"])).json()["status"] == "PENDING"


async def test_kyc_reverification_is_admin_only(client, db_session, promote_role):
    victim = await register_and_login(client, "kycvictim")
    attacker = await register_and_login(client, "kycattacker")
    res = await client.post(
        "/api/v1/admin/kyc/request-reverification",
        json={"user_id": victim["user_id"], "reason": "nope"},
        headers=attacker["headers"],
    )
    assert res.status_code == 403
