#!/usr/bin/env sh
set -e
if [ -S /run/pcscd/pcscd.comm ]; then
  echo "Using host pcscd"
else
  echo "Starting local pcscd"
  mkdir -p /run/pcscd
  pcscd --disable-polkit -f &
  for i in $(seq 1 50); do [ -S /run/pcscd/pcscd.comm ] && break; sleep 0.1; done
fi
# ensure data dir, then exec app (drop to appuser if you use gosu)
mkdir -p /data
exec "$@"

