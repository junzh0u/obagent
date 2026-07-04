# Email → vault ingest (Gmail) — plan

**Status (2026-06-29): BUILT.** `scripts/gmail-ingest.gs` is written; obagent needs
no code change. A late revision (see next section) simplified the original design —
read the revision as the source of truth; the sections below it are preserved as
design history and rationale.

**Update (2026-07-03):** the script moved to `scripts/gmail-ingest/Code.js`, now a
clasp project (`obagent-ingest`) deployed with `scripts/gmail-ingest/deploy.sh`
instead of paste-deploy, with an `install()` function that creates the labels + the
15-min trigger. "Paste into a new Apps Script project" steps below are superseded.

## Revision (2026-06-29) — as built, simpler than planned

The deploy already routes everything through one two-way Google-Drive Cloud Sync
(`/volume1/gdrive` as the NAS root), and the consume inbox lives **inside** it at
Drive `paperless/consume/{type}/`. So the dedicated `EmailIngest/` folder, the
separate `/inbox-email/` mount + Cloud Sync task, and the extra `run.sh` line were
all dropped — email **reuses the existing consume inbox**:

- **Apps Script writes into `consume/<Type>/`**, not a flat `EmailIngest/`. It
  **routes by type** (`ROUTING_RULES` match `from`+`subject` → `Receipts`, default
  `Documents`) and get-or-creates the `<Type>` subfolder.
  Script property is **`CONSUME_FOLDER_ID`** (the Drive `consume/` folder id), not
  `DRIVE_FOLDER_ID`.
- **Drain** is the existing two-way sync: a file lands in Drive `consume/<Type>/` →
  syncs to the NAS consume mount → the normal `obagent consume` **moves** it into
  the vault → the local delete propagates back up → Drive folder empties. Same
  mechanism as any scan; nothing email-specific.
- **No obagent wiring.** No `OBAGENT_EMAIL_INBOX`, no extra `run.sh` step. compose
  just points `OBAGENT_CONSUME` at the Drive-synced consume folder
  (`/volume1/gdrive/paperless/consume:/consume`), which the existing `obagent
  consume` already loops over per type.
- Everything in *Dedup — robust design* below is unchanged and still applies.

**One-time setup (revised):**
1. Gmail **filter** → label real-document mail `obagent/inbox` (nested label;
   create `obagent/ingested` too).
2. Make sure Drive `paperless/consume/` is two-way Cloud-Synced to the NAS consume
   path and that `OBAGENT_CONSUME` points there. Copy that folder's Drive id.
3. Paste `scripts/gmail-ingest.gs` into a new Apps Script project; set the
   **`CONSUME_FOLDER_ID`** script property to that id; set a ~15-min time-driven
   trigger on `ingestEmail`; authorize Gmail + Drive. Edit `ROUTING_RULES` to taste.
4. Verify: label a test mail → confirm a PDF lands in Drive `consume/<Type>/`, syncs
   to the NAS, becomes a note, and disappears from Drive (drained).

---

### Original design (history)

The text below was the pre-build design (a dedicated `EmailIngest/` folder drained
to `/inbox-email/` by its own two-way Cloud Sync task, everything → `Documents/`).
Superseded by the revision above; kept for the rationale and rejected alternatives.

## Goal

Monitor a Gmail address and feed selected incoming mail into the obagent pipeline
as documents: render the **mail body to PDF** and pull every **attachment**, land
them in a dedicated NAS folder (`/inbox-email/`), and `consume` ingests them like
any scanner upload.

Key insight: this is a **feeder**, not an obagent-core change. obagent already has
the seams — `consume` takes an explicit source path, and `--min-age` gates slow
uploads. The pipeline, Fields, render, Notion sync are all untouched; the only new
*code* is one Apps Script. (`OBAGENT_CONSUME_PREHOOK` is still available as an
alt-path feeder, but the Cloud Sync route doesn't need it.)

## Decisions (made 2026-06-28)

- **Mailbox:** Gmail.
- **What to capture:** body PDF **and** attachments (both, every matching mail).
- **Route:** **Apps Script → Drive** (chosen over a self-hosted poller). Rationale:
  no Gmail credentials in the NAS container, rides the existing Drive sync, no
  Chromium added to the image. Body-PDF fidelity is basic, but low-stakes — the
  real document is the attachment, which is byte-perfect either way.
- **Scope:** **label-gated, not "all mail."** A Gmail filter routes only real
  documents into a label; the script processes that label. ("Every incoming email"
  would flood the vault with newsletter/marketing junk — each becomes an OCR'd
  document note.)
- **Drain (Drive → NAS):** **Synology Cloud Sync, two-way**, into a *dedicated*
  local folder (`/inbox-email/`), **not** the scanner inbox. Two-way is the right
  mode *because* `consume` **moves** source files by default (`ingest_source`
  moves into `_assets_/<sha>/src/`; `--keep-original` opts out) — so the local
  delete propagates back up and empties `EmailIngest/`. Dedicated folder keeps raw
  scanner scans off Google Drive (a two-way sync of the scanner inbox would push
  them up). Chosen over an rclone-`move` prehook: reuses Cloud Sync infra already
  trusted for export, no rclone token in the container.
- **No multi-source consume needed.** The per-type command already takes an
  explicit positional path (`resolve_sources` recurses), so `run.sh` just adds one
  line: `obagent document consume /inbox-email` after the main `obagent consume`.
  The dedicated email folder can be flat (no per-type subdirs). Multi-root support
  in the top-level `consume` was considered and dropped as YAGNI.
- **Dedup:** lives with the feeder — a Gmail label swap (`obagent-inbox` →
  `obagent-ingested`), backed by a per-message processed-ID set (see *Dedup —
  robust design*). obagent's content-addressed sha is a backstop, but only for
  byte-identical files (reliable for attachments, *not* for re-rendered body PDFs).
- **Routing:** everything → `Documents/` (re-file in vault/Notion later). Body PDF
  and each attachment become **separate** document notes (obagent is
  one-note-per-file).

## Data flow

```
Gmail (filter labels incoming mail `obagent-inbox`)
   │   ⟵ Apps Script, time-driven trigger every ~15 min
   ▼
For each thread labeled obagent-inbox (and not obagent-ingested):
   • render HTML body → body.pdf
   • pull each attachment
   • write all to Drive folder  EmailIngest/
   • swap labels: -obagent-inbox +obagent-ingested      ← dedup lives here
   ▼
Drive: EmailIngest/  "2026-06-28 0930 - ACME invoice.pdf", "… - invoice.pdf"
   │   ⟵ Synology Cloud Sync (two-way) → NAS local /inbox-email/
   ▼
/inbox-email/  → `obagent document consume /inbox-email` (moves files out)
   │            consume's local *delete* propagates back up via two-way sync
   ▼           → drains Drive EmailIngest/  ← this is the drain
vault → Notion + Drive export
```

## Build — one code artifact + config

The only code to write is the Apps Script. The drain is Cloud Sync (GUI, no
script) and consume already exists — `run.sh` just gains one line.

### 1. `scripts/gmail-ingest.gs` (Apps Script, checked into repo, paste-deployed)

Config consts at top:
- `SEARCH_QUERY = "label:obagent-inbox -label:obagent-ingested"`
- `DRIVE_FOLDER_ID = "<EmailIngest folder id>"`
- `LABEL_DONE = "obagent-ingested"`, `LABEL_INBOX = "obagent-inbox"`

Per matching message:
- Body → PDF: `Utilities.newBlob(message.getBody(), "text/html").getAs("application/pdf")`.
- Attachments: `message.getAttachments()` → each blob.
- Filenames: sanitized `YYYY-MM-DD HHmm - {subject}[ - {attname}].pdf` (strip
  `/`, control chars; cap length).
- Save all blobs to `DriveApp.getFolderById(DRIVE_FOLDER_ID)`.
- **Dedup (robust):** see *Dedup — robust design* below — per-message processed-ID
  set + `LockService`, with the label swap as a coarse filter.
- Wrap per-thread in try/catch so one bad message doesn't stall the batch; log
  failures (they keep `obagent-inbox` and retry next run).

Trigger: time-driven, ~every 15 min (Apps Script → Triggers).

### 2. Drain: Synology Cloud Sync task (no code)

- New Cloud Sync task: Google Drive `EmailIngest/` ⟷ NAS `/inbox-email/`,
  **bidirectional (two-way)**.
- **Leave "Don't remove files in the destination folder…" OFF** — the drain
  depends on the local delete (consume's move) propagating back up to Drive.
- Keep `--min-age` ≥ the sync's settle time so consume never grabs a file
  mid-download (avoids two-way conflict copies). `OBAGENT_MIN_AGE=60` is fine.

### 3. Wiring: one line in `run.sh` + a mount

- `run.sh`, right after the main consume:
  ```sh
  obagent document consume --min-age "$OBAGENT_MIN_AGE" "$OBAGENT_EMAIL_INBOX"
  ```
  (guard with `[ -n "${OBAGENT_EMAIL_INBOX:-}" ]` so it's a no-op when unset).
- `docker-compose.yml`: bind-mount the Cloud Sync target into the container and set
  `OBAGENT_EMAIL_INBOX=/inbox-email`. `.env.example`: document `OBAGENT_EMAIL_INBOX`.
- No `OBAGENT_CONSUME_PREHOOK`, no rclone — Cloud Sync handles Drive↔NAS.
- Docs: a short "Email ingest" section in `CLAUDE.md` / `README.md`.

## Dedup — robust design (why the bare label swap leaks)

The naive "`label:obagent-inbox -label:obagent-ingested`, then swap labels" works
for one-message-per-thread mail but double-exports in three cases:

1. **Thread-level labels + a reply.** `GmailApp.search()` returns *threads* and
   labels are *thread-level*; iterating `thread.getMessages()` re-exports old
   messages when a new reply re-applies `obagent-inbox` to the thread.
2. **Non-atomic export→label.** ~6-min execution cap; a timeout/error after the
   Drive write but before the label swap re-processes the thread next run.
3. **Body PDF isn't byte-stable.** `getAs("application/pdf")` may stamp a creation
   time, so the sha backstop won't dedup a re-rendered body (it *does* dedup
   identical attachments).

Robust version:
- **Per-message processed-ID set** is the source of truth: for each message, skip
  if `message.getId()` is already recorded; else export, then record it
  *incrementally* (so a crash only risks the one in-flight message). Store in
  `PropertiesService` (script properties), pruned to recent IDs — or a high-water
  `internalDate` watermark + a small same-second tie-break set (same shape as the
  Notion-sync watermark+shadow).
- **`LockService.getScriptLock()`** at entry to stop overlapping trigger runs.
- **Label swap** stays, but only to keep each query small — not for correctness.
- Layers: feeder ID-set (primary) → label query (small batches) → obagent sha
  (identical attachment bytes). Body-PDF dedup rests entirely on the ID set.

## One-time setup (manual, ~10 min)

1. Gmail **filter** → apply label `obagent-inbox` to the senders/subjects that are
   real documents. Create the `obagent-ingested` label too.
2. Create Drive folder `EmailIngest`; copy its folder ID into the `.gs`.
3. Paste `scripts/gmail-ingest.gs` into a new Apps Script project; set a
   time-driven trigger (~15 min). Authorize Gmail + Drive scopes.
4. Create a Synology Cloud Sync task: Drive `EmailIngest/` ⟷ NAS `/inbox-email/`,
   **two-way**, deletions propagate (advanced toggle OFF).
5. Add the `/inbox-email` bind-mount + `OBAGENT_EMAIL_INBOX` to compose and the
   extra `obagent document consume` line to `run.sh`; redeploy.
6. Verify: send a test mail to the labeled address → confirm a PDF lands in
   `EmailIngest/`, syncs to `/inbox-email/`, becomes a note in the vault, and the
   file disappears from `EmailIngest/` (drained).

## Open questions / revisit when building

- **Body PDF always, or only when no attachments?** Decided: always (user wants
  both). Revisit if body PDFs prove noisy.
- **Grouping:** body + attachments of one email become separate notes. If grouping
  matters, would need a multi-embed convention (obagent supports multi-embed per
  note for receipts; documents are one-per-file today).
- **Subject/sender → type routing** (e.g. statements → `Bank Statements/`): out of
  scope for v1; everything → `Documents/`. (If revisited: route in the `.gs` to
  per-type subdirs under `EmailIngest/` and add matching `obagent <type> consume`
  lines — still no obagent code change.)
- **Resolved — Drive→NAS drain:** Cloud Sync two-way (above), not rclone. Works
  because consume moves files; keeps the rclone token out of the container.
- **Resolved — multi-source consume:** not needed; explicit per-type `consume`
  path in `run.sh`.

## Rejected alternatives (and why)

- **Self-hosted Gmail poller in the container** (Python + IMAP/OAuth + headless
  Chromium): better body fidelity and lives in the repo, but needs a Gmail
  app-password/token in `.env` and Chromium in the image. Rejected for the
  no-creds-in-container + lighter-image win; body fidelity is low-stakes.
- **Inbound webhook** (Cloudflare Email Workers / SES→S3 / Mailgun): push not poll,
  most scalable, but needs a public endpoint and a domain you control. Overkill for
  a single Gmail address.
- **Multi-root support in top-level `consume`** (`OBAGENT_CONSUME` as an
  `os.pathsep` list, loop roots × types): ~20 lines + tests, cleaner single
  command. Dropped as YAGNI — there's exactly one extra source, and the per-type
  command already takes an explicit path, so `run.sh` covers it with one line and
  zero code.
- **rclone-`move` prehook** (Drive `EmailIngest/` → inbox): explicit/predictable
  drain, but needs an rclone gdrive token in the container. Dropped in favor of
  Cloud Sync, which is already trusted for export and keeps no token in the image.
- **Cloud Sync into the *existing* scanner inbox** (no dedicated folder): zero
  config, but two-way would push raw unprocessed scans up to Google Drive. Dropped
  for privacy; dedicated `/inbox-email/` instead.
