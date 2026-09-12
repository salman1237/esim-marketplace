import os

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use")
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://esim_test:esim_test_pw@localhost:55432/esim_test",
    ),
)

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.database import Base, engine, AsyncSessionLocal
from app.models.catalog import Country, Product
from app.models.wallet import Wallet, WalletType


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture(autouse=True)
def mock_vivape():
    """VivaPeAdapter's real methods hit a live third-party API - tests must
    never do that. Applied to every test (checkout_svc.provision_esim is
    the sole caller, so this is harmless for tests that never touch
    checkout) and defaults to simulating a successful VivaPe purchase. A
    test exercising the provisioning-failure/refund path can reconfigure
    the yielded mocks' return_value/side_effect, e.g.:
        mock_vivape.create_transaction.side_effect = Exception("VivaPe down")
    """
    from unittest.mock import AsyncMock, patch
    import app.services.checkout_svc as checkout_svc_module

    create_transaction_mock = AsyncMock(return_value={"purchase_trx": {"id": 999001}})

    def _fake_esim_data(*args, **kwargs):
        # A fresh ICCID per call - ESIMProfile.iccid is unique, and this
        # shared test DB has no per-test rollback, so a fixed canned value
        # collides across tests/runs within the same session.
        #
        # Shaped like a real VivaPe "worldmove"-type get-esim-by-trx response
        # (qrcodeContent carries the LPA, not "lpa"/"qr_code" - see
        # checkout_svc._extract_esim_details) so this fixture actually
        # exercises the real parsing path instead of a fictional one.
        unique_suffix = uuid.uuid4().hex[:14].upper()
        matching_id = uuid.uuid4().hex[:12].upper()
        return {
            "iccid": f"89882{unique_suffix}",
            "qrcodeContent": f"LPA:1$rsp.truphone.com${matching_id}",
        }

    get_esim_by_trx_mock = AsyncMock(side_effect=_fake_esim_data)

    with patch.object(checkout_svc_module.VivaPeAdapter, "create_transaction", create_transaction_mock), \
         patch.object(checkout_svc_module.VivaPeAdapter, "get_esim_by_trx", get_esim_by_trx_mock):
        yield type("VivaPeMocks", (), {
            "create_transaction": create_transaction_mock,
            "get_esim_by_trx": get_esim_by_trx_mock,
        })()


@pytest_asyncio.fixture
async def promote_role(db_session):
    """Returns an async fn(user_id, role_str) that sets a user's role directly
    via the DB — there's no public self-promotion endpoint (by design), so
    tests that need a MERCHANT/ADMIN/SUPER_ADMIN account use this instead."""
    from sqlalchemy import select
    from app.models.user import User, UserRole
    from app.services.ledger_svc import LedgerService

    async def _promote(user_id: str, role_str: str):
        role = UserRole(role_str)
        res = await db_session.execute(select(User).where(User.id == user_id))
        user = res.scalar_one()
        user.role = role
        await db_session.commit()
        await LedgerService.ensure_wallets_for_user(db_session, user_id, role)

    return _promote


async def register_and_login(client: AsyncClient, role_hint: str = "user") -> dict:
    """Registers a fresh user and returns {token, headers, user_id, username, email}."""
    suffix = uuid.uuid4().hex[:8]
    email = f"{role_hint}_{suffix}@example.com"
    username = f"{role_hint}_{suffix}"
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "username": username, "password": "TestPass123!", "phone": "+8801700000000"},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    return {
        "token": data["access_token"],
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
        "user_id": data["user_id"],
        "username": username,
        "email": email,
    }


async def partner_auth_headers(client: AsyncClient, raw_api_key: str) -> dict:
    """Exchanges a partner's raw API key for a short-lived access token
    (POST /partner/auth/token) and returns the Bearer header for it - the
    raw key itself is never sent to any other /partner/* route."""
    res = await client.post("/api/v1/partner/auth/token", json={"api_key": raw_api_key})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def fund_wallet(db_session, user_id: str, amount: Decimal = Decimal("100.0000")):
    """Directly credits a user's DEFAULT wallet for test setup (bypasses payment gateways)."""
    from sqlalchemy import select
    res = await db_session.execute(
        select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.DEFAULT)
    )
    wallet = res.scalar_one()
    wallet.balance = Decimal(str(wallet.balance)) + amount
    await db_session.commit()


async def create_test_product(
    db_session,
    price: Decimal = Decimal("9.9900"),
    supplier_product_id: int | None = 999001,
    supplier_receiver_amount: Decimal | None = Decimal("1000.0000"),
) -> Product:
    """`supplier_product_id`/`supplier_receiver_amount` default to a fake
    but non-null mapping so provision_esim takes the VivaPe branch, which
    the autouse `mock_vivape` fixture makes succeed by default without any
    real network call. Pass supplier_product_id=None to build a product
    with no supplier mapping at all - exercises provision_esim's other
    refund reason (VivaPe branch skipped entirely, not just failing)."""
    suffix = uuid.uuid4().hex[:6]
    country = Country(
        id=int(uuid.uuid4().int % 1_000_000_000),
        iso2=f"T{suffix.upper()}",  # not a real ISO2 code; just needs to be unique per test
        name_en=f"Testland {suffix}",
        is_active=True,
    )
    db_session.add(country)
    await db_session.flush()

    product = Product(
        country_id=country.id,
        title_en=f"Test eSIM {suffix} 3GB 15 Days",
        data_amount_gb=Decimal("3.0"),
        validity_days=15,
        cost_price=Decimal("5.0000"),
        retail_price=price,
        currency="USD",
        is_active=True,
        supplier_product_id=supplier_product_id,
        supplier_receiver_amount=supplier_receiver_amount,
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


async def wait_for_order(client, order_id: str, headers: dict, timeout: float = 10.0) -> dict:
    """Checkout returns 202 and provisions in a background task on the
    test's own event loop. Poll until the order settles instead of sleeping
    a fixed amount, which flakes under CI load."""
    import asyncio
    import time

    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        res = await client.get(f"/api/v1/orders/{order_id}", headers=headers)
        if res.status_code == 200:
            last = res.json()
            if last["status"] in ("COMPLETED", "FAILED"):
                return last
        await asyncio.sleep(0.05)
    raise AssertionError(f"order {order_id} did not settle within {timeout}s (last seen: {last})")
