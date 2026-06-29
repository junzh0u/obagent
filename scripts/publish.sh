#!/bin/sh
# Publish the vault:
#   1. `obagent export`  -> renamed, date-bucketed originals at $OBAGENT_EXPORT
#      (a Synology Cloud Sync folder -> Google Drive; browsable PDFs).
#   2. `git fetch` + ff  -> integrate remote commits (fast-forward ONLY; guarded,
#      never rebases/merges) so our commit lands on top and the push stays a clean
#      fast-forward. A divergence/conflict can't leave the repo half-merged.
#   3. `git commit`      -> stage + commit the vault's changes. A plain machine
#      commit (the NAS has no Claude/LLM committer); skipped when nothing changed.
#   4. `git push`        -> the vault repo to its git remotes.
#
# Env:
#   OBAGENT_VAULT        (required) vault dir (contains Receipts/, Documents/, ...)
#   OBAGENT_EXPORT       (required) Drive export root (used by `obagent export`)
#   OBAGENT_GIT_NAME     (optional) commit author name  (fallback if repo has none)
#   OBAGENT_GIT_EMAIL    (optional) commit author email (fallback if repo has none)
set -u

VAULT="${OBAGENT_VAULT:?OBAGENT_VAULT not set}"

obagent --vault "$VAULT" export || { echo "publish: export failed" >&2; exit 1; }

# Integrate remote commits first, guarded: fast-forward ONLY. If the branch has
# diverged (or local edits would be clobbered), --ff-only aborts cleanly with no
# side effects — we log and let the push below decide. Never rebases/merges, so a
# conflict can't leave the repo mid-merge.
if up=$(git -C "$VAULT" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null); then
    git -C "$VAULT" fetch --quiet || echo "publish: fetch failed (offline?), continuing" >&2
    git -C "$VAULT" merge --ff-only "$up" >/dev/null 2>&1 \
        || echo "publish: '$up' not fast-forwardable; committing anyway (push may be rejected if diverged)" >&2
fi

# Commit vault changes (notes, shadow) so the push has something to send. The NAS
# container has no global git identity — set a fallback only if none is configured.
git -C "$VAULT" config user.name  >/dev/null 2>&1 || git -C "$VAULT" config user.name  "${OBAGENT_GIT_NAME:-obagent}"
git -C "$VAULT" config user.email >/dev/null 2>&1 || git -C "$VAULT" config user.email "${OBAGENT_GIT_EMAIL:-obagent@localhost}"
git -C "$VAULT" add -A .
if ! git -C "$VAULT" diff --cached --quiet; then
    added=$(git -C "$VAULT" diff --cached --diff-filter=A --name-only | wc -l | tr -d ' ')
    edited=$(git -C "$VAULT" diff --cached --diff-filter=M --name-only | wc -l | tr -d ' ')
    if git -C "$VAULT" commit -q -m "vault sync: +${added} ~${edited} $(date -u +%Y-%m-%dT%H:%MZ)"; then
        echo "committed $(git -C "$VAULT" log -1 --format='%h %s')"
    else
        echo "publish: commit failed" >&2; exit 1
    fi
fi

# --quiet: success is silent (no transfer spam); errors still surface on stderr.
rc=0
for r in $(git -C "$VAULT" remote); do
    git -C "$VAULT" push --quiet "$r" || { echo "publish: push '$r' failed" >&2; rc=1; }
done
exit "$rc"
