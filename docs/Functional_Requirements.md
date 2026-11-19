# Functional Requirements - Real-time Support Chat
**Read when:** building a feature. Every FR maps to one `feature_list.json`
item. **Web ships first** (A-F below); mobile (G) is built after, against
beta, from the separate `Triptel-flutter` repo.

## A. Backend - data & transport
- **FR-C101 Message rich-content columns.** Migration: `SupportMessage` gets
  `message_type` (enum, default `TEXT`), `shared_order_id`
  (FK orders, SET NULL), `shared_product_id` (FK products, SET NULL).
- **FR-C102 WS connection manager.** `app/services/ws_manager.py`: register/
  unregister a socket per ticket, per the staff queue channel; broadcast
  helpers. Pure in-process, no persistence (see Rules.md).
- **FR-C103 Ticket WebSocket endpoint.** `WS /api/v1/ws/support/tickets/{id}`,
  `?token=` auth, same ownership check as `support.py`'s REST endpoints.
  Pushes `message`/`typing`/`ticket_status` events; accepts an inbound
  `typing` event from the client.
- **FR-C104 Staff queue WebSocket endpoint.** `WS /api/v1/ws/support/queue`,
  staff-only. Pushes `ticket_updated` whenever any ticket changes.
- **FR-C105 Broadcast on send.** `support_svc.post_message` (and ticket
  creation) pushes to both the ticket channel and the queue channel after a
  successful commit - the REST response is unchanged, this is additive.
- **FR-C106 Share an order or a package in a message.** Extend
  `POST /support/tickets/{id}/messages` (and ticket creation) with optional
  `shared_order_id`/`shared_product_id`; ownership-checked per Rules.md;
  serializer returns a summary block for each.
- **FR-C107 Author avatar in the serializer.** `serialize_message` includes
  `author_avatar_url` from `User.avatar_url`.

## B. Frontend (web) - the chat widget
- **FR-C201 Floating chat button.** Global, every page except auth pages.
  Unread-count badge. Opens the slide-over panel.
- **FR-C202 Slide-over panel - ticket list / new ticket.** Reuses the
  existing ticket-list and new-ticket logic from `app/support/` where it
  already exists, inside a panel instead of a page.
- **FR-C203 Slide-over panel - live thread.** `useSupportSocket` hook;
  extends `Thread`/`ReplyBox` (`components/support/TicketThread.tsx`) with
  avatars and rich-content bubbles; auto-scrolls on new message.
- **FR-C204 Typing indicator UI.** Animated dots when the other side is
  typing; sends the local typer's own `typing` events (debounced).
- **FR-C205 Share an order/package from the chat.** A picker over the
  user's own orders / the catalog; sends `shared_order_id`/
  `shared_product_id`; the thread renders the resulting card.
- **FR-C206 Reconnect & fallback.** Exponential backoff reconnect; while
  disconnected, falls back to the existing manual-fetch behavior so the
  thread is never silently stale with no way to refresh.

## C. Admin - staff side (needed for the feature to BE real-time)
- **FR-C301 Live-updating support queue.** `app/admin` (or wherever
  `SupportTab.tsx` lives) subscribes to the queue WS; new/updated tickets
  appear without a manual refresh.
- **FR-C302 Staff reply uses the same live thread.** Same `useSupportSocket`
  component, `for_staff` mode (author label, assignment).

## D. Non-functional gates
- See `docs/Non_Functional_Requirements.md` - a feature isn't `passing`
  until it clears these.

## E. Explicitly out of scope (noted, not to be built without a new FR)
- Read receipts ("seen" ticks).
- Online/offline presence indicators.
- Multi-instance WS fan-out (Redis pub/sub) - only needed if `esim-backend`
  is ever scaled past one instance; see Architecture.md.
- Voice/video, group chat, chat with anyone other than Support.

## F. Verification note
Every WS-touching FR needs **real two-socket evidence** (two connections,
one event, confirm both actually receive it), not just "the endpoint
accepts a connection." A WS handler that silently never broadcasts anything
still "works" by that weaker bar - don't let that happen.

## H. Guest (non-logged-in) chat
A visitor can chat with Support before creating an account. Same ticket
system, same WS transport, same ownership-check shape - identified by an
anonymous device token instead of a JWT.

- **FR-C401 Guest identity.** `SupportTicket.user_id` becomes nullable;
  gains `guest_token` (UUID, nullable, unique) and `guest_email` (nullable,
  settable mid-conversation). Exactly one of `user_id`/`guest_token` is set.
- **FR-C402 Guest session issuance.** `POST /support/guest/session` (no
  auth) returns a fresh `guest_token`. Frontend stores it in
  `localStorage`; it is the entire guest identity - nothing server-side
  needs a cookie.
- **FR-C403 Guest ticket + reply endpoints.** `POST /support/guest/tickets`
  and `POST /support/guest/tickets/{id}/messages` (no JWT) take
  `guest_token` in the body/header; same validation/attachment logic as the
  authed endpoints (shared helper, not a forked copy - see Rules.md).
- **FR-C404 Guest WS auth.** `WS /ws/support/tickets/{id}?token=` accepts
  either a JWT or a `guest_token` for a guest-owned ticket; same
  `ConnectionManager`, no new channel type.
- **FR-C405 Claim on sign-up/login.** `POST /support/guest/claim` (authed):
  given the caller's `guest_token`, reassigns every ticket it owns to
  `user_id = current_user.id`, clears `guest_token`. Called once by the
  frontend right after a successful login/register if a guest token exists
  in storage.
- **FR-C406 Widget works signed out.** `FloatingChatButton` no longer
  routes a logged-out visitor to login (overrides the FR-C201 behavior for
  guests specifically); it mints a guest session on first open instead.
- **FR-C407 Claim call on auth success.** Login/register success handler
  calls FR-C405's endpoint when a `guest_token` is present, then discards
  it from storage.

## I. AI assistant (RAG) on support chat
An AI drafts the first replies on a ticket - recommending packages,
resolving known issues from a knowledge base - and goes permanently silent
on that ticket the moment a staff member actually replies, or the moment it
hits something it shouldn't attempt itself.

- **FR-C501 pgvector + knowledge base table.** `CREATE EXTENSION vector` on
  the existing Postgres (flagged in `DECISIONS.md` - needs applying on
  beta/prod, not just local). New table `kb_chunks` (id, `source_type`
  enum: `CATALOG_PRODUCT`/`FAQ_ARTICLE`/`RESOLVED_TICKET`, `source_id`,
  `content`, `embedding vector(N)`, `country_slug` nullable, `updated_at`).
- **FR-C502 Catalog embedding sync.** On product create/update/delete, a
  service re-embeds that product's `kb_chunks` row (title+description+
  country+price band). Backfill script for existing catalog.
- **FR-C503 FAQ/known-issue authoring + embedding.** New `faq_articles`
  table (title, body, tags) + admin CRUD; on save, re-embeds into
  `kb_chunks`.
- **FR-C504 Opt-in resolved-ticket mining.** A `CLOSED` ticket gets an
  explicit staff action "Add to knowledge base" (per-ticket, never
  automatic - see Rules.md and `DECISIONS.md`); on confirm, a redaction
  pass strips the customer's name/email/order id before embedding the
  Q&A pair as a `RESOLVED_TICKET` chunk.
- **FR-C505 Retrieval service.** `kb_svc.retrieve(query, k, filters)`:
  embeds the query, cosine-similarity top-K over `kb_chunks` (pgvector
  `<=>` operator), optional `source_type`/`country_slug` filter.
- **FR-C506 AI reply service.** `ai_svc.reply(ticket, message)`: builds a
  system prompt (role, guardrails - see Rules.md) + retrieved context +
  recent thread, calls the model, returns plain text or a structured
  "recommend this product" action the caller renders as a `PRODUCT_SHARE`
  message (reusing FR-C106, not a new message type).
- **FR-C507 sender_type on messages.** `SupportMessage.sender_type` enum
  (`CUSTOMER`/`STAFF`/`AI`), additive alongside the existing `is_staff`
  bool (kept for backward compat, derived together). Frontend shows a
  distinct "AI Assistant" badge for `AI` messages - never rendered
  identically to a staff reply (see Rules.md, trust/disclosure).
- **FR-C508 Auto-reply trigger.** On a new `CUSTOMER` message to a ticket
  where `ai_enabled = true` and no `STAFF` message exists yet in the
  thread, a background task calls FR-C506 and posts+broadcasts its result
  like any other message (reuses FR-C105's broadcast-after-commit).
- **FR-C509 Permanent handoff on staff reply.** `SupportTicket.ai_enabled`
  (bool, default `true`). The first `STAFF` message ever posted on a
  ticket flips it to `false`, in the same transaction. No auto-resume.
- **FR-C510 Guardrail-triggered handoff.** FR-C506's prompt must refuse
  (not attempt) anything account/order-specific - refunds, cancellations,
  disputes, "where is my order" status claims. On a refusal, the service
  sets `ai_enabled = false` immediately (doesn't wait for staff to reply)
  and posts a canned "a team member will take it from here" message - see
  Rules.md for the exact scope of what counts as a refusal trigger.
- **FR-C511 Manual hand-back to AI.** Staff-only action
  (`POST /support/tickets/{id}/ai-resume`) sets `ai_enabled = true` again -
  the only way AI replying resumes once FR-C509/FR-C510 has silenced it.
- **FR-C512 Admin visibility.** Staff queue (`SupportTab.tsx`) shows
  whether a ticket is AI-handled or human-handled, and surfaces
  guardrail-triggered handoffs (FR-C510) distinctly from a normal staff
  takeover, so staff know which tickets are actually waiting on a human.

## J. Mobile (separate repo, built second)
Tracked in `Triptel-flutter/docs/Functional_Requirements.md` as its own
FR range, `blocked` until the corresponding web FR here is live on beta.
This applies to guest chat (H) and the AI assistant (I) the same way it
already applies to A-C.
