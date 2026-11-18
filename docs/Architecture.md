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
