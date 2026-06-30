# Deploying obagent on a Synology NAS (Container Manager + docker compose)

obagent runs unattended on the NAS: Container Manager builds the image from this
repo and runs `scripts/loop.sh` as an always-on service. Each pass does
**consume → notion sync → publish** (`scripts/run.sh`). The container reads four
host folders:

| Container path | Host path | What it is |
|---|---|---|
| `/vault` | `/volume1/paperless/obsidian-vaults` | the **obsidian-vaults** git repo root (`.git` + `Paperless/`) |
| `/consume` | `/volume1/gdrive/paperless/consume` | inbox, per-type subdirs — Cloud Sync ↔ Drive (scans, phone, email) |
| `/export` | `/volume1/gdrive/paperless/export` | export outbox — Cloud Sync ↔ Drive |
| `/purge-queue` | `/volume1/paperless/purge-queue` | consume records consumed inbox paths here; a host job drains them |
| `/root/.ssh` | `/volume1/paperless/ssh` | the SSH deploy key for `git push` (read-only) |

The compose file itself lives with this repo at `/volume1/paperless/obagent`.
`OBAGENT_VAULT=/vault/Paperless`, so `/vault` must be the **repo root** (not the
`Paperless` subdir) — that's what makes the git-diff sync narrowing and the push work.

> Loop service vs Task Scheduler: this guide uses the **loop service** (simplest;
> one Project; continuous `docker compose logs`). To run discrete passes instead,
> skip the loop and have **Task Scheduler** run
> `docker compose run --rm obagent /app/scripts/run.sh` every N minutes — `run.sh`
> has a `flock` no-overlap guard and exits non-zero on failure (so DSM can email you).

Enable **SSH** (Control Panel → Terminal & SNMP) to run the commands below, or use
File Station + the Container Manager UI where noted. Commands assume `sudo`/admin.

## 1. Put the obagent repo on the NAS
The compose `build: .` needs this source on the NAS.
```sh
git clone <your-obagent-remote> /volume1/paperless/obagent
cd /volume1/paperless/obagent && git checkout feat/notion-sync   # or master once merged
```
(No remote yet? Copy the folder up with File Station / `rsync`.)

## 2. Clone the vault repo on the NAS
```sh
git clone git@github.com:junzh0u/obsidian-vaults.git /volume1/paperless/obsidian-vaults
cd /volume1/paperless/obsidian-vaults
# origin fans out to both remotes (SSH URLs, so the deploy key authenticates):
git remote set-url --add --push origin git@github.com:junzh0u/obsidian-vaults.git
git remote set-url --add --push origin git@gitlab.com:junzhou/obsidian-vaults.git
git config user.name "obagent"; git config user.email "obagent@junz.info"  # commit identity
```
Confirm it's on `main` tracking `origin/main`.

## 3. Create the directory layout
```sh
mkdir -p /volume1/gdrive/paperless/consume/Documents /volume1/gdrive/paperless/consume/Receipts \
         "/volume1/gdrive/paperless/consume/Bank Statements"
mkdir -p /volume1/gdrive/paperless/export /volume1/paperless/ssh /volume1/paperless/purge-queue
```
(`purge-queue` is **not** under `/volume1/gdrive` — it's container↔host only, never
synced to Drive. See "Draining the Drive consume inbox" below.)

## 4. SSH deploy key (so the container can `git push`)
```sh
ssh-keygen -t ed25519 -f /volume1/paperless/ssh/id_ed25519 -N ""
ssh-keyscan github.com gitlab.com > /volume1/paperless/ssh/known_hosts
chmod 600 /volume1/paperless/ssh/id_ed25519 /volume1/paperless/ssh/known_hosts
cat /volume1/paperless/ssh/id_ed25519.pub
```
Add that public key as a **deploy key with write access** on **both** the GitHub and
GitLab `obsidian-vaults` repos. The container mounts this folder at `/root/.ssh`;
git uses `id_ed25519` automatically.
- **Gotcha:** the private key must be mode `600` or SSH refuses it; `known_hosts`
  must exist or the push hangs on host verification. Both handled above.

## 5. Cloud Sync `/volume1/gdrive` ↔ Google Drive (two-way)
DSM → **Cloud Sync** → Google Drive → local path `/volume1/gdrive`, direction
**two-way**. One task covers both the **consume inbox** (scans/phone/email land in
Drive `paperless/consume/{type}/` and sync down to the NAS) and the **export
outbox** (vault PDFs sync up). Leave **"Don't remove files in the destination
folder…" OFF** — draining the inbox depends on a host-side delete propagating up to
Drive (see "Draining the Drive consume inbox" below).

> Why not just let `consume` delete the file? It can't reach Drive. obagent runs in
> the container; a delete there (move-out or `rm`) is real on disk but fires **no
> event Cloud Sync's watcher receives**, and on its next reconcile two-way Cloud Sync
> re-downloads the "missing" file. Only a **host-side** delete propagates. So obagent
> runs in copy mode and records consumed paths to the purge queue, and a host job does
> the deleting — set up next.

## 6. Create `.env`
```sh
cd /volume1/paperless/obagent && cp .env.example .env && vi .env
```
Fill the **secrets** (`NOTION_TOKEN`, `MISTRAL_API_KEY`, `OPENAI_API_KEY`) and the
**two data-source ids** (`OBAGENT_NOTION_RECEIPT_DS`, `OBAGENT_NOTION_DOCUMENT_DS`).
Leave the path vars commented — compose sets them. **Do not set
`OBAGENT_CONSUME_PREHOOK`** (the `nas-mount` prehook is for the Mac; the NAS has the
inbox mounted directly).

## 7. Check `docker-compose.yml`
The volume paths already match the table above; adjust only if yours differ, and
confirm `OBAGENT_VAULT: /vault/Paperless` matches your subdir name. `OBAGENT_MIN_AGE`
(60s) and `OBAGENT_INTERVAL` (60s) can stay.

## 8. Create the Container Manager Project
DSM → **Container Manager** → **Project** → **Create**:
- **Name:** `paperless-sync`
- **Path:** `/volume1/paperless/obagent`
- **Source:** "Use existing docker-compose.yml" → Next → it builds the image (first
  build ~1–2 min) and starts the service. `restart: always` keeps it looping.

Over SSH instead: `cd /volume1/paperless/obagent && sudo docker compose up -d --build`.

## 9. Draining the Drive consume inbox (host purge job)
Two-way Cloud Sync **cannot** drain the inbox on its own: a delete from inside the
container fires no event its watcher sees, and on reconcile it re-downloads the file
(see the note under step 5). So `OBAGENT_PURGE_QUEUE: /purge-queue/queue` (set in
compose) tells `consume` to **copy** each source into the vault and append its path
to the queue; a **host** job then deletes those inbox files — a host-side delete that
Cloud Sync *does* propagate up to Drive.

DSM → **Control Panel** → **Task Scheduler** → **Create** → **Scheduled Task** →
**User-defined script**:
- **User:** `root` (the inbox + queue are owned by the NAS/container user).
- **Schedule:** repeat every ~5 minutes (Daily, "Repeat every 5 minutes").
- **Run command:**
  ```sh
  sh /volume1/paperless/obagent/scripts/purge-consumed.sh
  ```
  The script reads the queue at `/volume1/paperless/purge-queue/queue` and `rm`s each
  recorded inbox file. Override `OBAGENT_PURGE_QUEUE_HOST` / `OBAGENT_INBOX_HOST` /
  `OBAGENT_INBOX_CONTAINER` in the command only if your paths differ from the defaults
  in the script header.

It only ever `rm`s files **under the configured inbox prefix** that obagent has
**already copied into the vault** — zero data-loss risk (the vault copy is the source
of truth), idempotent, and race-safe (it atomically claims a batch, so paths queued
mid-run are handled next time).

## 10. Verify
Dry-run first (no writes), then watch the live loop:
```sh
cd /volume1/paperless/obagent
sudo docker compose run --rm obagent obagent --vault /vault/Paperless notion sync --dry-run
sudo docker compose logs -f          # or Container Manager → Project → Logs
```
Look for the framed output: `✓ consume`, the sync timing lines, `✓ publish` with a
`committed …` line and an error-free push. Then drop a test PDF into Drive
`paperless/consume/Documents` (or NAS `/volume1/gdrive/paperless/consume/Documents`),
wait for it to sync + `min-age` + `interval`, and watch it flow. The source stays in
the inbox briefly, then the host purge job (step 9) `rm`s it and it **disappears from
Drive** — confirm it does *not* re-download.

## 11. Point the scanner
Set the scanner's scan-to-folder (or SMB share) to
`/volume1/gdrive/paperless/consume/Documents` (or the matching type) — the same
Drive-synced inbox that scans, phone uploads, and email ingest all share. The
`--min-age 60` gate protects against grabbing a file mid-upload/sync.

## 12. (Optional) Email ingest
To also feed Gmail into this inbox, deploy `scripts/gmail-ingest.gs` as an Apps
Script (set its `CONSUME_FOLDER_ID` to the Drive `consume/` folder id, ~15-min
trigger). It drops body PDFs + attachments into Drive `consume/{Receipts,Documents}/`,
which this same Cloud Sync pulls down. See `plan-email-ingest.md`.

## Updating later
```sh
cd /volume1/paperless/obagent && git pull
sudo docker compose up -d --build    # or Container Manager → Project → Build, then Up
```

## Troubleshooting
- **Push fails / hangs** → key not mode `600`, missing `known_hosts`, vault remote on
  `https://` instead of `git@`, or the deploy key lacks write access.
- **`notion sync` does a full pass every run** ("no git repo visible") → the container
  can't run git on the vault. Either `/vault` isn't the repo **root** (it must be, not the
  `Paperless` subdir), or git's **dubious-ownership** guard is tripping because the mounted
  files are owned by the NAS user while the container runs as root. The image trusts the
  mount via `git config --system --add safe.directory '*'` (rebuild if you're on an older
  image). The same guard would also block the machine commit + push.
- **Nothing consumed** → check `/consume` (Drive `paperless/consume/`) has the per-type
  subdirs, and files have finished syncing and are older than `OBAGENT_MIN_AGE`.
- **Commit identity error** → set `user.name`/`user.email` in the vault clone (step 2) or
  `OBAGENT_GIT_NAME`/`OBAGENT_GIT_EMAIL` in `.env`.
- **A failed pass** is loud in the log (`✗ … FAILED`) and exits non-zero.
