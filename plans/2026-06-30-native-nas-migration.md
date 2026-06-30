# Migrate obagent off Docker → native uv on the NAS host — plan

**Status (2026-06-30): BUILT** (repo side). Confirmed on the NAS: `uv` installs and
`uv sync` builds a standalone **Python 3.14 (x86_64)** natively — `uv run obagent
--help` prints the CLI. This dropped the Docker container, runs obagent directly on the
DSM host, and **deleted the purge-queue workaround** — because the bug it worked around
disappears when deletes happen host-side. Repo: purge-queue removed, Docker retired,
`loop.sh`/`redeploy.sh`/`purge-consumed.sh` deleted, `run.sh`/`publish.sh` kept, docs
rewritten. Dotfiles: `bin/junz-rs2423/_obagent` (thin wrapper → `scripts/run.sh`).
Remaining = the operator NAS steps in Track B (uv tool install, Task Scheduler, etc.).

## Why (the root cause, and why native fixes it)

Synology **Cloud Sync** propagates a delete to Google Drive only when the delete
happens **on the host**; a delete from inside the **container's mount namespace** fires
no event its watcher receives, and on reconcile bidirectional Cloud Sync re-downloads
the "missing" file. Proven empirically (host `rm` drains, container unlink doesn't).

Both inbox-draining paths delete *in the container*, so both are broken under Docker:
- **consume**: `shutil.move` = copy + unlink (`commands/ingest.py:36`) — inbox source
  never drains from Drive.
- **export**: dangling cleanup `existing.unlink()` (`commands/export.py:130`) — a
  removed export never drains from Drive. (This is the second bug, same cause.)

The purge-queue (`OBAGENT_PURGE_QUEUE` + `scripts/purge-consumed.sh`, commit `0515084`)
patched **consume only**, by recording paths for a host job to delete. Export would
need the same patch. **Running obagent natively on the host makes every delete a
host-side delete** → Cloud Sync drains both, and the workaround (and the export bug)
vanish with *less* code, not more.

Docker was only ever chosen because "the NAS has no Python 3.14" (CLAUDE.md). `uv`
solves that — now confirmed on the actual box. Going native also retires a pile of
container-only friction: image rebuild / stale-container redeploys, the git
dubious-ownership `safe.directory` gymnastics, and bind-mount path translation.

## What changes — overview

Two tracks: **(A) repo changes** (here, committed) and **(B) NAS redeploy** (the new
DEPLOY.md). The deployment model flips from *compose loop service* to *DSM Task
Scheduler runs `scripts/run.sh` on the host*.

## Track A — repo changes

### A1. Delete the purge-queue feature (revert `0515084`, targeted)
Not a blind `git revert` (later commits touched the same docs). Remove:
- `commands/consume.py`: the `--purge-queue` option in `_api_and_model_options`; the
  `purge_queue` param on `_consume_path` and **both** consume commands; the
  `_queue_append` helper; the two append call-sites; restore `keep_original` (drop
  `effective_keep`). Back to plain move-or-keep.
- `tests/shared/test_consume_purge_queue.py` — delete.
- `scripts/purge-consumed.sh` — delete.
- `.env.example` — drop `OBAGENT_PURGE_QUEUE`.

### A2. Retire Docker + the loop daemon
- Delete `Dockerfile`, `docker-compose.yml`, `.dockerignore` (container-only; git
  history keeps them if Docker is ever wanted again).
- Delete `scripts/loop.sh` — DSM Task Scheduler replaces the loop entirely.

### A3. Keep the pass in the repo; a thin dotfiles wrapper invokes it
The **pass logic** stays versioned in the repo (updates with `git pull`); only the
**env wiring** lives in the operator's dotfiles.
- `scripts/run.sh`, `scripts/publish.sh` → **stay** (one pass: consume → notion sync →
  publish; `flock` no-overlap; per-step framing; the guarded ff-only push). Minor
  comment tweaks only (drop loop.sh / Docker references). They inherit env from the
  wrapper and call the bare `obagent` CLI (on PATH via `uv tool install`).
- `scripts/loop.sh`, `scripts/redeploy.sh`, `scripts/purge-consumed.sh` → **delete**
  (loop replaced by Task Scheduler; redeploy is a one-liner `git pull && uv tool install
  . --force --reinstall`; purge-queue gone).
- Repo `scripts/` keeps `run.sh`, `publish.sh`, `gmail-ingest.gs`.
- **Dotfiles** `bin/<host>/_obagent` (modeled on the existing `_orgav`): set HOME/PATH,
  source the shell rc (`OBAGENT_*`) + the gitignored `.zshenv.secret` (API keys + DS
  ids), then `exec sh .../scripts/run.sh`. DSM's bare env means the wrapper owns env
  setup, not run.sh.

### A4. Docs
- **`DEPLOY.md`**: rewrite around uv + Task Scheduler (the new shape is Track B
  below). Remove the container path table, the dubious-ownership troubleshooting, and
  the purge-job section. **Cloud Sync section simplifies**: leave deletions ON; both
  consume drain and export delete now work because obagent runs on the host.
- **`CLAUDE.md`** Deployment section: rewrite for native; remove the
  Dockerfile/compose/`loop.sh`-as-compose-command bullets, the "Consume-inbox drain"
  subsection, and the purge-queue line. Fix the Email-ingest **Drain** bullet — under
  native, `consume` **moves** the source and the host-side delete drains Drive (the
  *original* claim, true again).
- **`README.md`**: Deployment — replace the `docker compose` block with the uv flow;
  drop the purge-queue paragraph. Email-ingest — the "consume moves → drains" line is
  correct again.

### A5. `just check`, commit
Removing purge-queue drops its 5 tests (452 remain). One commit for the feature
removal, one for the Docker retirement + docs, one for the script rework — or grouped
as judged at commit time.

## Track B — NAS redeploy (the new DEPLOY.md)

Prereqs: SSH enabled; an admin user **U** that owns `/volume1/paperless` (run
everything as U so file ownership and uv's `$HOME` stay consistent).

1. **uv** (done): `curl -LsSf https://astral.sh/uv/install.sh | sh` → `~/.local/bin`.
2. **obagent repo as a real git clone** (not a folder-copy — a copy drags a foreign
   `.venv`/`.env`; a clone respects `.gitignore`):
   ```sh
   git clone <obagent-remote> /volume1/paperless/obagent
   cd /volume1/paperless/obagent
   uv tool install . --compile-bytecode      # `obagent` → ~/.local/bin, with Python 3.14
   ```
   (If keeping the existing dir: ensure it's a clone, `git pull`, `rm -rf .venv`.)
3. **Vault repo** clone (unchanged from today) + commit identity + dual push remotes.
4. **Deploy key, user-independent**: reuse `/volume1/paperless/ssh/id_ed25519` and pin
   it on the vault repo so push works regardless of which user/HOME runs the job:
   ```sh
   git -C /volume1/paperless/obsidian-vaults config core.sshCommand \
     'ssh -i /volume1/paperless/ssh/id_ed25519 -o UserKnownHostsFile=/volume1/paperless/ssh/known_hosts'
   ```
5. **Env in the zsh dotfile** (operator's choice — not a project `.env`): `export` the
   secrets + Notion DS ids + host path vars in `~/.zshenv.<host>` (sourced by
   `~/.zshenv`, which loads for **every** zsh invocation incl. non-interactive):
   ```sh
   export OBAGENT_VAULT=/volume1/paperless/obsidian-vaults/Paperless
   export OBAGENT_CONSUME=/volume1/gdrive/paperless/consume
   export OBAGENT_EXPORT=/volume1/gdrive/paperless/export
   export OBAGENT_MIN_AGE=60
   export NOTION_TOKEN=… MISTRAL_API_KEY=… OPENAI_API_KEY=… OBAGENT_NOTION_*_DS=…
   ```
   ⚠️ If this file is in a `.dotfiles` git repo, **gitignore it** (or source secrets
   from a separate untracked file) — it holds API tokens.
6. **Cloud Sync** `/volume1/gdrive` ↔ Drive, two-way, "remove deleted files" **ON**
   (default). No purge job. consume drains (move) and export-delete drains, both
   host-side.
7. **DSM Task Scheduler** → user-defined script, **user U**, every ~5 min. Launch
   **through zsh** so the dotfile env loads (Task Scheduler runs a bare env, not a
   login shell):
   ```sh
   export HOME=/volume1/homes/U          # so zsh finds ~/.zshenv
   exec zsh -c '/volume1/paperless/obagent/scripts/run.sh'
   ```
   zsh sources `~/.zshenv` → `~/.zshenv.<host>` → exported vars reach run.sh + obagent
   (also picks up `~/.local/bin` on PATH if the dotfile adds it; else export PATH here
   too). `run.sh` flocks against overlap and runs consume → notion sync → publish.
   (Alternative: a "boot-up" trigger launching `scripts/loop.sh` for a persistent loop
   — but the scheduled task is simpler and reboot-safe.)
8. **Decommission Docker**: stop + delete the `paperless-sync` Container Manager
   project and the `obagent` image. Remove the `/volume1/paperless/purge-queue` dir.

## Risks & gotchas

- **Task Scheduler sparse env**: it does **not** source shell dotfiles. The job sets
  `HOME` and launches via `zsh -c` so `~/.zshenv` → the host dotfile loads (step 7);
  vars must be `export`ed there, and PATH must include `~/.local/bin` (from the dotfile
  or exported in the command), or `uv`/`obagent` aren't found. Run as the **same user**
  that ran `uv tool install` (consistent `HOME` → uv's cached Python is reused).
  Sanity-check with `zsh -c 'env | grep OBAGENT'` as that user before scheduling.
- **git ownership**: running as the repo-owning user avoids the dubious-ownership
  guard entirely (no more `safe.directory '*'`). If a job ever runs as root over a
  user-owned repo, add `safe.directory` for root or just don't.
- **DSM upgrades** could disturb `~/.local`; recovery is re-running `uv tool install`.
- **min-age still matters** — a slow Cloud Sync download must settle before consume
  grabs it; keep `OBAGENT_MIN_AGE`.
- **uv self-update / Python pin**: `uv.lock` + `requires-python` pin deps; the managed
  3.14 is cached under `~/.local/share/uv`. Stable across runs.

## Verification (after cutover)

1. Drop a test PDF into Drive `consume/Documents/` → syncs down → consumed → **source
   gone from the NAS inbox AND from Drive** (no re-download). ← consume drain, native.
2. Delete a vault note (or `notion sync --prune` a trashed row) → next `export`
   dangling-cleanup unlinks the stale export → **gone from Drive**. ← export delete,
   native (the new bug, fixed).
3. `publish.sh` commits + pushes the vault cleanly (deploy key via `core.sshCommand`).

## Rollback

Docker artifacts live in git history; `git revert` the retirement commit and
`docker compose up -d --build` restores the old model. The vault, Notion link, and
shadow are untouched by this migration (deployment-only change).
