# Rules
**Read when:** writing any chat-related code.

## Data model
- Extend `SupportMessage`/`SupportTicket`, never build a parallel chat table.
  A ticket and its chat are **the same thread** - no customer should ever see
  two different places their message might be.
- `message_type` is explicit (`TEXT`/`ORDER_SHARE`/`PRODUCT_SHARE`), never
  inferred from "is `shared_order_id` set". Inferring it is exactly the kind
  of implicit coupling that breaks the moment a message type is added later.
- `shared_order_id`/`shared_product_id` are `ON DELETE SET NULL` - a message
  must stay readable (as plain text + "this item is no longer available")
  even if the order/product it referenced is gone later.

## Sharing an order or package
- The sender must actually own what they're sharing: a customer can only
  share **their own** order (`order.buyer_id == sender.id` or
  `order.beneficiary_id == sender.id`, same check `esims.py`'s `_load`
  already uses) - never let a customer reference someone else's order id in
  a chat message. A product (package) can be shared freely - it's public
  catalog data, same visibility rule as `GET /catalog/products/{id}`.
- Staff can share any order (they're troubleshooting it).

## Typing indicator
- **Never persisted.** It is a pure WS broadcast, not a `SupportMessage` row,
  not a DB write of any kind. A typing event the recipient's socket missed
  (disconnected, reconnecting) is simply gone - that's correct, not a bug to
  "fix" with a stored-and-replayed event.
- Client auto-clears a remote "typing" state after ~3s of silence even if no
  explicit "stopped typing" event arrives (the sender's tab can die mid-type).

## Avatars
- `author_avatar_url` comes straight from `User.avatar_url` (already exists -
  set by Google sign-in's picture, or an admin-managed upload elsewhere).
  **Never invent a generated-avatar service call** for a user with no photo;
  the client shows initials instead. No new field, no new upload path for
  this feature specifically.

## WebSocket auth
- A WS handshake has no `Authorization` header from a browser - the token
  travels as `?token=`. It is validated with the *same* JWT decode path as
  the HTTP dependency (`get_current_user`'s core logic), not a second,
  parallel implementation that can drift from it.
- Reject the connection (close code 4401 or similar, not a silent timeout)
  on an invalid/expired token or a ticket the caller doesn't own - same 404
  discipline the REST endpoints already use for "not yours" vs "doesn't
  exist" doesn't fully apply to a socket close code, but don't leak which
  case it was in the close reason text either.

## Delivery guarantees (be honest about what "real-time" means here)
- The WS push is **best-effort**, not guaranteed delivery. `POST .../messages`
  (the REST write) is the source of truth and already succeeds/fails on its
  own; a dropped WS push just means the recipient sees the new message on
  their next reconnect/poll-fallback instead of instantly. Never make a
  feature depend on the WS push having arrived - it's a UX improvement over
  "worse delivery," not a new source of truth.
- No multi-instance fan-out yet (see Architecture.md). If `esim-backend`
  ever runs more than one replica, a message sent while the recipient's
  socket is connected to a *different* instance silently won't reach them
  until they reconnect/poll - that's a known, accepted gap today, not
  something to silently paper over by, e.g., writing to a DB column just to
  make it "work" without saying so in `DECISIONS.md`.

## Process (harness)
- **Autonomous** (CLAUDE.md -> Operating mode). Build, verify, commit, push,
  continue - no check-ins for ordinary feature work.
- **WIP = 1** in `feature_list.json`.
- A feature only moves to `passing` via its own verification command,
  proven to fail when the feature is reverted.
- Web ships first (against beta). Mobile FRs in `Triptel-flutter` stay
  `blocked` until a web chat FR has actually shipped and been smoke-tested
  live on `beta.triptel.co` - not "the code is written," actually live.
