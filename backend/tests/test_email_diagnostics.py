"""The admin console can tell whether outgoing mail actually works.

"Emails aren't arriving" used to be indistinguishable from "emails are
arriving in spam": a missing SMTP_HOST logged a warning inside the container
and nothing else. These endpoints answer it without shell access.
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.core.config import settings
from conftest import register_and_login

pytestmark = pytest.mark.asyncio


async def _admin(client, promote_role, name="mailadmin"):
    admin = await register_and_login(client, name)
    await promote_role(admin["user_id"], "SUPER_ADMIN")
    return admin


async def test_settings_report_what_the_server_is_actually_configured_with(client, promote_role, monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "mail.example.test", raising=False)
    monkeypatch.setattr(settings, "SMTP_USERNAME", "hello@example.test", raising=False)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "secret", raising=False)
    monkeypatch.setattr(settings, "SMTP_PORT", 465, raising=False)
    monkeypatch.setattr(settings, "NOTICE_BCC_EMAIL", "records@example.test", raising=False)

    admin = await _admin(client, promote_role)
    body = (await client.get("/api/v1/admin/notification-settings", headers=admin["headers"])).json()

    assert body["smtp_configured"] is True
    assert body["smtp_host"] == "mail.example.test"
    assert body["smtp_mode"] == "implicit TLS (SMTPS)"
    assert body["bcc_email"] == "records@example.test"
    assert body["missing_settings"] == []


async def test_missing_settings_are_named_rather_than_just_flagged(client, promote_role, monkeypatch):
    """"Not configured" is not actionable. Which variable is missing, is."""
    monkeypatch.setattr(settings, "SMTP_HOST", "", raising=False)
    monkeypatch.setattr(settings, "SMTP_USERNAME", "", raising=False)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "", raising=False)

    admin = await _admin(client, promote_role, "mailadmin2")
    body = (await client.get("/api/v1/admin/notification-settings", headers=admin["headers"])).json()

    assert body["smtp_configured"] is False
    assert set(body["missing_settings"]) == {"SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD"}


async def test_the_test_button_explains_an_unconfigured_server(client, promote_role, monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "", raising=False)
    monkeypatch.setattr(settings, "SMTP_USERNAME", "", raising=False)

    admin = await _admin(client, promote_role, "mailadmin3")
    res = await client.post("/api/v1/admin/notification-settings/test",
                            json={"to_email": "someone@example.com"}, headers=admin["headers"])
    body = res.json()
    assert res.status_code == 200
    assert body["sent"] is False
    assert "SMTP_HOST" in body["reason"]


async def test_the_test_button_sends_a_real_email_when_configured(client, promote_role, monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "mail.example.test", raising=False)
    monkeypatch.setattr(settings, "SMTP_USERNAME", "hello@example.test", raising=False)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "secret", raising=False)
    monkeypatch.setattr(settings, "SMTP_PORT", 465, raising=False)

    admin = await _admin(client, promote_role, "mailadmin4")
    sender = AsyncMock()
    with patch("app.services.email_svc.aiosmtplib.send", sender):
        res = await client.post("/api/v1/admin/notification-settings/test",
                                json={"to_email": "someone@example.com"}, headers=admin["headers"])
    assert res.json()["sent"] is True
    sender.assert_awaited()


async def test_the_test_button_reports_the_failure_instead_of_claiming_success(client, promote_role, monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "mail.example.test", raising=False)
    monkeypatch.setattr(settings, "SMTP_USERNAME", "hello@example.test", raising=False)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "secret", raising=False)

    admin = await _admin(client, promote_role, "mailadmin5")
    failing = AsyncMock(side_effect=ConnectionRefusedError("connection refused"))
    with patch("app.services.email_svc.aiosmtplib.send", failing):
        res = await client.post("/api/v1/admin/notification-settings/test",
                                json={"to_email": "someone@example.com"}, headers=admin["headers"])
    body = res.json()
    assert body["sent"] is False
    assert "connection refused" in body["reason"]


async def test_a_plain_customer_cannot_read_the_mail_server_settings(client):
    user = await register_and_login(client, "mailnosy")
    res = await client.get("/api/v1/admin/notification-settings", headers=user["headers"])
    assert res.status_code == 403


async def test_a_plain_customer_cannot_send_test_emails(client):
    """Otherwise the button is an open relay for anyone with an account."""
    user = await register_and_login(client, "mailnosy2")
    res = await client.post("/api/v1/admin/notification-settings/test",
                            json={"to_email": "someone@example.com"}, headers=user["headers"])
    assert res.status_code == 403
