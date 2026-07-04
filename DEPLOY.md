# Deploying obagent on a Synology NAS (native — uv + Task Scheduler)

obagent runs unattended on the NAS as a plain host process — **no Docker**.
[`uv`](https://docs.astral.sh/uv/) installs a standalone Python 3.14 on the host, the
`obagent` CLI installs to `~/.local/bin`, and a DSM **Task Scheduler** job runs one
**consume → notion sync → publish** pass on an interval. The orchestration glue (the
entry script + env) lives in your **dotfiles**, not this repo.

> **Why native, not Docker?** Synology **Cloud Sync** propagates a delete to Google
> Drive only when it happens **on the host**. A delete from inside a container (consume
> moving a source out of the inbox, export removing a stale file) fires no event Cloud
> Sync's watcher receives, and on its next reconcile two-way Cloud Sync re-downloads the
> "missing" file — so the Drive consume inbox never drains and stale exports never
> disappear. Running on the host fixes both. (Earlier versions ran in Docker with an
> `OBAGENT_PURGE_QUEUE` workaround; `plans/2026-06-30-native-nas-migration.md` has the
> full rationale.)

The host folders obagent touches:

| Path | What it is |
|---|---|
| `/volume1/paperless/obsidian-vaults` | the **obsidian-vaults** git repo (`OBAGENT_VAULT` = its `Paperless/` subdir) |
| `/volume1/gdrive/paperless/consume` | inbox, per-type subdirs — Cloud Sync ↔ Drive (scans, phone, email) |
| `/volume1/gdrive/paperless/export` | export outbox — Cloud Sync ↔ Drive |
| `~/.ssh` (job user's home) | the SSH deploy key for `git push` |

Enable **SSH** (Control Panel → Terminal & SNMP) to run the commands below. Run them as
the user that will own the deployment (e.g. `junz`) — one user throughout means
consistent file ownership (no git "dubious ownership") and a stable `$HOME` for uv.

## 1. Install uv + Python 3.14
```sh
curl -LsSf https://astral.sh/uv/install.sh | sh   # uv -> ~/.local/bin (static musl binary)
. ~/.local/bin/env                                 # PATH for this session
uv python install 3.14
```

## 2. Clone the obagent repo + install the CLI
Use **git clone** (not a folder-copy — a copy drags a foreign `.venv`/`.env` and
arch-mismatched binaries):
```sh
git clone <your-obagent-remote> /volume1/paperless/obagent
cd /volume1/paperless/obagent
sh scripts/install.sh                             # `obagent` -> ~/.local/bin
obagent --help                                    # smoke test
```
Update later with a bare `git pull` — `scripts/run.sh` reinstalls the binary at
the start of the next pass whenever the checkout's HEAD has moved (its `sync
binary` step), so the installed `obagent` never lags the code. To update
immediately without waiting for a pass, run `sh scripts/install.sh` yourself
(it reinstalls and records the commit, so the next pass skips the redundant
rebuild).

## 3. Clone the vault repo
```sh
git clone git@github.com:junzh0u/obsidian-vaults.git /volume1/paperless/obsidian-vaults
cd /volume1/paperless/obsidian-vaults
# origin fans out to both remotes (SSH URLs, so the deploy key authenticates):
git remote set-url --add --push origin git@github.com:junzh0u/obsidian-vaults.git
git remote set-url --add --push origin git@gitlab.com:junzhou/obsidian-vaults.git
git config user.name "obagent"; git config user.email "obagent@junz.info"  # commit identity
```
Confirm it's on `main` tracking `origin/main`.

## 4. SSH deploy key (so the push authenticates)
Put the key in the job user's home `~/.ssh` — running natively as that user, git/ssh
finds it automatically (no `core.sshCommand` needed; the `_obagent` wrapper exports the
same `HOME`):
```sh
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
chmod 600 ~/.ssh/id_ed25519
ssh-keyscan github.com gitlab.com >> ~/.ssh/known_hosts   # so the non-interactive push
                                                          # doesn't hang on host verification
cat ~/.ssh/id_ed25519.pub
```
Add that public key as a **deploy key with write access** on **both** the GitHub and
GitLab `obsidian-vaults` repos.
- **Gotcha:** the key must be mode `600` (ssh refuses a group/world-readable key) and
  `~/.ssh/known_hosts` must hold the host keys, or a scheduled (non-interactive) push
  hangs. Both handled above.
- Only if the key *can't* live in the job user's home (shared path, or the job runs as a
  different user) do you need to pin it on the vault repo instead:
  `git -C /volume1/paperless/obsidian-vaults config core.sshCommand 'ssh -i <key> -o UserKnownHostsFile=<known_hosts>'`.

## 5. Directory layout
```sh
mkdir -p /volume1/gdrive/paperless/consume/Documents \
         /volume1/gdrive/paperless/consume/Receipts \
         "/volume1/gdrive/paperless/consume/Bank Statements" \
         /volume1/gdrive/paperless/export
```

## 6. Cloud Sync `/volume1/gdrive` ↔ Google Drive (two-way)
DSM → **Cloud Sync** → Google Drive → local path `/volume1/gdrive`, direction
**two-way**. One task covers both the **consume inbox** (scans/phone/email land in Drive
`paperless/consume/{type}/` and sync down) and the **export outbox** (vault PDFs sync
up). Leave **"Don't remove files in the destination folder…" OFF** — draining the inbox
and removing stale exports both rely on the NAS-side delete propagating up, and now that
obagent runs on the host, it does.

## 7. Environment
obagent reads its config from the environment. Put the **non-secret paths** in your
shell rc / dotfile and the **secrets** in a separate **gitignored** file:
```sh
# tracked dotfile (e.g. ~/.config/zsh/.zshenv.<host>):
export OBAGENT_VAULT=/volume1/paperless/obsidian-vaults/Paperless
export OBAGENT_CONSUME=/volume1/gdrive/paperless/consume
export OBAGENT_EXPORT=/volume1/gdrive/paperless/export

# GITIGNORED file (e.g. ~/.config/zsh/.zshenv.secret) — API tokens + Notion DS ids:
export NOTION_TOKEN=ntn_…
export MISTRAL_API_KEY=…
export OPENAI_API_KEY=…
export OBAGENT_NOTION_RECEIPT_DS=…
export OBAGENT_NOTION_DOCUMENT_DS=…
```
(`.env.example` lists every var obagent reads. A type whose `..._DS` is unset is simply
not synced.)

## 8. The Task Scheduler entry script
DSM Task Scheduler runs jobs with a **bare environment** — it does **not** source your
shell dotfiles. So the scheduled job is a small entry script (kept in your dotfiles)
that sets `HOME`/`PATH`, sources your rc **and** the secrets file, then hands off to the
pass logic in this repo (`scripts/run.sh`):
```bash
#!/bin/bash
export HOME=/volume1/homes/<you>
export PATH=$HOME/.local/bin:$PATH         # so `obagent` (uv tool) + `uv` resolve
source <your rc>        # -> OBAGENT_VAULT/CONSUME/EXPORT
source <your secrets>   # -> API keys + Notion DS ids (gitignored)
exec sh /volume1/paperless/obagent/scripts/run.sh
```
`scripts/run.sh` runs one guarded pass (a `flock` lockfile prevents overlap):
`obagent consume --min-age` → `obagent notion sync` → `scripts/publish.sh` (`obagent
export` → Drive, then a guarded `git fetch && merge --ff-only`, a machine `git commit`
of the vault changes, and `git push` to every remote). Keeping the pass in the repo
means it updates with `git pull`; the dotfiles wrapper only owns env setup.

Then DSM → **Control Panel → Task Scheduler → Create → Scheduled Task → User-defined
script**: **User** = you (the deployment owner), **Schedule** = repeat every ~5 min,
**Run command** = the entry script's full path.

## 9. Verify
Dry-run first (no writes):
```sh
obagent --vault /volume1/paperless/obsidian-vaults/Paperless notion sync --dry-run
```
Then drop a test PDF into Drive `paperless/consume/Documents/` (or NAS
`/volume1/gdrive/paperless/consume/Documents`), wait for it to sync down + settle
(`--min-age`) + the next tick, and watch it flow: a note appears in the vault, the
source **disappears from the inbox and from Drive** (drained host-side), and `publish`
commits + pushes. Confirm the source does **not** re-download. Run the entry script by
hand once (`bash <entry-script>`) to confirm it picks up the env before scheduling.

## 10. Point the scanner
Set the scanner's scan-to-folder (or SMB share) to
`/volume1/gdrive/paperless/consume/Documents` (or the matching type) — the same
Drive-synced inbox that scans, phone uploads, and email ingest all share. The
`--min-age 60` gate protects against grabbing a file mid-upload/sync.

## 11. (Optional) Email ingest
To also feed Gmail into this inbox, run `scripts/obagent-gmail-ingest/deploy.sh` (clasp —
creates the `obagent-gmail-ingest` Apps Script project and pushes the code; re-run to push
updates). Then in the Apps Script editor set the `CONSUME_FOLDER_ID` script property
to the Drive `consume/` folder id and run `install()` once (creates the labels + the
15-min trigger). It drops body PDFs + attachments into Drive
`consume/{Receipts,Documents}/`, which this same Cloud Sync pulls down. See
`plans/2026-06-29-email-ingest.md`.

## Updating later
```sh
cd /volume1/paperless/obagent && git pull --ff-only
```
`run.sh` reinstalls the binary on the next pass when HEAD has moved (its `sync
binary` step, keyed on a stamp in `.git/`), so `git pull` alone is enough. To
apply the update immediately instead of waiting for a pass, also run:
```sh
sh scripts/install.sh
```

## Troubleshooting
- **Nothing runs / `obagent: not found`** → the Task Scheduler job didn't get your env:
  it runs a bare shell and does **not** source dotfiles. Ensure the entry script sets
  `HOME` + `PATH` (incl. `~/.local/bin`) and sources both your rc and the secrets file.
  Test by hand as your user: `bash <entry-script>`.
- **Push fails / hangs** → deploy key not mode `600`, missing `~/.ssh/known_hosts` (a
  non-interactive push hangs on host verification), vault remote on `https://` instead of
  `git@`, the key not in the job user's `~/.ssh` (so git doesn't find it), or the key
  lacks write access.
- **`notion sync` does a full pass every run** ("no git repo visible") → git can't run on
  the vault. Usually fixed by running the job as the user that **owns** the vault repo (no
  dubious-ownership guard); otherwise `git config --global --add safe.directory '*'` for
  the job's user.
- **Nothing consumed** → check `/volume1/gdrive/paperless/consume/{type}/` has the file,
  it finished syncing, and it's older than `--min-age`.
- **Source re-appears on Drive after consume** → the delete happened off-host (you're
  still running in a container, or a different machine holds the inbox). obagent must run
  on the same host Cloud Sync watches.
- **Commit identity error** → set `user.name`/`user.email` in the vault clone (step 3) or
  `OBAGENT_GIT_NAME`/`OBAGENT_GIT_EMAIL` in the env.
