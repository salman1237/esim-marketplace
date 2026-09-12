import pytest
from decimal import Decimal
from conftest import register_and_login, fund_wallet, create_test_product

pytestmark = pytest.mark.asyncio


async def test_commission_tier_crud_requires_super_admin(client, promote_role):
    admin = await register_and_login(client, "tieradmin")
    await promote_role(admin["user_id"], "ADMIN")

    denied = await client.post(
        "/api/v1/admin/commission-tiers", json={"min_volume_usd": 100, "rate_pct": 10}, headers=admin["headers"]
    )
    assert denied.status_code == 403

    await promote_role(admin["user_id"], "SUPER_ADMIN")
    created = await client.post(
        "/api/v1/admin/commission-tiers", json={"min_volume_usd": 100, "rate_pct": 10}, headers=admin["headers"]
    )
    assert created.status_code == 200, created.text
    tier_id = created.json()["id"]

    listing = await client.get("/api/v1/admin/commission-tiers", headers=admin["headers"])
    assert any(t["id"] == tier_id for t in listing.json())

    dup = await client.post(
        "/api/v1/admin/commission-tiers", json={"min_volume_usd": 100, "rate_pct": 15}, headers=admin["headers"]
    )
    assert dup.status_code == 400

    deleted = await client.delete(f"/api/v1/admin/commission-tiers/{tier_id}", headers=admin["headers"])
    assert deleted.status_code == 200


async def test_no_tiers_configured_uses_flat_rate(client, db_session, promote_role):
    """Baseline: with zero tiers, behavior is identical to before this
    feature existed - the merchant's own flat commission_rate_pct."""
    merchant = await register_and_login(client, "flatratemerchant")
    await promote_role(merchant["user_id"], "MERCHANT")
    await fund_wallet(db_session, merchant["user_id"], Decimal("100.0000"))
    product = await create_test_product(db_session, price=Decimal("10.0000"))

    from conftest import wait_for_order

    res = await client.post(
        "/api/v1/orders/checkout",
        json={"product_id": product.id, "payment_method": "WALLET", "is_buy_for_user": True, "auto_create_user": True},
        headers=merchant["headers"],
    )
    assert res.status_code == 202, res.text
    await wait_for_order(client, res.json()["id"], merchant["headers"])

    reseller_orders = await client.get("/api/v1/orders/reseller-orders", headers=merchant["headers"])
    # Default MerchantProfile.commission_rate_pct is 5.00 (model default).
    assert Decimal(str(reseller_orders.json()[0]["commission_earned"])) == Decimal("0.5000")


async def test_commission_tier_applies_once_volume_threshold_crossed(client, db_session, promote_role):
    """Regression test for the actual feature: a merchant's rate should
    jump to the tiered rate once their cumulative COMPLETED reseller
    volume crosses a configured threshold - not before."""
    sa = await register_and_login(client, "tiersetup")
    await promote_role(sa["user_id"], "SUPER_ADMIN")
    tier_res = await client.post(
        "/api/v1/admin/commission-tiers", json={"min_volume_usd": 15, "rate_pct": 20}, headers=sa["headers"]
    )
    assert tier_res.status_code == 200, tier_res.text

    merchant = await register_and_login(client, "tieredmerchant")
    await promote_role(merchant["user_id"], "MERCHANT")
    await fund_wallet(db_session, merchant["user_id"], Decimal("100.0000"))
    product = await create_test_product(db_session, price=Decimal("10.0000"))

    from conftest import wait_for_order

    for _ in range(3):
        res = await client.post(
            "/api/v1/orders/checkout",
            json={"product_id": product.id, "payment_method": "WALLET", "is_buy_for_user": True, "auto_create_user": True},
            headers=merchant["headers"],
        )
        assert res.status_code == 202, res.text
        # Settle each order before placing the next: the tier rate depends
        # on cumulative COMPLETED volume, so letting three provision
        # concurrently would make the volume each one sees nondeterministic.
        await wait_for_order(client, res.json()["id"], merchant["headers"])

    reseller_orders = await client.get("/api/v1/orders/reseller-orders", headers=merchant["headers"])
    commissions = sorted(Decimal(str(o["commission_earned"])) for o in reseller_orders.json())
    # Order 1 (volume before it: $0): flat 5% of $10 = $0.50
    # Order 2 (volume before it: $10, still < $15): flat 5% of $10 = $0.50
    # Order 3 (volume before it: $20, >= $15 threshold): tiered 20% of $10 = $2.00
    assert commissions == [Decimal("0.5000"), Decimal("0.5000"), Decimal("2.0000")]
