#!/bin/sh
# One pass of the paperless pipeline: ingest new scans -> reconcile with Notion
# -> publish. Run on a schedule (Synology Task Scheduler) or in a loop (loop.sh).
#
# Steps are isolated (one failing does not abort the others). Each is framed with
# a ▶ start / ✓ done / ✗ FAILED marker + elapsed time; sub-output is indented and
# de-noised. A pass with any failed step prints a ✗ summary and exits non-zero, so
# problems are easy to spot in the log.
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
ts() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }

VAULT="${OBAGENT_VAULT:?OBAGENT_VAULT not set}"
MIN_AGE="${OBAGENT_MIN_AGE:-60}"

# Color only on a terminal (so redirected logs stay clean).
if [ -t 1 ]; then
    C_G=$(printf '\033[32m'); C_R=$(printf '\033[31m')
    C_DIM=$(printf '\033[2m'); C_B=$(printf '\033[1m'); C_0=$(printf '\033[0m')
else
    C_G=""; C_R=""; C_DIM=""; C_B=""; C_0=""
fi

# Lines that carry no information in a log: section banners, the prehook echo,
# empty-inbox / all-unchanged / nothing-to-push no-ops, blank lines. ("N unchanged"
# with nothing else is dropped; lines like "5 unchanged, 1 vault_updated" survive.)
NOISE='^=== |^[[:space:]]*\$ |^0 files found|^Everything up-to-date$|^[0-9]* unchanged$|^[[:space:]]*$'

FAILED=""
step() {  # step LABEL CMD...
    label="$1"; shift
    printf '  %s▶%s %s\n' "$C_DIM" "$C_0" "$label"
    start=$(date +%s)
    rcf="$(mktemp)"
    { "$@"; echo $? >"$rcf"; } 2>&1 | grep -vE "$NOISE" | sed "s/^/      ${C_DIM}/;s/\$/${C_0}/"
    rc=$(cat "$rcf"); rm -f "$rcf"
    el=$(( $(date +%s) - start ))
    if [ "$rc" -eq 0 ]; then
        printf '  %s✓%s %s %s(%ss)%s\n' "$C_G" "$C_0" "$label" "$C_DIM" "$el" "$C_0"
    else
        printf '  %s✗ %s FAILED (exit %s, %ss)%s\n' "$C_R" "$label" "$rc" "$el" "$C_0"
        FAILED="${FAILED}${FAILED:+, }${label}"
    fi
}

# No-overlap guard: if a previous pass is still running, skip this one. The lock
# lives on the (bind-mounted) vault so it is shared across `docker run` ticks.
LOCK="${OBAGENT_LOCK:-$VAULT/.obagent/run.lock}"
mkdir -p "$(dirname "$LOCK")"
exec 9>"$LOCK"
if command -v flock >/dev/null 2>&1; then
    flock -n 9 || { printf '%s  skipped — another run in progress\n' "$(ts)"; exit 0; }
fi

pass_start=$(date +%s)
printf '\n%s──────── %s ────────%s\n' "$C_B" "$(ts)" "$C_0"
step "consume (min-age ${MIN_AGE}s)" obagent --vault "$VAULT" consume --min-age "$MIN_AGE"
step "notion sync" obagent --vault "$VAULT" notion sync
step "publish" "$HERE/publish.sh"

el=$(( $(date +%s) - pass_start ))
if [ -n "$FAILED" ]; then
    printf '  %s✗ pass FAILED: %s (%ss)%s\n' "$C_R" "$FAILED" "$el" "$C_0"
    exit 1
fi
printf '  %s✓ pass complete (%ss)%s\n' "$C_G" "$el" "$C_0"
