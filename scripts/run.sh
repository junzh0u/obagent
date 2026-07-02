#!/bin/sh
# One pass of the paperless pipeline: pull the vault (ff-only) -> ingest new scans
# -> reconcile with Notion -> publish. Run on a schedule (Synology Task Scheduler),
# typically via a thin dotfiles wrapper that sets up the env first (see DEPLOY.md
# "entry script").
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
REPO="$(cd "$HERE/.." && pwd)"
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
NOISE='^=== |^[[:space:]]*\$ |^0 files found|^Everything up-to-date$|^[0-9]* unchanged$|^No case collisions\.$|^[[:space:]]*$'

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

# Pick up remote vault changes before processing, fast-forward ONLY (guarded — like
# publish.sh; never rebases/merges, so a divergence can't leave the repo mid-merge).
# So consume/notion-sync act on the latest notes (e.g. edits from a laptop/phone) and
# the end-of-pass push stays a clean fast-forward. Soft: an offline fetch or a non-ff
# divergence logs and continues on local state (publish re-checks the ff at the end,
# and a diverged push fails loudly there).
# Warn-only vault integrity check: flag any case-colliding note filenames (e.g.
# Costco.md / costco.md) that would collide on the case-insensitive Drive export.
# `render` prevents these locally, but a cross-machine git merge can still land
# two case-variants. Read-only; run `obagent check --apply` to merge them.
# Exit 1 = collisions found -> warn-only, don't fail the pass. Any OTHER nonzero
# (127 missing binary, 2 stale binary without `check`, crash) is surfaced, so a
# forgotten `uv tool install` after a code pull shows up as a FAILED step.
check_vault() {
    obagent --vault "$VAULT" check
    rc=$?
    [ "$rc" -eq 1 ] && return 0
    return "$rc"
}

# Keep the installed `obagent` in lockstep with this checkout, so a bare
# `git pull` of the code repo is enough — no separate `uv tool install` to
# forget (which would silently run stale code). Reinstalls only when HEAD moved
# (a no-op otherwise, keyed on the stamp scripts/install.sh writes under .git/).
# The install + stamp live in scripts/install.sh so a manual `just install`
# satisfies this guard too. Soft: a missing uv, non-git checkout, or failed
# install logs and continues on whatever binary is on PATH — other steps run.
sync_binary() {
    command -v uv >/dev/null 2>&1 || { echo "uv not found; skipping binary sync"; return 0; }
    head=$(git -C "$REPO" rev-parse HEAD 2>/dev/null) || return 0
    stamp="$REPO/.git/obagent-installed-commit"
    [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$head" ] && return 0
    if sh "$HERE/install.sh" >/dev/null 2>&1; then
        echo "reinstalled obagent @ ${head}"
    else
        echo "obagent reinstall failed; continuing on current binary"
    fi
}

pull_vault() {
    up=$(git -C "$VAULT" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null) || return 0
    git -C "$VAULT" fetch --quiet || { echo "fetch failed (offline?), continuing on local state"; return 0; }
    git -C "$VAULT" merge --ff-only "$up" >/dev/null 2>&1 \
        || echo "'$up' not fast-forwardable; continuing on local state"
    return 0
}

# No-overlap guard: if a previous pass is still running, skip this one — so an
# overlapping Task Scheduler tick no-ops instead of racing.
LOCK="${OBAGENT_LOCK:-$VAULT/.obagent/run.lock}"
mkdir -p "$(dirname "$LOCK")"
exec 9>"$LOCK"
if command -v flock >/dev/null 2>&1; then
    flock -n 9 || { printf '%s  skipped — another run in progress\n' "$(ts)"; exit 0; }
fi

pass_start=$(date +%s)
printf '\n%s──────── %s ────────%s\n' "$C_B" "$(ts)" "$C_0"
step "sync binary" sync_binary
step "vault pull" pull_vault
step "consume (min-age ${MIN_AGE}s)" obagent --vault "$VAULT" consume --min-age "$MIN_AGE"
step "notion sync" obagent --vault "$VAULT" notion sync
step "case-collision check" check_vault
step "publish" sh "$HERE/publish.sh"

el=$(( $(date +%s) - pass_start ))
if [ -n "$FAILED" ]; then
    printf '  %s✗ pass FAILED: %s (%ss)%s\n' "$C_R" "$FAILED" "$el" "$C_0"
    exit 1
fi
printf '  %s✓ pass complete (%ss)%s\n' "$C_G" "$el" "$C_0"
