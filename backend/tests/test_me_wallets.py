import pytest
from decimal import Decimal

from conftest import register_and_login, fund_wallet

pytestmark = pytest.mark.asyncio


async def test_me_lists_spendable_default_wallet_first(client, db_session, promote_role):
    """The header shows the first wallet as the user's balance. Wallets came
    back unordered, so a merchant/admin whose COMMISSION wallet happened to
    be first saw $0.00 despite having funds."""
    user = await register_and_login(client, "walletorder")
    await promote_role(user["user_id"], "MERCHANT")  # gets a COMMISSION wallet too
    await fund_wallet(db_session, user["user_id"], Decimal("25.0000"))

    me = await client.get("/api/v1/auth/me", headers=user["headers"])
    assert me.status_code == 200
    wallets = me.json()["wallets"]
    assert {w["wallet_type"] for w in wallets} >= {"DEFAULT", "COMMISSION"}

    first = wallets[0]
    assert first["wallet_type"] == "DEFAULT"
    assert first["type"] == "DEFAULT"  # kept for existing clients
    assert Decimal(str(first["balance"])) == Decimal("25.0000")
