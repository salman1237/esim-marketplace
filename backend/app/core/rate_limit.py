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
from app.core.security import decode_access_token

# Disabled outside production: the test suite (and local dev) calls
# /auth/register and /auth/login many times in a tight loop, which would
# otherwise trip these limits and make tests flaky for a reason that has
# nothing to do with what they're testing. Real abuse protection only
# matters where it's actually exposed to the internet.
limiter = Limiter(key_func=get_remote_address, enabled=settings.ENVIRONMENT == "production")


def get_partner_api_key(request):
    """Rate-limit key for /partner/* routes — keyed by the caller's
    partner access token (decoded just far enough to read its ApiKey id)
    rather than IP, since a partner's own backend typically calls from a
    small set of shared/NATed IPs that would otherwise pool every partner
    behind that IP into one limit. Falls back to IP if the token is
    missing/invalid — the route's own auth dependency is what actually
    rejects bad tokens, this just needs *a* stable bucket key."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        payload = decode_access_token(auth_header[len("Bearer "):])
        if payload and payload.get("role") == "PARTNER_API" and payload.get("sub"):
            return payload["sub"]
    return get_remote_address(request)
