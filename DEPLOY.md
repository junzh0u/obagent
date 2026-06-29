# Deploying obagent on a Synology NAS (Container Manager + docker compose)

obagent runs unattended on the NAS: Container Manager builds the image from this
repo and runs `scripts/loop.sh` as an always-on service. Each pass does
**consume → notion sync → publish** (`scripts/run.sh`). The container reads four
host folders:

| Container path | Host path | What it is |
|---|---|---|
| `/vault` | `/volume1/paperless/obsidian-vaults` | the **obsidian-vaults** git repo root (`.git` + `Paperless/`) |
| `/consume` | `/volume1/paperless/consume` | scanner drop (per-type subdirs) |
| `/drive` | `/volume1/gdrive/paperless` | a Cloud Sync folder → Google Drive |
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
mkdir -p /volume1/paperless/consume/Documents /volume1/paperless/consume/Receipts \
         "/volume1/paperless/consume/Bank Statements"
mkdir -p /volume1/gdrive/paperless /volume1/paperless/ssh
```

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

## 5. Cloud Sync the export folder → Google Drive
DSM → **Cloud Sync** → Google Drive → local path `/volume1/gdrive/paperless`,
direction **Upload only**. This turns exported PDFs into browsable Drive files.

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
(60s) and `OBAGENT_INTERVAL` (300s) can stay.

## 8. Create the Container Manager Project
DSM → **Container Manager** → **Project** → **Create**:
- **Name:** `paperless-sync`
- **Path:** `/volume1/paperless/obagent`
- **Source:** "Use existing docker-compose.yml" → Next → it builds the image (first
  build ~1–2 min) and starts the service. `restart: always` keeps it looping.

Over SSH instead: `cd /volume1/paperless/obagent && sudo docker compose up -d --build`.

## 9. Verify
Dry-run first (no writes), then watch the live loop:
```sh
cd /volume1/paperless/obagent
sudo docker compose run --rm obagent obagent --vault /vault/Paperless notion sync --dry-run
sudo docker compose logs -f          # or Container Manager → Project → Logs
```
Look for the framed output: `✓ consume`, the sync timing lines, `✓ publish` with a
`committed …` line and an error-free push. Then drop a test PDF in
`/volume1/paperless/consume/Documents`, wait `min-age` + `interval`, and watch it flow.

## 10. Point the scanner
Set the scanner's scan-to-folder (or SMB share) to `/volume1/paperless/consume/Documents`
(or the matching type). The `--min-age 60` gate protects against grabbing a file
mid-upload.

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
- **Nothing consumed** → check `/consume` has the per-type subdirs and files are older than
  `OBAGENT_MIN_AGE`.
- **Commit identity error** → set `user.name`/`user.email` in the vault clone (step 2) or
  `OBAGENT_GIT_NAME`/`OBAGENT_GIT_EMAIL` in `.env`.
- **A failed pass** is loud in the log (`✗ … FAILED`) and exits non-zero.
