import time
import httpx
from decimal import Decimal
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.payment import PaymentLog
from app.core.config import settings
from app.services.gateway_config_svc import ShurjoPayConfig, get_shurjopay_config

class ShurjoPayService:
    # Credentials come from the admin console when a Super Admin has saved
    # them, otherwise from the SHURJOPAY_* environment settings - see
    # gateway_config_svc. Resolved per call so a change applies immediately.

    @staticmethod
    async def authenticate(db: AsyncSession, config: Optional[ShurjoPayConfig] = None) -> dict:
        config = config or await get_shurjopay_config(db)
        url = f"{config.base_url}/api/get_token"
        payload = {
            "username": config.username,
            "password": config.password
        }
        async with httpx.AsyncClient(verify=True, timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()

            # Log - never the password or the bearer token.
            log = PaymentLog(
                gateway="SHURJOPAY",
                endpoint="api/get_token",
                request_payload={"username": config.username, "base_url": config.base_url},
                response_payload={k: v for k, v in data.items() if k != "token"} if isinstance(data, dict) else data,
                status_code=resp.status_code
            )
            db.add(log)
            await db.commit()
            return data

    @staticmethod
    async def initiate_payment(
        db: AsyncSession,
        order_id: str,
        amount_bdt: Decimal,
        customer_name: str,
        customer_email: str,
        customer_phone: str,
        customer_address: str = "Dhaka, Bangladesh",
        customer_post_code: str = "1212",
        client_ip: str = "127.0.0.1"
    ) -> dict:
        config = await get_shurjopay_config(db)
        auth_data = await ShurjoPayService.authenticate(db, config)
        token = auth_data.get("token")
        store_id = auth_data.get("store_id")

        if not token:
            raise Exception("Failed to get ShurjoPay authorization token")

        url = f"{config.base_url}/api/secret-pay"
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "prefix": config.prefix,
            "token": token,
            "return_url": settings.SHURJOPAY_RETURN_URL,
            "cancel_url": settings.SHURJOPAY_CANCEL_URL,
            "store_id": store_id,
            "amount": str(amount_bdt),
            "order_id": order_id,
            "currency": "BDT",
            "customer_name": customer_name,
            "customer_email": customer_email,
            "customer_phone": customer_phone or "01700000000",
            "customer_address": customer_address,
            "customer_city": "Dhaka",
            "customer_post_code": customer_post_code,
            "client_ip": client_ip
        }

        async with httpx.AsyncClient(verify=True, timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            data = resp.json()

            log = PaymentLog(
                gateway="SHURJOPAY",
                order_id=order_id,
                endpoint="api/secret-pay",
                request_payload={k: v for k, v in payload.items() if k != "token"},
                response_payload=data,
                status_code=resp.status_code
            )
            db.add(log)
            await db.commit()
            return data

    @staticmethod
    async def verify_payment(db: AsyncSession, order_id: str) -> dict:
        config = await get_shurjopay_config(db)
        auth_data = await ShurjoPayService.authenticate(db, config)
        token = auth_data.get("token")
        url = f"{config.base_url}/api/verification"
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(verify=True, timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json={"order_id": order_id})
            data = resp.json()

            log = PaymentLog(
                gateway="SHURJOPAY",
                order_id=order_id,
                endpoint="api/verification",
                request_payload={"order_id": order_id},
                response_payload=data,
                status_code=resp.status_code
            )
            db.add(log)
            await db.commit()
            return data
