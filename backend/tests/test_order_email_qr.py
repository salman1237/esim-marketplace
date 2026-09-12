import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.services.email_svc import EmailService

pytestmark = pytest.mark.asyncio

LPA = "LPA:1$rsp.esim.pub$7C6661C51C6B67EF26D0D622BF625B10"


@pytest.fixture
def smtp_configured(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "mail.example.test", raising=False)
    monkeypatch.setattr(settings, "SMTP_USERNAME", "hello@example.test", raising=False)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "secret", raising=False)
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "hello@example.test", raising=False)
    monkeypatch.setattr(settings, "SMTP_PORT", 465, raising=False)


def _sent_message(sender):
    return sender.await_args.args[0]


def _part(msg, content_type):
    return next(
        p.get_payload(decode=True).decode()
        for p in msg.walk()
        if p.get_content_type() == content_type
    )


async def test_order_email_embeds_qr_and_activation_details(db_session, smtp_configured):
    sender = AsyncMock()
    with patch("app.services.email_svc.aiosmtplib.send", sender):
        await EmailService.send_order_confirmation(
            db_session, "customer@example.test", "ORD-1", "Singapore 3GB", "8986210115", LPA
        )

    msg = _sent_message(sender)

    # multipart/related must WRAP the alternative, otherwise Gmail renders
    # the cid: image as a broken placeholder.
    assert msg.get_content_type() == "multipart/related"
    assert msg.get_payload()[0].get_content_type() == "multipart/alternative"

    # Keyed by Content-ID, not by counting images: a deployment with a
    # brand logo uploaded carries that inline too, and the count would
    # depend on unrelated state.
    qr_parts = [p for p in msg.walk() if p.get("Content-ID") == "<esim_qr>"]
    assert len(qr_parts) == 1
    assert qr_parts[0].get_content_type() == "image/png"
    assert qr_parts[0].get_payload(decode=True)[:8] == b"\x89PNG\r\n\x1a\n"

    text = _part(msg, "text/plain")
    assert LPA in text
    assert "8986210115" in text

    assert msg["Date"]
    assert msg["Message-ID"]


async def test_order_email_renders_order_details_table(db_session, smtp_configured):
    """Customers get the same at-a-glance detail table the supplier's own
    delivery email shows, instead of just an ICCID and a code."""
    sender = AsyncMock()
    with patch("app.services.email_svc.aiosmtplib.send", sender):
        await EmailService.send_order_confirmation(
            db_session, "customer@example.test", "ADM-9", "Bangladesh, 3 Days, 3GB", "8986210179", LPA,
            validity_days=3,
            data_label="3.00 GB",
            purchase_reference="60084",
            purchased_at=datetime(2026, 7, 8, 22, 18, tzinfo=timezone.utc),
        )

    msg = _sent_message(sender)
    html = _part(msg, "text/html")
    text = _part(msg, "text/plain")

    for expected in ["Order Details", "ADM-9", "8986210179", "3 Days", "3.00 GB", "60084", "2026-07-08 22:18 UTC"]:
        assert expected in html, expected
        assert expected in text or expected == "Order Details", expected

    assert "Quick Installation Tips" in html


async def test_order_email_omits_rows_it_has_no_value_for(db_session, smtp_configured):
    """A table with blank cells reads as a bug - optional fields are left
    out entirely when the caller doesn't supply them."""
    sender = AsyncMock()
    with patch("app.services.email_svc.aiosmtplib.send", sender):
        await EmailService.send_order_confirmation(
            db_session, "customer@example.test", "ORD-2", "Singapore 3GB", "8986210115", LPA
        )

    html = _part(_sent_message(sender), "text/html")
    assert "Plan Validity" not in html
    assert "Purchase ID" not in html
    assert "Purchase Date" not in html
    assert "Order ID" in html


async def test_order_email_still_sends_when_qr_generation_fails(db_session, smtp_configured):
    """A broken QR must never cost the customer their delivery email - the
    activation code is in the body as copyable text regardless."""
    sender = AsyncMock()
    with patch("app.services.email_svc.qrcode.make", side_effect=RuntimeError("boom")), \
         patch("app.services.email_svc.aiosmtplib.send", sender):
        await EmailService.send_order_confirmation(
            db_session, "customer@example.test", "ORD-3", "Singapore 3GB", "8986210115", LPA
        )

    sender.assert_awaited_once()
    msg = _sent_message(sender)
    assert [p for p in msg.walk() if p.get("Content-ID") == "<esim_qr>"] == []
    html = _part(msg, "text/html")
    assert "cid:esim_qr" not in html
    assert LPA in html
