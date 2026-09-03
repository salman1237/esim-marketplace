import pytest
import uuid
from decimal import Decimal
from sqlalchemy import select
from app.models.wallet import Wallet, WalletType, LedgerRefType
from app.services.ledger_svc import LedgerService

pytestmark = pytest.mark.asyncio


async def _make_wallet(db_session, balance=Decimal("0.0000")):
    from app.models.user import User, UserRole
    user = User(
        email=f"ledger_{uuid.uuid4().hex[:8]}@example.com",
        username=f"ledger_{uuid.uuid4().hex[:8]}",
        hashed_password="x",
        role=UserRole.USER,
    )
    db_session.add(user)
    await db_session.flush()
    wallet = Wallet(user_id=user.id, wallet_type=WalletType.DEFAULT, balance=balance, currency="USD")
    db_session.add(wallet)
    await db_session.commit()
    await db_session.refresh(wallet)
    return wallet


async def test_credit_and_debit_balance_math(db_session):
    wallet = await _make_wallet(db_session, Decimal("10.0000"))
    await LedgerService.credit(db_session, wallet.id, Decimal("5.0000"), LedgerRefType.ADMIN_ADJUSTMENT)
    await db_session.commit()
    await db_session.refresh(wallet)
    assert wallet.balance == Decimal("15.0000")

    await LedgerService.debit(db_session, wallet.id, Decimal("3.0000"), LedgerRefType.ORDER_PURCHASE)
    await db_session.commit()
    await db_session.refresh(wallet)
    assert wallet.balance == Decimal("12.0000")


async def test_debit_more_than_balance_raises(db_session):
    wallet = await _make_wallet(db_session, Decimal("5.0000"))
    with pytest.raises(ValueError):
        await LedgerService.debit(db_session, wallet.id, Decimal("100.0000"), LedgerRefType.ORDER_PURCHASE)


async def test_idempotency_key_prevents_double_credit(db_session):
    """Regression test: this is the mechanism that prevents a replayed
    payment-gateway callback (or a retried request) from crediting a wallet
    twice for the same event."""
    wallet = await _make_wallet(db_session, Decimal("0.0000"))
    key = f"test-idempotent-{uuid.uuid4().hex}"

    await LedgerService.credit(db_session, wallet.id, Decimal("20.0000"), LedgerRefType.DEPOSIT_GATEWAY, idempotency_key=key)
    await db_session.commit()
    await db_session.refresh(wallet)
    assert wallet.balance == Decimal("20.0000")

    # Replay with the same idempotency key: must be a no-op, not a second credit.
    await LedgerService.credit(db_session, wallet.id, Decimal("20.0000"), LedgerRefType.DEPOSIT_GATEWAY, idempotency_key=key)
    await db_session.commit()
    await db_session.refresh(wallet)
    assert wallet.balance == Decimal("20.0000")


async def test_balance_equals_sum_of_ledger_entries(db_session):
    wallet = await _make_wallet(db_session, Decimal("0.0000"))
    await LedgerService.credit(db_session, wallet.id, Decimal("50.0000"), LedgerRefType.DEPOSIT_MANUAL)
    await LedgerService.debit(db_session, wallet.id, Decimal("20.0000"), LedgerRefType.ORDER_PURCHASE)
    await LedgerService.credit(db_session, wallet.id, Decimal("5.0000"), LedgerRefType.COMMISSION_EARNED)
    await db_session.commit()

    from app.models.wallet import WalletLedgerEntry
    res = await db_session.execute(select(WalletLedgerEntry).where(WalletLedgerEntry.wallet_id == wallet.id))
    entries = res.scalars().all()
    total = sum((Decimal(str(e.amount)) if e.tx_type.value == "CREDIT" else -Decimal(str(e.amount))) for e in entries)

    await db_session.refresh(wallet)
    assert wallet.balance == total == Decimal("35.0000")
