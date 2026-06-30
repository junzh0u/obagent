# Consume-inbox Drive drain via host-side purge queue — plan

**Status (2026-06-30): BUILT.** `OBAGENT_PURGE_QUEUE` (copy mode + record consumed
paths), `scripts/purge-consumed.sh` (host drain), compose mount/env, `.env.example`,
`DEPLOY.md` (§5 reasoning + new §9 drain job), `CLAUDE.md`/`README.md`, and tests
(`tests/shared/test_consume_purge_queue.py`) all landed. This fixes the broken
"Cloud Sync drains the Drive consume inbox" assumption from the deployment.

## Problem & diagnosis (why the current drain fails)

The deploy assumed: `consume` **moves** a source out of the Drive-synced inbox
(`/volume1/gdrive/paperless/consume`) → the local file is deleted → Synology **Cloud
Sync (bidirectional)** propagates that deletion up → the file disappears from Google
Drive (drain). **It doesn't work.** Confirmed empirically:

- obagent runs **in a Docker container**; it removes the source via
  `shutil.move` = copy + **`os.unlink`** (`commands/ingest.py:36`), an unlink in the
  container's mount namespace.
- The unlink **is real** — a host `ls` shows the file gone (bind mount shares the
  host inodes; the filesystem state is consistent across the docker boundary).
- But Cloud Sync is **event-driven** and **never receives the delete event** for the
  container's unlink (its log shows only the initial download, no delete). Container
  *creates* are picked up (export uploads work), container *deletes* are not.
- On reconciliation (task restart / consistency scan) Cloud Sync **bidirectional**
  resolves "gone locally, present on Drive" as **re-download**, not delete-remote
  (restarting the task re-downloaded every consumed file). There is **no toggle** for
  this in bidirectional mode (the delete-propagation toggle only exists for one-way).
- A **host-side** delete (File Station UI *or* `rm` over SSH) **does** propagate to
  Drive — because the host performs the op, so Cloud Sync's watcher gets the event.

**Conclusion:** no container-side operation (unlink, move, rename) and no mount/compose
option can fix this — it's an event-delivery gap, not a filesystem-state or mount
problem. The delete must be **performed on the host**. Cloud Sync config stays as-is
(bidirectional); we just move *who* does the delete.

Rejected alternatives:
- **rclone `move`** (delete from Drive via the Drive API, bypassing Cloud Sync):
  robust, but needs a Google Drive token in the container — the thing we've worked to
  avoid.
- **sha-match host script** (no obagent change; host re-hashes each inbox file and
  `rm`s it if `_assets_/<sha>/` exists in the vault): works, but re-hashes the inbox
  every run and re-implements obagent's content-addressing in shell.
- **Scan `metadata.json`** (obagent already records `original_filepath` +
  `consumed_at` at `ingest.py:38-40`): zero code change, but walks *all* history every
  run (thousands of stale `rm -f` no-ops).

## Chosen design — host-side purge queue

obagent records the path of each consumed source to a **queue file** (on a shared
bind-mount), in **copy** mode so the source stays in the inbox. A **host** Task
Scheduler job drains the queue with `rm` — a host-side delete, which Cloud Sync
*does* propagate, removing the file from Drive.

End-to-end flow:
1. File lands in Drive `consume/<type>/` (scanner-via-Drive / phone / email Apps
   Script) → Cloud Sync **downloads** it to the NAS inbox (works today).
2. `obagent consume` (with `OBAGENT_PURGE_QUEUE` set) **copies** it into
   `vault/<type>/_assets_/<sha>/`, writes the note, **leaves the source** in the
   inbox, and **appends the source path** to the queue.
3. Host job (Task Scheduler, every few min): claims the queue, **`rm`s** each listed
   source on the host.
4. Cloud Sync hears the host delete event → removes the file from Drive. **Drained.**

Why copy (not move) is non-negotiable: the file must still be in the inbox when the
*host* deletes it — the host's `rm` is what fires the event. If obagent unlinked it
first, the host would `rm` an already-gone path → no event → no drain.

## Build — obagent feature (`OBAGENT_PURGE_QUEUE`)

Small, additive. Files: `commands/consume.py` (+ a tiny helper), tests.

1. **New option** `--purge-queue PATH` (envvar `OBAGENT_PURGE_QUEUE`,
   `click.Path(path_type=Path)`, default `None`) added to **`_api_and_model_options`**
   in `commands/consume.py` so **both** consume entry points get it (the per-type
   `make_consume_command` and the top-level `consume_all`). Thread the resulting
   `purge_queue` param into `_consume_path`.

2. **`_consume_path(...)`** — add `purge_queue: Path | None = None`. Behavior when set:
   - Force **copy** mode: pass `keep_original=True` to `ingest_source` regardless of
     the `--keep-original` flag (compute `effective_keep = keep_original or purge_queue
     is not None`).
   - **Append the source path** to the queue once the file's bytes are safely in the
     vault, i.e.:
     - On a **duplicate** (`ingest_source` returns `None` — already in `_assets_/`):
       append immediately (it's already fully in the vault → safe to drop), then the
       existing `skipped += 1; continue`.
     - On a **new** ingest (`target_dir` set): append at the **end** of the iteration,
       *after* `render_note` (so a mid-pipeline OCR/LLM exception leaves the source in
       the inbox for a clean retry; render-only warnings still queue it — the asset is
       in the vault and render is re-runnable).
   - Append helper:
     ```python
     def _queue_append(queue: Path, source: Path) -> None:
         with queue.open("a") as f:           # O_APPEND: atomic per small line
             f.write(f"{source.resolve()}\n")
     ```
     (`source.resolve()` matches what `metadata.json` records — the **container**
     absolute path, e.g. `/consume/Receipts/x.pdf`.)

3. **Wire the param** in both commands: `make_consume_command`'s `consume` and
   `consume_all` receive `purge_queue` from the option and pass it to `_consume_path`.

4. **No `run.sh` change** — `obagent consume` reads `OBAGENT_PURGE_QUEUE` from the env
   (like `OBAGENT_CONSUME_PREHOOK`). Setting the env var in `.env` turns the mode on.

### obagent tests (`tests/.../test_consume_unit.py` or a new file)
- `purge_queue` set → source is **copied** (still exists at the source path) and its
  resolved path is **appended** to the queue; queue has one line per consumed file.
- **Duplicate** (sha already in vault) → still appended to the queue (so re-downloaded
  already-consumed files get drained).
- A **mid-pipeline failure** (OCR raises) → source **not** appended (retry-safe).
- `purge_queue` unset → unchanged behavior (move, no queue).

## Build — host purge script (`scripts/purge-consumed.sh`)

Runs on the **host** (DSM Task Scheduler), not in the container. Checked into the repo
as the reference script; deployed by pasting into a scheduled task.

```sh
#!/bin/sh
# Drain the obagent purge queue: delete (host-side) the consumed inbox files obagent
# recorded, so Cloud Sync sees the deletion and removes them from Google Drive.
set -u
QUEUE="${OBAGENT_PURGE_QUEUE_HOST:-/volume1/paperless/purge-queue/queue}"
HOST_INBOX="${OBAGENT_INBOX_HOST:-/volume1/gdrive/paperless/consume}"
CONTAINER_INBOX="${OBAGENT_INBOX_CONTAINER:-/consume}"   # prefix obagent recorded

[ -f "$QUEUE" ] || exit 0
batch="$QUEUE.$$"
mv "$QUEUE" "$batch" 2>/dev/null || exit 0   # atomically claim this batch; obagent's
                                             # next append starts a fresh queue file
sort -u "$batch" | while IFS= read -r p; do
    [ -n "$p" ] || continue
    case "$p" in
        "$CONTAINER_INBOX"/*)                       # translate container -> host path
            rm -f "$HOST_INBOX${p#"$CONTAINER_INBOX"}" ;;
        *) : ;;                                      # outside the known inbox -> skip
    esac
done
rm -f "$batch"
```

Key points:
- **Path translation:** obagent records the container path (`/consume/...`); the
  bind mount is a clean prefix, so swap `/consume` → `$HOST_INBOX`. The `case` guard
  only ever `rm`s paths **under the known inbox** (safety — never an arbitrary path).
- **Concurrency:** `mv "$QUEUE" "$batch"` atomically claims the batch; entries obagent
  appends during processing land in a new queue and are handled next run. Nothing lost.
- **Idempotent / safe:** the queue lists only files obagent **provably** consumed (the
  copy is in the vault). `rm -f` on an already-gone path is a harmless no-op. No
  data-loss risk. `sort -u` dedups within a batch.
- An mtime quiescence guard isn't needed (obagent only queues a path *after* copying,
  so the source is quiescent), but is harmless if added.

`sh -n scripts/purge-consumed.sh` to syntax-check (shell scripts aren't unit-tested in
this repo, same as `run.sh`/`publish.sh`).

## Build — compose + env + docs

- **`docker-compose.yml`:** add a shared bind-mount for the queue dir and set the env:
  ```yaml
  environment:
    OBAGENT_PURGE_QUEUE: /purge-queue/queue
  volumes:
    - /volume1/paperless/purge-queue:/purge-queue   # obagent writes; host job drains
  ```
  Consume mounts stay as-is (Cloud Sync still downloads into
  `/volume1/gdrive/paperless/consume:/consume`; `OBAGENT_CONSUME=/consume`).
- **`.env.example`:** document `OBAGENT_PURGE_QUEUE` (optional; host-purge drain).
- **`DEPLOY.md`:** new "Draining the Drive consume inbox" section —
  - Why: Cloud Sync (bidirectional) does **not** propagate the container's deletions;
    a host-side delete does. So obagent records consumed paths; a host job deletes them.
  - `mkdir -p /volume1/paperless/purge-queue`.
  - Set `OBAGENT_PURGE_QUEUE=/purge-queue/queue` (compose already does).
  - Create a **DSM Task Scheduler** user-defined script (root) running
    `scripts/purge-consumed.sh` every ~5 min (mount the repo or paste the script;
    set `*_HOST`/`*_CONTAINER` vars if paths differ).
  - Leave the Cloud Sync task **bidirectional and unchanged** — it still downloads;
    the host job is what drains. No rclone, no Google token.
- **`CLAUDE.md` Deployment section:** one line — the drain is a host Task Scheduler
  job draining `OBAGENT_PURGE_QUEUE` (Cloud Sync can't see container deletes).

## Safety summary

- obagent never deletes the inbox file itself (copy mode); only the host does, and only
  paths obagent recorded as consumed (bytes already in `_assets_/<sha>/`). Zero
  data-loss risk; the vault copy is the source of truth.
- The host script only `rm`s under the configured inbox prefix; a stale/foreign queue
  line is skipped. `rm -f` + batch-claim make it idempotent and race-safe.
- A failed consume (OCR/LLM) leaves the source un-queued → retried next pass.

## One-time setup (deploy)

1. `mkdir -p /volume1/paperless/purge-queue` on the NAS.
2. Add the queue mount + `OBAGENT_PURGE_QUEUE` to compose (above); redeploy the image
   (rebuild for the obagent feature).
3. DSM **Task Scheduler** → user-defined script (root), `scripts/purge-consumed.sh`,
   every ~5 min.
4. Verify: drop a test file in Drive `consume/<type>/` → it downloads, becomes a note,
   the source stays in the inbox briefly, then the host job `rm`s it and it
   **disappears from Drive** (drained). Confirm no re-download.
