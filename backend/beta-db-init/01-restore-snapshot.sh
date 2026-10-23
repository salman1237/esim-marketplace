#!/bin/bash
# Restores a one-time snapshot of production data on the beta database's
# FIRST boot only. Postgres only runs scripts in this directory when the
# data directory is empty, so a redeploy of an already-seeded beta stack
# never re-runs this and never overwrites whatever beta has since done to
# its own (separate) data.
#
# The snapshot file itself is never committed to this repo - it is real
# customer data (emails, phone numbers, NID numbers, wallet balances, order
# history) and is bind-mounted in from the host at an absolute path outside
# the git checkout. See docker-compose.beta.yml. It must be WORLD-READABLE
# on the host (chmod 644) - the postgres image runs as its own unprivileged
# user, and a root-only file bind-mounted in restores silently with every
# row skipped rather than failing loudly, which is exactly what happened
# the first time this ran.
#
# Does not use `set -e`: pg_restore routinely exits non-zero for things that
# are not failures (ownership it was told to skip via --no-owner, a role
# that doesn't exist on this server) and a hard exit here would abort
# Postgres's own startup sequence over a warning. Its exit code and output
# are logged either way, specifically so a genuine partial failure - as
# opposed to a cosmetic warning - is visible in `docker logs esim-db-beta`
# rather than discovered later as a quietly short table.
SNAPSHOT=/snapshot/prod-snapshot.dump

if [ ! -f "$SNAPSHOT" ]; then
  echo "No snapshot file found at $SNAPSHOT - starting with an empty beta database."
  exit 0
fi

if [ ! -r "$SNAPSHOT" ]; then
  echo "FATAL: $SNAPSHOT exists but is not readable by this container's user."
  echo "Fix on the host: chmod 644 <the file bind-mounted at this path>."
  exit 1
fi

echo "Restoring one-time production snapshot into beta database..."
pg_restore --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$SNAPSHOT" 2>&1
rc=$?
echo "pg_restore exited with status $rc (non-zero is often just ownership/role warnings from --no-owner - check the output above for anything beyond that)."
