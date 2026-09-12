import pytest
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


async def test_order_email_embeds_qr_and_activation_details(db_session, smtp_configured):
    sender = AsyncMock()
    with patch("app.services.email_svc.aiosmtplib.send", sender):
        await EmailService.send_order_confirmation(
            db_session, "customer@example.test", "ORD-1", "Singapore 3GB", "8986210115", LPA
        )

    msg = _sent_message(sender)

    # QR rides along as an inline image so it renders without the client
    # fetching a remote URL (usually blocked, and worse for spam scoring).
    images = [p for p in msg.walk() if p.get_content_type() == "image/png"]
    assert len(images) == 1
    assert images[0].get("Content-ID") == "<esim_qr>"
    assert images[0].get_payload(decode=True)[:8] == b"\x89PNG\r\n\x1a\n"

    # Plain-text alternative carries the same details, for clients that
    # don't render HTML at all.
    text = next(
        p.get_payload(decode=True).decode()
        for p in msg.walk()
        if p.get_content_type() == "text/plain"
    )
    assert LPA in text
    assert "8986210115" in text

    # Headers that spam filters expect to exist.
    assert msg["Date"]
    assert msg["Message-ID"]


async def test_order_email_still_sends_when_qr_generation_fails(db_session, smtp_configured):
    """A broken QR must never cost the customer their delivery email - the
    activation code is in the body as copyable text regardless."""
    sender = AsyncMock()
    with patch("app.services.email_svc.qrcode.make", side_effect=RuntimeError("boom")), \
         patch("app.services.email_svc.aiosmtplib.send", sender):
        await EmailService.send_order_confirmation(
            db_session, "customer@example.test", "ORD-2", "Singapore 3GB", "8986210115", LPA
        )

    sender.assert_awaited_once()
    msg = _sent_message(sender)
    assert [p for p in msg.walk() if p.get_content_type() == "image/png"] == []
    html = next(
        p.get_payload(decode=True).decode()
        for p in msg.walk()
        if p.get_content_type() == "text/html"
    )
    assert "cid:esim_qr" not in html
    assert LPA in html
