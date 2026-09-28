# AI Agent Continuation Guide — Triptel

Version 1.0 · 28 September 2026

**Read this first if you are an AI coding agent (Claude Code, Cursor, Copilot,
Codex, Gemini CLI, …) picking this project up on a new machine.** It contains
everything needed to be productive without re-deriving it: how to run the
system, the conventions the codebase follows, the mistakes already made and
fixed, and the rules that must not be broken.

---

## 1. One-paragraph orientation

Triptel is a live travel-eSIM marketplace at <https://triptel.co>. FastAPI +
PostgreSQL backend, Next.js 15 frontend, deployed by Docker Compose through
Dokploy on a VPS, with GitHub Actions running 382 tests before every deploy.
It sells prepaid eSIM data plans bought wholesale from VivaPe, direct to
travellers and through travel agencies ("merchants") who are recruited by
distributors ("agents"). The hard part is not traffic — it is the money: a
three-wallet double-entry ledger, a commission chain with an
admin-approved agent bonus, discounts, referral credit that must never become
cash, and manual payouts.

Start with [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md), then
[`03_System_Architecture.md`](03_System_Architecture.md).

---

## 2. Repository layout

```
D:\eSim  (or wherever you clone it)
├── backend/
│   ├── app/
│   │   ├── api/v1/        18 routers — HTTP surface only
│   │   ├── services/      31 modules — ALL business logic
│   │   ├── models/        20 modules — SQLAlchemy ORM, 34 tables
│   │   ├── schemas/       Pydantic request/response models
│   │   ├── core/          config, database, security, deps, rate limiting, logging
│   │   ├── templates/email  8 HTML templates
│   │   └── main.py        app factory, startup seeding, schedulers
│   ├── alembic/versions/  20 migrations
│   ├── tests/             60 test files, 382 tests
│   └── requirements*.txt
├── frontend/
│   └── src/
│       ├── app/           25 routes (App Router)
│       ├── components/    shared + admin/ merchant/ support/ esim/ explore/ finance/
│       └── lib/           api.ts (all HTTP calls), AppSettingsContext.tsx
├── business/              ← this documentation
├── .github/workflows/     CI: test → deploy
├── docker-compose.yml
├── .env.example
├── PARTNER_API_DOCUMENTATION.md
└── vivape_doc.json        supplier's published Postman collection
```

There is **no `CLAUDE.md`** in the repository. This file is the equivalent.

---

## 3. Running it locally

Verified working on 28 September 2026. Adjust paths for your machine.

### 3.1 Prerequisites

- Python 3.11, Node.js 20+, Docker
- `pip install -r backend/requirements-dev.txt`
- `cd frontend && npm install`

### 3.2 Database

Any PostgreSQL 16 will do. A throwaway container:

```bash
docker run -d --name esim-test-pg \
  -e POSTGRES_USER=esim_test -e POSTGRES_PASSWORD=esim_test_pw \
  -e POSTGRES_DB=esim_test -p 55432:5432 postgres:16-alpine
```

That database name and credentials are what `backend/tests/conftest.py`
expects by default, so the test suite works with no further configuration.

For a local *development* instance, create a second database:

```bash
docker exec esim-test-pg psql -U esim_test -d postgres -c "CREATE DATABASE esim_docs OWNER esim_test;"
```

### 3.3 Backend

```bash
cd backend
export DATABASE_URL="postgresql+asyncpg://esim_test:esim_test_pw@localhost:55432/esim_docs"
export SECRET_KEY="local-dev-secret-not-production"
export ENVIRONMENT=development
export CATALOG_SYNC_INTERVAL_HOURS=0       # skip the supplier sync locally
export ALLOWED_ORIGINS="http://localhost:3010"
export FRONTEND_BASE_URL="http://localhost:3010"
export VIVAPE_EMAIL=x VIVAPE_PASSWORD=x SHURJOPAY_USERNAME=x SHURJOPAY_PASSWORD=x
export PYTHONPATH="$PWD"

python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

On first boot the app seeds a Super Admin, platform settings, six languages
and default currency rates:

```
superadmin@esim.local / SuperAdmin2026!
```

### 3.4 Frontend

```bash
cd frontend
NEXT_PUBLIC_API_URL="http://localhost:8010" npx next dev -p 3010
```

Open <http://localhost:3010>.

> `NEXT_PUBLIC_*` values are **inlined at build time**. `next dev` reads them
> from the environment, but a production image must receive them as Docker
> **build args** — setting them only as runtime environment has no effect on
> JavaScript that was already bundled.

### 3.5 Seeding demo data

A seed script that creates countries, products, customers, a merchant, an
agent, orders, eSIMs with telemetry, a support ticket, a withdrawal, discount
codes and a pending bonus request is the fastest way to get a realistic local
system. The one used to produce this documentation's screenshots creates:

| Account | Password | Role |
|---|---|---|
| `superadmin@esim.local` | `SuperAdmin2026!` | Super Admin (seeded by the app itself) |
| `admin@triptel.co` | `Demo2026!` | Admin |
| `rafiq@example.com` | `Demo2026!` | Customer with eSIMs, BDT preference |
| `sadia@example.com` | `Demo2026!` | Customer, referred, pending KYC |
| `sales@wanderlusttravels.com` | `Demo2026!` | Approved merchant, 20% rate, 5% agent bonus |
| `desk@bluehorizon.travel` | `Demo2026!` | Pending merchant |
| `agent@skyroute.com` | `Demo2026!` | Approved agent, code `SKYROUTE` |

Write your own against `backend/app/models/` — it is about 250 lines. Two
things to get right: create wallets via
`LedgerService.ensure_wallets_for_user()`, and **fund wallets through
`LedgerService.credit()`**, never by writing `wallet.balance` directly, or the
ledger integrity invariant breaks and a test will catch you.

### 3.6 Tests

```bash
cd backend && python -m pytest -q
```

Expect **382 passed**, in roughly 8–11 minutes. Do not pass
`TEST_DATABASE_URL` unless you mean to — the conftest default is already
correct, and overriding it with the wrong credentials produces 382 identical
`InvalidPasswordError` setup errors that look like a catastrophe and are not.

### 3.7 Frontend checks

```bash
cd frontend && npx tsc --noEmit && npm run build
```

---

## 4. Conventions this codebase follows

Match them. They are consistent throughout and deviating creates noise.

### Structure

| Rule | Why |
|---|---|
| Routers validate and authorise; **services decide and mutate**; models describe | Keeps HTTP concerns out of business logic |
| Logic reached from two entry points lives in **one service** | `distribute_commission()` is called from both wallet checkout and the Partner API — duplicating it would let them drift |
| Supplier calls go through `services/vivape_adapter.py` only | Makes a second supplier additive |
| Schema changes are **always** Alembic migrations | The app never creates tables |

### Comments

The codebase comments **why**, not what — usually the decision or the bug that
motivated the code. Examples that are actually in the source:

```python
# Promo credit is spent first on purpose: it is the balance the customer
# cannot get back as cash, so using it up before their own money is the
# outcome that favours them.

# Resolve the agent FIRST, because the deduction is only legitimate if
# somebody is actually receiving it.

# The NET rate: this line shows up in the merchant's own ledger, and naming
# the pre-deduction rate here would give the bonus away.
```

Write in that register. Do not add "# increment counter" comments.

### Money

- Everything stored is `Numeric(18, 4)` in **EUR**.
- Use `Decimal`, never `float`.
- Quantize to `Decimal("0.01")` for display and `Decimal("0.0001")` for
  storage.
- Any credit or debit that a retry could duplicate takes an
  **idempotency key**.
- Balance changes take a row lock (`SELECT … FOR UPDATE`).
- The caller owns the transaction boundary; `LedgerService` does **not**
  commit.

### Tests

- One test file per feature area, named `test_<area>.py`.
- Test names are sentences: `test_suspending_the_agent_hands_the_full_rate_back`.
- Test the business rule, not the implementation.
- Beware substring assertions — a fixture named "bonusm5 tours" once matched
  a check for `"bonus"`, and an order number `ORD-20260928` once matched a
  check for `"20"`. Both were false positives that cost real time.

---

## 5. Hard rules — do not break these

| # | Rule |
|---|---|
| 1 | **All persisted money is EUR.** Convert at the edges only. |
| 2 | **Reward credit can never become cash.** No code path from the REWARD wallet to a withdrawal, including through refunds. |
| 3 | **Refunds split by how the order was paid.** Promo back to promo, cash back to cash. |
| 4 | **Commission only on delivery.** Never on a pending or refunded order. |
| 5 | **A merchant is never shown the agent bonus.** Merchant-facing endpoints report the net rate. If you add a new merchant-facing field, check it does not leak the gross rate. |
| 6 | **The agent is resolved before the bonus is derived.** No agent → no deduction. |
| 7 | **Private uploads are never served from the public `/uploads` mount.** KYC, withdrawal proofs and support attachments have their own volumes and authenticated endpoints. |
| 8 | **Public share tokens are random, never sequential.** `secrets.token_hex(16)`. |
| 9 | **Live credentials never enter source, tests, git or the deploy environment.** ShurjoPay credentials live in the admin console, encrypted. The Google OAuth *client secret* is not used by this flow and must not be stored anywhere. |
| 10 | **Production database writes, secrets and Dokploy environment changes are performed by the platform owner, not by an agent.** Do not write to the production database. |
| 11 | **A green CI run is not proof that production changed.** Verify against the live system after every deploy. |
| 12 | **Store UTC, display Bangladesh time.** Never render a date with a bare `toLocaleString()` — use `frontend/src/lib/datetime.ts` or `app/core/timeutil.py`. A bare call follows the viewer's own timezone, and this product's viewers are travellers. |
| 13 | **Never relabel a supplier timestamp as UTC.** Honour any offset it carries; only a genuinely naive string falls back to `SUPPLIER_TIMEZONE`. |

---

## 6. Deploying

```bash
git add <files> && git commit && git push origin main
```

That is the whole deploy. GitHub Actions runs the suite and, only if it
passes, calls the Dokploy API to redeploy. Migrations run from the container
entrypoint before the app starts.

**Then verify against production**, which is a standing rule, not a
suggestion:

```bash
# is the new endpoint actually live?
curl -s https://triptel.co/openapi.json | python -c "import sys,json; print([p for p in json.load(sys.stdin)['paths'] if 'your-new-path' in p])"

# is the new frontend bundle actually serving?
curl -s https://triptel.co/wallet | grep -o 'static/chunks/app/wallet/page-[a-z0-9]*\.js'
```

Note: the OpenAPI document is at `https://triptel.co/openapi.json`, **not**
`/api/v1/openapi.json`.

If the Dokploy trigger flakes (it does, occasionally), rerun the failed job:

```bash
gh run rerun <run-id> --failed
```

---

## 7. Mistakes already made — do not repeat them

Each of these cost real time. They are recorded so they cost nobody else any.

| # | What happened | The lesson |
|---|---|---|
| 1 | The Dokploy **git webhook silently no-op'd** on a branch mismatch, reporting it as a redirect that `curl -f` treats as success. A deploy appeared green and shipped nothing, for days | CI green ≠ deployed. The pipeline now calls the Dokploy **API**, which returns an honest queued/error result |
| 2 | A suspended agent's bonus was deducted from the merchant and **paid to nobody** — the deduction and the payout were independent checks | Resolve the recipient first, then derive the deduction from it |
| 3 | eSIM **validity was dated from purchase**, so a 3-day plan bought a week early showed as expired on arrival | Validity runs from first activation. `activated_at`/`expires_at` stay null until install |
| 4 | `is_activated` read VivaPe's **coupon-window timestamps** and reported an uninstalled eSIM as active | Derive activation from `is_installed`/`status_code` only |
| 5 | A refresh cooldown **disabled the button for 45 s after any page view** | Track forced refreshes separately (`last_forced_at`) from cached reads |
| 6 | A "Live status" button was placed **inside the QR reveal panel**, invisible to anyone who had not tapped it — and pointless for anyone who had already installed | Put an entry point where the user actually is |
| 7 | Validation stricter than conversion: checking for a `CurrencyRate` row rejected BDT even though `get_effective_rate` has fallbacks | Validate against the same source the operation will use — hence `SUPPORTED_CURRENCIES` |
| 8 | An `alembic check` drift from a redundant `UniqueConstraint` **and** unique index on the same column | Pick one. Run `alembic check` before pushing |
| 9 | A careless edit truncated `OverviewTab.tsx` and left a `_unusedTail` wrapper | Read the whole region before a structural edit |
| 10 | Bash heredocs failed on apostrophes in prose; `sleep 300; tail` was blocked by the harness; `\| tail` buffered a background pytest run so it looked hung | Use the Write tool for prose; use a background task plus an `until` loop to wait |

| 11 | Supplier timestamps were sliced to `[:19]` and stamped UTC, which threw away any offset they carried and assumed UTC for the rest. An eSIM that came alive at 16:47 Dhaka time was shown as 00:47 the next morning | Convert, never relabel. And a comment reading "an hour's drift is immaterial" is a sign nobody measured it — it was eight |

### Supplier-specific gotchas

- **HTTP/2 is mandatory** (`http2=True` in httpx). HTTP/1.1 is rejected.
- **VivaPe returns HTTP 200 for business errors.** Parse the body.
- **`esim/apn-details` is broken upstream** — returns `{"code":401,"msg":"驗證失敗"}`.
- **The `/api/worldmove/*-callback` endpoints are inbound to VivaPe**, not
  available to us. That is why status is polled rather than pushed.
- The supplier token is cached for 30 minutes.

### Postgres/Alembic gotchas

- Extending a Postgres enum requires `ALTER TYPE … ADD VALUE` inside
  `op.get_context().autocommit_block()`.
- Exercise every migration up → down → up against a throwaway database before
  merging.

---

## 8. Regenerating the screenshots

The 50 images in `business/screenshots/` were captured with Playwright
against the local instance described in §3, seeded as in §3.5.

```bash
pip install playwright && playwright install chromium
```

The capture script signs in through `POST /api/v1/auth/login`, writes the JWT
into `localStorage` under `esim_token` before navigating, waits for the page,
optionally clicks a tab, and takes a full-page screenshot at 1440×950 (plus
three at 390×844 for mobile).

Two things that will otherwise waste your time:

- **Dashboards need ~6 seconds**, not 2. At 2 s you capture skeleton loaders
  and it is not obvious from the file that you did. Check a sample image.
- **Tab selectors are exact button labels**, and several carry live counts —
  use `button:has-text('KYC Review')`, not the full label with its number.

---

## 9. Where the project stands

**Complete and live.** Catalogue, storefront, accounts, KYC, wallet and
ledger, gateway and manual top-up, multi-currency top-up, checkout and
provisioning, eSIM live status and public tracking, merchant portal, Partner
API, agent portal, agent bonus with approval, withdrawals, discount codes,
referrals, support ticketing, notifications, admin console, reporting.

**Open — business tasks, not engineering ones:**

- Run one real ShurjoPay top-up end to end against the live gateway.
- Enter real bKash / Nagad / bank deposit account details in the admin
  console.
- Replace the placeholder support numbers (`+880 1700-000000`).
- Fill in the Declaration's bracketed business details; get all six legal
  pages reviewed by a lawyer.
- Set withdrawal rules, referral amounts, top-up limits and any launch
  discount codes — all ship at zero or disabled.
- Create a test account to prove the `system@triptel.co` email round-trip.
- Raise VivaPe's enumerable status-page URL with the supplier.

**Sensible engineering next steps, none urgent:**

- A second supplier behind the existing adapter, to remove the concentration
  risk.
- Move the schedulers out of the web process before running more than one
  replica.
- Managed, replicated PostgreSQL.
- Move the JWT from `localStorage` to an httpOnly cookie with CSRF
  protection.

---

## 10. Working effectively on this codebase

1. **Read before writing.** The services are dense and the comments explain
   decisions you will otherwise undo.
2. **Change the service, not the router.**
3. **Write the test first when touching money.** The ledger invariant test
   has caught real bugs in this code.
4. **Run the full suite before pushing.** It takes ten minutes and the deploy
   depends on it.
5. **Verify production after deploying.** Every time.
6. **Never write to the production database.** Ask the owner.
7. **When a business rule seems arbitrary, it probably is not.** The agent
   bonus confidentiality, the promo-credit firewall and the
   validity-from-activation rule all came from real requirements or real
   incidents. Check
   [`02_Business_Requirements_Specification.md`](02_Business_Requirements_Specification.md) §5
   before changing one.

---

## 11. Prompt to start a fresh AI session

Paste this into a new agent session in the repository root:

> This is Triptel, a live travel eSIM marketplace (FastAPI + PostgreSQL +
> Next.js 15, deployed via Dokploy, tested by GitHub Actions).
>
> Before doing anything, read `business/09_AI_Agent_Continuation_Guide.md`
> in full, then `business/03_System_Architecture.md`. The hard rules in §5 of
> the continuation guide are not negotiable — in particular: all stored money
> is EUR; reward credit can never become cash; refunds split by how the order
> was paid; a merchant is never shown the agent bonus; production database
> writes and live secrets are handled by the owner, not by you; and a green CI
> run is not proof that production changed.
>
> Business logic belongs in `backend/app/services/`, not in routers. Schema
> changes are always Alembic migrations. Run `cd backend && python -m pytest -q`
> (expect 382 passed) before pushing anything.
>
> My task is: <describe it>
