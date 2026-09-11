# Partner Reseller API — Documentation

Base URL: `https://triptel.co/api/v1/partner`

This API lets an approved reseller partner browse the eSIM catalog, place orders on behalf of their own customers, and receive delivery confirmation — either by polling or via a signed webhook — from their own backend, without a browser session.

Getting a partner set up is an **admin-only, manual step**: a Super Admin issues your API key from the admin console (Merchants tab → API Access) once your merchant application is approved. There is no self-service signup for API access.

---

## 1. Authentication

All `/partner/*` endpoints except the token endpoint itself require a **Bearer access token** in the `Authorization` header. The long-lived API key you were issued (`esim_live_...`) is **never** sent on these calls directly — it is only ever used once, to obtain a token.

### 1.1 Exchange your API key for an access token

```
POST /api/v1/partner/auth/token
Content-Type: application/json

{
  "api_key": "esim_live_1a2b3c4d5e6f7g8h..."
}
```

**Response `200`:**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

- Tokens are valid for **1 hour** (`expires_in` is in seconds). There is no refresh token — when a token expires, call this endpoint again with your API key to get a new one. This is a standard OAuth2 Client Credentials–style flow.
- `401 Unauthorized` if the key is invalid, malformed, or has been revoked.
- Rate limited to **10 requests/minute per IP**.

### 1.2 Use the token on every other call

```
GET /api/v1/partner/me
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

- `401 Unauthorized` if the token is missing, malformed, expired, or was issued for a different purpose (e.g. you cannot use a regular user login token here, and this token cannot be used against the regular customer-facing API either — the two are strictly separated even though both are JWTs).
- If your key is revoked by an admin, any tokens already issued for it stop working on their very next use (revocation is checked on every call, not just at token-issuance time) — you don't have to wait out the full hour.

### Example: full flow with `curl`

```bash
TOKEN=$(curl -s -X POST https://triptel.co/api/v1/partner/auth/token \
  -H "Content-Type: application/json" \
  -d '{"api_key": "esim_live_..."}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s https://triptel.co/api/v1/partner/me \
  -H "Authorization: Bearer $TOKEN"
```

---

## 2. Endpoints

All request/response bodies are JSON. All endpoints below require the `Authorization: Bearer <token>` header from step 1.2 unless noted otherwise.

### `GET /partner/countries`

Lists all active destination countries.

**Query params:** `search` (optional) — filters by country name or ISO2 code.

**Response `200`:**
```json
[
  {
    "id": 1,
    "iso2": "US",
    "iso3": "USA",
    "name_en": "United States",
    "name_bn": null,
    "flag_url": "https://...",
    "region": null,
    "is_popular": true,
    "is_active": true
  }
]
```

Rate limit: **120/minute**.

---

### `GET /partner/countries/{iso2}/products`

Lists active eSIM data products for a country.

**Path param:** `iso2` — case-insensitive (e.g. `us`, `US`).

**Response `200`:**
```json
[
  {
    "id": "a1b2c3d4-...",
    "country_id": 1,
    "title_en": "1GB / 7 Days",
    "title_bn": null,
    "data_amount_gb": 1.0,
    "validity_days": 7,
    "retail_price": 4.50,
    "currency": "USD",
    "is_unlimited": false,
    "is_active": true,
    "coverage_networks": null
  }
]
```

`404` if the country ISO2 doesn't exist. Rate limit: **120/minute**.

---

### `GET /partner/me`

Your merchant profile, effective commission rate, and current wallet balance.

**Response `200`:**
```json
{
  "business_name": "Acme Travel Co",
  "commission_rate_pct": 5.00,
  "wallet_balance": 142.5000,
  "wallet_currency": "USD",
  "webhook_configured": true
}
```

`commission_rate_pct` reflects any active volume-based commission tier, falling back to your flat rate. Rate limit: **120/minute**.

---

### `POST /partner/orders`

Places an order and provisions an eSIM **asynchronously**. Your merchant wallet is debited the product's `retail_price` immediately; the order returns in `PROCESSING` status right away — poll `GET /partner/orders/{id}` or wait for the webhook (see §3) to find out whether it completed.

**Request:**
```json
{
  "product_id": "a1b2c3d4-...",
  "customer_reference": "your-internal-order-id-123"
}
```
`customer_reference` is optional — it's echoed back in every response and webhook so you can reconcile against your own records without storing our `order_id` first.

**Response `200`:**
```json
{
  "order_id": "e5f6a7b8-...",
  "order_no": "PTR-20260904-A1B2C3",
  "status": "PROCESSING"
}
```

**Errors:**
- `400` — insufficient wallet balance (`"Insufficient wallet balance. Please top up."`). No order is created.
- `404` — `product_id` not found or inactive.

Rate limit: **30/minute**.

**What happens after `PROCESSING`:** a background job attempts to provision the actual eSIM. Two outcomes:
- **Success →** order becomes `COMPLETED`, `iccid`/`lpa_string`/`qr_code_data` are populated, and commission is credited to your account.
- **Failure →** order becomes `FAILED`, no eSIM is issued, and **the full amount is refunded to your wallet automatically**. No commission is paid on a failed order. You'll see this via polling or the webhook — there's no silent partial state.

---

### `GET /partner/orders/{order_id}`

Polls the current state of an order — the fallback if you're not using webhooks, and useful to confirm terminal state either way.

**Response `200`:**
```json
{
  "order_id": "e5f6a7b8-...",
  "order_no": "PTR-20260904-A1B2C3",
  "customer_reference": "your-internal-order-id-123",
  "status": "PROCESSING",
  "iccid": null,
  "lpa_string": null,
  "qr_code_data": null,
  "is_mock_fallback": null,
  "created_at": "2026-09-04T12:00:00Z"
}
```

`status` is one of `PROCESSING`, `COMPLETED`, `FAILED`. Once `COMPLETED`, `iccid`/`lpa_string`/`qr_code_data` are populated and `is_mock_fallback` is `false`. `404` if the order doesn't exist or doesn't belong to you.

Rate limit: **120/minute**.

---

### `PUT /partner/webhook-config`

Sets, rotates, or clears your webhook endpoint. Self-service — no admin involvement needed.

**Request (set/rotate):**
```json
{ "webhook_url": "https://yourapp.example.com/webhooks/esim" }
```

**Response `200`:**
```json
{
  "webhook_url": "https://yourapp.example.com/webhooks/esim",
  "webhook_secret": "whsec_...",
  "warning": "Store this secret securely - it will not be shown again in full."
}
```

A **new** `webhook_secret` is generated every time you set or change the URL — save it immediately, it's used to verify webhook signatures (§3) and is never shown again. Losing it means calling this endpoint again to get a fresh one (which also rotates your URL's secret, even if you re-submit the same URL).

**Request (clear):** send `{"webhook_url": null}` (or omit the field) to remove your webhook entirely — you'll only be able to poll after that.

**Response (clear):**
```json
{ "webhook_url": null, "webhook_secret": null }
```

Rate limit: **10/minute**.

---

## 3. Webhooks

If you have a `webhook_url` configured, we POST to it once your order reaches a terminal state (`COMPLETED` or `FAILED`).

**Delivery attempts:** one immediately when the order finishes processing; if that fails (non-2xx response, timeout, connection error), a retry sweep runs every 5 minutes and tries again, up to **3 attempts total**. There's no dead-letter queue after that — poll `GET /partner/orders/{id}` if you suspect a delivery was missed.

### Payload

```json
{
  "order_id": "e5f6a7b8-...",
  "customer_reference": "your-internal-order-id-123",
  "status": "COMPLETED",
  "iccid": "8988212345678901234",
  "lpa_string": "LPA:1$rsp.truphone.com$MATCHID123",
  "qr_code_data": "LPA:1$rsp.truphone.com$MATCHID123",
  "is_mock_fallback": false
}
```

On a `FAILED` order, `iccid`/`lpa_string`/`qr_code_data`/`is_mock_fallback` are all `null` — check `status` first.

### Signature verification

Every delivery includes an `X-Webhook-Signature` header: the **HMAC-SHA256** of the exact raw request body, hex-encoded, using your `webhook_secret`.

```python
import hmac, hashlib

def verify_webhook(raw_body: bytes, signature_header: str, webhook_secret: str) -> bool:
    expected = hmac.new(webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
```

Always verify against the **raw bytes** of the request body, before any JSON parsing — re-serializing and re-hashing a parsed-then-reserialized payload is not guaranteed to match byte-for-byte.

---

## 4. Rate limits

| Endpoint | Limit |
|---|---|
| `POST /partner/auth/token` | 10/minute (per IP) |
| `POST /partner/orders` | 30/minute (per API key) |
| `PUT /partner/webhook-config` | 10/minute (per API key) |
| Everything else (`countries`, `products`, `me`, order polling) | 120/minute (per API key) |

A `429` response means you've hit the limit — back off and retry after a short delay. Limits are keyed to your specific API key (via the token), not your IP, except for the token endpoint itself (which has no partner identity yet).

---

## 5. Errors

Standard HTTP status codes; error detail is always in the JSON body's `detail` field:

```json
{ "detail": "Insufficient wallet balance. Please top up." }
```

| Status | Meaning |
|---|---|
| `400` | Bad request — invalid input or a business rule violation (e.g. insufficient balance) |
| `401` | Missing/invalid/expired token, or invalid/revoked API key at the token endpoint |
| `404` | Resource not found, or not found (deliberately indistinguishable from "not yours") |
| `429` | Rate limit exceeded |
| `502` | Upstream provisioning failure (should be rare from your side — see the async order flow above, this shouldn't surface on `POST /partner/orders` itself since provisioning happens after that call returns) |

---

## 6. Getting your API key rotated or revoked

Contact your account admin — key issuance and revocation are Super-Admin-only actions performed from the internal admin console, not exposed via this API. If you suspect your key has leaked, ask for immediate revocation; any access tokens already issued from it will stop working on their next use, not just after they naturally expire.
