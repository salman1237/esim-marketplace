# Architecture
**Read when:** touching the chat system's structure, the WS connection
manager, or routing.

## Existing stack (relevant to chat)
| Layer | Reality |
|---|---|
| Backend | FastAPI, async SQLAlchemy 2.0, PostgreSQL. Layering: `api/` (routers, thin) -> `services/` (business rules) -> models. Routers never run raw queries. |
| Frontend | Next.js App Router, TypeScript. `src/lib/api.ts` is the one place `fetch` is called from; components never call it directly. |
| Auth | JWT, `Authorization: Bearer`, no refresh token. `GET /auth/me` for session restore. |
| File uploads | Disk-backed, private filename on disk, served only through an authenticated endpoint (`support_svc.py`'s existing pattern for ticket attachments; KYC/withdrawal proofs use the same shape). |
| Deploy | `esim-backend` (prod) / `esim-backend-beta` (beta), **one container each**, no Redis, no load balancer across backend replicas (confirmed in `docker-compose*.yml`). |

## The chat system

### Data model: extends SupportTicket/SupportMessage, doesn't replace it
Already have `SupportTicket` (status, category, order link, assignee, queue
ordering by `last_message_at`) and `SupportMessage` (`body`, `is_staff`,
`attachments`). A parallel "chat" system would duplicate a working ticket
queue, ownership rules, and the admin support UI for nothing - the only real
gap is **delivery speed** (currently: open a page, nothing pushes to it) and
**rich content** (sharing an order/package inline). So:

- `SupportMessage` gets two new nullable FKs: `shared_order_id -> orders.id`,
  `shared_product_id -> products.id` (both `ON DELETE SET NULL` - a message
  stays readable if the order/product is later removed).
- `SupportMessage.message_type` (`TEXT` default, `ORDER_SHARE`,
  `PRODUCT_SHARE`) - the client needs a tag to render a rich card, not just
  infer it from a non-null FK (future-proofs a message carrying more than
  one kind of attachment later, and matches how `TicketCategory` is already
  an explicit enum rather than inferred).
- Everything else (status transitions, staff queue, attachments, email
  fallback) is untouched. A customer who never opens a WebSocket still gets
  their ticket exactly as today.

### Real-time transport
**Writes stay REST, delivery becomes WebSocket.** `POST
/support/tickets/{id}/messages` keeps doing exactly what it does today
(multipart, file attachments, validation, `support_svc.post_message`) - after
it commits, it pushes the serialized message to every open WebSocket
connection for that ticket. This is deliberately *not* "send the message
over the socket": that would mean re-implementing multipart upload, auth,
and validation inside a WS handler for no benefit.

Two WS endpoints:
- `WS /api/v1/ws/support/tickets/{ticket_id}?token=<jwt>` - a customer or
  staff member viewing one thread. Same ownership check as the REST
  endpoints (`_ticket_for` in `support.py`). Receives `message`, `typing`,
  and `ticket_status` events for that ticket; can *send* a `typing` event
  (ephemeral, never persisted - see Rules.md).
- `WS /api/v1/ws/support/queue?token=<jwt>` - **staff only**. Receives a
  `ticket_updated` event (id, status, last_message_at, unread-ish summary)
  whenever any ticket changes, so the admin queue list updates live instead
  of needing a page refresh. Without this, "real-time support" is only
  real-time for the customer - staff would still be polling, which defeats
  the point.

`ConnectionManager` (new, `app/services/ws_manager.py`) is a single
in-process `dict[ticket_id, set[WebSocket]]` + `set[WebSocket]` for the
queue channel. **This only works because there is one backend instance per
environment today** (see CLAUDE.md's Hard Constraints). If that ever
changes, this needs Redis pub/sub (or similar) between instances - don't
build that now, just don't let anything accidentally commit to the
single-instance assumption being permanent (e.g. don't key anything on "the
process that received the message is the only one that needs to know").

### Frontend (web)
- `FloatingChatButton` - global, mounted in `app/layout.tsx` next to
  `Footer`/`MobileBottomNav` (same place every other global chrome lives).
  Confirmed: `POST /support/tickets` requires `get_current_user` - a ticket
  cannot be opened signed out. A logged-out visitor's floating button routes
  to login/register with a return path (the existing pending-purchase
  pattern elsewhere in this app), not a new mechanism.
- Opens a slide-over panel (not a full page nav) showing the ticket list or
  the active thread - a widget, not a route change, is what makes this feel
  "snappy" rather than a page load away.
- `useSupportSocket(ticketId)` hook: opens the WS, reconnects with backoff on
  drop, exposes `messages`, `typingUsers`, `sendTyping()`. Confirmed:
  `TicketThread.tsx` (`Thread`/`ReplyBox`/`StatusBadge`) is a pure renderer
  today with **no polling at all** - whatever page uses it only sees new
  messages on a manual refresh. So this genuinely adds real-time delivery
  where there was none, not an upgrade over an existing poll. Reuse
  `Thread`/`ReplyBox` as-is where possible; extend `Thread` to render a
  message's avatar (`author_avatar_url`, new field - see Rules.md) and a
  rich card for `message_type != TEXT`.

### Mobile (separate repo, built second)
Same WS endpoints, consumed from Flutter once this ships to beta. See
`Triptel-flutter/docs/Architecture.md` for the client-side design - not
duplicated here to avoid the two docs drifting.

## Guest chat

### Why not a cookie-based anonymous session middleware
Considered: a generic "anonymous session" layer (signed cookie, server
tracks it like a user). Rejected - it's a second identity system next to
JWT for one feature. Instead: a bare `guest_token` UUID, generated
server-side on request, handed back once, stored client-side, and sent
back exactly where a JWT would go (`?token=` on the WS, a field on the two
guest REST endpoints). It never becomes a session, never gets renewed,
never expires server-side - the table row it's attached to (`SupportTicket
.guest_token`) is the only state. Simpler, and it composes with "claim on
login" (FR-C405) as a single UPDATE, not a session-migration dance.

### Ownership check, extended not forked
`_ticket_for()` in `support.py` currently resolves "is this the caller's
ticket" from a JWT's `user_id`. The guest endpoints don't duplicate that
function - they call the **same** `support_svc` functions
(`post_message`, `create_ticket`, serializers) with a caller identity that
is either `(user_id=X, guest_token=None)` or `(user_id=None,
guest_token=Y)`. One ownership predicate, two ways to arrive at it. This
mirrors how `Rules.md` already treats "ownership rule for chat = ownership
rule for the ticket" - the same discipline applies to guest identity.

## RAG AI assistant

### Where it sits relative to the existing send path
`POST /support/tickets/{id}/messages` (and the guest equivalent) is
unchanged by this feature up through its existing commit + FR-C105
broadcast. The AI assistant is a **second writer** on the same ticket,
triggered *after* that commit, not a branch inside it:

```
customer message committed -> broadcast (existing)
        |
        v  (background task, only if ai_enabled)
  kb_svc.retrieve() -> ai_svc.reply() -> support_svc.post_message()
  (sender_type=AI)  -> commit -> broadcast (same FR-C105 path)
```

This keeps the write path's existing guarantees (validation, attachments,
ownership) completely untouched, and means the AI's reply looks like any
other message to every piece of code downstream of `post_message` -
WS push, email fallback (if ever extended to AI messages), serialization.

### Knowledge base: one table, three sources, pgvector on the existing DB
`kb_chunks` lives in the same Postgres instance already deployed (not a
new vector-DB service - this is the explicitly chosen option per
`DECISIONS.md`, keeping with the "no new infra without flagging it"
constraint). Three `source_type`s feed it, each re-embedded independently
on its own change event:
- `CATALOG_PRODUCT` - kept fresh by a hook on product save, so a
  price/description change can't make the AI recommend stale info.
- `FAQ_ARTICLE` - staff-authored, re-embedded on save from a small admin
  CRUD screen (reuses the existing admin shell/auth, not a new app).
- `RESOLVED_TICKET` - **opt-in per ticket**, staff-triggered, redacted
  before embedding (see Rules.md). Deliberately not an automatic nightly
  mine of every closed ticket - a wrong resolution or another customer's
  PII silently entering the KB is a worse failure than a smaller KB.

Retrieval (`kb_svc.retrieve`) is a single cosine-similarity query
(pgvector `<=>`) over `kb_chunks`, optionally filtered by `source_type`
and `country_slug` - no separate search service, no reranking tier; add
one only if retrieval quality is measured to need it (YAGNI, matching this
project's existing pattern of not building for a problem that isn't
confirmed yet).

### Model choice
`ai_svc.py` calls Claude Haiku 5.5 (`claude-haiku-5-5`) - support chat is
exactly the workload shape (chat/classification/Q&A, high volume, latency-
sensitive) that the cheapest current model handles well, confirmed against
Anthropic's own current cost-tuning guidance rather than assumed. If a
later measurement shows Haiku's answers are the bottleneck (not latency or
cost), the escalation path is effort/prompt tuning first, then a step up
to Sonnet - not changing architecture.

### Guardrails live in the service, not just the prompt
FR-C510's refusal categories (refund/cancel/dispute/order-status) are
checked in `ai_svc.py` itself after the model responds (a structured
"action requested" field the prompt is instructed to always fill in), not
left to the model to reliably self-censor in free text every time. A
prompt-only guardrail is a suggestion the model can drift from under
adversarial or unusual phrasing; a service-level check on a structured
field is a gate the code enforces.

### Trust: AI messages are never visually indistinguishable from staff
`sender_type = AI` renders with its own badge (FR-C507) everywhere a
message appears - ticket thread, admin queue, any future transcript
export. A customer must always be able to tell whether a human has
actually looked at their ticket.
