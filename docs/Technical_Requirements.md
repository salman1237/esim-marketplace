# Technical Requirements
**Read when:** adding a dependency, or touching build/test/verification.

## Dependencies
- **No new dependency needed for WS support** - `uvicorn[standard]` (already
  in `backend/requirements.txt`) bundles the `websockets` package FastAPI's
  `WebSocket` uses. Confirmed before writing this doc.
- Frontend: native browser `WebSocket` API is enough; no client library
  needed for the scope in `Functional_Requirements.md`.
- Anything beyond that (Redis, a message broker) needs a `DECISIONS.md`
  entry first - see CLAUDE.md's Hard Constraints.

## Commands
| Command | Does |
|---|---|
| `cd backend && python -m pytest` | Backend test suite |
| `cd backend && python -m pytest tests/test_support_chat_*.py -q` | This feature's backend tests |
| `cd frontend && npm run build` | Type-checks + production build |
| `cd frontend && npm run lint` | Lint |

Backend tests need a real Postgres reachable at `TEST_DATABASE_URL` (see
`backend/tests/conftest.py`) - the project does not use SQLite for tests.
If none is running locally, use a disposable instance scoped to the test run
rather than touching whatever Postgres the machine already has for other
projects (precedent: `GET /catalog/featured`'s own verification did this).

## Verification layers
1. **Static** - the backend has no configured `mypy`/`ruff` gate today
   (unlike the PDF's hypothetical example) - don't invent one as a blocking
   gate for this feature; match what the repo actually enforces.
2. **Runtime** - pytest for the backend (model, ownership checks, broadcast
   fan-out with a fake/test WS client), and a frontend build for the UI.
3. **End-to-end** - a real two-socket test proving broadcast actually
   reaches a second connection (Functional_Requirements.md §F), plus a
   manual check against a real beta deployment before marking a UI feature
   `passing` (WS behavior through a real reverse proxy/Dokploy routing can
   differ from an in-process test client - confirm it once for real before
   trusting the loop blindly here).

## Known environment facts (don't re-derive these)
- `esim-backend`/`esim-backend-beta`: one container each, no replicas, no
  Redis (confirmed in `docker-compose.yml`/`docker-compose.beta.yml`).
- VPS access and Dokploy deploy mechanics: see this project's existing
  memory/history docs - not repeated here.
