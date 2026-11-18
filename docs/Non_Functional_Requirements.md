# Non-Functional Requirements
**Read when:** a feature touches latency, reconnect behavior, or accessibility.
Not `passing` until it clears the bars that apply to it.

## Latency ("real-time" has to mean something)
- A message sent by one party reaches an already-connected recipient's UI in
  **under ~500ms** on a normal connection (same-machine/same-network test is
  enough evidence; don't over-engineer measurement for this).
- Typing indicator: appears within ~300ms of the remote side typing, clears
  within ~3s of them stopping (Rules.md).

## Reliability
- A WS drop never loses a message - the REST write already succeeded before
  any broadcast is attempted; on reconnect, the client re-fetches the thread
  to catch anything missed while disconnected (never trusts the socket as
  the only source of truth - Rules.md).
- Reconnect: exponential backoff (e.g. 1s, 2s, 4s... capped), not a tight
  retry loop that hammers the backend.
- The chat widget degrades to "works, just not live" (manual refresh) if WS
  is blocked by a network/proxy - never a hard error that blocks viewing or
  sending messages.

## Security & privacy
- WS auth is real auth (Rules.md), not "anyone who finds the ticket id."
- Shared order/product cards never leak another customer's data (Rules.md's
  ownership check).
- Uploaded images/files follow the existing attachment rules (size/type caps
  already enforced server-side in `support_svc.py` - don't relax them for chat).

## Accessibility
- Typing indicator and new-message arrival are announced to screen readers
  (an `aria-live="polite"` region), not purely a visual animation.
- Floating button and panel are keyboard-navigable; panel traps focus while open.
- Text contrast meets WCAG AA in both the customer and staff bubble colors.

## Mobile-readiness (for the later Flutter build)
- Every behavior here is described in terms the WS protocol itself
  guarantees (event shape, ownership, latency), not in terms of a specific
  web component - so the mobile implementation can meet the same bars
  without re-deriving them from the web UI's code.
