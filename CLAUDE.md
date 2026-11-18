# CLAUDE.md

## Goal
Reliable, verified work over speed. This file governs the whole `D:\eSim` web
monorepo (FastAPI backend + Next.js frontend, one deploy unit) going forward,
introduced alongside the first task it was written for: **real-time customer
support chat**.

## Project Overview
Triptel - travel eSIM marketplace. `backend/` (FastAPI, async SQLAlchemy,
PostgreSQL) + `frontend/` (Next.js). Two environments: `beta.triptel.co`
(branch `development`) and `triptel.co` (branch `main`). The customer mobile
app is a **separate repo** (`D:\eSim\Triptel-flutter`, own harness) that talks
to this backend's REST/WS API - see "Cross-repo" below.

## Quick Start
- Backend: `cd backend && uvicorn app.main:app --reload`
- Backend tests: `cd backend && python -m pytest`
- Frontend: `cd frontend && npm run dev`
- Full verification: see `docs/Technical_Requirements.md` -> "Verification"

## Start
1. Read `claude-progress.md` (done, active, next step, blocked).
2. Open `feature_list.json`, take the single `active` item, or the first
   `not_started` one in build order.
3. Verify you start from green (`docs/Technical_Requirements.md`).

## Operating mode: AUTONOMOUS (per explicit instruction)
No approval needed for implementation work. Pick the next feature, build it,
verify it, commit it, push to `development`, update state, continue - without
stopping to check in. The loop:
```
pick -> build -> verify -> commit & push -> log -> next
```
**Still stop and ask** before: anything touching real money beyond what a
feature's own verification needs, force-push/history rewrite, deleting data,
or a decision explicitly flagged "ask before deciding" in `DECISIONS.md`.
Everything else: keep going.

## End (every feature)
1. Tests pass (new + existing). Frontend type-checks / builds.
2. `feature_list.json` evidence + state updated (only a passing verification
   command moves an item to `passing`).
3. `claude-progress.md` updated with what shipped and the exact next step.
4. Commit + `git push origin development`. Small, scoped commits.

## Hard Constraints
- Every stored money amount is **EUR** (`settings.BASE_CURRENCY`), including
  rows a supplier labels otherwise - convert for display only.
- `PROCESSING`/an empty poll on an order is **not a failure** - never invent
  a failure/retry UI for that.
- A support ticket's ownership rule (`user_id == current_user.id` or staff)
  is the ownership rule for its chat too - reuse it, don't re-derive it.
- No new dependency that needs infrastructure not already deployed (Redis,
  a message broker, a second service) without flagging it in `DECISIONS.md`
  first - both `esim-backend` and `esim-backend-beta` are **single-instance**
  containers today (confirmed: no `deploy.replicas` in docker-compose*.yml),
  so an in-memory connection manager is fine for WebSocket fan-out *now*, but
  say so explicitly wherever that assumption is load-bearing.
- A WebSocket client (browser) cannot set custom headers on the handshake -
  auth travels as a `?token=` query param, validated the same way the
  `Authorization: Bearer` header is everywhere else. Never accept an
  unauthenticated WS connection to a ticket/queue channel.

## Topic Docs
- **Architecture** (`docs/Architecture.md`) - required before touching the
  chat system's structure, the WS connection manager, or routing.
- **Rules** (`docs/Rules.md`) - required before writing any chat-related code.
- **Functional Requirements** (`docs/Functional_Requirements.md`) - required
  before building a feature; every FR = one `feature_list.json` item.
- **Technical Requirements** (`docs/Technical_Requirements.md`) - dependencies,
  commands, verification layers.
- **Non-Functional Requirements** (`docs/Non_Functional_Requirements.md`) -
  latency, reconnect, accessibility bars a feature must clear.

## Cross-repo: the mobile app
`D:\eSim\Triptel-flutter` is a separate git repo/harness (its own
`CLAUDE.md`). Per explicit instruction: **web ships first**, against
`beta.triptel.co`; the mobile chat screen is built *after*, against the same
beta API once it's live. Its `feature_list.json` already has the mobile chat
FRs queued as `blocked` with a reason pointing back here - don't unblock them
until a chat FR here has actually shipped to beta and been smoke-tested live
(same "confirmed, not guessed" discipline as the rest of this project).
Keep `Triptel-flutter/docs/API.md`'s WS section in sync with whatever this
repo's WS endpoints actually do, the same way `GET /catalog/featured` was
documented there when it shipped.
