#!/bin/sh
set -e
# Started as root: make the data dirs writable by the unprivileged app user, so
# bind-mounted host folders (owned by root on Synology) work without the user
# having to chmod anything. Then drop privileges and run the app as `bridge`.
if [ "$(id -u)" = "0" ]; then
  for d in /app/cover_cache /app/uploads /app/webdav; do
    mkdir -p "$d"
    chown bridge:bridge "$d" 2>/dev/null || true
  done
  exec gosu bridge "$@"
fi
# Already non-root (e.g. named-volume deploy): just run.
exec "$@"
