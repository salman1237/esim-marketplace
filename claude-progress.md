# claude-progress.md
Session log. Read first at session start, update last at session end.

## Current state (2026-11-18) — mode: AUTONOMOUS, web ships first
- **Phase:** Initialize (harness written, no feature code yet).
- **Active feature:** none.
- **Next step:** `FR-C102` (WS connection manager), then `FR-C103` →
  `FR-C107` (backend transport), then the frontend FRs, then `FR-C301`/
  `FR-C302` (admin). Mobile is a separate repo, built after a web FR is live
  on beta - see `Triptel-flutter/claude-progress.md`.

## Done
- 2026-11-18 — **FR-C101 passing.** `SupportMessage` gains `message_type`
  (TEXT/ORDER_SHARE/PRODUCT_SHARE, default TEXT), `shared_order_id`,
  `shared_product_id` (both `ON DELETE SET NULL`). Migration
  `c3f7a2e81d94` (chain: ...→b8e4f2a917c3→c3f7a2e81d94). Verified against a
  disposable local Postgres instance (not the user's shared one, not
  beta/prod) — migration applies cleanly on the full history, 4/4 new tests
  pass, the SET NULL behavior specifically proven non-vacuous (temporarily
  removed `ondelete`, confirmed the test fails with a real IntegrityError,
  restored, confirmed green again). 17/18 existing `tests/test_support.py`
  tests still pass; the one failure is the same pre-existing
  background-order-provisioning-doesn't-settle-in-10s environment flake
  already diagnosed as unrelated during the `GET /catalog/featured` work
  (nothing in this diff touches orders/checkout). No frontend/admin
  serializer changes yet — `support_svc.serialize_message` doesn't expose
  these fields until FR-C106/C107.
- 2026-11-18 — Harness initialized for this feature: `CLAUDE.md`, `AGENTS.md`,
  `docs/{Architecture,Rules,Functional_Requirements,Technical_Requirements,
  Non_Functional_Requirements}.md`, `feature_list.json` (15 FRs),
  `DECISIONS.md`, `.claude/` (settings, hooks, skills, reviewer agent).
  Confirmed before writing: no existing WS infra anywhere in the backend; no
  Redis/multi-replica deploy (single container per environment); existing
  `SupportTicket`/`SupportMessage` is the right foundation to extend (status,
  category, order link, staff queue, attachments all already real and
  working) rather than a parallel chat system; `User.avatar_url` already
  exists; `uvicorn[standard]` already bundles WS support (no new dependency).
  `TicketThread.tsx` (web) confirmed to have **zero** live-update mechanism
  today (pure renderer, no polling) - this is a genuine real-time gap, not
  an upgrade over an existing poll.

## Blocked / needs confirming during build (not blocking the harness itself)
- Whether Dokploy's reverse proxy (Traefik, typically) passes WebSocket
  upgrade headers through cleanly for `esim-backend`/`esim-backend-beta` -
  not yet confirmed live. Confirm this the moment FR-C103 is built, against
  beta, before marking it `passing` - a WS endpoint that only works in an
  in-process test client but not through the real proxy is not actually done.

## Mirrored in Triptel-flutter
`Triptel-flutter/feature_list.json` has mobile chat FRs appended, `blocked`
with reason "waiting for a web chat FR to ship live on beta" — its own
autonomous loop keeps progressing its existing, unrelated queue in the
meantime; this doesn't pause that repo's work.
