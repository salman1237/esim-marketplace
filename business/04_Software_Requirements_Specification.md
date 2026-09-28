# Software Requirements Specification (SRS) — Triptel

Version 1.0 · 28 September 2026
Conforms in spirit to IEEE 830; adapted for a system that is already built.

---

## 1. Introduction

### 1.1 Purpose

This document specifies the software requirements for the Triptel eSIM
marketplace. It states what the software does, how it is constrained, and
what interfaces it exposes. Business justification for each capability is in
`02_Business_Requirements_Specification.md`; requirement IDs there (`BR-…`)
are cross-referenced from here.

### 1.2 Product scope

A web platform that sells prepaid travel eSIM data plans direct to consumers,
through resellers, and through a machine API — with an internal wallet
ledger, a commission and distribution system, and an administrative console.

### 1.3 Definitions

| Term | Meaning |
|---|---|
| **eSIM** | An embedded SIM profile installed by QR code or activation string |
| **ICCID** | The unique serial number identifying a SIM profile |
| **LPA string** | `LPA:1$<SM-DP+ address>$<matching ID>` — the activation string a phone consumes |
| **SM-DP+** | The carrier server that delivers the profile to the handset |
| **Base currency** | EUR. Every stored monetary value is in it |
| **Beneficiary** | The person who receives the eSIM, who may differ from the buyer |
| **Merchant** | An approved reseller |
| **Agent** | An approved distributor who recruits merchants |
| **Reward credit** | Promotional balance: spendable on eSIMs, never withdrawable |
| **Idempotency key** | A unique string making a credit or debit safe to retry |

### 1.4 Technology baseline

| Layer | Technology |
|---|---|
| Frontend | Next.js 15 App Router · React · TypeScript · Tailwind CSS |
| Backend | FastAPI · Python 3.11 · async SQLAlchemy 2.0 · Pydantic |
| Database | PostgreSQL 16 · Alembic (20 migrations) |
| Scheduling | APScheduler, in-process |
| Auth | JWT HS256 (7-day expiry) · bcrypt · Google ID token verification |
| Container | Docker Compose · Dokploy |
| CI/CD | GitHub Actions |

---

## 2. Overall description

### 2.1 Actors

| Actor | Authentication | Capabilities |
|---|---|---|
| Anonymous visitor | none | Browse catalogue, read legal pages, open a public eSIM tracking link, register |
| Customer (`USER`) | JWT | Buy, wallet, eSIMs, withdraw, refer, support, KYC |
| Merchant (`MERCHANT`) | JWT + approved profile | All customer capabilities, plus reseller portal, commission, statements, API keys |
| Agent (`AGENT`) | JWT + approved profile | All customer capabilities, plus agent portal, merchant network, bonus requests |
| Admin (`ADMIN`) | JWT | Operational queues, catalogue, reports, support, customer wallet actions |
| Super Admin (`SUPER_ADMIN`) | JWT | All admin capabilities, plus staff/roles, branding, languages, gateway credentials |
| Partner system | API key → bearer token | Catalogue read, order creation, order read, webhook configuration |

> An agent may simultaneously be a merchant. Capability is determined by the
> **presence of an approved profile**, not solely by the role field.

### 2.2 Operating environment

Modern browsers, desktop and mobile (the UI is responsive and includes a
mobile bottom navigation bar). Backend runs on Linux under Docker.

### 2.3 Design constraints

| # | Constraint |
|---|---|
| C1 | All persisted money is EUR |
| C2 | Supplier calls must use HTTP/2 |
| C3 | The supplier returns HTTP 200 for business errors — responses must be parsed, not trusted |
| C4 | ShurjoPay settles in BDT only |
| C5 | Schema changes are Alembic migrations; the application never creates tables |
| C6 | `NEXT_PUBLIC_*` values are build-time, not runtime |
| C7 | Live gateway credentials must not exist in source, tests, or the deploy environment |
| C8 | Private uploads must never be served from the public static mount |

---

## 3. Functional requirements

Each requirement lists the endpoints or UI that satisfy it. All endpoints are
prefixed `/api/v1`.

### 3.1 Authentication and accounts — `BR-ACC-*`

| ID | Requirement | Interface |
|---|---|---|
| FR-AUTH-1 | Register with email, username and password | `POST /auth/register` (5/min) |
| FR-AUTH-2 | Sign in and receive a JWT | `POST /auth/login` (10/min) |
| FR-AUTH-3 | Sign in with a Google ID token | `POST /auth/google` |
| FR-AUTH-4 | Request and complete a password reset with a hashed, single-use, expiring token | `POST /auth/forgot-password`, `POST /auth/reset-password` (5/min) |
| FR-AUTH-5 | Read the current identity, wallets, profiles and preferences | `GET /auth/me` |
| FR-AUTH-6 | Update preferred currency | `PUT /auth/me/preferences` |
| FR-AUTH-7 | Apply to become a merchant, optionally quoting an agent code | `POST /auth/apply-merchant` |
| FR-AUTH-8 | Enforce role-based access on every protected route | `require_admin`, `require_super_admin` dependencies |

### 3.2 KYC — `BR-ACC-3..5`

| ID | Requirement | Interface |
|---|---|---|
| FR-KYC-1 | Submit an NID number and up to two document images | `POST /kyc/submit` |
| FR-KYC-2 | Read own submission status | `GET /kyc/me` |
| FR-KYC-3 | Staff review queue | `GET /admin/kyc/queue` |
| FR-KYC-4 | Staff view a document image, authenticated only | `GET /admin/kyc/{id}/document/{side}` |
| FR-KYC-5 | Approve or reject with a reason | `POST /admin/kyc/{id}/approve`, `/reject` |
| FR-KYC-6 | Force a user to re-verify | `POST /admin/kyc/request-reverification` |

### 3.3 Catalogue — `BR-CAT-*`

| ID | Requirement | Interface |
|---|---|---|
| FR-CAT-1 | List active countries | `GET /catalog/countries` |
| FR-CAT-2 | List products for a country | `GET /catalog/countries/{iso2}/products` |
| FR-CAT-3 | Serve a destination landing page by slug | `GET /catalog/destinations/{slug}` |
| FR-CAT-4 | Read one product | `GET /catalog/products/{id}` |
| FR-CAT-5 | Synchronise the supplier catalogue on demand and on a 4-hour schedule | `POST /admin/catalog/sync` + scheduler |
| FR-CAT-6 | Apply a global markup that re-prices every product | `PUT /admin/pricing` (default 25%) |
| FR-CAT-7 | Override an individual product's price or visibility | `PUT /admin/catalog/{id}` |
| FR-CAT-8 | Export the catalogue | `GET /admin/catalog/export.xlsx` |

### 3.4 Wallet and ledger — `BR-PAY-7,8`

| ID | Requirement | Interface |
|---|---|---|
| FR-WAL-1 | Return the user's wallets and balances | `GET /wallets/my-wallets` |
| FR-WAL-2 | Return the transaction ledger, filterable by wallet type | `GET /wallets/ledger` |
| FR-WAL-3 | Every entry records type, amount, balance before, balance after, reference and description | `wallet_ledger_entries` |
| FR-WAL-4 | Every credit and debit may carry a unique idempotency key; a repeat returns the original entry rather than creating a second | `LedgerService` |
| FR-WAL-5 | Balance changes take a row lock on the wallet | `SELECT … FOR UPDATE` |
| FR-WAL-6 | Spending draws from reward credit first, then the main balance, returning the promo share | `LedgerService.spend()` |
| FR-WAL-7 | Each wallet's balance must always equal the sum of its ledger entries | Invariant, covered by test |

### 3.5 Money in — `BR-PAY-1..6`

| ID | Requirement | Interface |
|---|---|---|
| FR-PAY-1 | Start a gateway top-up in a chosen currency | `POST /payments/shurjopay/topup?amount=&currency=` |
| FR-PAY-2 | Reject an unsupported currency | 11 supported: USD, BDT, EUR, GBP, AED, SAR, THB, SGD, JPY, MYR, INR |
| FR-PAY-3 | Check the amount against min/max configured **in base currency** | `topup_limits_svc` (default €1–€2000) |
| FR-PAY-4 | A BDT amount must be charged exactly as typed, with no EUR round-trip | `payments.py` |
| FR-PAY-5 | Handle the browser callback and the server-to-server IPN | `GET /payments/shurjopay/callback`, `GET|POST /payments/shurjopay/ipn` |
| FR-PAY-6 | Credit idempotently so a retried IPN cannot double-credit | Idempotency key per gateway order |
| FR-PAY-7 | Submit a manual deposit with bank/method, transaction ID and currency | `POST /wallets/manual-deposit` |
| FR-PAY-8 | Validate the method against the configured active list | `payment_methods_svc` |
| FR-PAY-9 | Staff approve or reject a manual deposit; approval credits at that day's rate | `POST /admin/payments/manual/{id}/approve`, `/reject` |
| FR-PAY-10 | Pay for an order directly by gateway without pre-funding the wallet | `POST /payments/shurjopay/order-initiate` |

### 3.6 Ordering and provisioning — `BR-ORD-*`

| ID | Requirement | Interface |
|---|---|---|
| FR-ORD-1 | Check out from the wallet, optionally for another beneficiary, optionally creating that account | `POST /orders/checkout` |
| FR-ORD-2 | Apply at most one discount code, validated and priced server-side | `POST /discounts/preview` then checkout |
| FR-ORD-3 | Order total is stored **after** discount, so commission, profit and refunds all follow | `orders.total_amount` |
| FR-ORD-4 | Provision through the supplier and persist ICCID, SM-DP+, matching ID, LPA string and QR | `checkout_svc.provision_esim()` |
| FR-ORD-5 | On supplier failure, mark the order FAILED and refund automatically | `_refund_failed_order()` |
| FR-ORD-6 | A refund must return funds in the same proportion they were paid | Prevents promo→cash conversion |
| FR-ORD-7 | Distribute merchant commission, agent commission and agent bonus only on delivery | `distribute_commission()` |
| FR-ORD-8 | Email the eSIM with QR and tracking link | `order_confirmation.html` |
| FR-ORD-9 | Recover orders whose provisioning was interrupted | Sweep every 2 min |
| FR-ORD-10 | List own eSIMs and read one order | `GET /orders/my-esims`, `GET /orders/{id}` |
| FR-ORD-11 | Provide a printable eSIM sheet | `/my-esims/{id}/print` |

### 3.7 eSIM lifecycle — `BR-SIM-*`

| ID | Requirement | Interface |
|---|---|---|
| FR-SIM-1 | Return live status: data used, remaining, install state, device model, activation and expiry | `GET /esims/{id}/status` (60/min) |
| FR-SIM-2 | Cache telemetry for 5 minutes | `esim_telemetry_svc.TTL` |
| FR-SIM-3 | Allow a forced refresh no more than once every 45 seconds, tracked separately so page views never disable the button | `POST /esims/{id}/refresh` (20/min) |
| FR-SIM-4 | Derive activation from install state only, never from supplier coupon-window timestamps | `esim_telemetry_svc` |
| FR-SIM-5 | Set validity from first activation | `activated_at` / `expires_at`, null until installed |
| FR-SIM-6 | Serve a public status page from a 128-bit random token, with sensitive fields withheld | `GET /esims/public/{token}` |
| FR-SIM-7 | The public route must be declared before the authenticated `{id}` route so it is not shadowed | `esims.py` route order |

### 3.8 Merchant portal — `BR-MER-*`

| ID | Requirement | Interface |
|---|---|---|
| FR-MER-1 | Portal overview: sales, commission, balances | `GET /merchant/overview` |
| FR-MER-2 | Sell to a customer, creating their account if needed | `POST /orders/checkout` with beneficiary |
| FR-MER-3 | List and read own orders | `GET /merchant/orders`, `/orders/{id}` |
| FR-MER-4 | Transfer commission into the main wallet | `POST /merchant/commission/transfer` |
| FR-MER-5 | Monthly statement, on screen and as CSV | `GET /merchant/statement`, `.csv` |
| FR-MER-6 | Manage API access | `GET /merchant/api-access` |
| FR-MER-7 | Configure and test a webhook | `PUT /merchant/webhook-config`, `POST /merchant/webhook-test` |
| FR-MER-8 | **Never disclose the agent bonus** — all merchant-facing figures show the net rate | `merchant.py::_commission_info`, `partner.py` |

### 3.9 Agent portal — `BR-AGT-*`

| ID | Requirement | Interface |
|---|---|---|
| FR-AGT-1 | Apply to become an agent | `POST /agent/apply` |
| FR-AGT-2 | Read own status and agent code | `GET /agent/status` |
| FR-AGT-3 | Overview: partners, delivered sales, volume, commission | `GET /agent/overview` |
| FR-AGT-4 | Generate an invite link that pre-fills the B2B application with the agent code | `/reseller?agent=<CODE>` |
| FR-AGT-5 | List merchants and add one that has no agent | `GET /agent/merchants`, `POST /agent/merchants` |
| FR-AGT-6 | Request a bonus between 0% and 10% for a specific merchant | `POST /agent/bonus-requests` |
| FR-AGT-7 | Read own bonus requests and their decisions | `GET /agent/bonus-requests` |
| FR-AGT-8 | Sales, commission ledger and statements | `GET /agent/orders`, `/commission-ledger`, `/statement`, `/statement.csv` |
| FR-AGT-9 | Transfer commission to the main wallet | `POST /agent/commission/transfer` |

### 3.10 Agent bonus approval — `BR-AGT-5..8`

| ID | Requirement | Interface |
|---|---|---|
| FR-BON-1 | Staff queue of pending bonus requests showing current, requested and the resulting net merchant rate | `GET /admin/agent-bonus-requests` |
| FR-BON-2 | Approve — and only then write `agent_bonus_pct` on the merchant | `POST /admin/agent-bonus-requests/{id}/approve` |
| FR-BON-3 | Reject with a note | `POST /admin/agent-bonus-requests/{id}/reject` |
| FR-BON-4 | A bonus is capped at the merchant's own rate | `agent_svc.bonus_pct_for()` |
| FR-BON-5 | With no approved agent, no deduction occurs at all | `distribute_commission()` |

### 3.11 Withdrawals — `BR-WDR-*`

| ID | Requirement | Interface |
|---|---|---|
| FR-WDR-1 | Read eligibility and configured rules | `GET /withdrawals/config` |
| FR-WDR-2 | Manage saved payout accounts (bank or mobile), with a default | `GET|POST /withdrawals/accounts`, `DELETE`, `POST …/default` |
| FR-WDR-3 | Refuse a request without approved KYC or a saved account | `withdrawal_svc.eligibility()` |
| FR-WDR-4 | Debit the main wallet at request time | `WITHDRAWAL_HOLD` |
| FR-WDR-5 | Snapshot account details onto the request | `account_snapshot` JSON |
| FR-WDR-6 | User may cancel while pending; money returns in full | `POST /withdrawals/{id}/cancel` |
| FR-WDR-7 | Staff queue, approve with proof upload and payment reference, or reject | `GET /admin/withdrawals`, `/approve`, `/reject`, `/proof` |
| FR-WDR-8 | Freeze the conversion rate at approval | `conversion_rate`, `payout_amount` |
| FR-WDR-9 | A paid withdrawal can never be rejected afterwards | State machine |
| FR-WDR-10 | Email at request, approval and rejection | Three templates |
| FR-WDR-11 | Configure min, max, fee type/value, payout currency, processing time, enabled | `GET|PUT /admin/withdrawal-settings` |

### 3.12 Discounts — `BR-GRO-1..5`

| ID | Requirement | Interface |
|---|---|---|
| FR-DIS-1 | Preview a code against a product and return the discounted price | `POST /discounts/preview` |
| FR-DIS-2 | Support percent and fixed types, with an optional maximum discount | `DiscountType` |
| FR-DIS-3 | Support scope ALL / COUNTRY / PRODUCT, a date window, a minimum order and first-order-only | `DiscountCode` |
| FR-DIS-4 | Count usage from redemptions joined to live orders, including a 30-minute pending hold — never from a counter | `discount_svc` |
| FR-DIS-5 | Enforce one code per order at the database level | `UNIQUE (order_id)` |
| FR-DIS-6 | Full CRUD and a redemption list | `GET|POST|PUT|DELETE /admin/discounts…` |

### 3.13 Referrals — `BR-GRO-6..8`

| ID | Requirement | Interface |
|---|---|---|
| FR-REF-1 | Issue every user a referral code | `users.referral_code` |
| FR-REF-2 | Validate a code before signup | `GET /referrals/validate` |
| FR-REF-3 | Claim a referral and record the relationship | `POST /referrals/claim` |
| FR-REF-4 | Read own referral status and rewards | `GET /referrals/me` |
| FR-REF-5 | Reward on joining, first purchase and merchant conversion, configurable per event and per side | `GET|PUT /admin/referral-settings` |
| FR-REF-6 | Credit rewards to the **reward** wallet only | `REWARD_EARNED` |
| FR-REF-7 | One reward per referred person per event | `UNIQUE (referred_id, event)` |
| FR-REF-8 | Reverse a reward if the qualifying order is refunded | `REWARD_REVERSED` |

### 3.14 Support — `BR-SUP-*`

| ID | Requirement | Interface |
|---|---|---|
| FR-SUP-1 | List ticket categories | `GET /support/categories` (ESIM, PAYMENT, REFUND, ACCOUNT, PARTNER, OTHER) |
| FR-SUP-2 | Create a ticket, optionally linked to an order, with attachments | `POST /support/tickets` |
| FR-SUP-3 | List and read own tickets | `GET /support/tickets`, `/{id}` |
| FR-SUP-4 | Post a message with up to 5 attachments of 5 MB each | `POST /support/tickets/{id}/messages` |
| FR-SUP-5 | Status follows the last speaker: customer → OPEN, staff → ANSWERED | `support_svc.post_message()` |
| FR-SUP-6 | A customer reply to a RESOLVED ticket reopens it and clears the resolution timestamp | `support_svc` |
| FR-SUP-7 | Staff queue filterable by status, including ALL | `GET /support/queue` |
| FR-SUP-8 | Assign, resolve and close | `POST …/assign`, `/resolve`, `/close` |
| FR-SUP-9 | Serve attachments only to the ticket owner or staff | `GET /support/attachments/{id}` |
| FR-SUP-10 | Email each new message to the other party | `notify_svc` |

### 3.15 Partner API — `BR-MER-7`

| ID | Requirement | Interface |
|---|---|---|
| FR-API-1 | Exchange an API key for a bearer token | `POST /partner/auth/token` (10/min) |
| FR-API-2 | Read the partner's own profile and commission rate (net only) | `GET /partner/me` |
| FR-API-3 | Browse countries and products | `GET /partner/countries`, `/countries/{iso2}/products` |
| FR-API-4 | Create an order, idempotent on `customer_reference` | `POST /partner/orders` |
| FR-API-5 | List and read orders | `GET /partner/orders`, `/orders/{id}` |
| FR-API-6 | Configure a webhook for delivery notifications | `PUT /partner/webhook-config` |
| FR-API-7 | Rate limit per API key | 120/min |
| FR-API-8 | Retry failed webhook deliveries and log every attempt | Sweep every 5 min |

Full reference: [`PARTNER_API_DOCUMENTATION.md`](../PARTNER_API_DOCUMENTATION.md)
and the public page at `/api-docs`.

### 3.16 Administration — `BR-ADM-*`

| ID | Requirement | Interface |
|---|---|---|
| FR-ADM-1 | Dashboard: users, orders, revenue, active eSIMs, trends, "needs attention" | `GET /admin/dashboard`, `/stats` |
| FR-ADM-2 | Merchant approval queue with commission and agent assignment | `GET /admin/merchants/queue`, `/approve`, `/reject`, `/commission`, `/agent` |
| FR-ADM-3 | Agent approval queue and rate management | `GET /admin/agents`, `/approve`, `/reject`, `/commission`, `/margin-check` |
| FR-ADM-4 | All orders, filterable | `GET /admin/orders` |
| FR-ADM-5 | Sales report with breakdown and CSV | `GET /admin/reports/sales`, `/breakdown`, `.csv` |
| FR-ADM-6 | Finance: platform summary, merchant statements, supplier reconciliation, all with CSV | `GET /admin/finance/*` |
| FR-ADM-7 | Search customers (available to plain Admin, unlike full user management) | `GET /admin/customers/search` |
| FR-ADM-8 | Recharge a customer's wallet directly, audit-logged | `POST /admin/customers/{id}/wallet/recharge` |
| FR-ADM-9 | Purchase an eSIM for a customer, charged to **that customer's** wallet | `POST /admin/customers/{id}/purchase-esim` |
| FR-ADM-10 | Staff and user management, roles and status — Super Admin only | `GET|POST /admin/users`, `/role`, `/status`, `/make-reseller` |
| FR-ADM-11 | Branding and asset upload | `PUT /admin/branding`, `POST /admin/branding/upload` |
| FR-ADM-12 | Currency rate overrides | `PUT /admin/currencies/override` |
| FR-ADM-13 | Languages, translations and machine auto-translation | `/admin/languages*`, `PUT /admin/translations` |
| FR-ADM-14 | Legal document editing | `GET /admin/legal`, `PUT /admin/legal/{slug}` (privacy, data-policy, terms, declaration, refund-policy, payment-policy) |
| FR-ADM-15 | ShurjoPay credential management and a live test | `GET|PUT|DELETE /admin/payment-gateways/shurjopay`, `/test` |
| FR-ADM-16 | Deposit method configuration | `GET|PUT /admin/payment-methods` |
| FR-ADM-17 | Commission tier management | `GET|POST|DELETE /admin/commission-tiers` |
| FR-ADM-18 | Notification settings, including the system mailbox | `GET|PUT /admin/notification-settings` |
| FR-ADM-19 | Audit log and supplier call log with summaries | `GET /admin/audit-logs`, `/summary`, `/supplier-logs` |
| FR-ADM-20 | Supplier account balance | `GET /admin/supplier/account` |

### 3.17 Notifications — `BR-NOT-*`

Ten events send automatic email, each copied to the system mailbox
(`system@triptel.co`, configurable, stored non-public):

| Event | Recipients |
|---|---|
| Account created | User + system |
| B2B / merchant application submitted | Applicant, agent if quoted, admin, system |
| Agent application submitted | Applicant, admin, system |
| Referral code used | Referrer + system |
| Agent code used | Agent + system |
| Agent approved | Agent + system |
| Merchant approved | Merchant + system |
| Referred party became a merchant | Referrer + system |
| Transaction (order paid) | Buyer + system |
| Withdrawal (requested / paid / rejected) | User, admin, system |

### 3.18 Platform settings — `BR-ADM-7`

| ID | Requirement | Interface |
|---|---|---|
| FR-SET-1 | Serve public settings for the storefront | `GET /settings/public` |
| FR-SET-2 | Serve active languages and translations | `GET /settings/languages`, `/translations/{code}` |
| FR-SET-3 | Serve currency rates | `GET /settings/rates` |
| FR-SET-4 | Serve legal documents | `GET /settings/legal`, `/legal/{slug}` |
| FR-SET-5 | `is_public` must gate what the storefront can read; the system email and legal drafts are non-public | `platform_settings` |

---

## 4. Non-functional requirements

### 4.1 Security

| ID | Requirement |
|---|---|
| NFR-SEC-1 | Passwords stored with bcrypt; never logged or returned |
| NFR-SEC-2 | JWT HS256, 7-day expiry; `SECRET_KEY` required at boot, production refuses the development default |
| NFR-SEC-3 | Google sign-in verifies the ID token server-side; the OAuth client secret is not used and must not be stored |
| NFR-SEC-4 | Partner API keys stored hashed with a visible prefix only |
| NFR-SEC-5 | Rate limits: 5/min login, registration and password reset; 10–20/min sensitive mutations; 60/min status; 120/min per partner key |
| NFR-SEC-6 | CORS restricted to an explicit origin allowlist; no wildcard with credentials |
| NFR-SEC-7 | KYC documents, withdrawal proofs and support attachments served only through authenticated endpoints from private volumes |
| NFR-SEC-8 | Public share tokens are 128 bits of cryptographic randomness, never sequential |
| NFR-SEC-9 | Live gateway credentials stored encrypted in the admin console, never in source, tests or deploy configuration |
| NFR-SEC-10 | Every administrative mutation audit-logged with actor, IP, user agent and before/after state |

### 4.2 Reliability and data integrity

| ID | Requirement |
|---|---|
| NFR-REL-1 | Each wallet's balance always equals the sum of its ledger entries |
| NFR-REL-2 | Balance changes occur under a row lock |
| NFR-REL-3 | Credits and debits are idempotent where a retry is possible |
| NFR-REL-4 | An order, its ledger movements and its eSIM profile commit in one transaction |
| NFR-REL-5 | Interrupted provisioning self-recovers within 2 minutes |
| NFR-REL-6 | Failed webhooks retry on a 5-minute sweep with every attempt logged |
| NFR-REL-7 | A failing background job logs and continues; it must not stop the scheduler |
| NFR-REL-8 | Six named volumes survive redeploys |

### 4.3 Performance

| ID | Requirement |
|---|---|
| NFR-PERF-1 | eSIM telemetry cached 5 minutes; forced refresh throttled to 45 seconds |
| NFR-PERF-2 | Supplier token cached 30 minutes |
| NFR-PERF-3 | Email sending backgrounded so it never blocks a response |
| NFR-PERF-4 | Provisioning runs in the background after the paying transaction commits |
| NFR-PERF-5 | Catalogue sync backgrounded at startup so a slow supplier never delays boot or health checks |

### 4.4 Usability and accessibility

| ID | Requirement |
|---|---|
| NFR-USE-1 | Responsive from 390 px upwards, with a mobile bottom navigation bar |
| NFR-USE-2 | Six languages with RTL support for Arabic |
| NFR-USE-3 | Prices display in the user's chosen currency everywhere |
| NFR-USE-4 | Every admin tab shows its pending queue count |
| NFR-USE-5 | Failure is reported honestly — a failed order says so and explains the refund rather than presenting a fake success |

### 4.5 Maintainability

| ID | Requirement |
|---|---|
| NFR-MNT-1 | Business logic lives in services, not routers |
| NFR-MNT-2 | Logic shared by two entry points must be in one service |
| NFR-MNT-3 | Schema changes only via Alembic; `alembic check` must report no drift |
| NFR-MNT-4 | Migrations exercised up → down → up before merge |
| NFR-MNT-5 | The full test suite must pass before any deploy |
| NFR-MNT-6 | Supplier calls isolated in one adapter module |

### 4.6 Observability

| ID | Requirement |
|---|---|
| NFR-OBS-1 | Structured logging with request IDs |
| NFR-OBS-2 | Every supplier call logged with payload, status and latency |
| NFR-OBS-3 | Every gateway call logged |
| NFR-OBS-4 | A health endpoint for orchestration (`GET /health`) |
| NFR-OBS-5 | The admin dashboard surfaces stuck orders, ledger balance, failed orders, stalled installs and every pending queue |

### 4.7 Compliance

| ID | Requirement |
|---|---|
| NFR-CMP-1 | KYC required before payout |
| NFR-CMP-2 | Six editable legal documents: Privacy Policy, Data Privacy, Terms & Conditions, Declaration, Refund Policy, Payment Policy |
| NFR-CMP-3 | Identity documents retained privately and served only to authorised staff |
| NFR-CMP-4 | Financial records immutable — the ledger is append-only |

---

## 5. External interfaces

### 5.1 VivaPe (supplier)

| Property | Value |
|---|---|
| Base URL | `https://app.vivape.net/api` |
| Protocol | **HTTP/2 required** |
| Auth | Email/password → token, cached 30 min |
| Error convention | HTTP 200 even for business errors; parse the body |
| Used for | Catalogue, order creation, eSIM retrieval, usage, device info, account balance |
| Not available | `*-callback` endpoints are inbound to VivaPe, so status is polled |
| Known issue | Their public status page is enumerable by sequential ID |

### 5.2 ShurjoPay (payments)

| Property | Value |
|---|---|
| Methods | Cards, bKash, Nagad, Rocket |
| Settlement | BDT only |
| Return | `GET /api/v1/payments/shurjopay/callback` |
| Cancel | `/wallet?topup=cancelled` |
| IPN | `GET|POST /api/v1/payments/shurjopay/ipn` |
| Minimum | ৳10, independent of the platform minimum |
| Credentials | Admin console, encrypted at rest |

### 5.3 SMTP

Port 465 implicit TLS or 587 STARTTLS. Eight HTML templates: base, welcome,
order confirmation, password reset, notice, and three withdrawal states.
Production sends as `hello@triptel.co`.

---

## 6. Complete endpoint inventory

178 endpoints across 156 paths, all prefixed `/api/v1` except `/health`.

| Group | Count |
|---|---|
| Admin & Super Admin | 85 |
| Agent Portal | 12 |
| Support | 10 |
| Merchant Dashboard | 9 |
| Withdrawals | 9 |
| Authentication | 8 |
| Partner API | 8 |
| Public Settings | 6 |
| Payment Gateways | 5 |
| Finance & Reconciliation | 5 |
| Catalog | 4 |
| Orders & eSIMs | 4 |
| Wallets & Ledger | 3 |
| Referrals | 3 |
| eSIM Status | 3 |
| KYC | 2 |
| Discount Codes | 1 |
| Health | 1 |

The authoritative, always-current list is the OpenAPI document:

```
https://triptel.co/openapi.json
```

---

## 7. Verification

**382 automated backend tests**, all passing as of this document. Coverage by
area, from `backend/tests/`:

| Area | Test files |
|---|---|
| Ledger and wallets | `test_ledger`, `test_me_wallets`, `test_base_currency`, `test_currency_svc` |
| Checkout and refunds | `test_checkout`, `test_async_checkout`, `test_gateway_checkout`, `test_gateway_rejection` |
| Commission and agents | `test_agents`, `test_agent_bonus`, `test_commission_tiers`, `test_selling_profit` |
| eSIM lifecycle | `test_esim_status`, `test_esim_links`, `test_esim_provisioning_parsing`, `test_order_email_qr` |
| Payments | `test_shurjopay_*` (4 files), `test_payment_methods`, `test_topup_currency` |
| Withdrawals | `test_withdrawals` |
| Growth | `test_discount_codes`, `test_referrals` |
| Partner API | `test_partner_*` (6 files) |
| Support | `test_support` |
| Access control | `test_rbac`, `test_auth`, `test_google_login`, `test_rate_limiting`, `test_password_reset` |
| Admin | `test_admin`, `test_admin_dashboard`, `test_admin_catalog_search`, `test_admin_customer_actions` |
| Catalogue | `test_catalog_*` (4 files), `test_package_sorting`, `test_destination_page` |
| Reporting | `test_finance`, `test_sales_breakdown` |
| Platform | `test_translations`, `test_legal_content`, `test_email_svc`, `test_email_tls_mode`, `test_notifications` |

Run with:

```bash
cd backend && python -m pytest -q
```

A Postgres instance must be reachable at the URL in `tests/conftest.py`
(default `postgresql+asyncpg://esim_test:esim_test_pw@localhost:55432/esim_test`).
