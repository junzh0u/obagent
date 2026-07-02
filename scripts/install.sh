#!/bin/sh
# Install/refresh the `obagent` binary from this checkout and record which commit
# it was built from, so run.sh's per-pass guard (sync_binary) can skip a
# redundant reinstall. Whoever installs owns the stamp — a manual run here keeps
# the guard truthful, exactly like the pass's own reinstall. The stamp lives
# under .git/ (never tracked, per-checkout). Callers: `just install`, run.sh.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
uv tool install "$REPO" --compile-bytecode --force --reinstall
git -C "$REPO" rev-parse HEAD >"$REPO/.git/obagent-installed-commit" 2>/dev/null || true
