#!/bin/sh
# Daily health inspection of the scheduled obagent pass.
#
# Reads the pass-history log that run.sh appends on scheduled runs (one line per
# clean pass, full output per failed pass) and decides whether the pipeline is
# healthy:
#   - healthy (fresh log, no failed passes in the window): print one line, exit 0
#   - anything wrong (failed passes, stale/missing log = the schedule itself
#     died): ask Claude Code (headless `claude -p`) to diagnose from the log +
#     this repo's docs, attempt a trivial safe fix (permissions, stale lock —
#     never data deletion or code changes) and verify with one pass, then print
#     the report and exit 1 — the report goes out whether or not it auto-fixed
#
# Runs daily as a deep inspector delegated from the dotfiles task-watchdog
# (bin/junz-rs2423/task-watchdog, its own DSM Task Scheduler job) rather than
# via a dedicated DSM task: the watchdog merges this report into its alert and
# owns the notification email (same contract — non-zero exit means the report
# must reach the operator, exit 0 means all quiet).
#
# Env (same wrapper as run.sh provides these):
#   OBAGENT_PASS_LOG                    pass-history log; same default as run.sh
#                                       ($XDG_STATE_HOME|~/.local/state)/obagent/
#                                       pass-history.log
# Optional:
#   OBAGENT_INSPECT_WINDOW_HOURS        how far back to look (default 24)
#   OBAGENT_INSPECT_STALE_MINUTES       log mtime older than this means the
#                                       5-min schedule is dead (default 30)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

PASS_LOG="${OBAGENT_PASS_LOG:-${XDG_STATE_HOME:-${HOME:-/tmp}/.local/state}/obagent/pass-history.log}"
WINDOW_H="${OBAGENT_INSPECT_WINDOW_HOURS:-24}"
STALE_MIN="${OBAGENT_INSPECT_STALE_MINUTES:-30}"

# One-shot end-to-end test of the notification channel: `touch` the flag file,
# then run the Task Watchdog DSM task once (Task Scheduler -> Run). The script
# skips the inspection and exits 1 immediately, so the watchdog reports a
# failing deep inspection and its email carries this message. Self-clears.
TEST_FLAG="$REPO/.inspect-test-notification"
if [ -f "$TEST_FLAG" ]; then
    rm -f "$TEST_FLAG"
    echo "TEST notification from scripts/inspect.sh — if you are reading this as"
    echo "an email, the obagent alert channel works end to end. No action needed."
    exit 1
fi

problems=""
add_problem() { problems="${problems}  - $1
"; }

recent=""
if [ ! -f "$PASS_LOG" ]; then
    add_problem "pass-history log missing at $PASS_LOG — the pass schedule may not be running at all"
else
    age_min=$(( ($(date +%s) - $(stat -c %Y "$PASS_LOG")) / 60 ))
    [ "$age_min" -gt "$STALE_MIN" ] \
        && add_problem "pass-history log is stale (${age_min} min old; passes run every 5 min) — the schedule appears dead or stuck"

    # Slice entries from the last WINDOW_H hours. Every entry starts with (or
    # contains, for failed-pass banners) an ISO-8601 UTC timestamp, so a string
    # compare against the cutoff works; once inside the window, keep everything
    # (failed-pass blocks span many lines after their banner).
    cutoff=$(date -u -d "@$(( $(date +%s) - WINDOW_H * 3600 ))" +%Y-%m-%dT%H:%M:%SZ)
    recent=$(awk -v c="$cutoff" '
        found { print; next }
        match($0, /[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z/) {
            if (substr($0, RSTART, RLENGTH) >= c) { found = 1; print }
        }' "$PASS_LOG")

    failed=$(printf '%s\n' "$recent" | grep -c 'pass FAILED' || true)
    ok=$(printf '%s\n' "$recent" | grep -c 'pass complete' || true)
    [ "$failed" -gt 0 ] && add_problem "$failed failed pass(es) in the last ${WINDOW_H}h (${ok} clean)"
    [ "$failed" -eq 0 ] && [ "$ok" -eq 0 ] \
        && add_problem "no completed passes in the last ${WINDOW_H}h"
fi

if [ -z "$problems" ]; then
    echo "healthy: ${ok} clean passes in the last ${WINDOW_H}h, no failures"
    exit 0
fi

echo "obagent pipeline problems detected:"
printf '%s' "$problems"
echo

# Diagnose with Claude Code (headless, read-only tools). Falls back to the raw
# log excerpt if the CLI is unavailable — the notification still goes out.
if command -v claude >/dev/null 2>&1; then
    prompt="You are inspecting the health of obagent's scheduled pipeline on this NAS.
scripts/run.sh runs every 5 minutes via DSM Task Scheduler (code pull -> sync
binary -> vault pull -> consume -> notion sync -> case-collision check ->
publish); this repo's CLAUDE.md documents the architecture. Detected problems:

${problems}
Below is the pass-history log for the last ${WINDOW_H}h (clean passes are one
line, failed passes include their full output). Diagnose the most likely root
cause: what failed, since when, why. You may Read/Grep this repo and the DSM
scheduler logs under /volume1/logs/synoscheduler/obagent/.

If the fix is TRIVIAL and safe — file permissions/ownership, a stale lock, a
missing directory, freeing an obviously-safe blocked file — apply it, then
verify by running one pass ('sh scripts/run.sh'; the flock guard makes overlap
safe) and confirm it completes. Do NOT attempt anything beyond that: no
deleting or rewriting vault notes/sources, no git resets/force-pushes/history
edits, no code changes, no config rewrites — for those, describe the fix and
leave it to the operator.

Reply concisely in plain text — your reply is the body of an alert email.
State clearly: the diagnosis, whether you fixed it (and how, with the verify
result), or what the operator needs to do.

$(printf '%s\n' "$recent" | tail -n 500)"
    if diagnosis=$(cd "$REPO" && claude -p "$prompt" --allowedTools "Read,Grep,Glob,Bash" 2>&1); then
        echo "─── diagnosis (claude) ───"
        printf '%s\n' "$diagnosis"
    else
        echo "(claude diagnosis failed; raw log follows)"
        printf '%s\n' "$recent" | tail -n 100
    fi
else
    echo "(claude CLI not found; raw log follows)"
    printf '%s\n' "$recent" | tail -n 100
fi
exit 1
