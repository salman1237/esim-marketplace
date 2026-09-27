"""Financial reconciliation: the money cycle, VivaPe (supplier) checks and
merchant monthly statements.

Everything here is read-only and computed from records that already exist -
the double-entry wallet ledger, orders (with their cost snapshot and VivaPe
transaction id) and the supplier request log - so the reports can be run
for any past period and always agree with each other."""
import csv
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import SupplierTransactionLog
from app.models.catalog import Product
from app.models.merchant import MerchantProfile
from app.models.order import Order, OrderStatus
from app.models.user import User, UserRole
from app.models.wallet import LedgerRefType, LedgerTxType, Wallet, WalletLedgerEntry, WalletType
from app.models.withdrawal import WithdrawalRequest, WithdrawalStatus

CENTS = Decimal("0.01")
CREATE_TRX_ENDPOINT = "create-transaction"
# An order still PAID/PROCESSING after this long needs a human look.
STUCK_AFTER = timedelta(minutes=30)
MAX_LIST = 200


def cents(value) -> str:
    return str(Decimal(str(value or 0)).quantize(CENTS))


def period_bounds(date_from: Optional[date], date_to: Optional[date]) -> Tuple[datetime, datetime]:
    """Inclusive calendar days in UTC -> [start, end). Defaults to this month so far."""
    today = datetime.now(timezone.utc).date()
    date_from = date_from or today.replace(day=1)
    date_to = date_to or today
    if date_to < date_from:
        raise ValueError("date_to is before date_from")
    start = datetime(date_from.year, date_from.month, date_from.day, tzinfo=timezone.utc)
    end_day = date_to + timedelta(days=1)
    return start, datetime(end_day.year, end_day.month, end_day.day, tzinfo=timezone.utc)


def month_bounds(month: str) -> Tuple[datetime, datetime]:
    try:
        year, mon = (int(p) for p in month.split("-"))
        start = datetime(year, mon, 1, tzinfo=timezone.utc)
    except Exception:
        raise ValueError("month must look like 2026-09")
    end = datetime(year + (mon == 12), 1 if mon == 12 else mon + 1, 1, tzinfo=timezone.utc)
    return start, end


def _signed_amount():
    return case((WalletLedgerEntry.tx_type == LedgerTxType.CREDIT, WalletLedgerEntry.amount), else_=-WalletLedgerEntry.amount)


# --------------------------------------------------------------------------
# Money cycle
# --------------------------------------------------------------------------

async def money_cycle_summary(db: AsyncSession, start: datetime, end: datetime) -> dict:
    # Ledger movements in the period, split by who holds the wallet.
    ledger_rows = (await db.execute(
        select(
            Wallet.wallet_type, User.role, WalletLedgerEntry.reference_type, WalletLedgerEntry.tx_type,
            func.count(WalletLedgerEntry.id), func.coalesce(func.sum(WalletLedgerEntry.amount), 0),
        )
        .select_from(WalletLedgerEntry)
        .join(Wallet, WalletLedgerEntry.wallet_id == Wallet.id)
        .join(User, Wallet.user_id == User.id)
        .where(WalletLedgerEntry.created_at >= start, WalletLedgerEntry.created_at < end)
        .group_by(Wallet.wallet_type, User.role, WalletLedgerEntry.reference_type, WalletLedgerEntry.tx_type)
    )).all()

    def ledger_sum(ref: LedgerRefType, tx: LedgerTxType, wallet_type: Optional[WalletType] = None) -> Decimal:
        return sum(
            (Decimal(str(total)) for wt, _role, r, t, _n, total in ledger_rows
             if r == ref and t == tx and (wallet_type is None or wt == wallet_type)),
            Decimal("0"),
        )

    breakdown: dict = {}
    for wallet_type, role, ref, tx, n, total in ledger_rows:
        holder = "merchant" if role == UserRole.MERCHANT else "customer"
        key = (ref.value, wallet_type.value, holder)
        item = breakdown.setdefault(key, {
            "reference_type": ref.value, "wallet_type": wallet_type.value, "holder": holder,
            "credits": Decimal("0"), "debits": Decimal("0"), "entries": 0,
        })
        item["credits" if tx == LedgerTxType.CREDIT else "debits"] += Decimal(str(total))
        item["entries"] += n

    # Orders placed in the period.
    order_rows = (await db.execute(
        select(
            Order.status, Order.payment_method, func.count(Order.id),
            func.coalesce(func.sum(Order.total_amount), 0),
            func.coalesce(func.sum(Order.total_amount).filter(Order.cost_amount.isnot(None)), 0),
            func.coalesce(func.sum(Order.cost_amount), 0),
            func.coalesce(func.sum(Order.reseller_commission_amount), 0),
            func.count(Order.id).filter(Order.external_trx_id.isnot(None)),
            func.coalesce(func.sum(Order.cost_amount).filter(Order.external_trx_id.isnot(None)), 0),
        )
        .where(Order.created_at >= start, Order.created_at < end)
        .group_by(Order.status, Order.payment_method)
    )).all()

    completed = [r for r in order_rows if r[0] == OrderStatus.COMPLETED]
    sales = sum((Decimal(str(r[3])) for r in completed), Decimal("0"))
    sales_with_cost = sum((Decimal(str(r[4])) for r in completed), Decimal("0"))
    supplier_cost = sum((Decimal(str(r[5])) for r in completed), Decimal("0"))
    commission = sum((Decimal(str(r[6])) for r in completed), Decimal("0"))
    gross_profit = sales_with_cost - supplier_cost
    failed_charged = [r for r in order_rows if r[0] == OrderStatus.FAILED]
    failed_charged_count = sum(r[7] for r in failed_charged)
    failed_charged_cost = sum((Decimal(str(r[8])) for r in failed_charged), Decimal("0"))

    gateway_paid = sum(
        (Decimal(str(r[3])) for r in order_rows
         if r[1].value == "SHURJOPAY" and r[0] in (OrderStatus.PAID, OrderStatus.PROCESSING, OrderStatus.COMPLETED, OrderStatus.FAILED)),
        Decimal("0"),
    )

    by_status: dict = {}
    for status, _pm, n, total, *_ in order_rows:
        s = by_status.setdefault(status.value, {"orders": 0, "amount": Decimal("0")})
        s["orders"] += n
        s["amount"] += Decimal(str(total))

    top_up_gateway = ledger_sum(LedgerRefType.DEPOSIT_GATEWAY, LedgerTxType.CREDIT)
    top_up_manual = ledger_sum(LedgerRefType.DEPOSIT_MANUAL, LedgerTxType.CREDIT)

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "money_in": {
            "gateway_top_ups": cents(top_up_gateway),
            "manual_deposits": cents(top_up_manual),
            "gateway_order_payments": cents(gateway_paid),
            "total": cents(top_up_gateway + top_up_manual + gateway_paid),
            "admin_adjustments_credit": cents(ledger_sum(LedgerRefType.ADMIN_ADJUSTMENT, LedgerTxType.CREDIT)),
            "admin_adjustments_debit": cents(ledger_sum(LedgerRefType.ADMIN_ADJUSTMENT, LedgerTxType.DEBIT)),
        },
        "wallets": {
            "spent_on_orders": cents(ledger_sum(LedgerRefType.ORDER_PURCHASE, LedgerTxType.DEBIT)),
            "refunded_to_wallets": cents(ledger_sum(LedgerRefType.REFUND, LedgerTxType.CREDIT)),
            "commission_earned": cents(ledger_sum(LedgerRefType.COMMISSION_EARNED, LedgerTxType.CREDIT)),
            "commission_moved_to_main_wallet": cents(
                ledger_sum(LedgerRefType.COMMISSION_TRANSFER, LedgerTxType.DEBIT, WalletType.COMMISSION)
            ),
            # The hold is taken when a withdrawal is requested, so these two
            # explain balance that left wallets without an order behind it.
            "withdrawals_held": cents(ledger_sum(LedgerRefType.WITHDRAWAL_HOLD, LedgerTxType.DEBIT)),
            "withdrawals_returned": cents(ledger_sum(LedgerRefType.WITHDRAWAL_REVERSED, LedgerTxType.CREDIT)),
            # Referral promo credit issued and clawed back. Not cash out: it
            # only ever becomes a discounted eSIM.
            "reward_credit_granted": cents(ledger_sum(LedgerRefType.REWARD_EARNED, LedgerTxType.CREDIT)),
            "reward_credit_reversed": cents(ledger_sum(LedgerRefType.REWARD_REVERSED, LedgerTxType.DEBIT)),
            "reward_credit_spent_on_orders": cents(
                ledger_sum(LedgerRefType.ORDER_PURCHASE, LedgerTxType.DEBIT, WalletType.REWARD)
            ),
        },
        "withdrawals": await withdrawals_in_period(db, start, end),
        "sales": {
            "completed_orders": sum(r[2] for r in completed),
            "selling_price": cents(sales),
            "supplier_cost": cents(supplier_cost),
            "gross_profit": cents(gross_profit),
            "merchant_commission": cents(commission),
            "net_profit": cents(gross_profit - commission),
            "by_status": {k: {"orders": v["orders"], "amount": cents(v["amount"])} for k, v in by_status.items()},
        },
        "supplier": {
            "expected_vivape_charges": cents(supplier_cost + failed_charged_cost),
            "charged_on_failed_orders": {"orders": failed_charged_count, "cost": cents(failed_charged_cost)},
        },
        "ledger_breakdown": [
            {**v, "credits": cents(v["credits"]), "debits": cents(v["debits"])}
            for v in sorted(breakdown.values(), key=lambda v: (v["reference_type"], v["wallet_type"], v["holder"]))
        ],
        "liabilities": await wallet_liabilities(db),
        "integrity": await ledger_integrity(db),
    }


async def withdrawals_in_period(db: AsyncSession, start: datetime, end: datetime) -> dict:
    """Cash actually paid out, and what is still queued. `paid_out` is the
    net amount sent (after the processing fee we keep), so it reconciles
    against the bank/bKash statements rather than against the ledger hold."""
    rows = (await db.execute(
        select(
            WithdrawalRequest.status,
            func.count(WithdrawalRequest.id),
            func.coalesce(func.sum(WithdrawalRequest.amount), 0),
            func.coalesce(func.sum(WithdrawalRequest.net_amount), 0),
            func.coalesce(func.sum(WithdrawalRequest.fee_amount), 0),
        )
        .where(WithdrawalRequest.created_at >= start, WithdrawalRequest.created_at < end)
        .group_by(WithdrawalRequest.status)
    )).all()
    by_status = {
        status.value: {
            "requests": n,
            "requested": cents(Decimal(str(gross))),
            "net": cents(Decimal(str(net))),
            "fees": cents(Decimal(str(fees))),
        }
        for status, n, gross, net, fees in rows
    }
    paid = by_status.get("PAID", {})
    return {
        "by_status": by_status,
        "paid_out": paid.get("net", cents(Decimal("0"))),
        "fees_kept": paid.get("fees", cents(Decimal("0"))),
    }


async def wallet_liabilities(db: AsyncSession) -> dict:
    """What we owe wallet holders right now - money received but not yet spent."""
    rows = (await db.execute(
        select(Wallet.wallet_type, User.role, func.count(Wallet.id), func.coalesce(func.sum(Wallet.balance), 0))
        .join(User, Wallet.user_id == User.id)
        .group_by(Wallet.wallet_type, User.role)
    )).all()
    groups: dict = {}
    total = Decimal("0")
    promo = Decimal("0")
    for wallet_type, role, n, balance in rows:
        holder = "merchant" if role == UserRole.MERCHANT else "customer"
        key = f"{holder}_{wallet_type.value.lower()}"
        g = groups.setdefault(key, {"wallets": 0, "balance": Decimal("0")})
        g["wallets"] += n
        g["balance"] += Decimal(str(balance))
        total += Decimal(str(balance))
        # Referral promo credit. A liability in eSIMs, never in cash: it can
        # buy a package but can never be withdrawn, so it must not be read as
        # money we might have to pay out.
        if wallet_type == WalletType.REWARD:
            promo += Decimal(str(balance))
    # Pending withdrawals are no longer in any wallet balance (the hold was
    # taken at request time), but we still owe the money - so they are a
    # separate payable, not part of the wallet total.
    pending = (await db.execute(
        select(
            func.count(WithdrawalRequest.id),
            func.coalesce(func.sum(WithdrawalRequest.net_amount), 0),
        ).where(WithdrawalRequest.status == WithdrawalStatus.PENDING)
    )).one()

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "groups": {k: {"wallets": v["wallets"], "balance": cents(v["balance"])} for k, v in sorted(groups.items())},
        "total": cents(total),
        "promo_credit": cents(promo),
        # What could actually be asked for in cash: everything except promo credit.
        "cash_owed": cents(total - promo),
        "pending_withdrawals": {"requests": pending[0], "payable": cents(Decimal(str(pending[1])))},
        "total_including_pending_withdrawals": cents(total + Decimal(str(pending[1]))),
    }


async def ledger_integrity(db: AsyncSession) -> dict:
    """Two checks that must always be zero: every wallet balance equals the
    sum of its ledger entries, and every entry's arithmetic adds up."""
    net = (
        select(WalletLedgerEntry.wallet_id, func.sum(_signed_amount()).label("net"))
        .group_by(WalletLedgerEntry.wallet_id)
        .subquery()
    )
    ledger_net = func.coalesce(net.c.net, 0)
    mismatch_filter = Wallet.balance != ledger_net
    mismatch_count = (await db.execute(
        select(func.count(Wallet.id)).select_from(Wallet).outerjoin(net, net.c.wallet_id == Wallet.id).where(mismatch_filter)
    )).scalar_one()
    mismatches = (await db.execute(
        select(Wallet.id, Wallet.wallet_type, Wallet.balance, ledger_net, User.username, User.email)
        .select_from(Wallet)
        .join(User, Wallet.user_id == User.id)
        .outerjoin(net, net.c.wallet_id == Wallet.id)
        .where(mismatch_filter)
        .limit(50)
    )).all()

    bad_entries = (await db.execute(
        select(func.count(WalletLedgerEntry.id)).where(
            WalletLedgerEntry.balance_after != WalletLedgerEntry.balance_before + _signed_amount()
        )
    )).scalar_one()

    return {
        "ok": mismatch_count == 0 and bad_entries == 0,
        "wallet_balance_mismatches": mismatch_count,
        "entries_with_bad_arithmetic": bad_entries,
        "mismatched_wallets": [
            {
                "wallet_id": wid, "wallet_type": wt.value, "balance": cents(balance), "ledger_total": cents(ledger),
                "difference": cents(Decimal(str(balance)) - Decimal(str(ledger))), "username": username, "email": email,
            }
            for wid, wt, balance, ledger, username, email in mismatches
        ],
    }


# --------------------------------------------------------------------------
# VivaPe reconciliation
# --------------------------------------------------------------------------

def _trx_id_from_log(payload) -> Optional[str]:
    purchase = payload.get("purchase_trx") if isinstance(payload, dict) else None
    trx_id = purchase.get("id") if isinstance(purchase, dict) else None
    return str(trx_id) if trx_id not in (None, "") else None


def _order_brief(order: Order, product: Product, buyer: User) -> dict:
    return {
        "order_id": order.id,
        "order_no": order.order_no,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "status": order.status.value,
        "payment_method": order.payment_method.value,
        "vivape_trx_id": order.external_trx_id,
        "product": product.title_en,
        "supplier_product_id": product.supplier_product_id,
        "cost": cents(order.cost_amount) if order.cost_amount is not None else None,
        "selling_price": cents(order.total_amount),
        "buyer": buyer.email or buyer.username,
    }


async def vivape_orders(db: AsyncSession, start: datetime, end: datetime, limit: int = 50000):
    """Every order in the period that VivaPe charged us for (has a trx id) -
    the list to match line by line against VivaPe's own statement."""
    return (await db.execute(
        select(Order, Product, User)
        .join(Product, Order.product_id == Product.id)
        .join(User, Order.buyer_id == User.id)
        .where(Order.created_at >= start, Order.created_at < end, Order.external_trx_id.isnot(None))
        .order_by(Order.created_at.asc())
        .limit(limit)
    )).all()


async def vivape_reconciliation(db: AsyncSession, start: datetime, end: datetime) -> dict:
    in_period = (Order.created_at >= start, Order.created_at < end)
    joined = lambda stmt: stmt.join(Product, Order.product_id == Product.id).join(User, Order.buyer_id == User.id)

    async def order_list(*conditions):
        rows = (await db.execute(
            joined(select(Order, Product, User)).where(*in_period, *conditions).order_by(Order.created_at.desc()).limit(MAX_LIST)
        )).all()
        return [_order_brief(*r) for r in rows]

    completed_with_trx, completed_cost = (await db.execute(
        select(func.count(Order.id), func.coalesce(func.sum(Order.cost_amount), 0))
        .where(*in_period, Order.status == OrderStatus.COMPLETED, Order.external_trx_id.isnot(None))
    )).one()

    charged_but_failed = await order_list(Order.status == OrderStatus.FAILED, Order.external_trx_id.isnot(None))
    completed_without_trx = await order_list(Order.status == OrderStatus.COMPLETED, Order.external_trx_id.is_(None))
    missing_cost = await order_list(Order.status == OrderStatus.COMPLETED, Order.cost_amount.is_(None))
    stuck = await order_list(
        Order.status.in_([OrderStatus.PAID, OrderStatus.PROCESSING]),
        Order.updated_at < datetime.now(timezone.utc) - STUCK_AFTER,
    )

    dup_ids = (await db.execute(
        select(Order.external_trx_id)
        .where(Order.external_trx_id.isnot(None))
        .group_by(Order.external_trx_id)
        .having(func.count(Order.id) > 1)
    )).scalars().all()
    duplicates = []
    if dup_ids:
        rows = (await db.execute(
            joined(select(Order, Product, User)).where(*in_period, Order.external_trx_id.in_(dup_ids)).order_by(Order.external_trx_id)
        )).all()
        duplicates = [_order_brief(*r) for r in rows][:MAX_LIST]

    # Supplier side: every create-transaction call we made in the period.
    logs = (await db.execute(
        select(SupplierTransactionLog.created_at, SupplierTransactionLog.response_payload, SupplierTransactionLog.status_code)
        .where(
            SupplierTransactionLog.endpoint == CREATE_TRX_ENDPOINT,
            SupplierTransactionLog.created_at >= start,
            SupplierTransactionLog.created_at < end,
        )
        .order_by(SupplierTransactionLog.created_at.asc())
        .limit(20000)
    )).all()
    logged_trx = {}
    failed_calls = 0
    for created_at, payload, _status in logs:
        trx_id = _trx_id_from_log(payload)
        if trx_id:
            logged_trx.setdefault(trx_id, created_at)
        else:
            failed_calls += 1

    known = set()
    if logged_trx:
        ids = list(logged_trx)
        for i in range(0, len(ids), 1000):
            known.update((await db.execute(
                select(Order.external_trx_id).where(Order.external_trx_id.in_(ids[i:i + 1000]))
            )).scalars().all())
    orphans = [
        {"vivape_trx_id": trx_id, "logged_at": at.isoformat() if at else None}
        for trx_id, at in logged_trx.items() if trx_id not in known
    ]

    issues = len(charged_but_failed) + len(completed_without_trx) + len(missing_cost) + len(stuck) + len(duplicates) + len(orphans)
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "ok": issues == 0,
        "totals": {
            "completed_orders_with_trx": completed_with_trx,
            "expected_cost_completed": cents(completed_cost),
            "charged_on_failed_orders": cents(sum((Decimal(o["cost"] or 0) for o in charged_but_failed), Decimal("0"))),
            "supplier_calls_succeeded": len(logged_trx),
            "supplier_calls_failed": failed_calls,
        },
        "exceptions": {
            "charged_but_failed": charged_but_failed,
            "supplier_trx_without_order": orphans[:MAX_LIST],
            "duplicate_trx_ids": duplicates,
            "completed_without_trx": completed_without_trx,
            "stuck_in_progress": stuck,
            "completed_missing_cost": missing_cost,
        },
    }


def vivape_orders_csv(rows) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Order no", "Date (UTC)", "Status", "VivaPe trx id", "VivaPe product id", "Product",
        "Cost (EUR)", "Selling price (EUR)", "Buyer", "Note",
    ])
    for order, product, buyer in rows:
        b = _order_brief(order, product, buyer)
        note = ""
        if order.status == OrderStatus.FAILED:
            note = "Customer refunded - VivaPe charge to recover"
        elif order.status != OrderStatus.COMPLETED:
            note = "Not completed yet"
        writer.writerow([
            b["order_no"], b["created_at"], b["status"], b["vivape_trx_id"], b["supplier_product_id"], b["product"],
            b["cost"], b["selling_price"], b["buyer"], note,
        ])
    return buf.getvalue()


def statement_csv(statement: dict) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    m = statement["merchant"]
    writer.writerow(["Merchant statement", statement["period"]["month"]])
    writer.writerow(["Merchant", m["business_name"] or m["username"], m["email"]])
    o = statement["orders"]
    writer.writerow(["Completed orders", o["completed"], "Sales volume (EUR)", o["sales_volume"], "Commission earned (EUR)", o["commission_earned"]])
    writer.writerow([])
    for w in statement["wallets"]:
        writer.writerow([f"{w['wallet_type']} wallet", "Opening", w["opening_balance"], "Credits", w["credits"],
                         "Debits", w["debits"], "Closing", w["closing_balance"], "Adds up" if w["consistent"] else "CHECK"])
        writer.writerow(["Date (UTC)", "Type", "Reference", "Reference id", "Description", "Amount (EUR)", "Balance after (EUR)"])
        for e in w["entries"]:
            signed = e["amount"] if e["tx_type"] == "CREDIT" else f"-{e['amount']}"
            writer.writerow([e["created_at"], e["tx_type"], e["reference_type"], e["reference_id"], e["description"], signed, e["balance_after"]])
        writer.writerow([])
    return buf.getvalue()


# --------------------------------------------------------------------------
# Merchant monthly statement
# --------------------------------------------------------------------------

async def merchant_statement(db: AsyncSession, user_id: str, start: datetime, end: datetime) -> Optional[dict]:
    row = (await db.execute(
        select(User, MerchantProfile).outerjoin(MerchantProfile, MerchantProfile.user_id == User.id).where(User.id == user_id)
    )).first()
    if not row:
        return None
    user, profile = row

    wallets = (await db.execute(select(Wallet).where(Wallet.user_id == user_id))).scalars().all()
    now = datetime.now(timezone.utc)
    wallet_sections = []
    for wallet in sorted(wallets, key=lambda w: w.wallet_type.value):
        last_before = (await db.execute(
            select(WalletLedgerEntry.balance_after)
            .where(WalletLedgerEntry.wallet_id == wallet.id, WalletLedgerEntry.created_at < start)
            .order_by(WalletLedgerEntry.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        opening = Decimal(str(last_before or 0))

        entries = (await db.execute(
            select(WalletLedgerEntry)
            .where(WalletLedgerEntry.wallet_id == wallet.id, WalletLedgerEntry.created_at >= start, WalletLedgerEntry.created_at < end)
            .order_by(WalletLedgerEntry.created_at.asc())
        )).scalars().all()

        credits = sum((Decimal(str(e.amount)) for e in entries if e.tx_type == LedgerTxType.CREDIT), Decimal("0"))
        debits = sum((Decimal(str(e.amount)) for e in entries if e.tx_type == LedgerTxType.DEBIT), Decimal("0"))
        closing = Decimal(str(entries[-1].balance_after)) if entries else opening

        by_type: dict = {}
        for e in entries:
            t = by_type.setdefault(e.reference_type.value, {"credits": Decimal("0"), "debits": Decimal("0"), "entries": 0})
            t["credits" if e.tx_type == LedgerTxType.CREDIT else "debits"] += Decimal(str(e.amount))
            t["entries"] += 1

        # A statement that doesn't add up is flagged, never silently "fixed".
        consistent = (opening + credits - debits).quantize(Decimal("0.0001")) == closing.quantize(Decimal("0.0001"))
        if end > now:
            consistent = consistent and closing.quantize(Decimal("0.0001")) == Decimal(str(wallet.balance)).quantize(Decimal("0.0001"))

        wallet_sections.append({
            "wallet_type": wallet.wallet_type.value,
            "currency": wallet.currency,
            "opening_balance": cents(opening),
            "credits": cents(credits),
            "debits": cents(debits),
            "closing_balance": cents(closing),
            "current_balance": cents(wallet.balance),
            "consistent": consistent,
            "by_type": {k: {"credits": cents(v["credits"]), "debits": cents(v["debits"]), "entries": v["entries"]} for k, v in sorted(by_type.items())},
            "entries": [
                {
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                    "tx_type": e.tx_type.value,
                    "reference_type": e.reference_type.value,
                    "reference_id": e.reference_id,
                    "description": e.description,
                    "amount": cents(e.amount),
                    "balance_after": cents(e.balance_after),
                }
                for e in entries
            ],
        })

    order_rows = (await db.execute(
        select(
            Order.status, func.count(Order.id),
            func.coalesce(func.sum(Order.total_amount), 0),
            func.coalesce(func.sum(Order.reseller_commission_amount), 0),
            func.count(Order.id).filter(Order.order_no.like("PTR-%")),
        )
        .where(Order.buyer_id == user_id, Order.is_reseller_order == True, Order.created_at >= start, Order.created_at < end)
        .group_by(Order.status)
    )).all()
    status_map = {s.value: {"orders": n, "amount": cents(total), "commission": cents(comm), "via_api": api} for s, n, total, comm, api in order_rows}
    completed = status_map.get("COMPLETED", {"orders": 0, "amount": "0.00", "commission": "0.00", "via_api": 0})

    return {
        "merchant": {
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "business_name": profile.business_name if profile else None,
            "commission_rate_pct": cents(profile.commission_rate_pct) if profile else None,
        },
        "period": {"start": start.isoformat(), "end": end.isoformat(), "month": start.strftime("%Y-%m")},
        "orders": {
            "completed": completed["orders"],
            "completed_via_api": completed["via_api"],
            "sales_volume": completed["amount"],
            "commission_earned": completed["commission"],
            "failed_refunded": status_map.get("FAILED", {}).get("orders", 0),
            "by_status": status_map,
        },
        "wallets": wallet_sections,
        "consistent": all(w["consistent"] for w in wallet_sections),
        "generated_at": now.isoformat(),
    }
