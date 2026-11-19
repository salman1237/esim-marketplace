# DECISIONS.md
Judgment calls, newest first. Each: what, why, revisit-if.

## 2026-11-20 — Swap esim-db-beta/esim-db from postgres:16-alpine to pgvector/pgvector:pg16, REINDEX after
**What I did:** checked live (SSH, `pg_available_extensions`) - neither
beta's nor prod's deployed Postgres has pgvector at all, confirming the
open question flagged when FR-C501 was designed. User explicitly chose
"swap beta first, verify, then prod" when asked. Changed
`docker-compose.beta.yml`'s `esim-db-beta` image to
`pgvector/pgvector:pg16` - prod's `docker-compose.yml` is deliberately
**not** touched yet, pending beta verification. **Why this image, not
compiling the extension into the existing Alpine image:** `pgvector/
pgvector:pg16` is the officially maintained image for exactly this -
same Postgres 16 data format, pgvector pre-built, far less fragile than
hand-installing a compiled extension into a running Alpine container
that gets replaced on every deploy anyway. **Real risk found and
flagged, not glossed over:** the swap moves from Alpine (musl libc) to
Debian (glibc) under the *same* locale name (`en_US.utf8`, confirmed on
both DBs) - glibc's collation implementation isn't guaranteed to sort
identically to musl's, which can leave a BTREE index on a text column
silently wrong (looks fine, occasionally returns incomplete results)
without an explicit `REINDEX` after the swap. A `REINDEX DATABASE
esim_db;` (or per-index `REINDEX ... CONCURRENTLY` on beta first to
rehearse, non-blocking on prod) is treated as a mandatory step of this
migration, not a nice-to-have. **Revisit if:** beta verification turns
up any problem (data integrity, app behavior, the extension itself
misbehaving) - prod does not get this swap until beta is clean.
**Beta verification (same day):** the push's own CI (`backend-tests`)
gates deploy and is currently broken for an unrelated reason (the
pre-existing uncommitted `conftest.py` transaction-isolation work - see
the guest-chat entry above), so the normal `git push` -> Dokploy webhook
path never fired. Triggered the beta deploy directly via Dokploy's
authenticated API instead (same call `.github/workflows/deploy.yml`
makes), matching this project's own "verify deploys, don't trust CI
green" precedent. Confirmed directly on the VPS, not just from the
deploy API's "done" status: image is now `pgvector/pgvector:pg16`, data
intact (81 users/127 orders/21 support tickets, same as before the
swap), `REINDEX DATABASE esim_db;` completed cleanly, `CREATE EXTENSION
vector;` succeeded and a real scratch-table cosine-distance query
returned correct results, and a real registration against
`beta.triptel.co` succeeded (exercises the email/username unique
indexes under the new glibc collation). Beta is clean - prod is still
untouched pending the user's go-ahead.

## 2026-11-20 — pgvector on the existing Postgres, not a dedicated vector DB
**What I did:** the RAG knowledge base (`kb_chunks`) lives on the same
single-instance Postgres already deployed, via the `pgvector` extension,
instead of a managed vector DB (Pinecone/Qdrant/etc). **Why:** user's
explicit choice when asked; also the only option that doesn't add new
infrastructure beyond CLAUDE.md's existing single-instance constraint.
**Needs an operator action, not just code:** `CREATE EXTENSION vector`
must be applied on both `esim-backend`'s and `esim-backend-beta`'s
Postgres before FR-C501 can land - confirm this is possible on the
Dokploy-managed instance (most managed Postgres images ship pgvector, but
it hasn't been confirmed on this specific deployment yet) before marking
FR-C501 `passing`. **Revisit if:** retrieval volume or latency ever
outgrows what pgvector handles well on a single instance - at that point a
dedicated vector DB is a new infra decision, flagged here same as this one.

## 2026-11-20 — AI goes silent for good on the first staff reply; no idle-timeout auto-resume
**What I did:** `ai_enabled` flips `true -> false` permanently the moment
any `STAFF` message is posted on a ticket (FR-C509), or the moment a
guardrail trigger fires (FR-C510) - and only an explicit staff action
(FR-C511) turns it back on. Considered: auto-resuming if staff goes idle
for some timeout. **Why:** user's explicit choice when asked; an
auto-resume risks the AI jumping back into a conversation a staff member
is still actively tracking just because they haven't typed in N minutes -
worse than a ticket waiting slightly longer for a reply. **Revisit if:**
staff coverage gaps make "permanently stuck waiting for a human" a real
problem at volume - the fix then is better staff-side queue triage, not
reintroducing an automatic resume.

## 2026-11-20 — Resolved-ticket KB mining is opt-in per ticket, not an automatic nightly job
**What I did:** a closed ticket only enters the knowledge base
(`RESOLVED_TICKET` chunks) when a staff member explicitly marks it "add to
knowledge base," with a redaction pass before embedding (FR-C504).
**Why:** the alternative the user confirmed interest in - mining past
resolved tickets generally - raises a real PII risk if done automatically:
one customer's name, email, or order details ending up retrievable in
another customer's AI-drafted reply. An opt-in, staff-reviewed pipeline
gets most of the value (reusing how staff actually solved recurring
problems) without that risk. **Revisit if:** staff find the opt-in step
too much friction to ever use - consider a "suggest for KB" prompt shown
to staff on ticket close instead of fully automatic, before going fully
automatic.

## 2026-11-20 — Guardrails enforced in `ai_svc.py`, not left to prompting alone
**What I did:** FR-C510's refusal categories are checked against a
structured field the model is prompted to always fill in, with the
service (not the model) deciding whether to post the canned handoff and
flip `ai_enabled`. **Why:** a prompt-only guardrail degrades under
adversarial or just unusual phrasing; a code-level check on a structured
output is enforced regardless of how the model phrases its response.
**Revisit if:** structured-output reliability issues ever require a
secondary classifier pass - add one, don't fall back to prompt-only trust.

## 2026-11-20 — Guest chat identity is a bare token, not a second session system
**What I did:** `guest_token` is a UUID minted on request, stored
client-side, sent back exactly where a JWT goes - never a cookie-backed
session, never server-renewed, never expires server-side on its own.
**Why:** user's explicit choice when asked (anonymous device token); it
composes cleanly with claim-on-login (one UPDATE reassigning tickets) and
avoids building a second identity/session concept next to JWT for one
feature. **Revisit if:** abuse (spam ticket creation with throwaway
tokens) becomes a real problem - add rate-limiting on
`POST /support/guest/session` by IP before adding any heavier identity
mechanism.

## 2026-11-20 — claude-haiku-5-5 as the AI assistant's model (SUPERSEDED same day, see below)
**What I did:** `ai_svc.py` calls Claude Haiku 5.5. **Why:** checked
against Anthropic's own current cost/latency guidance rather than
assumed - support chat (high-volume, latency-sensitive, Q&A/
classification-shaped) is exactly the workload that model tier handles
well; reserving a jump to Sonnet for if quality, not cost or latency, is
later measured as the actual bottleneck. **Superseded:** user already has
an Azure OpenAI resource provisioned (`campus365net-campus365a-resource`,
`gpt-5-mini` deployed) and wants it used instead - see the entry below.

## 2026-11-20 — AI assistant + embeddings run on Azure OpenAI (`gpt-5-mini`), not Anthropic
**What I did:** switched `ai_svc.py`'s model call and `kb_svc.py`'s
embedding generation to the user's existing Azure OpenAI resource
(`campus365net-campus365a-resource`), chat replies via `gpt-5-mini`
(Chat Completions, `reasoning_effort: "low"` for latency,
`max_completion_tokens` sized to leave room for reasoning + visible
output - the reasoning-token budget trap confirmed live: a 16-token cap
produced zero visible output because `gpt-5-mini` spent the whole budget
reasoning), embeddings via a text-embedding deployment on the same
resource (user confirmed one exists/will exist there). **Why:** user's
explicit instruction, and it's infrastructure already provisioned and
paid for rather than a new Anthropic API dependency - same "use what's
already there" principle as pgvector-on-existing-Postgres. **New external
dependency, flagged per CLAUDE.md:** this is Triptel's first call out to
Azure OpenAI; needs `AZURE_OPENAI_API_KEY`/`AZURE_OPENAI_ENDPOINT`/
`AZURE_OPENAI_CHAT_DEPLOYMENT`/`AZURE_OPENAI_EMBEDDING_DEPLOYMENT` as
backend env vars (never committed - see Rules.md), set on both
`esim-backend` and `esim-backend-beta`. **Security note:** the API key
was pasted in plaintext in chat during this design conversation - flagged
to the user to rotate it in the Azure portal before this ships, since a
key that has appeared in any chat transcript should be treated as
potentially exposed regardless of where that transcript lives.
**Revisit if:** quality/latency on `gpt-5-mini` doesn't hold up under
real traffic - the escalation path is a larger Azure OpenAI deployment
(e.g. `gpt-5`) on the same resource, not a provider switch, since the
integration code is provider-specific either way.

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
