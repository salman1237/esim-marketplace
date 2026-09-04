"""Shared rate limiter instance.

Split into its own module (rather than living in main.py) so route
modules can import `limiter` and apply `@limiter.limit(...)` without a
circular import back to the app object. In-memory storage is fine here:
this runs as a single backend container, not a horizontally-scaled
fleet - see docker-compose.yml.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.config import settings

# Disabled outside production: the test suite (and local dev) calls
# /auth/register and /auth/login many times in a tight loop, which would
# otherwise trip these limits and make tests flaky for a reason that has
# nothing to do with what they're testing. Real abuse protection only
# matters where it's actually exposed to the internet.
limiter = Limiter(key_func=get_remote_address, enabled=settings.ENVIRONMENT == "production")


def get_partner_api_key(request):
    """Rate-limit key for /partner/* routes — keyed by the caller's raw
    API key rather than IP, since a partner's own backend typically calls
    from a small set of shared/NATed IPs that would otherwise pool every
    partner behind that IP into one limit."""
    return request.headers.get("X-API-Key") or get_remote_address(request)
