"""/auth/me reports both capabilities, not whichever one the role names.

An approved merchant who is later approved as an agent keeps role=MERCHANT -
see approve_agent, which only promotes a plain USER. Anything keyed on the
role alone therefore hides the agent portal from exactly the accounts that
have one, which is what the navigation used to do.
"""
from decimal import Decimal

import pytest

from app.models.agent import AgentProfile, AgentStatus
from app.models.merchant import MerchantProfile, MerchantStatus
from conftest import register_and_login

pytestmark = pytest.mark.asyncio


async def _me(client, user):
    res = await client.get("/api/v1/auth/me", headers=user["headers"])
    assert res.status_code == 200, res.text
    return res.json()


async def test_a_plain_customer_has_neither_profile(client):
    body = await _me(client, await register_and_login(client, "plain"))
    assert body["merchant_profile"] is None
    assert body["agent_profile"] is None


async def test_an_agent_profile_is_reported(client, db_session, promote_role):
    user = await register_and_login(client, "soloagent")
    await promote_role(user["user_id"], "AGENT")
    db_session.add(AgentProfile(
        user_id=user["user_id"], company_name="Solo Routes", contact_phone="+8801700000001",
        agent_code="SOLO1", commission_rate_pct=Decimal("2.00"), status=AgentStatus.APPROVED,
    ))
    await db_session.commit()

    body = await _me(client, user)
    assert body["agent_profile"]["status"] == "APPROVED"
    assert body["agent_profile"]["agent_code"] == "SOLO1"
    assert body["merchant_profile"] is None


async def test_an_account_that_is_both_reports_both(client, db_session, promote_role):
    """The case the navigation got wrong: role says MERCHANT, and the agent
    capability is only visible through the profile."""
    user = await register_and_login(client, "bothcaps")
    await promote_role(user["user_id"], "MERCHANT")
    db_session.add(MerchantProfile(
        user_id=user["user_id"], business_name="Dual Travel", contact_phone="+8801700000002",
        commission_rate_pct=Decimal("10.00"), status=MerchantStatus.APPROVED,
    ))
    db_session.add(AgentProfile(
        user_id=user["user_id"], company_name="Dual Distribution", contact_phone="+8801700000002",
        agent_code="DUAL1", commission_rate_pct=Decimal("2.00"), status=AgentStatus.APPROVED,
    ))
    await db_session.commit()

    body = await _me(client, user)
    assert body["role"] == "MERCHANT"
    assert body["merchant_profile"]["status"] == "APPROVED"
    assert body["agent_profile"]["status"] == "APPROVED"


async def test_a_pending_agent_is_reported_as_pending_not_approved(client, db_session):
    """The portal shows an applicant their status, so "has a profile" and
    "may trade" have to stay distinguishable."""
    user = await register_and_login(client, "pendingagent")
    db_session.add(AgentProfile(
        user_id=user["user_id"], company_name="Waiting Co", contact_phone="+8801700000003",
        agent_code="WAIT1", commission_rate_pct=Decimal("2.00"), status=AgentStatus.PENDING,
    ))
    await db_session.commit()

    body = await _me(client, user)
    assert body["agent_profile"]["status"] == "PENDING"


async def test_a_suspended_agent_is_not_reported_as_approved(client, db_session):
    user = await register_and_login(client, "suspendedagent")
    db_session.add(AgentProfile(
        user_id=user["user_id"], company_name="Stopped Co", contact_phone="+8801700000004",
        agent_code="STOP1", commission_rate_pct=Decimal("2.00"), status=AgentStatus.SUSPENDED,
    ))
    await db_session.commit()

    body = await _me(client, user)
    assert body["agent_profile"]["status"] == "SUSPENDED"
