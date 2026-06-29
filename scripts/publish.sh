#!/bin/sh
# Publish the vault:
#   1. `obagent export`  -> renamed, date-bucketed originals at $OBAGENT_EXPORT
#      (a Synology Cloud Sync folder -> Google Drive; browsable PDFs).
#   2. `git push`        -> the vault repo to its git remotes (GitHub, GitLab).
#
# Env:
#   OBAGENT_VAULT        (required) vault dir (contains Receipts/, Documents/, ...)
#   OBAGENT_EXPORT       (required) Drive export root (used by `obagent export`)
#   OBAGENT_GIT_REMOTES  (optional) space-separated remotes; default: all configured
set -u

VAULT="${OBAGENT_VAULT:?OBAGENT_VAULT not set}"

obagent --vault "$VAULT" export || { echo "publish: export failed" >&2; exit 1; }

remotes="${OBAGENT_GIT_REMOTES:-$(git -C "$VAULT" remote)}"
rc=0
for r in $remotes; do
    git -C "$VAULT" push "$r" || { echo "publish: push '$r' failed" >&2; rc=1; }
done
exit "$rc"
