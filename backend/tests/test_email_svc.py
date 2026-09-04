import pytest
from app.services.email_svc import EmailService
from app.core.config import settings

pytestmark = pytest.mark.asyncio


async def test_smtp_not_configured_in_test_env():
    """CI/local tests never have real SMTP creds - confirms the safety
    net this whole service is built around actually engages here."""
    assert settings.smtp_configured is False


async def test_send_welcome_does_not_raise_when_unconfigured(db_session):
    # Must not raise even though nothing is actually sent - registration
    # must never fail because email isn't configured.
    await EmailService.send_welcome(db_session, "nobody@example.com", "testuser")


async def test_send_password_reset_does_not_raise_when_unconfigured(db_session):
    await EmailService.send_password_reset(db_session, "nobody@example.com", "some-token")


async def test_send_order_confirmation_does_not_raise_when_unconfigured(db_session):
    await EmailService.send_order_confirmation(
        db_session, "nobody@example.com", "ORD-TEST-001", "Thailand 5GB", "8988...", "LPA:1$test$test"
    )


async def test_templates_render_with_real_platform_name(db_session):
    """Regression-proofing: a Jinja2 template typo (undefined variable,
    bad block tag) would only surface at render time, not import time -
    make sure it actually renders without raising."""
    from app.services.email_svc import _env

    html = _env.get_template("welcome.html").render(
        platform_name="Test Platform", username="tester",
        frontend_base_url="https://example.com", year=2026,
    )
    assert "Test Platform" in html
    assert "tester" in html
