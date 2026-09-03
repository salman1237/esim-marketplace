#!/bin/sh
set -e

# Bootstraps the database schema via Alembic before starting the app.
#
# Two cases:
#   1. A genuinely fresh database (no `users` table yet): run every
#      migration from scratch with `alembic upgrade head`.
#   2. A database that already has the current schema but no
#      `alembic_version` table yet — this is exactly the state production
#      was left in after the 2026-09-03 schema reset (formerly handled by
#      _reset_stale_pre_migration_schema, now removed from app/main.py in
#      favor of this): `alembic stamp head` marks it as up to date without
#      trying to re-run CREATE TABLE against tables that already exist.
#
# After this one-time bootstrap, both cases converge: every future boot
# just runs `alembic upgrade head`, a no-op until a new migration is added.

BOOTSTRAP_MODE=$(python3 - <<'PYEOF'
import asyncio
from sqlalchemy import text
from app.core.database import engine

async def check():
    async with engine.connect() as conn:
        users_exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_name = 'users'"
        ))).first() is not None
        version_exists = (await conn.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_name = 'alembic_version'"
        ))).first() is not None
    await engine.dispose()
    print("stamp" if (users_exists and not version_exists) else "upgrade")

asyncio.run(check())
PYEOF
)

echo "Schema bootstrap mode: $BOOTSTRAP_MODE"

if [ "$BOOTSTRAP_MODE" = "stamp" ]; then
  alembic stamp head
else
  alembic upgrade head
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
