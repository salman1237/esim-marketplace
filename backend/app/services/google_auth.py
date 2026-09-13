"""Verifies "Sign in with Google" ID tokens.

Google Identity Services gives the browser a signed ID token (a JWT) and
the frontend posts it to POST /auth/google. Nothing in it is trusted until
it passes every check Google requires of a backend:

  - RS256 signature, against Google's published signing keys (JWKS)
  - `aud` is our own OAuth client ID - a token minted for another app that
    uses Google sign-in must not log anyone in here
  - `iss` is accounts.google.com, and `exp` has not passed

Google rotates its signing keys, so the key set is cached for the max-age
Google sends and refetched once when a token names a key we don't have.
"""
import re
import time

import httpx
from jose import JWTError, jwt

from app.core.logging import get_logger

logger = get_logger(__name__)

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
CLOCK_SKEW_SECONDS = 60
DEFAULT_JWKS_TTL_SECONDS = 3600


class GoogleTokenError(Exception):
    """The credential is not a valid Google ID token for this app."""


class GoogleUnavailableError(Exception):
    """Google's signing keys couldn't be fetched, so nothing can be verified."""


_cache: dict = {"jwks": None, "expires_at": 0.0}


def _reset_cache() -> None:
    _cache.update(jwks=None, expires_at=0.0)


async def _fetch_google_jwks() -> tuple[dict, int]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(GOOGLE_JWKS_URL)
        resp.raise_for_status()
    match = re.search(r"max-age=(\d+)", resp.headers.get("cache-control", ""))
    return resp.json(), int(match.group(1)) if match else DEFAULT_JWKS_TTL_SECONDS


async def _get_jwks(force_refresh: bool = False) -> dict:
    fresh = _cache["jwks"] is not None and time.monotonic() < _cache["expires_at"]
    if fresh and not force_refresh:
        return _cache["jwks"]
    try:
        jwks, max_age = await _fetch_google_jwks()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("google_jwks_fetch_failed", error=str(e))
        # Keys rotate slowly; a stale set beats locking everyone out.
        if _cache["jwks"] is not None:
            return _cache["jwks"]
        raise GoogleUnavailableError("Couldn't reach Google to verify sign-in") from e
    _cache.update(jwks=jwks, expires_at=time.monotonic() + max_age)
    return jwks


def _key_for(jwks: dict, kid: str) -> dict | None:
    return next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)


async def verify_google_id_token(credential: str, client_id: str) -> dict:
    """Returns the verified claims (sub, email, email_verified, name,
    picture, ...) or raises GoogleTokenError / GoogleUnavailableError."""
    try:
        header = jwt.get_unverified_header(credential)
    except JWTError:
        raise GoogleTokenError("Malformed Google credential")
    if header.get("alg") != "RS256" or not header.get("kid"):
        raise GoogleTokenError("Unexpected Google token header")

    key = _key_for(await _get_jwks(), header["kid"])
    if key is None:
        key = _key_for(await _get_jwks(force_refresh=True), header["kid"])
    if key is None:
        raise GoogleTokenError("Token signed with an unknown Google key")

    try:
        claims = jwt.decode(
            credential, key, algorithms=["RS256"], audience=client_id,
            options={"leeway": CLOCK_SKEW_SECONDS, "verify_at_hash": False},
        )
    except JWTError as e:
        raise GoogleTokenError(f"Invalid Google token: {e}")

    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleTokenError("Token was not issued by Google")
    if not claims.get("sub") or not claims.get("email"):
        raise GoogleTokenError("Google token is missing the account id or email")
    return claims
