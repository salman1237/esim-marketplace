"""Admin finance & reconciliation reports - see services/finance_svc.py."""
from datetime import date as Date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_admin
from app.services import finance_svc

router = APIRouter(prefix="/admin/finance", tags=["Finance & Reconciliation"], dependencies=[Depends(require_admin)])


def _period(date_from: Optional[Date], date_to: Optional[Date]):
    try:
        return finance_svc.period_bounds(date_from, date_to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _month(month: Optional[str]):
    try:
        return finance_svc.month_bounds(month or datetime.now(timezone.utc).strftime("%Y-%m"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _csv(content: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/summary")
async def finance_summary(date_from: Optional[Date] = None, date_to: Optional[Date] = None, db: AsyncSession = Depends(get_db)):
    start, end = _period(date_from, date_to)
    return await finance_svc.money_cycle_summary(db, start, end)


@router.get("/vivape")
async def vivape_reconciliation(date_from: Optional[Date] = None, date_to: Optional[Date] = None, db: AsyncSession = Depends(get_db)):
    start, end = _period(date_from, date_to)
    return await finance_svc.vivape_reconciliation(db, start, end)


@router.get("/vivape.csv")
async def vivape_reconciliation_csv(date_from: Optional[Date] = None, date_to: Optional[Date] = None, db: AsyncSession = Depends(get_db)):
    start, end = _period(date_from, date_to)
    rows = await finance_svc.vivape_orders(db, start, end)
    return _csv(finance_svc.vivape_orders_csv(rows), f"vivape-charges-{start.date()}-to-{end.date()}.csv")


@router.get("/merchant-statement")
async def merchant_statement(user_id: str, month: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    start, end = _month(month)
    statement = await finance_svc.merchant_statement(db, user_id, start, end)
    if not statement:
        raise HTTPException(status_code=404, detail="User not found")
    return statement


@router.get("/merchant-statement.csv")
async def merchant_statement_csv(user_id: str, month: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    start, end = _month(month)
    statement = await finance_svc.merchant_statement(db, user_id, start, end)
    if not statement:
        raise HTTPException(status_code=404, detail="User not found")
    name = statement["merchant"]["username"]
    return _csv(finance_svc.statement_csv(statement), f"statement-{name}-{statement['period']['month']}.csv")
