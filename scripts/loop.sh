#!/bin/sh
# Long-running monitor: run one pass (run.sh) every $OBAGENT_INTERVAL seconds.
# This is the docker-compose service command (restart: always). For one-off runs
# (e.g. Synology Task Scheduler) call scripts/run.sh directly instead.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
INTERVAL="${OBAGENT_INTERVAL:-300}"
trap 'echo "[loop] stopping"; exit 0' TERM INT
echo "[loop] running every ${INTERVAL}s"
while true; do
    "$HERE/run.sh" || echo "[loop] pass failed (continuing)"
    sleep "$INTERVAL" &
    wait "$!"  # backgrounded sleep so SIGTERM stops us promptly
done
