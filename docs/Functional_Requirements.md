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

## G. Mobile (separate repo, built second)
Tracked in `Triptel-flutter/docs/Functional_Requirements.md` as its own
FR range, `blocked` until the corresponding web FR here is live on beta.
