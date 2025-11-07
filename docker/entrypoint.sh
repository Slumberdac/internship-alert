#!/usr/bin/env sh
set -euo pipefail

# ensure writable data dir for the app user
mkdir -p /data
chown -R appuser:appuser /data || true

# Ensure runtime dir exists
mkdir -p /run/pcscd

# Start PC/SC without polkit (critical)
pcscd --disable-polkit -f &

# Wait for socket and relax perms so non-root can talk to it (if you drop privileges)
for i in $(seq 1 50); do
  [ -S /run/pcscd/pcscd.comm ] && break
  sleep 0.1
done
chmod 666 /run/pcscd/pcscd.comm || true

# If you want to run the app as appuser:
exec gosu appuser:appuser "$@"
