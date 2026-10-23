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
# the git checkout. See docker-compose.beta.yml.
set -e

SNAPSHOT=/snapshot/prod-snapshot.dump
if [ -f "$SNAPSHOT" ]; then
  echo "Restoring one-time production snapshot into beta database..."
  pg_restore --no-owner --no-acl -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$SNAPSHOT" || \
    echo "pg_restore reported warnings (often harmless - e.g. extension ownership). Continuing."
  echo "Snapshot restore complete."
else
  echo "No snapshot file found at $SNAPSHOT - starting with an empty beta database."
fi
