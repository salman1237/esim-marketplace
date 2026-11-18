# DECISIONS.md
Judgment calls, newest first. Each: what, why, revisit-if.

## 2026-11-18 — Extend SupportTicket/SupportMessage, don't build a parallel chat system
A real-time "support chat" and the existing support ticket system are the
same thing from the customer's point of view - one conversation with
Support. Building a second, parallel chat table/UI would mean two inboxes
for staff and a confusing "which one do I check" for customers. **What I
did:** add real-time delivery (WS) and rich content (order/product share,
avatar) on top of the existing model instead. **Why:** confirmed the
existing system already has everything else a chat needs (ownership rules,
staff queue, attachments, categories) and duplicating it serves no one.
**Revisit if:** product wants a genuinely separate "pre-sales chat" that
should NOT become a ticket (not requested here).

## 2026-11-18 — Writes stay REST, only delivery becomes WebSocket
Considered sending the message itself over the WS (fully real-time
protocol). **What I did:** kept `POST /support/tickets/{id}/messages` as the
only way to actually create a message (multipart, attachments, validation
all already correct there); the WS only *pushes* what REST already wrote.
**Why:** re-implementing multipart file upload, auth, and every existing
validation rule inside a WS handler duplicates working code for no real
latency benefit (the write itself is already fast) and adds a second place
those rules can drift. **Revisit if:** the REST write path itself becomes
the bottleneck (not expected at this scale).

## 2026-11-18 — Typing indicator is never persisted
**What I did:** typing events are WS-only, no DB table, no replay on
reconnect. **Why:** a typing indicator that's slightly wrong because of
timing is normal chat UX everywhere (iMessage, WhatsApp); persisting it
would be a database write for information that's stale within seconds and
never needs an audit trail - exactly the overbuilding this project avoids
elsewhere (e.g. REWARD wallet design, not generalizing withdrawal fee rules
beyond what's configured). **Revisit if:** never, barring a concrete new
requirement.

## 2026-11-18 — No Redis / multi-instance fan-out, yet
**What I did:** an in-process `dict`-based connection manager, explicitly
flagged in every relevant doc as depending on "one backend instance per
environment," confirmed true today. **Why:** adding Redis pub/sub now would
be infrastructure for a problem that doesn't exist yet (YAGNI) - this
project's own `Monetization rules`/`Dokploy pipeline` memories show the
pattern of fixing real, confirmed problems, not hypothetical ones.
**Revisit if:** `esim-backend`/`esim-backend-beta` are ever scaled to more
than one replica - at that point this becomes a real, not hypothetical, bug.

## 2026-11-18 — Web ships first, mobile is explicitly sequenced after
User's explicit instruction: implement for web first, then build the
Flutter client against the same beta API once it exists. **What I did:**
wrote the mobile FRs into `Triptel-flutter/feature_list.json` now (so the
plan is visible and the API doc has a place to be filled in), but set them
`blocked` rather than `not_started`, with the unblock condition being "a web
chat FR shipped live on beta," not "the code exists." **Why:** building the
mobile UI against a backend contract that hasn't been exercised for real
risks guessing field names wrong (exactly what `docs/API.md`'s whole purpose
is to prevent elsewhere in this project). **Revisit:** unblock those FRs the
moment FR-C103 (or whichever web FR first exposes the WS contract) is
confirmed live on beta - update both repos' progress logs together.
