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
            w = Wallet(user_id=user_id, wallet_type=WalletType.DEFAULT, balance=Decimal("0.0000"), currency="EUR")
            db.add(w)

        # 2. Reward Wallet for User
        if role == UserRole.USER:
            res_r = await db.execute(
                select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.REWARD)
            )
            if not res_r.scalar_one_or_none():
                w_r = Wallet(user_id=user_id, wallet_type=WalletType.REWARD, balance=Decimal("0.0000"), currency="EUR")
                db.add(w_r)

        # 3. Commission Wallet for Merchant
        if role == UserRole.MERCHANT:
            res_c = await db.execute(
                select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == WalletType.COMMISSION)
            )
            if not res_c.scalar_one_or_none():
                w_c = Wallet(user_id=user_id, wallet_type=WalletType.COMMISSION, balance=Decimal("0.0000"), currency="EUR")
                db.add(w_c)

        await db.commit()

    @staticmethod
    async def get_wallet(db: AsyncSession, user_id: str, wallet_type: WalletType):
        res = await db.execute(
            select(Wallet).where(Wallet.user_id == user_id, Wallet.wallet_type == wallet_type)
        )
        return res.scalar_one_or_none()

    @staticmethod
    async def ensure_reward_wallet(db: AsyncSession, user_id: str) -> Wallet:
        """The REWARD wallet holds referral promo credit. ensure_wallets_for_user
        only creates one for a plain USER, but a merchant or an admin can also
        be a referrer, so one is created on demand when a reward is granted.
        Caller commits."""
        wallet = await LedgerService.get_wallet(db, user_id, WalletType.REWARD)
        if wallet:
            return wallet
        wallet = Wallet(user_id=user_id, wallet_type=WalletType.REWARD, balance=Decimal("0.0000"), currency="EUR")
        db.add(wallet)
        await db.flush()
        await db.refresh(wallet)
        return wallet

    @staticmethod
    async def spendable(db: AsyncSession, user_id: str) -> dict:
        """What this user can pay an order with: promo credit plus main
        balance. Promo credit is spendable here but is never withdrawable -
        see withdrawal_svc, which only ever touches the DEFAULT wallet."""
        res = await db.execute(
            select(Wallet).where(
                Wallet.user_id == user_id,
                Wallet.wallet_type.in_([WalletType.DEFAULT, WalletType.REWARD]),
            )
        )
        balances = {WalletType.DEFAULT: Decimal("0"), WalletType.REWARD: Decimal("0")}
        frozen = False
        for wallet in res.scalars().all():
            balances[wallet.wallet_type] = Decimal(str(wallet.balance))
            if wallet.wallet_type == WalletType.DEFAULT and wallet.is_frozen:
                frozen = True
        return {
            "default": balances[WalletType.DEFAULT],
            "reward": balances[WalletType.REWARD],
            "total": balances[WalletType.DEFAULT] + balances[WalletType.REWARD],
            "frozen": frozen,
        }

    @staticmethod
    async def spend(
        db: AsyncSession,
        user_id: str,
        amount: Decimal,
        ref_type: LedgerRefType,
        ref_id: str = None,
        description: str = None,
        idempotency_prefix: str = None,
    ) -> Decimal:
        """Pays `amount` from promo credit first, then the main wallet, and
        returns how much came from promo credit. Promo credit is spent first on
        purpose: it is the balance the customer cannot get back as cash, so
        using it up before their own money is the outcome that favours them.

        Raises ValueError if the two together can't cover the amount. Does NOT
        commit - composes with the order it is paying for."""
        amount = Decimal(str(amount))
        if amount <= 0:
            return Decimal("0")

        reward_wallet = await LedgerService.get_wallet(db, user_id, WalletType.REWARD)
        reward_available = Decimal(str(reward_wallet.balance)) if reward_wallet else Decimal("0")
        reward_part = min(reward_available, amount)
        cash_part = amount - reward_part

        if reward_part > 0:
            await LedgerService.debit(
                db, reward_wallet.id, reward_part, ref_type, ref_id=ref_id,
                description=f"{description} (reward credit)" if description else None,
                idempotency_key=f"{idempotency_prefix}-reward" if idempotency_prefix else None,
            )

        if cash_part > 0:
            default_wallet = await LedgerService.get_wallet(db, user_id, WalletType.DEFAULT)
            if not default_wallet:
                raise ValueError("Insufficient wallet balance")
            await LedgerService.debit(
                db, default_wallet.id, cash_part, ref_type, ref_id=ref_id, description=description,
                idempotency_key=f"{idempotency_prefix}-default" if idempotency_prefix else None,
            )

        return reward_part

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
