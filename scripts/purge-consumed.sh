#!/bin/sh
# Drain the obagent purge queue on the HOST (DSM Task Scheduler), not in the
# container. obagent (consume with OBAGENT_PURGE_QUEUE set) copies each source
# into the vault and records its path here; this script deletes those inbox files
# host-side, so Cloud Sync sees the deletion and removes them from Google Drive.
# (A delete from inside the container is invisible to Cloud Sync's watcher — that
# is the whole reason this exists. See DEPLOY.md "Draining the Drive consume inbox".)
#
# Env (defaults match docker-compose.yml + the documented host layout):
#   OBAGENT_PURGE_QUEUE_HOST   queue file, host side   (default /volume1/paperless/purge-queue/queue)
#   OBAGENT_INBOX_HOST         consume inbox, host side (default /volume1/gdrive/paperless/consume)
#   OBAGENT_INBOX_CONTAINER    consume inbox prefix obagent recorded (default /consume)
set -u
QUEUE="${OBAGENT_PURGE_QUEUE_HOST:-/volume1/paperless/purge-queue/queue}"
HOST_INBOX="${OBAGENT_INBOX_HOST:-/volume1/gdrive/paperless/consume}"
CONTAINER_INBOX="${OBAGENT_INBOX_CONTAINER:-/consume}"

[ -f "$QUEUE" ] || exit 0

# Atomically claim this batch: obagent's next append starts a fresh queue file, so
# entries recorded while we work are handled next run. Nothing is lost.
batch="$QUEUE.$$"
mv "$QUEUE" "$batch" 2>/dev/null || exit 0

# sort -u dedups within the batch. Only ever rm under the known inbox prefix
# (safety): translate the container path obagent recorded to the host path.
sort -u "$batch" | while IFS= read -r p; do
    [ -n "$p" ] || continue
    case "$p" in
        "$CONTAINER_INBOX"/*)
            rm -f "$HOST_INBOX${p#"$CONTAINER_INBOX"}" ;;
        *) : ;;  # outside the known inbox -> skip (never rm an arbitrary path)
    esac
done

rm -f "$batch"
