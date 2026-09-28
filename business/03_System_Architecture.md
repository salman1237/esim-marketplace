# System Architecture — Triptel

Version 1.0 · 28 September 2026

---

## 1. Architectural summary

Triptel is a **three-tier web application with a single relational database
and one upstream supplier integration**. It is deliberately conventional:
there is no microservice mesh, no message broker, no event bus. Every
business operation is a database transaction, and correctness comes from
transaction boundaries and database constraints rather than from distributed
coordination.

```
                    Browser / Partner system
                              │
                              ▼
        ┌──────────────────────────────────────────┐
        │  Dokploy reverse proxy (TLS, routing)    │
        └───────────────┬──────────────────────────┘
                        │
        ┌───────────────┴───────────────┐
        ▼                               ▼
┌────────────────────┐        ┌────────────────────────┐
│  esim-frontend     │  HTTP  │  esim-backend          │
│  Next.js 15        │───────▶│  FastAPI (Python 3.11) │
│  App Router, SSR   │        │  + APScheduler jobs    │
└────────────────────┘        └───────┬────────────────┘
                                      │
              ┌───────────────────────┼─────────────────────┐
              ▼                       ▼                     ▼
      ┌──────────────┐      ┌──────────────────┐   ┌────────────────┐
      │ PostgreSQL16 │      │ VivaPe API       │   │ ShurjoPay      │
      │ esim-db      │      │ (eSIM supplier)  │   │ (payments)     │
      └──────────────┘      └──────────────────┘   └────────────────┘
              │                                             ▲
              ▼                                             │
      ┌──────────────────────────────┐             callback / IPN
      │ Docker volumes               │
      │ uploads · kyc · withdrawal   │      ┌──────────────┐
      │ support · logs               │      │ SMTP         │
      └──────────────────────────────┘      └──────────────┘
```

**Why this shape.** The money model is the hard part of this product, not the
traffic. A single Postgres instance with `FOR UPDATE` row locks and unique
constraints gives exact, auditable balances with far less machinery than any
distributed alternative — and the load (thousands of orders, not millions) is
nowhere near needing more.

---

## 2. Components

### 2.1 Frontend — `esim-frontend`

Next.js 15 App Router, React, TypeScript, Tailwind CSS. 25 routes.

| Area | Routes |
|---|---|
| Public | `/`, `/destinations`, `/explore/[slug]`, `/partners`, `/api-docs`, `/legal/[slug]`, `/track/[token]` |
| Auth | `/auth/login`, `/auth/register`, `/auth/forgot-password`, `/auth/reset-password` |
| Customer | `/wallet`, `/wallet/withdraw`, `/wallet/withdraw/[id]`, `/my-esims`, `/my-esims/[id]`, `/my-esims/[id]/print`, `/profile`, `/refer`, `/support`, `/support/[id]` |
| Merchant | `/reseller` (6 tabs) |
| Agent | `/agent` (5 tabs) |
| Admin | `/admin` (18 tabs) |

Notable choices:

- **Server-rendered first paint for public settings.** The root layout fetches
  platform settings on the server so the real brand name and logo are in the
  first byte rather than flashing a placeholder.
- **`AppSettingsContext`** is the single source of currency, language,
  translations, exchange rates and public settings for the whole client tree.
  A signed-in user's preferred currency is loaded from `/auth/me` so it
  follows them across devices; browser storage is only a fallback.
- **Client-side auth.** The JWT lives in `localStorage` under `esim_token`
  and is attached as a bearer token. There is no server-side session.
- `NEXT_PUBLIC_*` variables are inlined at **build** time, so they are passed
  as Docker build args, not only as runtime environment.

### 2.2 Backend — `esim-backend`

FastAPI, async SQLAlchemy 2.0, Pydantic. **178 endpoints** across 18 routers,
all mounted under `/api/v1`.

```
app/
├── api/v1/         18 routers  — HTTP surface only, no business logic
├── services/       31 modules  — all business logic lives here
├── models/         20 modules  — SQLAlchemy ORM, 34 tables
├── schemas/        Pydantic request/response models
├── core/           config, database, security, deps, rate limiting, logging
├── templates/email 8 HTML email templates
└── alembic/        20 migrations
```

The rule the codebase follows: **routers validate and authorise; services
decide and mutate; models describe.** Anything shared between two entry
points (for example, commission distribution, which is reached from both
wallet checkout and the Partner API) lives in a service so the two paths
cannot drift apart.

### 2.3 Background jobs

APScheduler runs in the backend process — no separate worker.

| Job | Interval | Purpose |
|---|---|---|
| Catalogue sync | 4 h (and once at startup) | Pull supplier products, apply markup |
| Stuck-order recovery | 2 min (and once at startup) | Finish orders whose provisioning was interrupted — a deploy is exactly the event that kills in-flight work |
| Webhook retry sweep | 5 min | Re-deliver failed partner webhooks |

Each job swallows and logs its own exceptions so one failing supplier call
cannot take the scheduler down.

### 2.4 Database

PostgreSQL 16. Schema is owned by Alembic; the application never creates
tables. Migrations run from the container entrypoint **before** the
application starts.

---

## 3. Data model

34 tables. Grouped by purpose:

### Identity and access
| Table | Purpose |
|---|---|
| `users` | One row per human. Role, status, preferred currency/language, referral code, `referred_by_id`, Google subject, KYC flag |
| `kyc_submissions` | One per user. NID number, two document filenames, review decision |
| `password_reset_tokens` | Hashed, single-use, expiring |
| `audit_logs` | Every administrative action, with before/after JSON |

### Catalogue
| Table | Purpose |
|---|---|
| `countries` | ISO codes, names, region, popularity flag |
| `products` | Supplier product ID, data allowance, validity days, **cost price and retail price**, coverage networks |

### Money
| Table | Purpose |
|---|---|
| `wallets` | One per user per type (DEFAULT / REWARD / COMMISSION), balance, currency, freeze flag |
| `wallet_ledger_entries` | Every movement: type, amount, **balance before and after**, reference type and ID, unique idempotency key |
| `manual_payment_requests` | bKash / Nagad / bank deposits awaiting approval |
| `payment_logs` | Raw gateway request/response |
| `bank_accounts` | Saved payout destinations, soft-deleted |
| `withdrawal_requests` | Amount, fee, net, **account snapshot**, frozen conversion rate, payout proof |

### Selling
| Table | Purpose |
|---|---|
| `orders` | Buyer and beneficiary (which differ for merchant sales), product, totals, discount, reward used, **agent commission and agent bonus**, payment method, status |
| `esim_profiles` | ICCID, SM-DP+ address, matching ID, LPA string, QR, status, **`activated_at` / `expires_at` (null until installed)**, `share_token` |
| `esim_telemetry` | Cached carrier data: bytes used, install state, device model, daily breakdown, `fetched_at`, `last_forced_at` |

### Channel
| Table | Purpose |
|---|---|
| `merchant_profiles` | Business details, **commission rate**, `agent_id`, **`agent_bonus_pct`**, webhook config, status |
| `agent_profiles` | Company, unique agent code, commission rate, status |
| `agent_bonus_requests` | The approval queue in front of `agent_bonus_pct` — current and requested percentage, decision |
| `commission_tiers` | Optional volume thresholds that override a merchant's flat rate |
| `api_keys` | Hashed partner keys, prefix, revocation |
| `webhook_delivery_logs` | Every attempt, with response status |

### Growth and support
| Table | Purpose |
|---|---|
| `discount_codes` | Type, value, cap, minimum, date window, scope, first-order-only |
| `discount_redemptions` | **Unique on `order_id`** — this is what enforces one code per order |
| `referral_rewards` | **Unique on (`referred_id`, `event`)** — this is what enforces one reward per event |
| `support_tickets` / `support_messages` / `support_attachments` | Ticketing with threaded messages and private files |

### Platform
| Table | Purpose |
|---|---|
| `platform_settings` | Generic key/value JSON store — branding, legal text, withdrawal rules, referral amounts, top-up limits, gateway config, system email. `is_public` decides what the storefront may read |
| `currency_rates` | Rate to base per currency, with a manual override |
| `languages` / `translations` | Six languages, namespaced keys, machine-translation flag |
| `supplier_transaction_logs` | Every VivaPe call: endpoint, payload, status, latency, cost |

### The three key constraints

Much of the business logic is enforced by the database rather than by code:

```sql
UNIQUE (wallet_ledger_entries.idempotency_key)  -- no double-credit, ever
UNIQUE (discount_redemptions.order_id)          -- one code per order
UNIQUE (referral_rewards.referred_id, event)    -- one reward per event
```

---

## 4. Key flows

### 4.1 Wallet checkout

```
POST /orders/checkout
  ├─ resolve beneficiary (may create an account for a walk-in traveller)
  ├─ validate and price the discount code
  ├─ LedgerService.spend()      reward credit first, then main balance
  │     └─ row lock on the wallet, ledger entries written with before/after
  ├─ Order created (status PENDING)
  ├─ commit  ◀── the customer's money is now definitively accounted for
  └─ background: provision_esim()
        ├─ VivaPe create-transaction  (HTTP/2, logged)
        ├─ success → ESIMProfile written, order COMPLETED
        │             ├─ distribute_commission()
        │             └─ delivery email with QR + tracking link
        └─ failure → order FAILED, _refund_failed_order()
                      └─ refunds split by how it was paid
```

### 4.2 Commission distribution

The order matters and was the subject of a real bug. The agent is resolved
**first**, and the bonus derived from that, because a deduction is only
legitimate if somebody is actually receiving it:

```python
agent_user_id, agent_pct = commission_rate_for_merchant(merchant_profile)
bonus_pct = bonus_pct_for(merchant_profile, gross_rate_pct) if agent_user_id else 0
rate_pct  = gross_rate_pct - bonus_pct      # what the merchant actually gets
```

With a suspended agent, `agent_user_id` is `None`, so `bonus_pct` is zero and
the merchant receives the full rate — rather than the slice being taken off
the merchant and paid to nobody.

The ledger line written to the merchant's wallet names the **net** rate, since
naming the pre-deduction rate there would give the bonus away.

### 4.3 Gateway top-up

```
POST /payments/shurjopay/topup  { amount, currency }
  ├─ validate currency is supported
  ├─ convert to base for the min/max check      (limits are configured in EUR)
  ├─ if currency is BDT → charge exactly that   (no EUR round-trip)
  │  else               → convert base → BDT
  └─ ShurjoPay checkout URL returned
        ↓ customer pays
  GET /payments/shurjopay/callback   → browser returns to /wallet
  POST /payments/shurjopay/ipn       → server-to-server confirmation
        └─ credit wallet with an idempotency key (retries are safe)
```

### 4.4 eSIM live status

```
GET /esims/{id}/status
  ├─ cached telemetry younger than 5 min?  → serve it
  └─ else → VivaPe esim/usage + esim/device-info → merge → cache

POST /esims/{id}/refresh
  └─ 45-second cooldown keyed on last_forced_at
     (only forced polls are throttled, so viewing the page never
      disables the button)
```

Activation state is derived from `is_installed` / `status_code` only — never
from supplier timestamps, which are populated during a coupon window and
would otherwise make an uninstalled eSIM look active.

### 4.5 Withdrawal

```
POST /withdrawals
  ├─ require approved KYC + saved payout account
  ├─ DEBIT main wallet now (WITHDRAWAL_HOLD)   ← held at request, not approval
  ├─ snapshot the payout account onto the request
  └─ emails to user + admin

approve → freeze conversion rate, require proof upload, status PAID
reject/cancel → CREDIT back in full (WITHDRAWAL_REVERSED)
```

---

## 5. Integrations

### VivaPe (supplier)

- REST over **HTTP/2 — mandatory**; the API rejects HTTP/1.1.
- Token authentication, cached for 30 minutes.
- Returns **HTTP 200 even for business errors**, so the response body is
  parsed for failure rather than trusting the status code.
- Every call is written to `supplier_transaction_logs` with payload, status
  and latency.
- Isolated in a single adapter module (`services/vivape_adapter.py`), which is
  what makes a second supplier an additive change rather than a rewrite.
- VivaPe's callback endpoints (`/api/worldmove/*-callback`) are **inbound to
  VivaPe**, not available to Triptel — which is why status is polled.

### ShurjoPay (payments)

Cards, bKash, Nagad, Rocket. Settles in **BDT only**. Both a browser callback
and a server-to-server IPN are handled; crediting is idempotent so a retried
IPN cannot double-credit. Live credentials are held in the admin console,
encrypted at rest — never in code, git, tests or the deploy environment.

### SMTP

Eight HTML templates. Port selects the encryption mode (465 implicit TLS, 587
STARTTLS). Sending is backgrounded so a slow mail server never delays an API
response.

---

## 6. Security

| Concern | Approach |
|---|---|
| Authentication | JWT bearer tokens, HS256, 7-day expiry; bcrypt password hashing |
| Google sign-in | ID token verified server-side; the OAuth **client secret is not used and must not be stored anywhere** |
| Authorisation | Role-based dependencies (`require_admin`, `require_super_admin`); capability checks (an approved agent profile, not a role) where a user can hold two roles at once |
| Partner API | Hashed API keys with a visible prefix; a short-lived token exchanged at `/partner/auth/token` |
| Rate limiting | Per-endpoint: 5/min on login and password reset, 10–20/min on sensitive mutations, 120/min for partner API keys |
| Private files | KYC documents, withdrawal proofs and support attachments live in their own Docker volumes and are served only through authenticated endpoints, never from the public `/uploads` mount |
| Public sharing | eSIM tracking links use `secrets.token_hex(16)` — 128 bits — specifically to avoid the enumerable-sequential-ID exposure seen on the supplier's own status page |
| Secrets | `SECRET_KEY` is required at boot and the application refuses to start in production with the development default; gateway credentials live in the admin console |
| CORS | Explicit origin allowlist; no wildcard, because credentials are allowed |
| Audit | Every administrative mutation records actor, IP, user agent and before/after state |

---

## 7. Deployment

### Topology

Docker Compose, orchestrated by **Dokploy** on a VPS. Four services:
`esim-db`, `esim-backend`, `esim-frontend`, plus Dokploy's own proxy on the
external `dokploy-network`.

Six named volumes, all of which must survive a redeploy:

```
esim_postgres_data · esim_uploads_data · esim_kyc_uploads_data
esim_withdrawal_uploads_data · esim_support_uploads_data · esim_logs_data
```

### Pipeline

```
git push origin main
      ↓
GitHub Actions "Test & Deploy"
      ├─ backend-tests: 382 pytest tests against a Postgres service container
      └─ deploy (only on main, only if tests pass)
            └─ POST /api/compose.deploy to the Dokploy API, retried 3×
                  ↓
            container rebuild → entrypoint runs `alembic upgrade head` → app starts
```

The pipeline calls the Dokploy **API** rather than using its git webhook: the
webhook silently no-ops on a branch mismatch and reports it as a redirect,
which `curl -f` does not treat as failure. That silent no-op caused a real
outage on 3 September 2026.

### The verification rule

**A green CI run is not proof that production changed.** After every deploy,
confirm against the live system directly — query `/openapi.json` for a new
endpoint, fetch the page and check the deployed bundle. This is a standing
rule, not a suggestion.

---

## 8. Configuration

Behaviour is driven from three places, in increasing order of operational
convenience:

1. **Environment variables** (`docker-compose.yml`) — database URL, secret
   key, supplier and SMTP credentials, upload paths, allowed origins. Changing
   these requires a redeploy.
2. **`platform_settings` table** — branding, legal text, withdrawal rules,
   referral amounts, top-up limits, payment methods, system email, selling
   profit percentage. Changing these takes effect immediately.
3. **Admin console** — the UI over (2), plus gateway credentials, catalogue
   prices, languages and translations.

The deliberate consequence: **the business can change its own text, prices,
rules and rates without an engineer.**

---

## 9. Quality controls

- **382 backend tests** covering the ledger's integrity invariant, checkout
  and refunds, commission and agent bonus arithmetic, RBAC, the Partner API,
  gateway callbacks, discounts, referrals, withdrawals, support and the
  supplier adapter.
- **Migration discipline** — `alembic check` for drift; migrations exercised
  up → down → up against a throwaway Postgres before merge.
- **Structured logging** via `structlog`, with request IDs.
- **Self-healing** — stuck-order recovery and webhook retries run
  continuously; the admin dashboard surfaces "needs attention" items
  including ledger balance, stuck orders and stalled installs.

---

## 10. Known architectural limitations

| Limitation | Consequence | Mitigation if it becomes a problem |
|---|---|---|
| Single supplier | No eSIM if VivaPe is down | Adapter isolation already makes a second supplier additive |
| Scheduler runs in-process | Jobs stop if the backend stops; a second replica would double-run them | Move to a dedicated worker before scaling horizontally |
| Single database instance | A single point of failure | Managed Postgres with replication |
| Client-side JWT in `localStorage` | Vulnerable to XSS if a script injection ever lands | httpOnly cookies + CSRF tokens |
| Status polled, not pushed | Up to 5 minutes stale | Supplier does not offer outbound callbacks to us; nothing to change today |
