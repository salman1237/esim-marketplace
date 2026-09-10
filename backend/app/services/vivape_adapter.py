import time
import httpx
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit import SupplierTransactionLog
from app.core.config import settings

class VivaPeAdapter:
    _token = None
    _token_expiry = 0

    @classmethod
    async def get_token(cls, db: AsyncSession, force_refresh: bool = False) -> str:
        if not force_refresh and cls._token and time.time() < cls._token_expiry:
            return cls._token

        url = f"{settings.VIVAPE_BASE_URL}/login"
        form_data = {
            "email": settings.VIVAPE_EMAIL,
            "password": settings.VIVAPE_PASSWORD
        }
        start_time = time.time()
        status_code = 0
        resp_data = None
        try:
            async with httpx.AsyncClient(verify=True, timeout=15.0) as client:
                resp = await client.post(url, data=form_data)
                status_code = resp.status_code
                try:
                    resp_data = resp.json()
                except Exception:
                    resp_data = {"raw": resp.text}

                token = resp_data.get("access_token") if isinstance(resp_data, dict) else None
                if resp.status_code == 200 and token:
                    cls._token = token
                    # Empirically much shorter-lived than any documented
                    # value: a token obtained at process start began
                    # failing (with a misleading 200 + generic error body,
                    # not 401) about 70 minutes later. Cache conservatively
                    # short; create_transaction() also force-refreshes and
                    # retries once on failure as a backstop against this.
                    cls._token_expiry = time.time() + 1800  # 30 min cache
                    return cls._token
                raise Exception(f"VivaPe login failed: {resp.status_code} - {resp.text}")
        finally:
            latency = int((time.time() - start_time) * 1000)
            log = SupplierTransactionLog(
                supplier_name="VIVAPE",
                endpoint="login",
                method="POST",
                request_payload={"email": settings.VIVAPE_EMAIL, "password": "***REDACTED***"},
                response_payload={k: v for k, v in (resp_data or {}).items() if k != "access_token"} if isinstance(resp_data, dict) else resp_data,
                status_code=status_code,
                latency_ms=latency
            )
            db.add(log)
            await db.commit()

    @classmethod
    async def call_api(cls, db: AsyncSession, method: str, endpoint: str, data: dict = None, params: dict = None, force_fresh_token: bool = False) -> dict:
        token = await cls.get_token(db, force_refresh=force_fresh_token)
        url = f"{settings.VIVAPE_BASE_URL}/{endpoint.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

        start_time = time.time()
        status_code = 0
        resp_data = None
        error_msg = None

        try:
            async with httpx.AsyncClient(verify=True, timeout=30.0) as client:
                if method.upper() == "GET":
                    resp = await client.get(url, headers=headers, params=params)
                else:
                    # VivaPe endpoints use FormData
                    resp = await client.post(url, headers=headers, data=data)
                
                status_code = resp.status_code
                try:
                    resp_data = resp.json()
                except Exception:
                    resp_data = {"raw": resp.text}
                return resp_data
        except Exception as e:
            error_msg = str(e)
            raise
        finally:
            latency = int((time.time() - start_time) * 1000)
            # Log supplier call
            log = SupplierTransactionLog(
                supplier_name="VIVAPE",
                endpoint=endpoint,
                method=method.upper(),
                request_payload={"params": params, "data": data},
                response_payload=resp_data or {"error": error_msg},
                status_code=status_code,
                latency_ms=latency
            )
            db.add(log)
            await db.commit()

    @classmethod
    async def get_countries(cls, db: AsyncSession) -> list:
        data = await cls.call_api(db, "GET", "countries")
        if isinstance(data, dict) and data.get("success"):
            return data.get("data", [])
        elif isinstance(data, list):
            return data
        return data.get("countries", []) if isinstance(data, dict) else []

    @classmethod
    async def get_products(cls, db: AsyncSession, country_id: int) -> list:
        data = await cls.call_api(db, "GET", "products", params={"country_id": country_id})
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            return data.get("data", []) or data.get("products", [])
        return []

    @classmethod
    async def create_transaction(cls, db: AsyncSession, product_id: int, receiver_amount: Decimal) -> dict:
        # VivaPe's own Postman example marks `phone` disabled for
        # activity=esim create-transaction calls (it's for the topup
        # activity type) — sending it was untested and is dropped here.
        # receiver_amount is sent as VivaPe's own example formats it
        # ("1000", not "1000.0") — str(Decimal) keeps trailing zeros
        # (Decimal("1000.0000") -> "1000.0000"), which live testing
        # showed VivaPe rejects with a generic "Transaction Failed!!".
        amount_str = f"{receiver_amount.normalize():f}"
        payload = {
            "product_id": str(product_id),
            "receiver_amount": amount_str,
            "activity": "esim"
        }
        result = await cls.call_api(db, "POST", "create-transaction", data=payload)

        # VivaPe's cached-token lifetime is far shorter in practice than the
        # 6-day window we cache it for (confirmed live: a token obtained at
        # redeploy started returning failures ~70 minutes later). Critically,
        # a stale/invalid token doesn't get a 401 here - VivaPe returns HTTP
        # 200 with a generic business-sounding error ("Insufficient
        # Balance.", "Transaction Failed!!") indistinguishable by message
        # alone from a real failure. Since no purchase_trx.id means VivaPe
        # never actually created a transaction (nothing to double-charge),
        # it's always safe to force a fresh login and retry once before
        # treating it as a genuine failure.
        purchase_trx = result.get("purchase_trx") if isinstance(result, dict) else None
        trx_id = purchase_trx.get("id") if isinstance(purchase_trx, dict) else None
        if not trx_id:
            result = await cls.call_api(db, "POST", "create-transaction", data=payload, force_fresh_token=True)

        return result

    @classmethod
    async def get_esim_by_trx(cls, db: AsyncSession, trx_id: int) -> dict:
        return await cls.call_api(db, "POST", "get-esim-by-trx", data={"trx_id": str(trx_id)})
