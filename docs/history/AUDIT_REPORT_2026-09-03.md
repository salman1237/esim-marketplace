> **Historical document — archived 2026-11-10.** This audits the codebase as it
> stood on 2026-09-03, an early-stage state. The specific defects below (the
> backend failing to import, `Order.buyer_id`/`beneficiary_id` not existing on
> the model, the undefined `WalletType` name, etc.) have since been fixed — the
> current codebase already uses the field names this report says are missing.
> Kept for the record of what was found and fixed, not as a description of the
> current system. Do not treat anything below as current.

# eSIM Marketplace Platform — Codebase Audit Report

**Date:** 2026-09-03
**Scope:** Full repository (`D:\eSim`) vs. `IMPLEMENTATION_PLAN.md` (Phases 0–8)
**Method:** Direct file review, static cross-checks between models/routes/schemas, and empirical verification (actual `pip install` + Python import of the FastAPI app; AST-level import analysis).

## Bottom line

The plan describes a mature 8-phase marketplace. What's committed is an early-stage skeleton with the right *shape* (models, routers, services, RBAC scaffolding all exist) but the money-moving core is not functional as written. Most severely: **the backend cannot start at all** due to an undefined name in `wallets.py`, and even if that one line is fixed, **the entire order/checkout/eSIM-issuance flow and the entire ShurjoPay payment gateway integration crash on every call** because the route/service code was written against field names that don't exist on the actual SQLAlchemy models. There is also a live SSH private key committed to git history, and no automated test suite despite an extensive one being specified in the plan.

None of this is cosmetic — these are the three things a marketplace exists to do (accept a user, take their money, hand them a working eSIM), and none of the three paths currently complete.

---

## CRITICAL — fix before anything else

### 1. The backend does not start
`backend/app/api/v1/wallets.py:61` — `async def get_wallet_ledger(wallet_type: WalletType, ...)` references `WalletType`, which is never imported in this file. Python evaluates parameter annotations at function-definition time, so this raises `NameError: name 'WalletType' is not defined` the moment the module is imported.

This was verified empirically, not just read: installing the project's dependencies and running `import app.main` reproduces
```
IMPORT FAILED: NameError name 'WalletType' is not defined
```
Since `app/api/v1/__init__.py` imports `wallets_router` unconditionally, **the whole FastAPI app fails to boot**. Nothing in the backend can be exercised — including the manual smoke test in `tests/test_full_workflow.py` — until this one line is fixed.

The same function also does `from app.models.wallet import LedgerEntry` (line 62) inside the handler body — the actual class is `WalletLedgerEntry`; this would `ImportError` the moment the (currently unreachable) route is hit. The whole endpoint duplicates `/wallets/ledger` above it and should probably just be deleted.

### 2. Checkout — the core purchase flow — cannot complete, for any role
`backend/app/api/v1/orders.py:71-81` constructs:
```python
order = Order(order_no=..., buyer_id=current_user.id, beneficiary_id=beneficiary_id, ...)
```
but `Order` (`backend/app/models/order.py:21-45`) has no `buyer_id` or `beneficiary_id` columns — it has `user_id` and `merchant_id`. SQLAlchemy's declarative constructor rejects unknown kwargs, so this raises `TypeError` immediately.

Even if that's fixed, `ESIMProfile(..., beneficiary_id=..., smdp_address=..., matching_id=..., status=ESIMStatus.RELEASED, expires_at=...)` at `orders.py:137-147` fails the same way: the model (`order.py:53-66`) has none of `beneficiary_id`/`smdp_address`/`matching_id`/`expires_at`, and `ESIMStatus.RELEASED` isn't even a valid enum member (only `ALLOCATED/INSTALLED/ACTIVE/EXPIRED` exist).

Downstream, `list_my_esims` and `list_reseller_orders` (`orders.py:155-213`) query `Order.buyer_id` / `ESIMProfile.beneficiary_id` — same nonexistent columns. `admin.py:319` (`GET /admin/orders`) does the same. The merchant-commission branch (`orders.py:94-113`) additionally reads `merchant_profile.commission_rate_pct` and writes `order.reseller_commission_amount`, neither of which exist (`MerchantProfile.commission_rate`, `Order.reseller_commission` are the real names).

**Net effect: no eSIM can be purchased — by a user, by a merchant buying for a customer, or by an admin issuing one — anywhere in the app.** This breaks Phases 2, 3, 5 and everything the frontend in Phase 6 depends on.

### 3. The ShurjoPay payment gateway is completely non-functional
`backend/app/services/shurjopay_svc.py` constructs `PaymentLog(gateway=..., endpoint=..., request_payload=..., response_payload=..., status_code=...)` in all three of its methods (`authenticate`, `initiate_payment`, `verify_payment`) — but `PaymentLog` (`backend/app/models/payment.py:38-49`) has none of `endpoint`/`request_payload`/`response_payload`/`status_code`; its actual columns are `transaction_id`, `order_id`, `status`, `amount`, `currency`, `raw_callback_payload` (the last two of which are required and never supplied either). Every call to `authenticate()` — which every other method calls first — throws `TypeError` before returning anything. **There is no working payment-gateway path.**

### 4. The manual bank-deposit queue is also broken
`backend/app/api/v1/wallets.py:39-57` — `ManualPaymentRequest(..., receipt_url=req.receipt_url, ...)`; the model's actual field is `deposit_slip_url` (`models/payment.py:19-36`). `TypeError` on every submission. The admin-side queue listing (`admin.py:188`) reads the same nonexistent `receipt_url` and also 500s.

**So all three payment paths — wallet checkout, gateway top-up, and manual bank deposit — are broken by the same class of bug: route/service code was written against a schema that doesn't match the committed models.** This is systemic, not a couple of typos — it strongly suggests the models were changed (or a different version of them was written) without updating the ~10 call sites that depend on the old field names, and that the code was never actually run end-to-end after that change (see "Why this wasn't caught" below).

### 5. `GET /auth/me` crashes for every logged-in user
`backend/app/api/v1/auth.py:69,71,76` reads `current_user.phone` (model field is `phone_number`), `current_user.is_kyc_verified` (doesn't exist on `User` at all — only `is_verified`), and `merchant.commission_rate_pct` (model field is `commission_rate`). This is likely the most-called authenticated endpoint (session bootstrap on every page load) — in practice the app is unusable past login. Same `current_user.phone` bug recurs in `orders.py:126` and `payments.py:30`.

### 6. `apply-merchant` crashes on every call
`auth.py:90-97` — `MerchantProfile(..., website=req.website, ...)`; the model has no `website` column. `TypeError` every time.

### 7. A live SSH private key is committed to git history
`esim_deploy_key` (OpenSSH private key, 7 lines, confirmed by reading the file header) and its `.pub` counterpart are tracked in git (`git ls-files` confirms both; last touched in commit `c6fc396`). Whoever holds a clone of this repo has direct SSH access to whatever host this key authorizes — almost certainly the Dokploy VPS (`89.116.122.118`) referenced throughout the plan. The repo is currently private on GitHub, which limits exposure today, but a committed private key is a standing liability (present in every clone, every backup, any future fork or collaborator, and permanently in history even if deleted from the tip). **Rotate/revoke this key on the server and remove it from git history**, don't just delete the file going forward.

### 8. Real-shaped credentials hardcoded as source-level defaults
`backend/app/core/config.py`, `.env.example`, and `docker-compose.yml` all bake in fallback values for `SECRET_KEY` (JWT signing key), the Postgres password, the VivaPe login (`merchantusd@vivape.co` / `merchantusd@36` — note this targets `app.vivape.net`, described in the plan as the *live* API, not a sandbox), and the ShurjoPay sandbox login. Because `config.py` uses `os.getenv("X", "<literal>")` pattern, **any environment where the corresponding env var isn't actually set silently falls back to these committed values** — including the JWT secret, which means tokens become forgeable by anyone who has read this repo if it's ever left unset in production. Also, `.github/workflows/deploy.yml:14` embeds a Dokploy deploy-webhook token in a plaintext `http://` URL — anyone with that URL can trigger a redeploy, and it's sent unencrypted.

### 9. Double-credit / spoofing risk in the payment callback (once #3 is fixed)
`GET /payments/shurjopay/callback` (`payments.py:34-69`) has no auth dependency and no signature validation on top of the server-to-server verify call — it just trusts whatever ShurjoPay's `/api/verification` returns for the client-supplied `order_id`. There is no local record of "this order was already credited," and the ledger's `idempotency_key` column (`models/wallet.py:56`) is never actually populated by any caller (`grep` across the codebase confirms zero call sites pass one). Once the `PaymentLog` bug is fixed, repeated calls to this callback — e.g. a user refreshing the return-URL page — would re-credit the wallet every time. The user is also located by an 8-character UUID-prefix substring match (`User.id.startswith(...)`), which is fragile.

---

## Why none of this was caught

`tests/test_full_workflow.py` is the only test in the repo — a hand-run `httpx` script, not wired into pytest/CI (no `pytest` in `requirements.txt`, no `conftest.py` anywhere). It deliberately stops at the *insufficient-balance* checkout failure (`assert res.status_code == 400`, line 81) — which returns **before** the broken `Order()`/`ESIMProfile()` construction is ever reached — and never calls `/auth/me`, `/admin/orders`, `/wallets/manual-deposit`, `/wallets/ledger/{type}`, or any ShurjoPay endpoint. Every one of the crashing paths above is invisible to the one test that exists.

---

## Phase-by-phase status vs. `IMPLEMENTATION_PLAN.md`

### Phase 0 — Repo/Dokploy scaffolding
Git repo, private GitHub remote, `Dockerfile`s, `docker-compose.yml`, and a GitHub Actions deploy trigger all exist. **Gap:** the SSH deploy key is committed (see Critical #7) and the deploy webhook token is exposed in plaintext over HTTP (Critical #8).

### Phase 1 — Backend core, schema, auth, settings, currency
- Async SQLAlchemy 2.0: implemented. **Alembic: listed in `requirements.txt` but there is no `alembic/` directory or `alembic.ini` anywhere** — schema is created via `Base.metadata.create_all` on every startup, which only adds missing tables and can never alter an existing one. No migration history, no safe schema evolution.
- 4 roles: implemented (`models/user.py`).
- `languages` table: implemented. **`translations` table: does not exist** — no model, no CRUD, no way to add a new ISO language code or edit a translation string (only `PUT /admin/languages/toggle`, which flips `is_active` on the 7 pre-seeded rows). The "Super Admin Translation Editor" and "auto-translate" features from the plan have no backend at all.
- `platform_settings`: implemented (table + public GET + super-admin PUT), but no dedicated service module, and no way to change the platform's default currency (not a field on the branding-update schema).
- Currency service: open.er-api.com primary + jsDelivr fallback both implemented (`currency_svc.py`), with fixed-point `Decimal` arithmetic. **No 6-hour TTL** — `sync_rates_from_api` just overwrites whenever it's manually invoked; nothing schedules it and `get_effective_rate` never checks staleness. **TLS verification is disabled (`verify=False`)** on every call to this API.
- Logging tables (`audit_logs`, `supplier_transaction_logs`, `payment_logs`, `wallet_ledger_entries`): all exist as schema. `AuditMiddleware`: **does not exist** — audit logging is 7 manual `AuditService.log_action()` calls sprinkled through `admin.py`, none of which pass `ip_address` or `user_agent` (both columns exist, always `NULL`), and none of which capture `before_state` (only `after_state` — so there's no actual before/after diff despite that being explicit in the plan). `CorrelationIdMiddleware`: implemented as an inline function in `main.py` (functionally fine, just not a named class).
- `structlog` is a dependency but is never imported anywhere — all logging is bare `print()`, and nothing is persisted to `/var/log/esim/` despite the Docker image creating that directory.
- Seeding (Super Admin, settings, currencies, 7 languages) works. **The default Super Admin password (`SuperAdmin2026!`) is hardcoded in `main.py` and printed to stdout on every fresh boot** — fine for a first-run bootstrap, risky if this print output ends up in persisted container logs and the password is never rotated.

### Phase 2 — Double-entry ledger & wallets
`LedgerService.credit`/`debit` genuinely use `SELECT ... FOR UPDATE` row locking and correctly compute `balance_before`/`balance_after` — this part is solid. Default/Reward/Commission wallet provisioning per role is correctly implemented. **Idempotency key tracking is stubbed**: the column and a unique index exist, but no caller ever passes a key, and there's no pre-check/catch around the resulting `IntegrityError` — so "prevent double debits or credits" isn't actually enforced anywhere. Separately, `credit()`/`debit()` each `commit()` internally, and `orders.py` commits the `Order` row as `COMPLETED` *before* debiting the wallet — so a failure between those two commits leaves a completed order with no payment taken (this is masked today only because checkout crashes even earlier — see Critical #2).

### Phase 3 — VivaPe adapter & catalog
Bearer-token caching/re-auth, `/countries` and `/products` sync, and `create-transaction → get-esim-by-trx` provisioning calls are all implemented and, unlike the payment/order code, their logging model (`SupplierTransactionLog`) actually matches how it's constructed — this part works. Two gaps: (a) product classification just substring-matches `"esim"` in the title/reference rather than specifically `esimgo_bundle`/`worldmove_esim` as specified; (b) **when the VivaPe call fails for any reason, `orders.py:116-135` silently falls back to a locally-fabricated fake ICCID/LPA/QR code and proceeds as if provisioning succeeded** — a paying customer could receive a QR code that was never issued by any supplier and will never connect. Combined with Critical #2 this code path is currently unreachable, but it needs to be removed (fail loudly + refund) rather than fixed in place, once checkout itself works. TLS verification is also disabled here.

### Phase 4 — Payments
Covered above (Critical #3, #4, #9). Additionally: **no signature validation** exists anywhere in the codebase (`grep` for `signature|hmac` returns nothing), despite the plan explicitly requiring it and the audit schema having a field for it. The manual queue has an approve endpoint but **no reject endpoint**.

### Phase 5 — Reseller / buy-for-user
Logic for "search existing user," "auto-generate user," and commission calculation is present in `orders.py`, but it's all downstream of the broken `Order`/`ESIMProfile` construction (Critical #2) and so cannot currently execute. Separately, **there's no role restriction on `is_buy_for_user`** — any authenticated `USER` (not just Merchant/Admin/Super Admin) can pass `is_buy_for_user: true` with a `beneficiary_email`, contradicting the plan's RBAC table which marks this feature "No Access" for the User role.

### Phase 6 — Frontend storefront (full detail in the frontend section below)
Multilingual engine, currency conversion, and dynamic branding are each wired about 20% of the way: the dependencies and some plumbing exist, but almost nothing is actually connected to visible UI. Checkout only ever sends `payment_method: "WALLET"` — the ShurjoPay button is a bare `alert()`.

### Phase 7 — Super Admin / Admin operations UI
There is one combined `admin/page.tsx` for both Admin and Super Admin, with **no role branching in the UI at all** — anything either role can reach, both can see and use, including a control that lets any user who loads the page reassign roles (including granting `SUPER_ADMIN`) via a plain `<select>`. Whether this is actually exploitable depends entirely on the backend's `require_super_admin` dependency correctly gating the underlying endpoint (it does, per the RBAC check above) — but there is no defense-in-depth on the client, and three built admin tabs (Orders, Catalog, Users) are wired up but unreachable because the tab-switcher component doesn't list them. No language/translation manager, no secrets viewer, no ledger JSON-inspect modal, no maintenance-mode toggle exist anywhere in the UI.

### Phase 8 — E2E verification & deployment
Not attempted in this audit (would require a running, non-crashing backend). Given Critical #1–#6, a live smoke test today would fail at nearly every step described in the plan's own verification checklist.

---

## Frontend findings (full detail — condensed from a dedicated pass)

- **`next-intl` is a dependency that is never imported or used anywhere.** No `[locale]` routing, no middleware, no `NextIntlClientProvider`. The four locale JSON files (`en`/`bn`/`ar`/`es` — missing `fr`/`de`/`zh`/`ja`/`ru`/`hi`/`tr`/`pt`/`it` from the plan's list) are never read by any component. The header's language switcher only toggles `dir="rtl"`/`ltr` on `<html>` and local component state — **no visible text on any page ever changes when you switch language.** `es.json` is also missing whole sections (`nav`, `reseller`, `wallet`, `admin`) that `en.json`/`bn.json` have.
- **RTL is half-done**: `dir="rtl"` is correctly applied for Arabic, but the app uses only physical Tailwind classes (`ml-`, `pr-`, `left-`, `space-x-*`) rather than logical ones (`ms-`, `pe-`, `start-`), so layout will visually break, not mirror correctly, in Arabic.
- **The currency switcher has no effect on any price anywhere** — every price in every page is a hardcoded `$`-literal string; `api.getRates()` is defined but never called. `wallet/page.tsx:41` separately hardcodes a `* 122.63` USD→BDT conversion literal in the client bundle, bypassing the currency engine entirely.
- **Dynamic branding is half-wired**: the header pulls `platform_name` from the settings API, but the footer is 100% hardcoded (contact email, WhatsApp, phone, copyright), there's no dynamic logo/favicon handling, and page `<title>`/meta description are static, set inside a `"use client"` root layout rather than Next's `metadata` export (which also weakens SSR SEO).
- **The ShurjoPay "Pay via Gateway" button is a fake `alert("Redirecting to ShurjoPay Sandbox...")`** — no real integration on the frontend at all.
- **`/profile` is linked from the header and the mobile bottom nav but the route doesn't exist** — a 404 on one of the four primary navigation destinations.
- **JWT is stored in `localStorage`**, not an httpOnly cookie — standard XSS-exfiltration exposure; there's no CSP configured to mitigate it, and `next.config.mjs` allows images from any remote host (`hostname: "**"`).
- **No RBAC branching in the admin UI** (see Phase 7 above) — anyone who can load `/admin` sees identical Super-Admin-only controls regardless of actual role; the page only checks for token *presence*, not role.
- Three built admin features (Orders/Catalog/Users tabs) are unreachable dead code because the tab switcher doesn't list them.
- `next.config.mjs` sets `typescript.ignoreBuildErrors: true` and `eslint.ignoreDuringBuilds: true` — type and lint errors are silently suppressed at build time.
- Declared-but-unused dependencies: `next-intl`, `framer-motion` (no count-up animation, no imports found), `canvas-confetti` (no QR "reveal ceremony" animation, no imports found) — the plan's signature UX moments (animated wallet balances, flip-and-reveal QR ceremony) don't exist despite the libraries being installed for them.
- Mobile bottom nav itself is solidly built (correct 44px touch targets, correct sticky positioning); the merchant/reseller portal (`reseller/page.tsx`) is the most complete role-specific page in the app.

---

## Recommended remediation order

1. Fix the `WalletType` import in `wallets.py` (one line) so the backend can start at all.
2. Reconcile `Order`/`ESIMProfile`/`MerchantProfile`/`PaymentLog`/`ManualPaymentRequest` — decide which is correct (the models or the route/service code) and make them agree everywhere; this is a single coordinated pass across ~6 files, not six separate bugs.
3. Add real integration coverage (pytest, run in CI) that actually exercises a *successful* checkout, a ShurjoPay round trip, and `/auth/me` — the exact paths that are currently broken and untested. This is what would have caught all of the above before it was ever committed.
4. Rotate/revoke `esim_deploy_key` on the VPS and strip it from git history; move all real credentials out of source defaults and into environment-only configuration with no committed fallback for `SECRET_KEY` in particular.
5. Add idempotency enforcement on the ledger service and the payment callback before re-enabling the ShurjoPay path.
6. Re-enable TLS verification (`verify=True`) on every outbound `httpx` call; fix the CORS wildcard-plus-credentials combination.
7. Wire the frontend's language switcher and currency switcher to something real, or remove them until they are — right now they're controls that visibly do nothing, which is worse for trust than not having them.
8. Set up Alembic before the schema needs its first real change in production.
