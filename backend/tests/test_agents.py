"""Agents: the merchant mapping, commission on top of the merchant's, and the
margin arithmetic that warns when the two rates cost more than a sale earns.

The two things most worth guarding: a refunded sale pays neither party, and
moving a merchant to another agent never rewrites who was paid for past sales.
"""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.agent import AgentProfile, AgentStatus
from app.models.merchant import MerchantProfile, MerchantStatus
from app.models.order import Order, OrderStatus
from app.models.user import UserRole
from app.models.wallet import LedgerRefType, Wallet, WalletLedgerEntry, WalletType
from conftest import create_test_product, fund_wallet, register_and_login, wait_for_order

pytestmark = pytest.mark.asyncio


async def _super_admin(client, promote_role, name="agadmin"):
    admin = await register_and_login(client, name)
    await promote_role(admin["user_id"], "SUPER_ADMIN")
    return admin


async def _wallet_balance(db_session, user_id: str, wallet_type=WalletType.COMMISSION) -> Decimal:
    wallet = (await db_session.execute(
        select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == wallet_type)
    )).scalar_one_or_none()
    if not wallet:
        return Decimal("0")
    await db_session.refresh(wallet)
    return Decimal(str(wallet.balance))


async def _approved_agent(client, db_session, admin, name="agent", rate: str | None = None):
    """An applied-for, admin-approved agent. Returns the login dict plus code."""
    user = await register_and_login(client, name)
    applied = await client.post(
        "/api/v1/agent/apply",
        json={"company_name": f"{name} Travel Group", "contact_phone": "+8801700000000"},
        headers=user["headers"],
    )
    assert applied.status_code == 200, applied.text

    profile = (await db_session.execute(
        select(AgentProfile).where(AgentProfile.user_id == user["user_id"])
    )).scalar_one()
    approve = await client.post(f"/api/v1/admin/agents/{profile.id}/approve", headers=admin["headers"])
    assert approve.status_code == 200, approve.text
    user["profile_id"] = profile.id
    user["code"] = approve.json()["agent_code"]

    if rate is not None:
        res = await client.put(
            f"/api/v1/admin/agents/{profile.id}/commission",
            json={"rate_pct": rate}, headers=admin["headers"],
        )
        assert res.status_code == 200, res.text
    return user


async def _merchant(client, db_session, promote_role, name="agmerchant", rate="5.00", agent_code=None):
    user = await register_and_login(client, name)
    applied = await client.post(
        "/api/v1/auth/apply-merchant",
        json={
            "business_name": f"{name} Tours", "contact_phone": "+8801700000000",
            **({"agent_code": agent_code} if agent_code else {}),
        },
        headers=user["headers"],
    )
    assert applied.status_code == 200, applied.text

    profile = (await db_session.execute(
        select(MerchantProfile).where(MerchantProfile.user_id == user["user_id"])
    )).scalar_one()
    profile.status = MerchantStatus.APPROVED
    profile.commission_rate_pct = Decimal(rate)
    await db_session.commit()
    await promote_role(user["user_id"], "MERCHANT")
    user["profile_id"] = profile.id
    user["applied"] = applied.json()
    return user


async def _sell(client, db_session, merchant, price="20.00"):
    """The merchant sells one eSIM to a customer, delivered."""
    product = await create_test_product(db_session, price=Decimal(price))
    customer = await register_and_login(client, "agbuyer")
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
    settled = await wait_for_order(client, res.json()["id"], merchant["headers"])
    return res.json()["id"], settled


async def test_apply_then_approve_grants_a_code_and_the_portal(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    user = await register_and_login(client, "agnew")

    before = await client.get("/api/v1/agent/status", headers=user["headers"])
    assert before.json() == {
        "is_agent": False, "status": None, "rejection_reason": None, "agent_code": None,
        "commission_rate_pct": "2.00", "can_apply": True,
    }
    # No portal access before approval.
    assert (await client.get("/api/v1/agent/overview", headers=user["headers"])).status_code == 403

    await client.post(
        "/api/v1/agent/apply",
        json={"company_name": "New Agent Co", "contact_phone": "+8801700000000"},
        headers=user["headers"],
    )
    pending = await client.get("/api/v1/agent/status", headers=user["headers"])
    assert pending.json()["status"] == "PENDING"
    assert pending.json()["is_agent"] is False
    assert (await client.get("/api/v1/agent/overview", headers=user["headers"])).status_code == 403

    profile = (await db_session.execute(
        select(AgentProfile).where(AgentProfile.user_id == user["user_id"])
    )).scalar_one()
    approved = await client.post(f"/api/v1/admin/agents/{profile.id}/approve", headers=admin["headers"])
    assert approved.status_code == 200, approved.text
    assert approved.json()["agent_code"].startswith("AG")

    after = await client.get("/api/v1/agent/status", headers=user["headers"])
    assert after.json()["is_agent"] is True
    # The client's default rate.
    assert after.json()["commission_rate_pct"] == "2.00"

    overview = await client.get("/api/v1/agent/overview", headers=user["headers"])
    assert overview.status_code == 200, overview.text
    assert overview.json()["merchants"] == 0

    # A plain user who is only an agent becomes AGENT; a commission wallet exists.
    from app.models.user import User
    refreshed = (await db_session.execute(select(User).where(User.id == user["user_id"]))).scalar_one()
    await db_session.refresh(refreshed)
    assert refreshed.role == UserRole.AGENT
    assert await _wallet_balance(db_session, user["user_id"]) == Decimal("0")


async def test_agent_code_on_the_b2b_application_maps_the_partner(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "agentmap")
    merchant = await _merchant(client, db_session, promote_role, "mappedmerchant", agent_code=agent["code"])

    assert merchant["applied"]["agent"] == "agentmap Travel Group"
    profile = (await db_session.execute(
        select(MerchantProfile).where(MerchantProfile.id == merchant["profile_id"])
    )).scalar_one()
    await db_session.refresh(profile)
    assert profile.agent_id == agent["user_id"]

    mine = await client.get("/api/v1/agent/merchants", headers=agent["headers"])
    assert mine.status_code == 200, mine.text
    assert [m["business_name"] for m in mine.json()] == ["mappedmerchant Tours"]


async def test_an_unknown_agent_code_never_blocks_the_application(client, db_session, promote_role):
    merchant = await _merchant(client, db_session, promote_role, "nocodemerchant", agent_code="AGZZZZZZ")
    assert merchant["applied"]["agent"] is None
    profile = (await db_session.execute(
        select(MerchantProfile).where(MerchantProfile.id == merchant["profile_id"])
    )).scalar_one()
    assert profile.agent_id is None


async def test_agent_earns_on_top_of_the_merchant_commission(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "agenttop", rate="2.00")
    merchant = await _merchant(client, db_session, promote_role, "topmerchant", rate="5.00", agent_code=agent["code"])

    order_id, settled = await _sell(client, db_session, merchant, price="20.00")
    assert settled["status"] == "COMPLETED"

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    await db_session.refresh(order)
    # 5% merchant + 2% agent, both of the 20.00 sale price.
    assert Decimal(str(order.reseller_commission_amount)) == Decimal("1.0000")
    assert Decimal(str(order.agent_commission_amount)) == Decimal("0.4000")
    assert order.agent_id == agent["user_id"]

    assert await _wallet_balance(db_session, merchant["user_id"]) == Decimal("1.0000")
    assert await _wallet_balance(db_session, agent["user_id"]) == Decimal("0.4000")

    entry = (await db_session.execute(
        select(WalletLedgerEntry).where(
            WalletLedgerEntry.reference_id == order_id,
            WalletLedgerEntry.reference_type == LedgerRefType.AGENT_COMMISSION_EARNED,
        )
    )).scalar_one()
    assert Decimal(str(entry.amount)) == Decimal("0.4000")


async def test_a_refunded_sale_pays_neither_party(client, db_session, promote_role, mock_vivape):
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "agentrefund", rate="2.00")
    merchant = await _merchant(client, db_session, promote_role, "refundmerchant", rate="5.00", agent_code=agent["code"])

    mock_vivape.create_transaction.side_effect = Exception("VivaPe down")
    order_id, settled = await _sell(client, db_session, merchant, price="20.00")
    assert settled["status"] == "FAILED"

    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    await db_session.refresh(order)
    assert Decimal(str(order.agent_commission_amount)) == Decimal("0")
    assert order.agent_id is None
    assert await _wallet_balance(db_session, agent["user_id"]) == Decimal("0")
    assert await _wallet_balance(db_session, merchant["user_id"]) == Decimal("0")


async def test_a_suspended_agent_stops_earning_but_keeps_what_they_earned(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "agentsusp", rate="2.00")
    merchant = await _merchant(client, db_session, promote_role, "suspmerchant", rate="5.00", agent_code=agent["code"])

    await _sell(client, db_session, merchant, price="20.00")
    assert await _wallet_balance(db_session, agent["user_id"]) == Decimal("0.4000")

    suspended = await client.post(
        f"/api/v1/admin/agents/{agent['profile_id']}/reject?reason=Under+review", headers=admin["headers"]
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["agent_status"] == "SUSPENDED"

    # The portal closes...
    assert (await client.get("/api/v1/agent/overview", headers=agent["headers"])).status_code == 403
    # ...the next sale pays them nothing...
    order_id, _ = await _sell(client, db_session, merchant, price="20.00")
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    await db_session.refresh(order)
    assert Decimal(str(order.agent_commission_amount)) == Decimal("0")
    # ...but the merchant still earns, and the agent keeps the earlier 0.40.
    assert Decimal(str(order.reseller_commission_amount)) == Decimal("1.0000")
    assert await _wallet_balance(db_session, agent["user_id"]) == Decimal("0.4000")


async def test_moving_a_merchant_to_another_agent_leaves_past_sales_alone(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    first = await _approved_agent(client, db_session, admin, "agentfirst", rate="2.00")
    second = await _approved_agent(client, db_session, admin, "agentsecond", rate="3.00")
    merchant = await _merchant(client, db_session, promote_role, "movedmerchant", rate="5.00", agent_code=first["code"])

    old_order_id, _ = await _sell(client, db_session, merchant, price="20.00")

    moved = await client.put(
        f"/api/v1/admin/merchants/{merchant['profile_id']}/agent",
        json={"agent_code": second["code"]}, headers=admin["headers"],
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["agent_user_id"] == second["user_id"]

    new_order_id, _ = await _sell(client, db_session, merchant, price="20.00")

    old_order = (await db_session.execute(select(Order).where(Order.id == old_order_id))).scalar_one()
    new_order = (await db_session.execute(select(Order).where(Order.id == new_order_id))).scalar_one()
    await db_session.refresh(old_order)
    await db_session.refresh(new_order)

    # The old sale still belongs to the first agent at their rate.
    assert old_order.agent_id == first["user_id"]
    assert Decimal(str(old_order.agent_commission_amount)) == Decimal("0.4000")
    # The new one to the second, at theirs.
    assert new_order.agent_id == second["user_id"]
    assert Decimal(str(new_order.agent_commission_amount)) == Decimal("0.6000")

    assert await _wallet_balance(db_session, first["user_id"]) == Decimal("0.4000")
    assert await _wallet_balance(db_session, second["user_id"]) == Decimal("0.6000")


async def test_admin_can_clear_the_mapping(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "agentclear", rate="2.00")
    merchant = await _merchant(client, db_session, promote_role, "clearmerchant", rate="5.00", agent_code=agent["code"])

    cleared = await client.put(
        f"/api/v1/admin/merchants/{merchant['profile_id']}/agent", json={}, headers=admin["headers"]
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["agent_user_id"] is None

    order_id, _ = await _sell(client, db_session, merchant, price="20.00")
    order = (await db_session.execute(select(Order).where(Order.id == order_id))).scalar_one()
    await db_session.refresh(order)
    assert Decimal(str(order.agent_commission_amount)) == Decimal("0")
    assert Decimal(str(order.reseller_commission_amount)) == Decimal("1.0000")


async def test_an_agent_can_claim_an_unassigned_partner_but_not_take_one(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    claimer = await _approved_agent(client, db_session, admin, "agentclaim", rate="2.00")
    rival = await _approved_agent(client, db_session, admin, "agentrival", rate="2.00")

    free = await _merchant(client, db_session, promote_role, "freemerchant", rate="5.00")
    taken = await _merchant(client, db_session, promote_role, "takenmerchant", rate="5.00", agent_code=rival["code"])

    ok = await client.post(
        "/api/v1/agent/merchants", json={"merchant": free["email"]}, headers=claimer["headers"]
    )
    assert ok.status_code == 200, ok.text
    assert "freemerchant Tours" in ok.json()["message"]

    again = await client.post(
        "/api/v1/agent/merchants", json={"merchant": free["username"]}, headers=claimer["headers"]
    )
    assert again.status_code == 400
    assert "already one of yours" in again.json()["detail"]

    steal = await client.post(
        "/api/v1/agent/merchants", json={"merchant": taken["email"]}, headers=claimer["headers"]
    )
    assert steal.status_code == 400
    assert "already has an agent" in steal.json()["detail"]

    missing = await client.post(
        "/api/v1/agent/merchants", json={"merchant": "nobody@example.com"}, headers=claimer["headers"]
    )
    assert missing.status_code == 404

    # The claim is on the audit log, so an admin can see who took what.
    from app.models.audit import AuditLog
    logged = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == "AGENT_CLAIMED_MERCHANT", AuditLog.actor_id == claimer["user_id"])
    )).scalars().all()
    assert len(logged) == 1
    assert logged[0].after_state["business_name"] == "freemerchant Tours"


async def test_an_agent_can_also_be_a_merchant(client, db_session, promote_role):
    """The client's rule. Role stays MERCHANT; the portal opens on the profile."""
    admin = await _super_admin(client, promote_role)
    both = await _merchant(client, db_session, promote_role, "bothroles", rate="5.00")

    applied = await client.post(
        "/api/v1/agent/apply",
        json={"company_name": "Both Roles Ltd", "contact_phone": "+8801700000000"},
        headers=both["headers"],
    )
    assert applied.status_code == 200, applied.text
    profile = (await db_session.execute(
        select(AgentProfile).where(AgentProfile.user_id == both["user_id"])
    )).scalar_one()
    await client.post(f"/api/v1/admin/agents/{profile.id}/approve", headers=admin["headers"])

    from app.models.user import User
    refreshed = (await db_session.execute(select(User).where(User.id == both["user_id"]))).scalar_one()
    await db_session.refresh(refreshed)
    assert refreshed.role == UserRole.MERCHANT  # not downgraded to AGENT

    # Both portals answer.
    assert (await client.get("/api/v1/agent/overview", headers=both["headers"])).status_code == 200
    assert (await client.get("/api/v1/merchant/overview", headers=both["headers"])).status_code == 200


async def test_an_agent_cannot_be_their_own_agent(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    both = await _merchant(client, db_session, promote_role, "selfagent", rate="5.00")
    applied = await client.post(
        "/api/v1/agent/apply",
        json={"company_name": "Self Agent Ltd", "contact_phone": "+8801700000000"},
        headers=both["headers"],
    )
    assert applied.status_code == 200
    profile = (await db_session.execute(
        select(AgentProfile).where(AgentProfile.user_id == both["user_id"])
    )).scalar_one()
    approved = await client.post(f"/api/v1/admin/agents/{profile.id}/approve", headers=admin["headers"])

    res = await client.put(
        f"/api/v1/admin/merchants/{both['profile_id']}/agent",
        json={"agent_code": approved.json()["agent_code"]}, headers=admin["headers"],
    )
    assert res.status_code == 400
    assert "their own agent" in res.json()["detail"]

    claim = await client.post(
        "/api/v1/agent/merchants", json={"merchant": both["email"]}, headers=both["headers"]
    )
    assert claim.status_code == 400
    assert "your own partner account" in claim.json()["detail"]


async def test_margin_check_warns_when_the_pair_costs_more_than_the_sale_earns(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)

    # The selling profit % is a markup on cost, so the margin as a share of the
    # selling price is profit/(100+profit).
    pricing = (await client.get("/api/v1/admin/pricing", headers=admin["headers"])).json()
    profit_pct = Decimal(str(pricing["selling_profit_pct"]))
    expected_margin = (profit_pct / (Decimal("100") + profit_pct) * Decimal("100")).quantize(Decimal("0.01"))

    fine = (await client.get(
        "/api/v1/admin/agents/margin-check?merchant_pct=5&agent_pct=2", headers=admin["headers"]
    )).json()
    assert Decimal(fine["margin_pct_of_price"]) == expected_margin
    assert Decimal(fine["combined_pct"]) == Decimal("7.00")
    assert fine["exceeds_margin"] is False
    assert fine["warning"] is None

    too_much = (await client.get(
        "/api/v1/admin/agents/margin-check?merchant_pct=40&agent_pct=30", headers=admin["headers"]
    )).json()
    assert too_much["exceeds_margin"] is True
    assert "lose money" in too_much["warning"]


async def test_setting_a_rate_returns_the_margin_but_still_saves(client, db_session, promote_role):
    """The rate is the admin's call - the warning informs, it doesn't block."""
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "agentrate")
    merchant = await _merchant(client, db_session, promote_role, "ratemerchant", rate="40.00", agent_code=agent["code"])

    res = await client.put(
        f"/api/v1/admin/agents/{agent['profile_id']}/commission",
        json={"rate_pct": "30.00"}, headers=admin["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["rate_pct"] == "30.00"
    assert res.json()["margin"]["exceeds_margin"] is True

    profile = (await db_session.execute(
        select(AgentProfile).where(AgentProfile.id == agent["profile_id"])
    )).scalar_one()
    await db_session.refresh(profile)
    assert Decimal(str(profile.commission_rate_pct)) == Decimal("30.00")

    over_limit = await client.put(
        f"/api/v1/admin/agents/{agent['profile_id']}/commission",
        json={"rate_pct": "80.00"}, headers=admin["headers"],
    )
    assert over_limit.status_code == 422


async def test_agent_portal_reports_sales_and_a_statement(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "agentreport", rate="2.00")
    merchant = await _merchant(client, db_session, promote_role, "reportmerchant", rate="5.00", agent_code=agent["code"])
    await _sell(client, db_session, merchant, price="20.00")

    overview = (await client.get("/api/v1/agent/overview", headers=agent["headers"])).json()
    assert overview["merchants"] == 1
    assert overview["sales"]["orders"] == 1
    assert Decimal(overview["sales"]["commission"]) == Decimal("0.4000")
    assert Decimal(overview["this_month"]["commission"]) == Decimal("0.4000")
    assert Decimal(overview["wallets"]["commission_balance"]) == Decimal("0.4000")

    orders = (await client.get("/api/v1/agent/orders", headers=agent["headers"])).json()
    assert orders["total"] == 1
    row = orders["rows"][0]
    assert row["merchant"] == merchant["username"]
    assert Decimal(row["my_commission"]) == Decimal("0.4000")
    assert Decimal(row["merchant_commission"]) == Decimal("1.0000")

    merchants = (await client.get("/api/v1/agent/merchants", headers=agent["headers"])).json()
    assert merchants[0]["orders"] == 1
    assert Decimal(merchants[0]["my_commission"]) == Decimal("0.4000")

    ledger = (await client.get("/api/v1/agent/commission-ledger", headers=agent["headers"])).json()
    assert Decimal(ledger["balance"]) == Decimal("0.4000")
    assert ledger["entries"][0]["reference_type"] == "AGENT_COMMISSION_EARNED"

    statement = await client.get("/api/v1/agent/statement", headers=agent["headers"])
    assert statement.status_code == 200, statement.text
    csv_res = await client.get("/api/v1/agent/statement.csv", headers=agent["headers"])
    assert csv_res.status_code == 200
    assert "attachment" in csv_res.headers["content-disposition"]


async def test_agent_cashes_out_through_the_main_wallet(client, db_session, promote_role):
    """Commission moves to the main wallet, which is what the Phase 1
    withdrawal flow pays out from."""
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "agentcash", rate="2.00")
    merchant = await _merchant(client, db_session, promote_role, "cashmerchant", rate="5.00", agent_code=agent["code"])
    await _sell(client, db_session, merchant, price="20.00")

    moved = await client.post("/api/v1/agent/commission/transfer", headers=agent["headers"])
    assert moved.status_code == 200, moved.text
    assert Decimal(moved.json()["transferred"]) == Decimal("0.4000")

    assert await _wallet_balance(db_session, agent["user_id"]) == Decimal("0")
    assert await _wallet_balance(db_session, agent["user_id"], WalletType.DEFAULT) == Decimal("0.4000")

    empty = await client.post("/api/v1/agent/commission/transfer", headers=agent["headers"])
    assert empty.status_code == 400


async def test_the_merchant_queue_shows_who_the_agent_is(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "agentqueue", rate="2.50")
    merchant = await _merchant(client, db_session, promote_role, "queuemerchant", rate="5.00", agent_code=agent["code"])

    queue = (await client.get("/api/v1/admin/merchants/queue", headers=admin["headers"])).json()
    row = next(m for m in queue if m["id"] == merchant["profile_id"])
    assert row["agent"]["username"] == agent["username"]
    assert row["agent"]["agent_code"] == agent["code"]
    assert row["agent"]["commission_rate_pct"] == 2.5

    unmapped = next((m for m in queue if m["agent"] is None), None)
    assert unmapped is not None  # other merchants in this suite have no agent


async def test_agent_endpoints_are_gated(client, db_session, promote_role):
    user = await register_and_login(client, "agplain")
    for path in ("/api/v1/agent/overview", "/api/v1/agent/merchants", "/api/v1/agent/orders"):
        assert (await client.get(path, headers=user["headers"])).status_code == 403

    assert (await client.get("/api/v1/admin/agents", headers=user["headers"])).status_code == 403
    assert (await client.get("/api/v1/admin/agents/margin-check", headers=user["headers"])).status_code == 403

    # A plain admin reviews agents but doesn't set rates.
    plain = await register_and_login(client, "agplainadmin")
    await promote_role(plain["user_id"], "ADMIN")
    assert (await client.get("/api/v1/admin/agents", headers=plain["headers"])).status_code == 200
    admin = await _super_admin(client, promote_role, "agrategate")
    agent = await _approved_agent(client, db_session, admin, "agentgate")
    assert (await client.put(
        f"/api/v1/admin/agents/{agent['profile_id']}/commission",
        json={"rate_pct": "3.00"}, headers=plain["headers"],
    )).status_code == 403


async def test_staff_accounts_cannot_be_agents(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role, "agstaff")
    res = await client.post(
        "/api/v1/agent/apply",
        json={"company_name": "Admin Agency", "contact_phone": "+8801700000000"},
        headers=admin["headers"],
    )
    assert res.status_code == 400
    assert "Staff accounts" in res.json()["detail"]


async def test_applying_twice_is_refused(client, db_session, promote_role):
    user = await register_and_login(client, "agtwice")
    body = {"company_name": "Twice Ltd", "contact_phone": "+8801700000000"}
    assert (await client.post("/api/v1/agent/apply", json=body, headers=user["headers"])).status_code == 200
    second = await client.post("/api/v1/agent/apply", json=body, headers=user["headers"])
    assert second.status_code == 400
    assert "already applied" in second.json()["detail"]


async def test_admin_agent_list_carries_earnings(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    agent = await _approved_agent(client, db_session, admin, "agentlist", rate="2.00")
    merchant = await _merchant(client, db_session, promote_role, "listmerchant", rate="5.00", agent_code=agent["code"])
    await _sell(client, db_session, merchant, price="20.00")

    listed = (await client.get("/api/v1/admin/agents", headers=admin["headers"])).json()
    row = next(a for a in listed if a["id"] == agent["profile_id"])
    assert row["merchants"] == 1
    assert row["orders"] == 1
    assert Decimal(row["commission_earned"]) == Decimal("0.40")
    assert row["status"] == "APPROVED"

    pending_only = (await client.get("/api/v1/admin/agents?status=PENDING", headers=admin["headers"])).json()
    assert all(a["status"] == "PENDING" for a in pending_only)
