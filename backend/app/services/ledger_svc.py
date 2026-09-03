from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.wallet import Wallet, WalletType, WalletLedgerEntry, LedgerTxType, LedgerRefType
from app.models.user import User, UserRole

class LedgerService:
    @staticmethod
    async def ensure_wallets_for_user(db: AsyncSession, user_id: str, role: UserRole):
        # 1. Default Wallet (all roles)
        res = await db.execute(
            select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.DEFAULT)
        )
        if not res.scalar_one_or_none():
            w = Wallet(user_id=user_id, wallet_type=WalletType.DEFAULT, balance=Decimal("0.0000"), currency="USD")
            db.add(w)

        # 2. Reward Wallet for User
        if role == UserRole.USER:
            res_r = await db.execute(
                select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.REWARD)
            )
            if not res_r.scalar_one_or_none():
                w_r = Wallet(user_id=user_id, wallet_type=WalletType.REWARD, balance=Decimal("0.0000"), currency="USD")
                db.add(w_r)

        # 3. Commission Wallet for Merchant
        if role == UserRole.MERCHANT:
            res_c = await db.execute(
                select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.COMMISSION)
            )
            if not res_c.scalar_one_or_none():
                w_c = Wallet(user_id=user_id, wallet_type=WalletType.COMMISSION, balance=Decimal("0.0000"), currency="USD")
                db.add(w_c)

        await db.commit()

    @staticmethod
    async def _find_by_idempotency_key(db: AsyncSession, idempotency_key: str):
        if not idempotency_key:
            return None
        res = await db.execute(
            select(WalletLedgerEntry).where(WalletLedgerEntry.idempotency_key == idempotency_key)
        )
        return res.scalar_one_or_none()

    @staticmethod
    async def credit(
        db: AsyncSession,
        wallet_id: str,
        amount: Decimal,
        ref_type: LedgerRefType,
        ref_id: str = None,
        description: str = None,
        idempotency_key: str = None
    ) -> WalletLedgerEntry:
        """Credits a wallet. Does NOT commit — caller owns the transaction boundary
        so this can be composed atomically with other writes in the same business
        operation (e.g. an Order + its debit + its eSIM profile)."""
        existing = await LedgerService._find_by_idempotency_key(db, idempotency_key)
        if existing:
            return existing

        # Lock wallet row with FOR UPDATE
        res = await db.execute(
            select(Wallet).where(Wallet.id == wallet_id).with_for_update()
        )
        wallet = res.scalar_one_or_none()
        if not wallet:
            raise ValueError("Wallet not found")

        bal_before = Decimal(str(wallet.balance))
        bal_after = bal_before + amount
        wallet.balance = bal_after

        entry = WalletLedgerEntry(
            wallet_id=wallet.id,
            tx_type=LedgerTxType.CREDIT,
            amount=amount,
            balance_before=bal_before,
            balance_after=bal_after,
            reference_type=ref_type,
            reference_id=ref_id,
            idempotency_key=idempotency_key,
            description=description
        )
        db.add(entry)
        await db.flush()
        await db.refresh(entry)
        return entry

    @staticmethod
    async def debit(
        db: AsyncSession,
        wallet_id: str,
        amount: Decimal,
        ref_type: LedgerRefType,
        ref_id: str = None,
        description: str = None,
        idempotency_key: str = None
    ) -> WalletLedgerEntry:
        """Debits a wallet. Does NOT commit — see credit()."""
        existing = await LedgerService._find_by_idempotency_key(db, idempotency_key)
        if existing:
            return existing

        res = await db.execute(
            select(Wallet).where(Wallet.id == wallet_id).with_for_update()
        )
        wallet = res.scalar_one_or_none()
        if not wallet:
            raise ValueError("Wallet not found")

        bal_before = Decimal(str(wallet.balance))
        if bal_before < amount:
            raise ValueError("Insufficient wallet balance")

        bal_after = bal_before - amount
        wallet.balance = bal_after

        entry = WalletLedgerEntry(
            wallet_id=wallet.id,
            tx_type=LedgerTxType.DEBIT,
            amount=amount,
            balance_before=bal_before,
            balance_after=bal_after,
            reference_type=ref_type,
            reference_id=ref_id,
            idempotency_key=idempotency_key,
            description=description
        )
        db.add(entry)
        await db.flush()
        await db.refresh(entry)
        return entry
