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


async def fund_wallet(db_session, user_id: str, amount: Decimal = Decimal("100.0000")):
    """Directly credits a user's DEFAULT wallet for test setup (bypasses payment gateways)."""
    from sqlalchemy import select
    res = await db_session.execute(
        select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.DEFAULT)
    )
    wallet = res.scalar_one()
    wallet.balance = Decimal(str(wallet.balance)) + amount
    await db_session.commit()


async def create_test_product(db_session, price: Decimal = Decimal("9.9900")) -> Product:
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
        supplier_product_id=None,  # forces the mock-fallback provisioning path (no live VivaPe call)
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product
