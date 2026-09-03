import time
import httpx
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.payment import PaymentLog
from app.core.config import settings

class ShurjoPayService:
    @staticmethod
    async def authenticate(db: AsyncSession) -> dict:
        url = f"{settings.SHURJOPAY_BASE_URL}/api/get_token"
        payload = {
            "username": settings.SHURJOPAY_USERNAME,
            "password": settings.SHURJOPAY_PASSWORD
        }
        async with httpx.AsyncClient(verify=True, timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
            
            # Log
            log = PaymentLog(
                gateway="SHURJOPAY",
                endpoint="api/get_token",
                request_payload={"username": settings.SHURJOPAY_USERNAME},
                response_payload=data,
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
        auth_data = await ShurjoPayService.authenticate(db)
        token = auth_data.get("token")
        store_id = auth_data.get("store_id")

        if not token:
            raise Exception("Failed to get ShurjoPay authorization token")

        url = f"{settings.SHURJOPAY_BASE_URL}/api/secret-pay"
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "prefix": settings.SHURJOPAY_PREFIX,
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
                request_payload=payload,
                response_payload=data,
                status_code=resp.status_code
            )
            db.add(log)
            await db.commit()
            return data

    @staticmethod
    async def verify_payment(db: AsyncSession, order_id: str) -> dict:
        auth_data = await ShurjoPayService.authenticate(db)
        token = auth_data.get("token")
        url = f"{settings.SHURJOPAY_BASE_URL}/api/verification"
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
