# claude-progress.md
Session log. Read first at session start, update last at session end.

## Current state (2026-11-18) — mode: AUTONOMOUS, web ships first
- **Phase:** Initialize (harness written, no feature code yet).
- **Active feature:** none.
- **Next step:** `FR-C101` (SupportMessage columns + migration), then
  `FR-C102` → `FR-C107` (backend transport), then the frontend FRs, then
  `FR-C301`/`FR-C302` (admin). Mobile is a separate repo, built after a web
  FR is live on beta - see `Triptel-flutter/claude-progress.md`.

## Done
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
