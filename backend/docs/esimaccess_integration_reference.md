# eSIM Access Integration Reference

**Written:** 2026-11-10, ahead of building `backend/app/services/esimaccess_adapter.py`.
**Purpose:** everything the adapter build needs, in one place, so it doesn't have to re-derive what
this project already knows about eSIM Access's API. Structured to mirror
`backend/app/services/vivape_adapter.py` so the two adapters stay comparable.

## How to read the confidence labels in this doc

eSIM Access's real documentation site, `docs.esimaccess.com`, is a JavaScript single-page app.
Automated fetching today (2026-11-10) only ever returned the page shell ("eSIM Access API for
resellers") with no rendered content — not a failure of judgment, the tooling available this
session genuinely cannot execute its JS. Every fact below is tagged with where it actually came
from:

- **`[OFFICIAL-FAQ]`** — fetched today from individual articles on `esimaccess.com/docs/...`
  (eSIM Access's own public knowledge-base, separate from and simpler than the SPA reference) or
  `esimaccess.com/esim-top-up-with-the-api/`. First-party, fetched today, but these are support
  articles, not the formal API reference — they don't claim to be exhaustive.
- **`[SDK]`** — read directly from the source of `esimaccess-python`
  (github.com/corbinlii/esimaccess-python), a third-party but functional, apparently-working
  open-source client. Treated as reliable for "this shape of call works," not as proof nothing
  else is required.
- **`[LIVE-PULL-2026-11-02]`** — carried over from this project's own earlier work: three LaTeX
  comparison documents in `D:\eSim-backups\supplier-comparison\` built from a real authenticated
  pull against eSIM Access's live API eight days ago. This is the strongest source in this
  document for catalogue shape and pricing, and per the user's standing instruction is treated as
  secondary to the live docs *only where they conflict* — they didn't, anywhere checked today.
- **`[THIRD-PARTY-UNCONFIRMED]`** — from search results about eSIM Access (blog posts, other
  wrapper libraries, community "skill" files) that could not be cross-checked against an official
  source today. Flagged explicitly; do not build load-bearing logic on these alone.
- **`[NOT FOUND TODAY]`** — asked about directly, no authoritative answer surfaced. Listed as an
  open question, not guessed at.

---

## 1. Base URL, transport, rate limit

- Base URL: **`https://api.esimaccess.com/api/v1/open`** — `[SDK]` (hardcoded in
  `esimaccess_python/api/package.py`) and consistent with `[THIRD-PARTY-UNCONFIRMED]` sources. Every
  endpoint below hangs off this prefix.
- Every endpoint in the SDK and in the one official worked example (`esim-top-up-with-the-api`) is
  called with **POST**, including read-only calls like balance query — `[SDK]`, `[OFFICIAL-FAQ]`.
  Unlike VivaPe, there do not appear to be any GET endpoints. Build `call_api()` assuming POST
  unless/until the real docs or a live test says otherwise.
- Rate limit: **~8 requests/second** — `[THIRD-PARTY-UNCONFIRMED]` only (a third-party Elixir client's
  README states this and adds its own retry/backoff around it). Not found on any first-party page
  today. Treat as a reasonable default for a limiter/backoff in the adapter, but confirm against
  real `429`/throttling behavior in testing rather than trusting it exactly.
- No evidence found of an HTTP/2 requirement analogous to VivaPe's (see the big warning at the top
  of `vivape_adapter.py`). Nothing suggests eSIM Access needs it, but given how expensive that
  VivaPe lesson was, it costs little to pass `http2=True` on the shared `httpx.AsyncClient` anyway
  and watch the `SupplierTransactionLog` latency/status columns during first real testing.

## 2. Authentication — RESOLVED, `[LIVE-CONFIRMED-2026-11-10]`

**Settled with a real call against the real account.** `RT-AccessCode` alone, no HMAC, no
timestamp, no signature, is sufficient — confirmed with a live `POST balance/query`, empty body,
single header, which returned `HTTP 200` and `{"success":true,"errorCode":"0","errorMsg":null,
"obj":{"balance":500000}}`. The MCP server's "every request is HMAC-SHA256 signed" claim does not
hold for this account/endpoint at least; `settings.ESIMACCESS_SECRET_KEY` is still defined and
threaded through for forward-compatibility (see point 2 below), but is not required today.

This also confirms the response envelope (`success`/`errorCode`/`errorMsg`/`obj`) and gives the
first real field name inside `obj`: **`balance`**, a raw integer in the same ×10,000 USD encoding
as package prices (500000 → $50.00).

The rest of this section is kept as a record of the investigation that led to the live test,
since the reasoning (why the SDK/quick-start evidence was trusted over the MCP docs) is still
useful context for anyone extending auth later (e.g. if a different account ever does require
signing).

---

Here is exactly what was confirmed vs. not, before the live call above settled it:

- **Confirmed, `[OFFICIAL-FAQ]`** (from `esimaccess.com/docs/what-api-authentication-method-do-you-support/`):
  > "We support the API key in header." ... and separately, HMAC-SHA256 is described as an
  > **additional** option, not stated as mandatory for every call.
- **Confirmed, `[SDK]`**: the only header the Python SDK ever sends is:
  ```
  RT-AccessCode: <your access code>
  ```
  No secret key, no HMAC signature, no timestamp or nonce header, on *any* call — balance, package
  list, order, query, cancel, suspend, revoke, top-up, SMS, webhook save/query. `auth.py` in full:
  ```python
  def authenticate(api_key: str) -> httpx.Client:
      headers = {"RT-AccessCode": api_key}
      client = httpx.Client(headers=headers)
      return client
  ```
- **Confirmed, `[OFFICIAL-FAQ]`**: the quick-start example on the real docs site itself (surfaced
  via search snippet, not independently re-fetched in full) is a `curl` to
  `.../balance/query` with just the `RT-AccessCode` header and an **empty body**, no signature.
- **Also claimed, `[THIRD-PARTY-UNCONFIRMED]`**: the eSIM Access *MCP server's* own integration guide
  (`mcp.esimaccess.com`) states flatly: "Every request to eSIMAccess is signed with HMAC-SHA256
  using your SecretKey" — but gives no header names, no canonical string, no example. This may
  describe a stricter mode some accounts are provisioned into, or it may be describing the MCP
  layer's own internal behavior rather than a universal requirement, or it may just be imprecise
  marketing copy. It is not reconcilable with the SDK and quick-start evidence above from what's
  available today.

**What this means for the adapter design:** build it the way VivaPe's adapter centralizes auth —
one place that sets request headers — but make that one place easy to extend. Concretely:

1. Start with `RT-AccessCode: settings.ESIMACCESS_ACCESS_CODE` as the only header, matching the SDK
   and the quick-start example — this is what's actually been shown to work.
2. Keep `settings.ESIMACCESS_SECRET_KEY` defined and threaded into the adapter's `call_api()`
   signature from day one (even if unused at first), so that if the real account's first live call
   comes back with an auth error, adding HMAC signing is a localized change in one method, not a
   rewrite. The likely shape if it's needed — standard for this class of API — is
   `HMAC-SHA256(secretKey, <timestamp + requestBody or similar>)` sent as another `RT-*` header
   alongside a timestamp header, mirroring the sibling provider eSIMfly's documented
   `RT-RequestID` / `RT-Timestamp` / `RT-Signature` headers (`[THIRD-PARTY-UNCONFIRMED]`, a
   **different company** on a similar white-label platform pattern — not proof of eSIM Access's own
   scheme, just the most concrete shape available to guess from if the simple header fails).
3. **Before writing any order-creation code against the real account**, make one real
   `balance/query` call with only `RT-AccessCode` set. If it succeeds, auth is settled and simple.
   If it fails with an auth-specific error, that response body will say far more about the real
   signing requirement than anything found today — read it and adjust.
4. No session/token model. Unlike VivaPe's login-and-cache-a-bearer-token with 30-minute expiry and
   a force-refresh retry path, eSIM Access's access code is a static long-lived credential sent on
   every call. **There is no `get_token()` equivalent, no token cache, no token lock, and no
   "stale token" retry path to port over from VivaPe.** This simplifies the adapter considerably:
   no `asyncio.Lock`, no `_token_expiry`, no `force_fresh_token` parameter. If signing is in fact
   required, the thing that could expire is a timestamp window on the signature, not a session —
   a different failure mode (clock skew) with a different fix (resync/retry immediately with a
   fresh timestamp), not a login call.

## 3. Response envelope & error conventions — confirmed, and it matters

**Confirmed `[OFFICIAL-FAQ]`**, from a full worked example on `esimaccess.com/esim-top-up-with-the-api/`
(the only official page found today showing a real response body):

```json
{
  "errorCode": null,
  "errorMsg": null,
  "success": true,
  "obj": {
    "transactionId": "fb9b22193f3c45aab4f052efbc878f30",
    "iccid": "89852245280001354019",
    "expiredTime": "2023-08-24T17:01:37+0000",
    "totalVolume": 5368709120,
    "totalDuration": 35,
    "orderUsage": 907415004
  }
}
```

**This is the same "always-200, business-error-in-the-body" model as VivaPe.** No official failure
example was found today, and no confirmation either way on whether genuine transport/auth failures
(bad access code, malformed request) get a non-200 HTTP status while only *business* failures (bad
package code, insufficient balance) get `success: false` inside a 200 — or whether literally
everything is 200. **Treat every call result the way `vivape_adapter.py` already treats VivaPe's: a
200 response is not proof of success. Check `success` (and that `obj` is actually present) before
treating any call as having done what was asked, exactly the discipline the comment block on
`create_transaction()` in `vivape_adapter.py` documents paying for in real money once already.**

Design implication for the adapter: give `call_api()` a thin, explicit success check (e.g. raise
or return a tagged failure when `resp_data.get("success") is not True`) rather than trusting HTTP
status alone — mirroring the lesson from VivaPe's stale-token-returns-200 incident, not copying its
specific retry logic (which was about a *session* expiring; eSIM Access has no session to expire).

**Error codes:** official FAQ (`do-you-have-a-list-of-error-codes`) only says a list "is found in
the API documentation" and does not reproduce it. `[THIRD-PARTY-UNCONFIRMED]` mentions one specific
code, `200010`, meaning "the eSIM is still being allocated" (i.e., query again shortly, not a real
failure) — plausible given the async provisioning model, but not independently verified today.
**Open question:** the full `errorCode` enum. Capture every `(errorCode, errorMsg)` pair the real
account actually returns into `SupplierTransactionLog` from day one (see §7) — this project already
has the infrastructure to build the real error catalogue empirically rather than needing it upfront.

## 4. Endpoints

All under `https://api.esimaccess.com/api/v1/open`, all POST, all wrapped in the `{success,
errorCode, errorMsg, obj}` envelope above unless noted. Source tags per endpoint.

| Purpose | Path | Source |
|---|---|---|
| Account balance | `/balance/query` | `[SDK]`, `[OFFICIAL-FAQ]` |
| Package list | `/package/list` | `[SDK]`, `[OFFICIAL-FAQ]` (full example) |
| Create order | `/esim/order` | `[SDK]` |
| Query profiles/orders | `/esim/query` | `[SDK]`; see version-note caveat below |
| Cancel (unused, refunded) | `/esim/cancel` | `[SDK]` |
| Suspend | `/esim/suspend` | `[SDK]` |
| Unsuspend | `/esim/unsuspend` | `[SDK]` |
| Revoke (active, no refund) | `/esim/revoke` | `[SDK]` |
| Top-up existing eSIM | `/esim/topup` | `[SDK]`, `[OFFICIAL-FAQ]` (full example) |
| Send SMS | `/esim/sendSms` | `[SDK]` |
| Set webhook URL | `/webhook/save` | `[SDK]` |
| Query webhook URL | `/webhook/query` | `[SDK]` |

**Version-note caveat on query:** a changelog snippet surfaced in search (`[THIRD-PARTY-UNCONFIRMED]`)
says *"esim/list endpoint removed, status function found in esim/query."* An official FAQ page
fetched today (`can-i-check-data-usage`) still shows a worked example against `/esim/list`,
suggesting that FAQ article is stale relative to the real reference. **Build against `/esim/query`
as current/correct** (matching the maintained SDK), and don't be surprised if `/esim/list` 404s or
is simply absent — don't implement it.

### 4.1 `package/list`

Request body, `[SDK]` + `[OFFICIAL-FAQ]`:
```json
{
  "locationCode": "",
  "type": "",
  "packageCode": "",
  "iccid": ""
}
```
- `locationCode` — ISO2 to filter to one country; `!RG` for regional bundles, `!GL` for global.
  Empty/omitted presumably returns everything (this is how the 3,259-package full pull was taken,
  per the live-pull docs — confirm the adapter's "sync everything" call uses this).
- `type` — `"BASE"` (default product list) or `"TOPUP"` (top-up products for an existing ICCID).
- `packageCode` — used with `TOPUP` to scope to one base package's top-up options.
- `iccid` — used with `TOPUP` to see what's actually top-up-eligible for that specific eSIM.

Response `obj.packageList[]`, confirmed fields from the official top-up example plus the fields
already known from this project's earlier research (`[LIVE-PULL-2026-11-02]` + `[OFFICIAL-FAQ]`):
`packageCode`, `slug`, `name`, `price` (int, ×10,000 USD), `retailPrice`, `currencyCode`, `volume`
(bytes), `duration`, `durationUnit`, `location` (ISO2 or comma list), `dataType` (1/2/3/4, see §6),
`ipExport`, `locationNetworkList`, `operatorList`, `supportTopUpType`, `description`, `activeType`,
`unusedValidTime`.

**Live catalogue shape — do not build against the doc sample alone — `[LIVE-PULL-2026-11-02]`,
re-confirmed as still the right caution today:** a real authenticated pull on 2026-11-02 returned
**3,259 packages across 202 countries**. An earlier pass at this same research had mistakenly
treated the doc site's *own embedded example response* (≈638 packages/121 countries, 566 of them
Day Passes) as representative, and that mistake produced visibly wrong conclusions — "only Japan has
fixed-data plans," "eSIM Access is several times cheaper" — that the corrected live pull reversed:
*every* one of the 202 countries offers fixed-data plans alongside Day Passes, and pricing is
closely matched with eSIM Access not consistently cheaper. **The adapter's catalogue sync must call
with no filter and page/paginate as needed to get the real ~3,259, never assume the doc examples
are the whole catalogue.**

### 4.2 `esim/order`

Request, `[SDK]`:
```json
{
  "transactionId": "unique-string-max-50-chars",
  "amount": 70000,
  "packageInfoList": [
    {"packageCode": "TOPUP_CKH491", "count": 1}
  ]
}
```
- `transactionId` is the idempotency key, sent **in the request body**, not a header — this is the
  concrete answer to "how is it actually sent" the task asked to pin down. Max 50 characters.
  `packageInfoList` items can carry an optional `price` and (per the earlier Day Pass research)
  `periodNum` for Day Pass plans — not independently re-verified today, but consistent with the
  dataType model in §6.
- Supports batch ordering in one call (`[OFFICIAL-FAQ]`, `can-i-order-in-batches`): multiple
  `packageInfoList` entries, or a `count` > 1 on one entry, in a single `esim/order` call returns
  a JSON list of the ordered eSIMs. No batch-size cap found today.
- Response: `obj` carries `orderNo` at minimum (per changelog reference and SDK usage pattern);
  exact full field list for `esim/order`'s own response not independently confirmed today — read it
  off the real first test call and record it here once the adapter exists.
- **Asynchronous provisioning, same pattern as VivaPe.** `[OFFICIAL-FAQ]` (`how-long-does-it-take...`):
  provisioning happens "within seconds" after the SM-DP+ server processes it, and the documented
  way to know it's done is the `ORDER_STATUS` webhook (§5) — polling isn't mentioned on that page,
  but `[THIRD-PARTY-UNCONFIRMED]` (the "skill" reference) describes a poll-every-3-seconds,
  up-to-4-retries pattern with the webhook as a fallback, which is a sane default shape for the
  adapter regardless of whether it's official: **do not assume synchronous completion; poll
  `esim/query` and/or wire the webhook, mirroring how `order_fulfilment.py` already has to handle
  VivaPe's async provisioning.**

### 4.3 `esim/query`

Request, `[SDK]`:
```json
{
  "orderNo": null,
  "iccid": null,
  "pager": {"pageNum": 1, "pageSize": 20, "total": null},
  "startTime": null,
  "endTime": null
}
```
Query by `orderNo` or `iccid`, paginated, optionally time-bounded. Response `obj` contains the
profile list with (per the still-live `/esim/list` FAQ example, which should carry over to the
fields on `/esim/query`): `iccid`, `totalVolume`, `orderUsage` (used bytes — remaining =
`totalVolume - orderUsage`), `totalDuration`, `durationUnit`, `expiredTime`, plus — per the project's
already-known package shape — ICCID, LPA/QR activation code, and status fields for order/esim/SM-DP+
state (exact enum values for those statuses not independently confirmed today; capture them from
real `SupplierTransactionLog` rows and the webhook payloads in §5, which do give some: `orderStatus`
example `GOT_RESOURCE`, `esimStatus` example `IN_USE`, `smdpStatus` example `INSTALLATION`).

### 4.4 `esim/cancel`, `esim/suspend`, `esim/unsuspend`, `esim/revoke`

All `[SDK]`, all take just `{"iccid": "..."}`.
- `cancel` — unused/inactive profile only, **refunds to account balance**. This is the capability
  VivaPe has no equivalent of at all (VivaPe's adapter has no cancel/refund method — see the
  `vivape-vs-esimaccess.tex` comparison's €28.61-lost-to-abandoned-eSIMs finding).
- `revoke` — closes an **active** profile, explicitly non-refundable.
- `suspend`/`unsuspend` — pause/resume data service without closing the profile (fraud/dispute
  handling use case per the earlier comparison work).

### 4.5 `esim/topup`

Request, `[SDK]` + `[OFFICIAL-FAQ]`:
```json
{"iccid": "...", "packageCode": "TOPUP_CKH491", "transactionId": "...", "amount": 70000}
```
Only valid when the target package's `supportTopUpType === 2` and the profile hasn't expired
(`[THIRD-PARTY-UNCONFIRMED]` for the exact `2` value, logically consistent with `supportTopUpType`
being a known field on the package schema). No VivaPe equivalent exists; this is new functionality,
not a port.

### 4.6 `esim/sendSms`, `webhook/save`, `webhook/query`

`sendSms` takes `{"iccid", "message"}` (max 500 chars, `[SDK]`'s own docstring/FAQ); network-dependent
and only works on already-installed eSIMs. `webhook/save` takes `{"webhook": "<https url>"}`;
`webhook/query` takes no body and returns the currently configured URL.

### 4.7 `balance/query`

`[LIVE-CONFIRMED-2026-11-10]` No request body needed (matches `[SDK]`, which sends none). Real
response against the real account:
```json
{"success": true, "errorCode": "0", "errorMsg": null, "obj": {"balance": 500000}}
```
`errorCode` is a **string** `"0"` on success, not an integer and not absent — worth matching exactly
in whatever success check the adapter writes. `obj.balance` is the only field present — no
`currencyCode` alongside it as originally guessed by analogy with other endpoints; the ×10,000 USD
encoding is assumed (500000 → $50.00) but not separately labelled in this response, so don't expect
a currency field here even though other endpoints may have one.

## 5. Webhooks

`[OFFICIAL-FAQ]` (`what-webhook-notifications-do-you-send`) — the clearest, most complete section
found today. Four event types, POSTed as JSON to the URL set via `webhook/save`, each shaped as
`{"notifyType": "...", "content": {...fields...}}`:

| `notifyType` | Fires when | `content` fields (examples) |
|---|---|---|
| `ORDER_STATUS` | ordered eSIMs are ready to download | `orderNo`, `transactionId`, `orderStatus` (e.g. `GOT_RESOURCE`) |
| `ESIM_STATUS` | an eSIM's install/use state changes | `orderNo`, `transactionId`, `iccid`, `esimStatus` (e.g. `IN_USE`), `smdpStatus` (e.g. `INSTALLATION`) |
| `DATA_USAGE` | remaining data ≤ 100 MB | `orderNo`, `transactionId`, `iccid`, `totalVolume`, `orderUsage`, `remain` |
| `VALIDITY_USAGE` | validity reaches 1 day remaining | `orderNo`, `transactionId`, `iccid`, `durationUnit`, `totalDuration`, `expiredTime`, `remain` |

This is unambiguously better than VivaPe, which has **no webhook support at all** today — the
adapter and `order_fulfilment.py` currently only know how to poll VivaPe. For eSIM Access, plan a
webhook receiver endpoint and use it as the primary fulfillment signal, with polling via
`esim/query` as a startup-safety fallback (covers the gap before a webhook URL is configured, and
covers delivery failures) — not the other way around.

Separately, account-level low-balance and payment-confirmation notices go by **email**, not webhook
(`[OFFICIAL-FAQ]`) — worth knowing but out of scope for the adapter itself.

## 6. Pricing, currency, and the two gotchas that already caused a documented mistake once

- **Encoding, confirmed `[OFFICIAL-FAQ]` + `[LIVE-PULL-2026-11-02]`:** USD, integer ×10,000.
  `70000` = $7.00 (the FAQ's North America 1GB/7Days TOPUP example); `7000` would be $0.70. Always
  divide by 10,000, never assume 2-decimal cents. `retailPrice` uses the same encoding and is eSIM
  Access's own suggested resale price — informational, not something the adapter needs to act on,
  but worth capturing per product.
- **`dataType` plan models, confirmed `[LIVE-PULL-2026-11-02]`:**

  | `dataType` | Model | Behavior |
  |---|---|---|
  | 1 | Fixed data | total allowance over the validity period |
  | 2 | Daily limit | speed reduced after the daily cap |
  | 3 | Daily limit | service cut off after the daily cap |
  | 4 | Daily unlimited | no total cap |

- **Day Pass pricing is not `price × days` — confirmed `[LIVE-PULL-2026-11-02]`, a real live-API
  pull, matching the derived figures this project already suspected almost exactly.** A Day Pass
  (`dataType` 2/3) sells a **daily allowance**, bought for a chosen number of days (`periodNum`),
  at a **tiered discount off the daily rate** the longer the stay:

  | Days purchased (`periodNum`) | Share of daily rate paid |
  |---|---|
  | 1–4 | 96% |
  | 5–9 | 92% |
  | 10–19 | 89% |
  | 20–29 | 85% |
  | 30–365 | 82% |

  Worked example from the live pull: China at $0.65/day for 1 GB/day costs **$4.19** for a 7-day
  purchase (not $0.65 flat), and delivers **7 GB total** over that week because the allowance
  renews daily. **The adapter/pricing layer must implement this tiered formula explicitly** — do
  not store or quote a Day Pass's "price" as its daily rate times the number of days; it will be
  wrong by the margin in that table, growing with length of stay.

- **The exit-IP/name-suffix gotcha is real and quantified, not theoretical — confirmed
  `[LIVE-PULL-2026-11-02]`.** A package name suffix like `(nonhkip)` is the *same* data/validity
  allowance sold on a *different exit IP*, not a duplicate. For China specifically: the plain
  (cheaper) packages exit via Hong Kong on China Mobile; the `(nonhkip)` packages exit via Singapore
  on China Telecom/Unicom, both still outside the mainland/Great Firewall, but at a real price
  premium that scaled from **+15% to +44%** across the five China tiers actually pulled live. This
  already caused one wrong conclusion in this project's own earlier comparison work (duplicate
  tiers that were really exit-IP variants). **Any catalogue model (the `Product` table, the admin
  UI, price comparisons) must carry `ipExport` / the exit-IP distinction as a first-class
  attribute of the product, not fold it away as a name-string oddity** — collapsing it will
  silently look like inexplicable duplicate pricing again.

## 7. Audit logging — reuse the existing table, add a `supplier_name` discriminator value

`backend/app/models/audit.py`'s `SupplierTransactionLog` already has everything the eSIM Access
adapter needs — it's generic (`supplier_name`, `endpoint`, `method`, `request_payload`,
`response_payload`, `status_code`, `latency_ms`, `cost_amount`) and not VivaPe-specific beyond the
column's default value (`default="VIVAPE"`). **No schema change needed here** — just construct rows
with `supplier_name="ESIMACCESS"` from the new adapter, exactly like `vivape_adapter.py`'s
`call_api()`/`get_token()` pattern of logging in a `finally:` block around every outbound call,
including the (request, response) pair with any secret redacted. Since eSIM Access has no login
call, there's no `login`-endpoint log row equivalent to VivaPe's — every real call is just a normal
`call_api()`-logged row.

## 8. Config settings — pattern to follow, no real values here

Following `config.py`'s existing `VIVAPE_*` pattern exactly (dev-only placeholder defaults, enforced
absent in production by the boot guard at the bottom of `config.py`):

```python
ESIMACCESS_BASE_URL: str = os.getenv("ESIMACCESS_BASE_URL", "https://api.esimaccess.com/api/v1/open")
ESIMACCESS_ACCESS_CODE: str = os.getenv("ESIMACCESS_ACCESS_CODE", "dev-only-not-a-real-access-code")
ESIMACCESS_SECRET_KEY: str = os.getenv("ESIMACCESS_SECRET_KEY", "dev-only-not-a-real-secret-key")
```

Add `ESIMACCESS_ACCESS_CODE` and `ESIMACCESS_SECRET_KEY` to the `_dev_only_placeholders` dict in the
production boot guard (around line 156 of `config.py`), the same way `VIVAPE_EMAIL`/`VIVAPE_PASSWORD`
and `SHURJOPAY_USERNAME`/`SHURJOPAY_PASSWORD` already are, so production refuses to boot on an
unset credential rather than silently calling eSIM Access with a placeholder. **No real Access
Code or Secret Key value appears anywhere in this document or was typed into this session** — this
project has had a credential leak into an agent transcript once before and had to rotate it; the
pattern above is deliberately a description, not a value, per that standing rule.

## 9. The open design question this doc was asked to surface, not answer

`Product.supplier_reference` (`backend/app/models/catalog.py`) is free text currently scoped
entirely to VivaPe's own wholesaler names: `esimgo_bundle`, `worldmove_esim`, `telna_esim`. **There
is no existing top-level column that says "which supplier (VivaPe vs. eSIM Access) this product
came from."** Two concrete options, left to the integration's owner to decide, not decided here:

1. **A new column**, e.g. `supplier` (enum or short string: `VIVAPE` / `ESIMACCESS`), orthogonal to
   `supplier_reference`, which keeps meaning "which wholesaler/feed inside that supplier." Cleaner
   long-term, needs a migration + backfill (`UPDATE products SET supplier = 'VIVAPE'` for all
   existing rows) and every existing VivaPe-only query/filter that implicitly assumed single-supplier
   now needs an explicit supplier clause where it matters (e.g. admin "which suppliers customers can
   buy from" toggle referenced in the earlier comparison doc, if real).
2. **A prefixed convention on `supplier_reference` itself**, e.g. `"esimaccess:JP_1_7"` vs.
   `"esimgo_bundle"`. No migration, cheaper short-term, but conflates two different concerns in one
   free-text column and pushes a `.split(":")`/`.startswith()` parse into every call site that needs
   to know the supplier — fragile exactly the way `supplier_receiver_amount`'s existing
   per-`supplier_reference` meaning-switching (documented in its own column comment) already is.

This doc takes no position on which to pick — it is flagged here, as the task asked, so the adapter
build doesn't silently invent an answer by, e.g., overloading `supplier_product_id` or jamming an
eSIM Access `packageCode` into a column sized and typed for VivaPe's integer IDs
(`supplier_product_id` is `Integer`; eSIM Access's `packageCode` is a string like `TOPUP_CKH491` —
**it will not fit that column at all**, which is itself a forcing function to resolve this before
writing the sync code, not just before writing migrations).

## 10. Sandbox / test mode

**`[NOT FOUND TODAY]`.** No mention of a sandbox, staging host, or test-mode flag in any official
page reached today. This matches what the earlier `[LIVE-PULL-2026-11-02]` comparison work already
concluded ("Sandbox: None found... test and cancel in production") and nothing found today
contradicts it. Plan to validate the integration the same way that doc recommended: deposit a small
real balance and exercise order → poll/webhook → install on a real handset → check usage → cancel
for refund, in that order, with `esim/cancel` as the recovery step for anything left over from
testing (and `esim/revoke` is the one testing action that is explicitly *not* reversible — don't use
it to clean up a test order; use `cancel`).

## 11. Rate limit, retries, and concurrency — design notes for `call_api()`

Unlike VivaPe, there's no documented need for:
- A token lock (`asyncio.Lock`) — no session to race on.
- A "stale token, retry with force-fresh" path — nothing to refresh.
- HTTP/2-specific pinning — no evidence of a transport-level quirk analogous to VivaPe's.

There probably *is* a need for:
- A simple rate limiter or semaphore around outbound calls if the catalogue sync (3,259+ packages,
  likely paginated) or a burst of concurrent checkouts could plausibly exceed ~8 req/s — cheap
  insurance even though that number is unconfirmed from a first-party source.
- Idempotent-retry safety is *less* of a concern than VivaPe by design: `transactionId` means a
  retried `esim/order` with the same ID should be recognized as the same request rather than
  double-charging — but this is the documented behavior of a different provider's API in general and
  hasn't been proven against eSIM Access's real account yet. **Test retrying an identical
  `esim/order` call with the same `transactionId` deliberately during validation (§10)** before
  relying on it in production the way the whole case for adding this supplier assumes.

---

## Summary of what's still genuinely open after today's research

1. ~~Exact signing requirement.~~ **RESOLVED `[LIVE-CONFIRMED-2026-11-10]`** — `RT-AccessCode` alone
   is sufficient; see §2. `balance/query`'s real response is now known too (§4.7).
2. **Full error code enum** beyond the one third-party-claimed example (`200010`) — no error was
   triggered by today's test call, so this is still unconfirmed.
3. **`esim/order`'s exact response field names** beyond the `obj`-wrapper + the fields confirmed via
   the top-up example — `balance/query`'s are now confirmed (§4.7), order's are not. Read off the
   first real test order.
4. **Exact current rate limit** — 8 req/s is third-party only.
5. **Whether `/esim/list` still works at all**, or is fully retired in favor of `/esim/query`.
6. **The `Product.supplier` design question (§9)** — a decision for whoever owns the migration, not
   something this document should decide.

None of these block starting the adapter build. Auth — the one item that genuinely would have —
is now settled against the real account, not just the docs.
