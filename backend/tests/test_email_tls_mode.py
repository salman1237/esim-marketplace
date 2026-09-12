import pytest
from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.services.email_svc import EmailService

pytestmark = pytest.mark.asyncio


@pytest.fixture
def smtp_configured(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "bdix.example.test", raising=False)
    monkeypatch.setattr(settings, "SMTP_USERNAME", "hello@example.test", raising=False)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "secret", raising=False)
    monkeypatch.setattr(settings, "SMTP_USE_TLS", True, raising=False)


async def test_port_465_uses_implicit_tls(monkeypatch, smtp_configured):
    """465 is SMTPS: encrypted from the first byte, with no STARTTLS
    command to issue. Sending start_tls=True there makes the handshake
    hang until the timeout instead of failing fast."""
    monkeypatch.setattr(settings, "SMTP_PORT", 465, raising=False)
    sender = AsyncMock()

    with patch("app.services.email_svc.aiosmtplib.send", sender):
        sent = await EmailService._send("to@example.test", "Subject", "<p>body</p>")

    assert sent is True
    kwargs = sender.await_args.kwargs
    assert kwargs["use_tls"] is True
    assert kwargs["start_tls"] is False
    assert kwargs["port"] == 465


async def test_port_587_uses_starttls(monkeypatch, smtp_configured):
    monkeypatch.setattr(settings, "SMTP_PORT", 587, raising=False)
    sender = AsyncMock()

    with patch("app.services.email_svc.aiosmtplib.send", sender):
        sent = await EmailService._send("to@example.test", "Subject", "<p>body</p>")

    assert sent is True
    kwargs = sender.await_args.kwargs
    assert kwargs["use_tls"] is False
    assert kwargs["start_tls"] is True


async def test_unconfigured_smtp_is_a_no_op_not_an_error(monkeypatch):
    """Checkout and password reset must never fail because email isn't
    set up - the send is best-effort and returns False instead."""
    monkeypatch.setattr(settings, "SMTP_HOST", "", raising=False)
    monkeypatch.setattr(settings, "SMTP_USERNAME", "", raising=False)
    sender = AsyncMock()

    with patch("app.services.email_svc.aiosmtplib.send", sender):
        sent = await EmailService._send("to@example.test", "Subject", "<p>body</p>")

    assert sent is False
    sender.assert_not_awaited()
