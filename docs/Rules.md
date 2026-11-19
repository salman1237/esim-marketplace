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

## Guest chat
- A guest ticket's ownership predicate is `(user_id == caller.user_id) or
  (guest_token == caller.guest_token)` - never two separate code paths for
  "is this mine," one shared check both authed and guest endpoints call
  (see Architecture.md). A ticket has exactly one of `user_id`/
  `guest_token` set, never both, never neither.
- `guest_token` is bearer-equivalent to a password for that ticket's
  content - treat it exactly like a JWT for logging/redaction purposes
  (never log it in full, never put it in a URL that ends up in server
  access logs beyond the WS `?token=` itself).
- Claiming (FR-C405) is a reassignment, not a merge - a guest token that
  owns multiple tickets gets all of them reassigned to the newly
  logged-in user in one transaction. If the authed account already has
  tickets of its own, nothing about those is touched.
- A claimed ticket's existing messages are untouched (same `sender_type`,
  same content) - claiming changes who owns the ticket, never what was
  said in it.

## AI assistant guardrails
- The AI never claims an order-specific fact it hasn't actually retrieved
  (status, tracking, refund eligibility) and never takes or promises an
  account-changing action (refund, cancellation, dispute resolution,
  changing an email/plan). Those are exactly the FR-C510 refusal triggers;
  when the model's structured response indicates one, the service posts
  the canned handoff message and sets `ai_enabled = false` - it does not
  retry phrasing the same action more cautiously.
- The AI **may** recommend packages (public catalog data, same visibility
  rule as sharing a product in chat already has) and answer from
  `kb_chunks` content. It must not answer a question the retrieved context
  doesn't actually support by guessing - "I'm not sure, let me get a team
  member" is the correct fallback over a fabricated answer.
- `ai_enabled` only goes `true -> false` automatically. It never goes
  `false -> true` automatically (FR-C509/FR-C510 are deliberately one-way);
  only the explicit staff action in FR-C511 turns it back on. This is the
  one behavior in this feature that's easy to get backwards under
  "helpful" refactoring later - don't add an idle-timeout auto-resume.
- Resolved-ticket mining (FR-C504) is **opt-in per ticket, staff-triggered,
  always redacted before embedding** - never a scheduled job that mines
  every `CLOSED` ticket automatically. A wrong resolution or another
  customer's PII entering the KB silently is worse than a smaller KB; see
  `DECISIONS.md`.
- `sender_type = AI` is never rendered or labeled in a way a customer could
  mistake for a staff reply, in the widget or the admin queue - this is a
  trust property of the feature, not a cosmetic choice.

## Process (harness)
- **Autonomous** (CLAUDE.md -> Operating mode). Build, verify, commit, push,
  continue - no check-ins for ordinary feature work.
- **WIP = 1** in `feature_list.json`.
- A feature only moves to `passing` via its own verification command,
  proven to fail when the feature is reverted.
- Web ships first (against beta). Mobile FRs in `Triptel-flutter` stay
  `blocked` until a web chat FR has actually shipped and been smoke-tested
  live on `beta.triptel.co` - not "the code is written," actually live.
