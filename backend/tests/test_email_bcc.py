"""Every outgoing email is blind-copied to the business mailbox.

The point is a single inbox holding a copy of everything a customer, merchant
or agent was actually sent - without the recipient seeing an internal address,
and without a visible Cc on every message that would read as bulk mail.
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.services.email_svc import EmailService

pytestmark = pytest.mark.asyncio


@pytest.fixture
def smtp(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "mail.example.test", raising=False)
    monkeypatch.setattr(settings, "SMTP_USERNAME", "hello@example.test", raising=False)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "secret", raising=False)
    monkeypatch.setattr(settings, "SMTP_PORT", 465, raising=False)
    monkeypatch.setattr(settings, "NOTICE_BCC_EMAIL", "records@example.test", raising=False)


async def _send_one(to="customer@example.test"):
    sender = AsyncMock()
    with patch("app.services.email_svc.aiosmtplib.send", sender):
        await EmailService._send(to, "Subject", "<p>Body</p>", text_body="Body")
    return sender


async def test_the_business_mailbox_is_added_to_the_envelope(smtp):
    sender = await _send_one()
    assert sender.await_args.kwargs["recipients"] == ["customer@example.test", "records@example.test"]


async def test_the_recipient_never_sees_the_blind_copy(smtp):
    """A Bcc that appears in the headers is not blind. The address belongs in
    the envelope only."""
    sender = await _send_one()
    message = sender.await_args.args[0]
    assert message["To"] == "customer@example.test"
    assert message["Bcc"] is None
    assert "records@example.test" not in message.as_string()


async def test_the_same_mail_is_not_sent_twice_to_the_business_mailbox(smtp):
    """When the recipient IS the business mailbox, one copy is enough."""
    sender = await _send_one(to="records@example.test")
    assert sender.await_args.kwargs["recipients"] == ["records@example.test"]


async def test_matching_is_case_insensitive(smtp):
    sender = await _send_one(to="RECORDS@example.TEST")
    assert sender.await_args.kwargs["recipients"] == ["RECORDS@example.TEST"]


async def test_an_empty_setting_turns_the_blind_copy_off(monkeypatch, smtp):
    monkeypatch.setattr(settings, "NOTICE_BCC_EMAIL", "", raising=False)
    sender = await _send_one()
    assert sender.await_args.kwargs["recipients"] == ["customer@example.test"]


async def test_a_failure_is_recorded_so_an_admin_can_be_told_why(monkeypatch, smtp):
    """Delivery used to fail into a container log nobody reads."""
    EmailService._last_error = None
    failing = AsyncMock(side_effect=ConnectionRefusedError("connection refused"))
    with patch("app.services.email_svc.aiosmtplib.send", failing):
        sent = await EmailService._send("customer@example.test", "S", "<p>B</p>")
    assert sent is False
    assert "connection refused" in (EmailService._last_error or "")


async def test_nothing_is_sent_when_smtp_is_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "", raising=False)
    monkeypatch.setattr(settings, "SMTP_USERNAME", "", raising=False)
    sender = AsyncMock()
    with patch("app.services.email_svc.aiosmtplib.send", sender):
        sent = await EmailService._send("customer@example.test", "S", "<p>B</p>")
    assert sent is False
    sender.assert_not_awaited()
