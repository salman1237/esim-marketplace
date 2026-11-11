"""Inbound webhook receiver for eSIM Access (reference doc §5) - the
primary fulfilment signal this project was missing entirely until now;
everything else (checkout's own polling loop, the customer status page,
recover_stuck_orders) only ever pulled via esim/query. This endpoint is
the push side: eSIM Access POSTs here the moment something changes,
instead of us finding out up to TTL/poll-interval minutes later.

Four event types, one envelope: {"notifyType": "...", "content": {...}}
(confirmed shape, §5). The payload's own status/usage fields are NEVER
trusted for anything consequential - exactly the same discipline
payments.py's ShurjoPay IPN handler already follows (only an id is read
from the body; the real state is re-fetched from the authoritative
source). Here that means: use orderNo/iccid to find the right row, then
let try_complete_order_from_webhook / esim_telemetry_svc's own
query_esim call establish the real state.

No signature or shared secret is documented anywhere in the reference
doc for this webhook (unlike, say, a typical HMAC-signed provider
webhook) - §4.6/§5 describe registering a plain HTTPS URL via
webhook/save with no mention of a signing scheme. Because nothing here
is trusted blindly (every event just triggers a re-fetch of the real
state, never a direct DB write from the payload), an unauthenticated
endpoint is safe: the worst a forged call can do is trigger a redundant,
harmless esim/query against our own eSIM Access account.

Always returns 200 for a syntactically valid envelope, even an unknown
notifyType or an identifier that matches nothing in this project - a
4xx/5xx here would make eSIM Access retry forever for events that were
never going to resolve to anything on our side.
"""
from fastapi import APIRouter, Request
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.core.database import get_db
from app.core.logging import get_logger
from app.services import esim_telemetry_svc
from app.services.order_fulfilment import try_complete_order_from_webhook

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["eSIM Access Webhook"])


@router.post("/esimaccess")
async def esimaccess_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        logger.warning("esimaccess_webhook_invalid_json")
        return {"status": "ignored", "reason": "invalid json"}

    if not isinstance(payload, dict):
        return {"status": "ignored", "reason": "not an object"}

    notify_type = payload.get("notifyType")
    content = payload.get("content")
    content = content if isinstance(content, dict) else {}
    order_no = content.get("orderNo")
    iccid = content.get("iccid")

    logger.info("esimaccess_webhook_received", notify_type=notify_type, order_no=order_no, iccid=iccid)

    if notify_type == "ORDER_STATUS":
        if order_no:
            await try_complete_order_from_webhook(order_no)
    elif notify_type in ("ESIM_STATUS", "DATA_USAGE", "VALIDITY_USAGE"):
        if iccid or order_no:
            await esim_telemetry_svc.refresh_by_iccid_or_order_no(db, iccid=iccid, order_no=order_no)
    else:
        logger.warning("esimaccess_webhook_unknown_notify_type", notify_type=notify_type)

    return {"status": "received"}
