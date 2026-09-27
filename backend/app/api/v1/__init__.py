from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.catalog import router as catalog_router
from app.api.v1.wallets import router as wallets_router
from app.api.v1.orders import router as orders_router
from app.api.v1.payments import router as payments_router
from app.api.v1.settings import router as settings_router
from app.api.v1.admin import router as admin_router
from app.api.v1.kyc import router as kyc_router
from app.api.v1.partner import router as partner_router
from app.api.v1.merchant import router as merchant_router
from app.api.v1.finance import router as finance_router
from app.api.v1.withdrawals import router as withdrawals_router
from app.api.v1.discounts import router as discounts_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(auth_router)
api_v1_router.include_router(catalog_router)
api_v1_router.include_router(wallets_router)
api_v1_router.include_router(orders_router)
api_v1_router.include_router(payments_router)
api_v1_router.include_router(settings_router)
api_v1_router.include_router(admin_router)
api_v1_router.include_router(kyc_router)
api_v1_router.include_router(partner_router)
api_v1_router.include_router(merchant_router)
api_v1_router.include_router(finance_router)
api_v1_router.include_router(withdrawals_router)
api_v1_router.include_router(discounts_router)
