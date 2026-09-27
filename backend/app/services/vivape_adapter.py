import asyncio
import time
import httpx
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit import SupplierTransactionLog
from app.core.config import settings

class VivaPeAdapter:
    """All calls MUST negotiate HTTP/2 (see http2=True on every
    httpx.AsyncClient below). Root-caused live on 2026-09-10/11: httpx
    defaults to HTTP/1.1-only, while curl (and every browser) negotiates
    HTTP/2 by default. Every one of ~27 real create-transaction attempts
    from this app that night failed with a generic error over HTTP/1.1,
    while curl succeeded for the identical account/product/payload almost
    every time. Explicitly forcing http2=True (requires the `h2` package)
    made identical requests succeed reliably in a controlled side-by-side
    test - VivaPe's origin (behind Cloudflare) appears to route HTTP/1.1
    and HTTP/2 traffic differently, with the HTTP/1.1 path broken for
    this endpoint specifically. Removing http2=True silently reintroduces
    that near-100% failure rate."""
    _token = None
    _token_expiry = 0
    _token_generation = 0
    _token_lock = asyncio.Lock()

    @classmethod
    async def get_token(cls, db: AsyncSession, force_refresh: bool = False) -> str:
        if not force_refresh and cls._token and time.time() < cls._token_expiry:
            return cls._token

        # VivaPe appears to invalidate a prior token the moment a NEW login
        # happens for the same account (single active session). This class
        # has multiple concurrent callers in the same process - live
        # checkouts, this method's own force_refresh retries, and the
        # periodic/on-deploy catalog sync (see main.py) - and without a
        # lock, two of them refreshing at once would each get a token, and
        # whichever login response the account processes second silently
        # kills the other's token before it's ever used. Confirmed live:
        # a token obtained and used within the same call still failed with
        # a misleading 200 + generic error body, while an isolated call
        # with no concurrent VivaPe traffic from this process succeeded
        # for the identical payload every time. Serializing refreshes (and
        # having a waiter re-check the cache once it acquires the lock, so
        # it reuses whatever the winner just got instead of logging in
        # again) removes that race entirely.
        generation_before_wait = cls._token_generation
        async with cls._token_lock:
            already_refreshed = cls._token_generation > generation_before_wait
            if cls._token and time.time() < cls._token_expiry and (already_refreshed or not force_refresh):
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
                async with httpx.AsyncClient(verify=True, timeout=15.0, http2=True) as client:
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
                        # failing (with a misleading 200 + generic error
                        # body, not 401) about 70 minutes later. Cache
                        # conservatively short; create_transaction() also
                        # force-refreshes and retries on failure as a
                        # backstop against this.
                        cls._token_expiry = time.time() + 1800  # 30 min cache
                        cls._token_generation += 1
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
            async with httpx.AsyncClient(verify=True, timeout=30.0, http2=True) as client:
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
        def _trx_id(r):
            purchase_trx = r.get("purchase_trx") if isinstance(r, dict) else None
            return purchase_trx.get("id") if isinstance(purchase_trx, dict) else None

        result = await cls.call_api(db, "POST", "create-transaction", data=payload)

        # VivaPe's cached-token lifetime is far shorter in practice than the
        # 6-day window we cache it for (confirmed live: a token obtained at
        # redeploy started returning failures ~70 minutes later). Critically,
        # a stale/invalid token doesn't get a 401 here - VivaPe returns HTTP
        # 200 with a generic business-sounding error ("Insufficient
        # Balance.", "Transaction Failed!!") indistinguishable by message
        # alone from a real failure. Since no purchase_trx.id means VivaPe
        # never actually created a transaction (nothing to double-charge),
        # it's always safe to retry with a fresh login before treating it
        # as a genuine failure.
        #
        # One delayed retry only. Earlier failures blamed on transient token
        # and settle-window issues turned out to be the app authenticating
        # to an empty VivaPe account, so extra attempts mostly just delayed
        # a genuine failure - and with provisioning now in the background,
        # a long retry chain only holds an order in PROCESSING for longer.
        for delay in (2.0,):
            if _trx_id(result):
                break
            await asyncio.sleep(delay)
            result = await cls.call_api(db, "POST", "create-transaction", data=payload, force_fresh_token=True)

        return result

    @classmethod
    async def get_esim_by_trx(cls, db: AsyncSession, trx_id: int) -> dict:
        return await cls.call_api(db, "POST", "get-esim-by-trx", data={"trx_id": str(trx_id)})

    @staticmethod
    def _esim_lookup(trx_id, iccid) -> dict:
        """VivaPe's diagnostics endpoints accept either identifier. The
        transaction id is preferred because it is what VivaPe's own status
        page keys on; the ICCID is the fallback for a profile whose order
        somehow has no supplier reference."""
        if trx_id:
            return {"transaction_id": str(trx_id)}
        if iccid:
            return {"iccid": str(iccid)}
        raise ValueError("Need a transaction id or an ICCID to look up an eSIM")

    @classmethod
    async def get_esim_usage(cls, db: AsyncSession, trx_id=None, iccid=None, refresh: bool = False) -> dict:
        """Live data usage. `refresh=true` makes VivaPe poll the upstream
        carrier instead of serving its own cache, so it is only sent when a
        human asked for fresh numbers."""
        payload = cls._esim_lookup(trx_id, iccid)
        if refresh:
            payload["refresh"] = "true"
        return await cls.call_api(db, "POST", "esim/usage", data=payload)

    @classmethod
    async def get_esim_device_info(cls, db: AsyncSession, trx_id=None, iccid=None) -> dict:
        """Whether the profile is installed, on which handset, and the
        carrier's provisioning event history. Its `history` is a superset of
        what esim/installation-progress returns, so only this is called."""
        return await cls.call_api(db, "POST", "esim/device-info", data=cls._esim_lookup(trx_id, iccid))

    @classmethod
    async def get_account_profile(cls, db: AsyncSession) -> dict:
        """Our own VivaPe account, including the prepaid balance every
        purchase is drawn from. A stale/invalid token or an empty account
        both surface as an HTTP 200 with a generic business error from
        create-transaction, so being able to read the balance directly is
        the only honest early warning."""
        return await cls.call_api(db, "GET", "user/profile")
