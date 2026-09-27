"""Automatic notification emails.

Two things matter: the right people get told, and the platform's system
mailbox gets a copy of everything monetary. The third - that a notification
can never break the thing it is reporting on - is tested by making the mailer
throw and checking the operation still succeeds.
"""
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.agent import AgentProfile
from app.models.merchant import MerchantProfile, MerchantStatus
from conftest import create_test_product, fund_wallet, register_and_login, wait_for_order

pytestmark = pytest.mark.asyncio

SYSTEM = "system@triptel.co"


class Mailbox:
    """Captures every notice instead of sending it."""

    def __init__(self):
        self.sent = []

    async def __call__(self, db, to_email, *, subject, title, intro, **kwargs):
        self.sent.append({"to": to_email, "subject": subject, "title": title, "intro": intro, **kwargs})

    def to(self, address):
        return [m for m in self.sent if m["to"] == address]

    def subjects(self, address=None):
        return [m["subject"] for m in self.sent if address is None or m["to"] == address]


def mailbox():
    """Patches the notice sender and drains the background tasks it spawns."""
    import app.services.notify_svc as svc
    box = Mailbox()
    return box, patch.object(svc, "send_notice", _capture(box))


def _capture(box: Mailbox):
    async def _send(db, *, to, subject, title, intro, rows=None, system_intro=None, copy_system=True, **kwargs):
        # Mirrors the real routing: the recipient, then the system copy.
        if to:
            await box(db, to, subject=subject, title=title, intro=intro, rows=rows)
        if copy_system:
            system_email = await _system_email(db)
            if not to or system_email.lower() != to.lower():
                await box(db, system_email, subject=f"[Triptel] {subject}", title=title,
                          intro=system_intro or intro, rows=rows)
    return AsyncMock(side_effect=_send)


async def _system_email(db):
    from app.services.notify_svc import get_system_email
    return await get_system_email(db)


async def _drain():
    """Notices are fire-and-forget tasks; let them run before asserting."""
    import asyncio
    for _ in range(6):
        await asyncio.sleep(0.02)


async def _super_admin(client, promote_role, name="notifyadmin"):
    admin = await register_and_login(client, name)
    await promote_role(admin["user_id"], "SUPER_ADMIN")
    return admin


async def test_the_system_mailbox_defaults_to_the_agreed_address(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role)
    res = await client.get("/api/v1/admin/notification-settings", headers=admin["headers"])
    assert res.status_code == 200, res.text
    assert res.json()["system_notice_email"] == SYSTEM
    assert res.json()["default"] == SYSTEM


async def test_the_system_mailbox_is_editable_and_gated(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role, "notifyadmin2")
    ok = await client.put(
        "/api/v1/admin/notification-settings",
        json={"system_notice_email": "finance@triptel.co"}, headers=admin["headers"],
    )
    assert ok.status_code == 200, ok.text
    assert (await client.get(
        "/api/v1/admin/notification-settings", headers=admin["headers"]
    )).json()["system_notice_email"] == "finance@triptel.co"

    bad = await client.put(
        "/api/v1/admin/notification-settings",
        json={"system_notice_email": "not-an-email"}, headers=admin["headers"],
    )
    assert bad.status_code == 422

    user = await register_and_login(client, "notifyuser")
    assert (await client.put(
        "/api/v1/admin/notification-settings",
        json={"system_notice_email": "x@y.co"}, headers=user["headers"],
    )).status_code == 403

    # Put it back for the rest of the session.
    await client.put(
        "/api/v1/admin/notification-settings",
        json={"system_notice_email": SYSTEM}, headers=admin["headers"],
    )
    # It must never leak into the public settings payload.
    public = (await client.get("/api/v1/settings/public")).json()
    assert "system_notice_email" not in public


async def test_a_new_account_is_reported_to_the_platform(client, db_session):
    box, patched = mailbox()
    with patched:
        user = await register_and_login(client, "notifynew")
        await _drain()

    assert box.to(SYSTEM), "the platform was not told about the new account"
    notice = box.to(SYSTEM)[0]
    assert user["username"] in notice["intro"]
    # The customer gets the welcome email, not a duplicate notice.
    assert box.to(user["email"]) == []


async def test_applying_as_a_partner_tells_the_applicant_and_the_platform(client, db_session):
    user = await register_and_login(client, "notifyb2b")
    box, patched = mailbox()
    with patched:
        res = await client.post(
            "/api/v1/auth/apply-merchant",
            json={"business_name": "Notify Tours", "contact_phone": "+8801700000000"},
            headers=user["headers"],
        )
        assert res.status_code == 200, res.text
        await _drain()

    assert any("Notify Tours" in s for s in box.subjects(user["email"]))
    assert any("Notify Tours" in s for s in box.subjects(SYSTEM))


async def test_applying_as_an_agent_tells_the_applicant_and_the_platform(client, db_session):
    user = await register_and_login(client, "notifyagent")
    box, patched = mailbox()
    with patched:
        res = await client.post(
            "/api/v1/agent/apply",
            json={"company_name": "Notify Agency", "contact_phone": "+8801700000000"},
            headers=user["headers"],
        )
        assert res.status_code == 200, res.text
        await _drain()

    assert any("Notify Agency" in s for s in box.subjects(user["email"]))
    assert any("Notify Agency" in s for s in box.subjects(SYSTEM))


async def test_using_an_agent_code_tells_that_agent(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role, "notifyadmin3")
    agent = await register_and_login(client, "notifycodeowner")
    await client.post(
        "/api/v1/agent/apply",
        json={"company_name": "Code Owner Ltd", "contact_phone": "+8801700000000"},
        headers=agent["headers"],
    )
    profile = (await db_session.execute(
        select(AgentProfile).where(AgentProfile.user_id == agent["user_id"])
    )).scalar_one()
    code = (await client.post(
        f"/api/v1/admin/agents/{profile.id}/approve", headers=admin["headers"]
    )).json()["agent_code"]

    applicant = await register_and_login(client, "notifyapplicant")
    box, patched = mailbox()
    with patched:
        await client.post(
            "/api/v1/auth/apply-merchant",
            json={"business_name": "Coded Tours", "contact_phone": "+8801700000000", "agent_code": code},
            headers=applicant["headers"],
        )
        await _drain()

    agent_mail = box.to(agent["email"])
    assert agent_mail, "the agent was not told their code was used"
    assert "Coded Tours" in agent_mail[0]["subject"]


async def test_approval_emails_reach_the_merchant_and_the_agent(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role, "notifyadmin4")

    merchant = await register_and_login(client, "notifymerchant")
    await client.post(
        "/api/v1/auth/apply-merchant",
        json={"business_name": "Approve Tours", "contact_phone": "+8801700000000"},
        headers=merchant["headers"],
    )
    m_profile = (await db_session.execute(
        select(MerchantProfile).where(MerchantProfile.user_id == merchant["user_id"])
    )).scalar_one()

    agent = await register_and_login(client, "notifyagent2")
    await client.post(
        "/api/v1/agent/apply",
        json={"company_name": "Approve Agency", "contact_phone": "+8801700000000"},
        headers=agent["headers"],
    )
    a_profile = (await db_session.execute(
        select(AgentProfile).where(AgentProfile.user_id == agent["user_id"])
    )).scalar_one()

    box, patched = mailbox()
    with patched:
        assert (await client.post(
            f"/api/v1/admin/merchants/{m_profile.id}/approve", headers=admin["headers"]
        )).status_code == 200
        assert (await client.post(
            f"/api/v1/admin/agents/{a_profile.id}/approve", headers=admin["headers"]
        )).status_code == 200
        await _drain()

    assert any("approved as a partner" in s for s in box.subjects(merchant["email"]))
    assert any("approved as an agent" in s for s in box.subjects(agent["email"]))
    # And the platform sees both.
    system = " ".join(box.subjects(SYSTEM))
    assert "partner" in system and "agent" in system


async def test_a_sale_is_reported_to_the_platform(client, db_session):
    user = await register_and_login(client, "notifybuyer")
    await fund_wallet(db_session, user["user_id"], Decimal("100"))
    product = await create_test_product(db_session, price=Decimal("12.50"))

    box, patched = mailbox()
    with patched:
        res = await client.post(
            "/api/v1/orders/checkout",
            json={"product_id": product.id, "payment_method": "WALLET"},
            headers=user["headers"],
        )
        await wait_for_order(client, res.json()["id"], user["headers"])
        await _drain()

    alerts = [m for m in box.to(SYSTEM) if "Sale" in m["subject"]]
    assert alerts, f"no transaction alert; got {box.subjects(SYSTEM)}"
    assert "12.50" in alerts[0]["subject"]
    assert user["username"] in alerts[0]["intro"]


async def test_a_referral_signup_tells_the_referrer(client, db_session, promote_role):
    admin = await _super_admin(client, promote_role, "notifyadmin5")
    await client.put(
        "/api/v1/admin/referral-settings",
        json={
            "is_enabled": True,
            "events": {"JOINING": {"referrer": "2.00", "referred": "1.00", "enabled": True}},
            "max_rewarded_referrals": None,
        },
        headers=admin["headers"],
    )
    referrer = await register_and_login(client, "notifyreferrer")
    code = (await client.get("/api/v1/referrals/me", headers=referrer["headers"])).json()["code"]

    box, patched = mailbox()
    with patched:
        import uuid as _uuid
        suffix = _uuid.uuid4().hex[:8]
        res = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"notifyjoin_{suffix}@example.com", "username": f"notifyjoin_{suffix}",
                "password": "TestPass123!", "referral_code": code,
            },
        )
        assert res.status_code == 200, res.text
        await _drain()

    told = box.to(referrer["email"])
    assert told, "the referrer was not told their code was used"
    assert "referral code" in told[0]["subject"]

    await client.put(
        "/api/v1/admin/referral-settings",
        json={"is_enabled": False, "events": {}, "max_rewarded_referrals": None},
        headers=admin["headers"],
    )


async def test_a_broken_mailer_never_breaks_the_thing_it_reports(client, db_session):
    """A notification failing must not cost a customer their purchase."""
    import app.services.notify_svc as svc

    user = await register_and_login(client, "notifyresilient")
    await fund_wallet(db_session, user["user_id"], Decimal("100"))
    product = await create_test_product(db_session, price=Decimal("10.00"))

    with patch.object(svc, "send_notice", AsyncMock(side_effect=Exception("SMTP exploded"))):
        res = await client.post(
            "/api/v1/orders/checkout",
            json={"product_id": product.id, "payment_method": "WALLET"},
            headers=user["headers"],
        )
        assert res.status_code == 202, res.text
        settled = await wait_for_order(client, res.json()["id"], user["headers"])
        await _drain()

    assert settled["status"] == "COMPLETED"

    # And an application still goes through.
    with patch.object(svc, "send_notice", AsyncMock(side_effect=Exception("SMTP exploded"))):
        applied = await client.post(
            "/api/v1/auth/apply-merchant",
            json={"business_name": "Resilient Tours", "contact_phone": "+8801700000000"},
            headers=user["headers"],
        )
        await _drain()
    assert applied.status_code == 200, applied.text


async def test_the_notice_template_renders(client, db_session):
    """The generic template every one of these events uses."""
    from app.services.email_svc import _env

    html = _env.get_template("notice.html").render(
        platform_name="Triptel", has_logo=False, year=2026,
        title="Your agent account is live", intro="You can now recruit travel agencies.",
        rows=[("Agent code", "AGX7K2M9"), ("Commission", "2% of each sale")],
        highlight="AGX7K2M9", highlight_label="Your agent code",
        cta_label="Open the agent portal", cta_url="https://triptel.co/agent",
        footnote=None,
    )
    assert "Your agent account is live" in html
    assert "AGX7K2M9" in html
    assert "https://triptel.co/agent" in html
    assert "Agent code" in html
