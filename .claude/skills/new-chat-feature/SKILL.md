---
name: new-chat-feature
description: Build one real-time support chat FR (backend WS/model or frontend widget) the house way - read the design docs, implement, prove broadcast with real two-socket evidence, verify, commit+push. Use for any FR-C1xx/C2xx/C3xx item.
---
# New chat feature

1. Read `docs/Functional_Requirements.md` for the FR, `docs/Architecture.md`
   for how it fits, `docs/Rules.md` before writing code.
2. Backend FR: extend `app/models/support.py`, `app/services/support_svc.py`,
   `app/services/ws_manager.py` (new), `app/api/v1/support.py` /
   `app/api/v1/ws_support.py` (new router) - never a parallel chat module.
3. Frontend FR: extend `components/support/TicketThread.tsx` and friends;
   new files go in `components/support/` or `lib/` (a hook), not duplicated
   elsewhere.
4. **WS evidence is non-negotiable** (Functional_Requirements.md §F): write a
   test that opens two connections to the same ticket, triggers a message,
   and asserts the SECOND connection received it. An endpoint that merely
   "accepts a connection" is not verified.
5. `cd backend && python -m pytest <relevant file>` and/or
   `cd frontend && npm run build`. Both before marking anything `passing`.
6. For the first WS-touching FR specifically: confirm the WS actually works
   through Dokploy's real proxy on beta (not just the in-process test
   client) before marking it `passing` - see `claude-progress.md`'s open item.
7. Commit (`feat(chat): <FR-id> <behavior>`), push to `development`, update
   `feature_list.json` evidence + state, update `claude-progress.md`.
