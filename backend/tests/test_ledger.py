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


async def test_concurrent_debits_never_violate_balance_invariant(db_session):
    """The plan's own Verification Plan explicitly requires this: 'Verify
    concurrent top-ups and purchases never violate balance invariant.'
    Using db_session for every concurrent call wouldn't actually exercise
    with_for_update()'s row lock - that only matters across separate
    transactions/connections, which a single shared session isn't. Each
    concurrent operation gets its own AsyncSessionLocal() instead, the
    same way independent real requests would."""
    import asyncio
    from app.core.database import AsyncSessionLocal

    wallet = await _make_wallet(db_session, Decimal("1000.0000"))

    async def _debit_one():
        async with AsyncSessionLocal() as session:
            await LedgerService.debit(session, wallet.id, Decimal("10.0000"), LedgerRefType.ORDER_PURCHASE)
            await session.commit()

    # 20 concurrent debits of $10 each against a $1000 wallet - if the row
    # lock didn't serialize these (a lost-update race), the final balance
    # would land above $800 (some debits reading a stale pre-debit
    # balance and overwriting each other's decrement).
    await asyncio.gather(*[_debit_one() for _ in range(20)])

    async with AsyncSessionLocal() as verify_session:
        from app.models.wallet import WalletLedgerEntry
        w_res = await verify_session.execute(select(Wallet).where(Wallet.id == wallet.id))
        final_wallet = w_res.scalar_one()

        e_res = await verify_session.execute(select(WalletLedgerEntry).where(WalletLedgerEntry.wallet_id == wallet.id))
        entries = e_res.scalars().all()
        assert len(entries) == 20
        computed_total = Decimal("1000.0000") - sum(Decimal(str(e.amount)) for e in entries)

        assert Decimal(str(final_wallet.balance)) == Decimal("800.0000")
        assert Decimal(str(final_wallet.balance)) == computed_total
