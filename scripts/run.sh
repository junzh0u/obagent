#!/bin/sh
# One pass of the paperless pipeline: ingest new scans -> reconcile with Notion
# -> publish. Run it on a schedule (Synology Task Scheduler) or in a loop.
# Each step is isolated: a failure is logged but does not abort the rest.
#
# Required env:
#   OBAGENT_VAULT     vault dir (contains Receipts/, Documents/, ...)
#   OBAGENT_CONSUME   inbox root (per-type subdirs)        -> `obagent consume`
#   OBAGENT_EXPORT    Drive export root (Cloud-Synced)     -> `obagent export`
#   NOTION_TOKEN, MISTRAL_API_KEY, OPENAI_API_KEY
# Optional:
#   OBAGENT_MIN_AGE       seconds a scan must be untouched before consuming (default 60)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }

VAULT="${OBAGENT_VAULT:?OBAGENT_VAULT not set}"
MIN_AGE="${OBAGENT_MIN_AGE:-60}"

# No-overlap guard: if a previous pass is still running, skip this one. The lock
# lives on the (bind-mounted) vault so it is shared across `docker run` ticks.
LOCK="${OBAGENT_LOCK:-$VAULT/.obagent/run.lock}"
mkdir -p "$(dirname "$LOCK")"
exec 9>"$LOCK"
if command -v flock >/dev/null 2>&1; then
    flock -n 9 || { log "another run in progress; skipping"; exit 0; }
fi

log "consume (min-age ${MIN_AGE}s)"
obagent --vault "$VAULT" consume --min-age "$MIN_AGE" || log "WARN: consume failed"

log "notion sync"
obagent --vault "$VAULT" notion sync || log "WARN: notion sync failed"

log "publish"
"$HERE/publish.sh" || log "WARN: publish failed"

log "done"
