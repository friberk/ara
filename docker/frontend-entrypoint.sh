#!/bin/sh
set -eu
# A named dependency volume survives rebuilds. Synchronize only when its lock changes.
current_lock=$(sha256sum /app/package-lock.json | cut -d ' ' -f 1)
installed_lock=$(cat /app/node_modules/.ara-lock-hash 2>/dev/null || true)
if [ "$current_lock" != "$installed_lock" ]; then
  npm ci --no-audit --no-fund
  printf '%s\n' "$current_lock" > /app/node_modules/.ara-lock-hash
fi
exec "$@"
