# Triptel Partner Reseller API

Base URL: `https://triptel.co/api/v1/partner`
Interactive version of this guide: <https://triptel.co/api-docs>

This API lets an approved reseller partner browse the eSIM catalog, buy eSIMs for their own customers from a prepaid USD wallet, and receive the activation details from their own backend — by webhook, by polling, or both.

---

## 0. How it works in one minute

1. **Onboarding (done by Triptel):** your account is made an approved reseller and a Super Admin issues you a long-lived **API key** (`esim_live_...`). You top up your **reseller wallet** (USD).
2. **Authenticate:** exchange the API key for a 1-hour **access token** (§1).
3. **Browse:** list countries and their products (§2.1, §2.2). `retail_price` (USD) is what your wallet is charged per eSIM.
4. **Order:** `POST /orders` with a `product_id` and your own `customer_reference`. Your wallet is debited immediately and the order comes back as `PROCESSING` (§2.4).
5. **Delivery:** within ~10–30 seconds the order becomes `COMPLETED` (eSIM details filled in) or `FAILED` (wallet refunded automatically). You learn this from the webhook (§3) or by polling `GET /orders/{order_id}` (§2.5).
6. **Commission:** on every completed order, your commission percentage of the order amount is credited to your separate commission balance (§2.3).

---

## 1. Authentication

Every endpoint except the token endpoint requires a **Bearer access token**. The API key itself is only ever sent to the token endpoint.

### 1.1 Exchange your API key for an access token

```
POST /api/v1/partner/auth/token
Content-Type: application/json

{ "api_key": "esim_live_1a2b3c4d5e6f..." }
```

**Response `200`:**

```json
{ "access_token": "eyJhbGciOiJIUzI1NiIs...", "token_type": "bearer", "expires_in": 3600 }
```

- Tokens last **1 hour**. There is no refresh token: request a new one with your API key. Cache the token and renew it shortly before `expires_in` elapses, or when any call returns `401`.
- `401` if the key is invalid or revoked. Rate limit: **10/minute per IP**.
- **Keep the API key server-side only.** Never ship it to a browser or mobile app.

### 1.2 Use the token

```
GET /api/v1/partner/me
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

- `401` if the token is missing, expired, malformed, or not a partner token (customer login tokens don't work here, and partner tokens don't work on the customer API).
- Revoking a key takes effect on the very next call, even for tokens issued before the revocation.

```bash
TOKEN=$(curl -s -X POST https://triptel.co/api/v1/partner/auth/token \
  -H "Content-Type: application/json" \
  -d '{"api_key": "esim_live_..."}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s https://triptel.co/api/v1/partner/me -H "Authorization: Bearer $TOKEN"
```

---

## 2. Endpoints

JSON in, JSON out. All amounts are **decimal strings or numbers in USD**; treat them as decimals, never floats, in your own accounting.

### 2.1 `GET /countries`

Active destination countries, alphabetical. Optional `search` query param filters by name or ISO2.

```json
[
  { "id": 1, "iso2": "SG", "iso3": "SGP", "name_en": "Singapore", "name_bn": null,
    "flag_url": "https://...", "region": null, "is_popular": true, "is_active": true }
]
```

Rate limit: 120/minute.

### 2.2 `GET /countries/{iso2}/products`

Active products for a country (ISO2 is case-insensitive), smallest data allowance first. `404` if the country doesn't exist.

```json
[
  {
    "id": "a1b2c3d4-...",
    "country_id": 1,
    "title_en": "Singapore 1GB 7 Days",
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

- `retail_price` is exactly what your wallet is charged when you order this product, at the moment you order it. Prices can change when the catalog syncs, so re-read the product shortly before charging your own customer, and store the price you quoted.
- For unlimited plans `is_unlimited` is `true` and `data_amount_gb` is `0` — show "Unlimited", not "0 GB".
- The catalog changes over time; products can be deactivated. Cache it for minutes to hours, not forever.

Rate limit: 120/minute.

### 2.3 `GET /me`

```json
{
  "business_name": "Ovigo Travel",
  "commission_rate_pct": 5.00,
  "wallet_balance": 142.5000,
  "wallet_currency": "USD",
  "commission_balance": 3.2500,
  "webhook_configured": true
}
```

- `wallet_balance`: prepaid funds that orders are paid from. Check it before charging your own customer, so you never take a customer's money when your wallet can't cover the eSIM.
- `commission_balance`: commission earned on completed orders, held separately from `wallet_balance`.
- `commission_rate_pct`: your effective rate, including any volume tier you've reached.

Rate limit: 120/minute.

### 2.4 `POST /orders`

Buys one eSIM. Your wallet is debited `retail_price` immediately; provisioning happens asynchronously.

**Request:**

```json
{ "product_id": "a1b2c3d4-...", "customer_reference": "your-order-id-123" }
```

**Response `200`** (the full order object, see §2.6, plus `idempotent_replay`):

```json
{
  "order_id": "e5f6a7b8-...",
  "order_no": "PTR-20260913-A1B2C3",
  "customer_reference": "your-order-id-123",
  "status": "PROCESSING",
  "amount": "4.5000",
  "currency": "USD",
  "product": { "id": "a1b2c3d4-...", "title": "Singapore 1GB 7 Days", "country_iso2": "SG",
               "data_amount_gb": 1.0, "is_unlimited": false, "validity_days": 7 },
  "iccid": null, "lpa_string": null, "qr_code_data": null,
  "smdp_address": null, "matching_id": null,
  "install_links": { "ios": null, "android": null },
  "is_mock_fallback": null,
  "created_at": "2026-09-13T10:00:00.123456+00:00",
  "updated_at": "2026-09-13T10:00:00.123456+00:00",
  "idempotent_replay": false
}
```

#### Idempotency: always send `customer_reference`

`customer_reference` is optional, but **strongly recommended**. It makes retries safe:

- Sending the **same** `customer_reference` with the **same** `product_id` again returns the **original** order (`"idempotent_replay": true`) and **does not charge your wallet again** — whatever state that order is in now.
- Sending the same `customer_reference` with a **different** `product_id` returns `409`.
- Without a `customer_reference`, every call is a new purchase. If your request times out and you retry, you may buy two eSIMs.

Use one unique value per eSIM you intend to sell, such as your own order ID. Up to 255 characters.

**Errors:** `400` insufficient wallet balance (no order created, nothing charged) · `404` product not found or inactive · `409` `customer_reference` reused for a different product.

**After `PROCESSING`:**
- **Success →** `COMPLETED`; `iccid`, `lpa_string`, `qr_code_data`, `smdp_address`, `matching_id` and `install_links` are filled in; commission is credited.
- **Failure →** `FAILED`; no eSIM; **the full amount is refunded to your wallet automatically**; no commission. Refund your own customer, or offer another product.
- If our server restarts mid-order, a recovery job finishes it within minutes: it fetches an eSIM the supplier already issued (never buying twice) or fails and refunds it. A `PROCESSING` order therefore always reaches `COMPLETED` or `FAILED`. Treat anything still `PROCESSING` after 15 minutes as a case to raise with us.

Rate limit: 30/minute.

### 2.5 `GET /orders/{order_id}`

The current state of one of your orders — the order object from §2.6. `404` if it doesn't exist or isn't yours. Poll every 3–5 seconds while `PROCESSING`; stop at `COMPLETED` or `FAILED`.

Rate limit: 120/minute.

### 2.6 `GET /orders`

Orders you placed through this API, newest first — for reconciliation and support lookups.

**Query params:** `customer_reference`, `status` (`PROCESSING` | `COMPLETED` | `FAILED`), `limit` (1–100, default 50), `offset` (default 0).

```json
{ "orders": [ { "order_id": "e5f6a7b8-...", "status": "COMPLETED", "...": "..." } ],
  "total": 1, "limit": 50, "offset": 0 }
```

#### The order object

| Field | Meaning |
|---|---|
| `order_id` | Our ID. Use it for `GET /orders/{order_id}`. |
| `order_no` | Human-readable number (`PTR-...`) — quote it to support. |
| `customer_reference` | Your reference, echoed back. |
| `status` | `PROCESSING`, `COMPLETED` or `FAILED`. |
| `amount`, `currency` | What your wallet was charged, e.g. `"4.5000"`, `"USD"`. |
| `product` | `id`, `title`, `country_iso2`, `data_amount_gb`, `is_unlimited`, `validity_days` at the time of the order. |
| `iccid` | The eSIM's ICCID. |
| `lpa_string` | Activation code `LPA:1$<smdp>$<matching id>`. Encode this into the QR code the customer scans. |
| `qr_code_data` | The string to encode in the QR code (usually identical to `lpa_string`). |
| `smdp_address`, `matching_id` | The two parts of the activation code, for manual entry on the phone. |
| `install_links.ios` | One-tap install link for iOS 17.4+. |
| `install_links.android` | One-tap install link for supported Android devices. Support is still uneven, so always show the QR code as well. |
| `is_mock_fallback` | Legacy field, always `false` on completed orders. Safe to ignore. |
| `created_at`, `updated_at` | ISO 8601 timestamps (UTC). |

Fields are only ever **added** to this object in future, never removed or renamed. Ignore fields you don't recognise.

### 2.7 `PUT /webhook-config`

Sets, rotates or clears your webhook endpoint. Self-service.

```json
{ "webhook_url": "https://api.yourapp.com/webhooks/triptel" }
```

**Response `200`:**

```json
{
  "webhook_url": "https://api.yourapp.com/webhooks/triptel",
  "webhook_secret": "whsec_...",
  "warning": "Store this secret securely - it will not be shown again in full."
}
```

- A **new** `webhook_secret` is generated on every call, even if you resubmit the same URL. The previous secret stops matching immediately, so deploy the new secret right away.
- `{"webhook_url": null}` clears the webhook; you can still poll.
- You can also set, rotate, remove and **test** your webhook from the Partner Dashboard at <https://triptel.co/reseller#api>. It must be a public `https://` URL.

Rate limit: 10/minute.

---

## 3. Webhooks

When an order reaches `COMPLETED` or `FAILED`, we `POST` the order object (§2.6) to your `webhook_url`:

```
POST /webhooks/triptel
Content-Type: application/json
X-Webhook-Signature: 5d41402abc4b2a76b9719d911017c592...

{ "order_id": "e5f6a7b8-...", "order_no": "PTR-20260913-A1B2C3", "customer_reference": "your-order-id-123",
  "status": "COMPLETED", "amount": "4.5000", "currency": "USD", "product": { "...": "..." },
  "iccid": "8965012345678901234", "lpa_string": "LPA:1$smdp.example.com$ABC123",
  "qr_code_data": "LPA:1$smdp.example.com$ABC123", "smdp_address": "smdp.example.com", "matching_id": "ABC123",
  "install_links": { "ios": "https://esimsetup.apple.com/esim_qrcode_provisioning?carddata=LPA%3A1%24...",
                     "android": "https://esimsetup.android.com/esim_qrcode_provisioning?carddata=LPA%3A1%24..." },
  "is_mock_fallback": false, "created_at": "...", "updated_at": "..." }
```

**Headers:** `X-Webhook-Signature` (see below) and `X-Webhook-Event`, which is `order.updated` for order deliveries.

**Test deliveries:** the dashboard's "Send test" button posts a signed ping with `X-Webhook-Event: webhook.test` and this body. It is not an order, so verify the signature and respond `2xx` without processing it:

```json
{ "event": "webhook.test", "business_name": "Ovigo Travel",
  "message": "Test delivery from Triptel. Respond with any 2xx status.", "sent_at": "2026-09-13T10:00:00+00:00" }
```

**Delivery:** one attempt when the order settles. If it fails (non-2xx, timeout after 10 seconds, connection error), a sweep every 5 minutes retries it, up to **3 attempts in total** within 24 hours. This applies to both `COMPLETED` and `FAILED` orders.

**Your receiver must:**
1. **Verify the signature** against the raw body before trusting anything (below). Reject with `401` if it doesn't match.
2. **Be idempotent.** The same order can arrive more than once, and a webhook can race your own polling. Key on `order_id` and make "already COMPLETED" a no-op.
3. **Respond `2xx` quickly** (well under 10 seconds). Do slow work after responding.
4. **Not rely on webhooks alone.** If an order you placed is still `PROCESSING` on your side after a few minutes, poll `GET /orders/{order_id}`.

### Signature verification

`X-Webhook-Signature` is the hex-encoded **HMAC-SHA256** of the exact raw request body, keyed with your `webhook_secret`.

```python
import hmac, hashlib

def verify_webhook(raw_body: bytes, signature_header: str, webhook_secret: str) -> bool:
    expected = hmac.new(webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")
```

```javascript
import crypto from "node:crypto";

function verifyWebhook(rawBody, signatureHeader, webhookSecret) {
  const expected = crypto.createHmac("sha256", webhookSecret).update(rawBody).digest("hex");
  const a = Buffer.from(expected), b = Buffer.from(signatureHeader || "");
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}
```

Compute it over the **raw bytes** you received. Re-serialising parsed JSON can change the bytes and break the signature.

---

## 4. Rate limits

| Endpoint | Limit |
|---|---|
| `POST /auth/token` | 10/minute (per IP) |
| `POST /orders` | 30/minute (per API key) |
| `PUT /webhook-config` | 10/minute (per API key) |
| Everything else | 120/minute (per API key) |

`429` means back off and retry after a short delay. Retrying `POST /orders` is safe only when you send the same `customer_reference`.

---

## 5. Errors

Errors always carry a human-readable `detail`:

```json
{ "detail": "Insufficient wallet balance. Please top up." }
```

| Status | Meaning | What to do |
|---|---|---|
| `400` | Invalid input or business rule (e.g. insufficient balance) | Don't retry unchanged; top up or fix the request |
| `401` | Missing/expired/invalid token, or invalid/revoked API key | Get a new token; if the key itself fails, contact us |
| `404` | Not found, or not yours (deliberately indistinguishable) | Check the ID |
| `409` | `customer_reference` already used for a different product | Use a new reference |
| `422` | Request body/query failed validation | Fix the request |
| `429` | Rate limited | Back off and retry |
| `5xx` | Temporary server problem | Retry with backoff (with the same `customer_reference` for orders) |

Branch on the status code, not the `detail` text.

---

## 6. Integration checklist

- [ ] API key stored as a server-side secret, never in client code or git.
- [ ] Access token cached and renewed on expiry or `401`.
- [ ] A unique `customer_reference` on every `POST /orders`, reused on retries.
- [ ] Wallet balance checked before charging your own customer.
- [ ] Product re-read before charging your customer; the quoted price stored on your order.
- [ ] Webhook endpoint verifies `X-Webhook-Signature` on the raw body and is idempotent.
- [ ] Polling fallback for orders stuck in `PROCESSING` on your side.
- [ ] `FAILED` orders refund or re-offer to your customer (your wallet is refunded automatically).
- [ ] Customer shown the QR code (from `qr_code_data`), the activation code, `smdp_address`/`matching_id` for manual entry, and the install links.
- [ ] `order_no` stored and visible to your support team.

## 7. Access, rotation and support

API keys are issued and revoked by a Triptel Super Admin; there is no self-service key management. Your Partner Dashboard (<https://triptel.co/reseller>) shows your key's prefix and when it was last used, all your orders (web and API) with their eSIM details, webhook delivery history, your balances, and lets you move earned commission into your main wallet. If a key may have leaked, ask for immediate revocation: tokens issued from it stop working on their next call. Quote the `order_no` when contacting support about an order.
