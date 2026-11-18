# claude-progress.md
Session log. Read first at session start, update last at session end.

## Current state (2026-11-18) — mode: AUTONOMOUS, web ships first
- **Phase:** Initialize (harness written, no feature code yet).
- **Active feature:** none.
- **Next step:** `FR-C105` (broadcast-on-write wiring into
  `support_svc.post_message`/`create_ticket`), then `FR-C106`/`FR-C107`,
  then the frontend FRs, then `FR-C301`/`FR-C302` (admin). Mobile is a
  separate repo, built after a web FR is live on beta - see
  `Triptel-flutter/claude-progress.md`.

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
- 2026-11-18 — **FR-C102 passing.** `app/services/ws_manager.py`:
  `ConnectionManager` with two channels (per-ticket set, staff queue set),
  `broadcast_to_*` that drops a socket on send failure instead of breaking
  delivery to everyone else. 7/7 pure in-process tests (fake socket, no
  network, no DB query content - though the session-scoped DB fixture still
  spins up since it's autouse). Non-vacuous: broke `broadcast_to_ticket`,
  confirmed exactly the 3 broadcast-dependent tests failed, restored,
  re-confirmed green. Real two-socket-through-an-actual-endpoint proof is
  FR-C103's job next - this only proves the manager's own fan-out logic.
- 2026-11-18 — **FR-C103 and FR-C104 passing.** `app/api/v1/ws_support.py`:
  `WS /ws/support/tickets/{id}` (customer-or-staff, ownership-checked
  exactly like the REST endpoints, typing broadcast excluding the sender)
  and `WS /ws/support/queue` (staff-only). Auth decodes `?token=` with the
  exact same `app.core.security.decode_access_token` the HTTP
  `Authorization` dependency uses - no second implementation. Both open
  their own `AsyncSessionLocal()` (a WS connection outlives one request's
  DI cycle).
  **Real build problem solved, worth remembering:** proving this with
  genuine two-socket evidence (not just "the endpoint accepts a
  connection") required `fastapi.testclient.TestClient`, not the async
  httpx `client` fixture used everywhere else in this suite -
  `TestClient` runs the ASGI app in its own background-thread "portal"
  with its own event loop. Two real bugs this surfaced: (1) writing test
  data via a plain `AsyncSessionLocal()` call from pytest's own loop and
  THEN opening a TestClient WS connection corrupted the shared engine's
  connection pool ("attached to a different loop") - fixed by doing ALL
  test setup (register, log in, create a ticket) through TestClient's own
  HTTP calls instead, so everything for a given test stays on one loop.
  (2) Even with that fix, test order still mattered - each
  `with TestClient(app) as tc:` block's portal thread dies at block-exit,
  and a pooled connection it touched poisons the *next* test's turn at the
  shared global `engine` regardless of which loop that is. Fixed with a
  local, file-scoped autouse fixture that disposes the engine's pool
  before and after every test in `test_support_chat_ws.py`. Both fixes are
  documented in that file's own module docstring for the next FR that
  needs this pattern.
  13/13 tests pass, including a real two-direction typing-event exchange
  between two live sockets. Ownership check proven non-vacuous (broke it,
  confirmed the rejection test failed, restored). 26/27 broader regression
  (`tests/test_support.py`) pass; the one failure is the same pre-existing
  background-order-provisioning timing flake already diagnosed twice this
  session as unrelated (nothing here touches orders/checkout).
  **Still open, not yet done:** confirming this actually works through
  Dokploy's real reverse proxy on beta (WS upgrade headers passed through
  cleanly) - only verified via TestClient so far. Do the real check before
  the frontend FRs that depend on it are marked passing.
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
