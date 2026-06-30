# Paperless: NAS auto-ingest + two-way Notion sync — Design

> **Archived design note (2026-06).** Records the *why* behind the NAS-auto-ingest +
> two-way Notion sync design, and the alternatives rejected along the way. A
> point-in-time snapshot, not living docs — for current state see `CLAUDE.md`
> (structure & conventions) and `DEPLOY.md` (NAS deployment). This superseded the
> original "NAS → Notion Ingest Watcher" idea (a NAS daemon that uploaded raw scans
> and let **Notion AI** do the OCR/extraction), abandoned after a step-back — see §17.
>
> **Where it landed:** keep the obagent **vault as the source of truth and the
> OCR/LLM pipeline**; move *consume* onto the always-on **NAS** so ingestion is
> automatic; add a **two-way sync with Notion** so documents can be browsed and
> **edited on a phone**, edits flowing back into the vault's frontmatter override layer.
>
> **As built, a few shapes differ from the spec below:** the monitor and publish are
> **shell** (`scripts/loop.sh` / `run.sh` / `publish.sh`), not `obagent monitor` /
> `apply` commands; **backfill** ran as a one-off function, not a CLI command;
> deployment is **docker compose** (Container Manager). The design intent stands.

---

## 1. Background & how this design evolved (the initiatives)

This document went through several full pivots. They're recorded here because the
*reasoning* matters as much as the destination, and because every rejected idea is
a trap we don't want to re-walk. The detailed rejections are in §17; this is the
narrative.

1. **Original idea (2026-06-27):** a crash-safe NAS daemon watches a folder,
   uploads each new scan to Notion with the file attached, and **Notion AI
   Autofill does the OCR + field extraction**. Notion becomes the source of truth;
   obagent's pipeline and the Obsidian vault get retired; Drive becomes a cold
   backup of originals.

2. **First wrinkle — slow scanner uploads.** The scanner→NAS copy is slow, so a
   naive "size stable for 10 s" gate could grab a half-written file. → we hardened
   the stability gate into a longer **quiescence gate**. (This idea *survives* —
   see §13.)

3. **Second wrinkle — Notion's trigger model.** Notion automations **cannot**
   trigger on a file being attached, only on a **property change**. We designed a
   two-step write (attach file, then PATCH a `Status` property to fire the agent)
   and the user confirmed a custom Notion AI agent *works* and that property-change
   triggering *works*.

4. **The step-back — "what do I actually gain vs. obagent? Is it worth it?"** We
   decomposed the vision into four independent axes:
   - **A.** Always-on unattended ingestion on the NAS — *real value*.
   - **B.** Notion as a single source of truth (stop reconciling stores) — *real value*.
   - **C.** Notion (not obagent) does the OCR/extraction — *the risky part*.
   - **D.** Drive as a cold backup fed at ingest — *real value*.

   Almost all the risk lives in **C** (black-box extractor, the WAF that blocks
   ~0.3% of files on the upload API would become an *extraction* tax, no API
   trigger, unproven quality at scale), and **C is the least valuable** part.

5. **Driver clarification.** The user's real pains were **"maintaining 3 stores"**
   and **"repeated re-sync waste"** — *not* OCR/LLM dollar cost and *not* upload
   throughput. Since cost wasn't the driver, **axis C earns nothing** → drop it.
   Keep obagent's proven OCR/LLM brain.

6. **The propagation problem.** "If I edit in Notion, how does that reach Google
   Drive?" Today the edit→publish loop runs *through* the `.md`. Moving the edit
   surface off the `.md` breaks it. This is what forced the two-way sync design.

7. **The real, current workflow (finally stated):**
   `scan → NAS → (manual) obagent on laptop → vault → edit metadata → (manual)
   batch-publish to 3 git remotes (GitHub, GitLab, NAS) + Google Drive`.
   **Two concrete dislikes:** the **Obsidian vault is too large for a phone**, and
   the **consume step is manual**. Plus a firm want: **edit in Notion**.

8. **Inspecting the vault changed everything.** The vault's structure is genuinely
   good (content-addressed assets, **per-model OCR/LLM caches** that make iterating
   the OCR model / prompt cheap), and obagent's `render` **preserves manually-edited
   frontmatter by default**. That means the `.md` frontmatter is already a sticky
   per-document **override layer** — exactly what a sync needs. So we *keep* the
   vault as SOR and make Notion a **two-way editing projection** whose edits land in
   that override layer.

The remaining design (joins, multi-asset notes, the sync algorithm) was worked out
from there; see §8–§12.

---

## 2. Current workflow (as-is)

```
scanner ─► NAS share ─► (manual) `obagent <type> consume` on laptop
                                   │  PDF → ingest(sha256 dedup) → ocr(Mistral) → llm(OpenAI) → render(.md)
                                   ▼
                          Obsidian vault (~/Workspace/obsidian-vaults/paperless)
                                   │  edit metadata via obagent alias/rename + (it turns out) frontmatter edits
                                   ▼
                          (manual) batch publish ──► GitHub  (.md, version-controlled)
                                                 ├─► GitLab  (redundant git mirror)
                                                 ├─► NAS     (redundant git remote)
                                                 └─► Google Drive
```

- **Stores today:** the **vault** (SOR + edit surface), **3 git remotes** (GitHub,
  GitLab, and a NAS bare repo — all for redundancy), and **Google Drive** (published
  copy; doubles as a *simplified mobile UI* — file preview on the phone). (A one-off
  importer also pushed everything into Notion once, in 2026-06; that copy is stale.)
  *In the new design the NAS git remote is dropped — the vault's working copy moves
  onto the NAS, so a NAS bare repo would be the same failure domain (§12).*
- **Pain points:** (1) vault too big for Obsidian mobile; (2) consume is manual;
  (3) no good way to edit on the phone.

---

## 3. What we keep (and why it's worth keeping)

These are the things the user explicitly values; the design must not regress them.

- **The vault's content-addressed structure.** Each document is keyed by the
  **sha256** of its original file, with **per-model caches** for OCR and LLM output.
  This is what makes "iterate the OCR model / prompt and re-derive" cheap and
  non-destructive. See §7.
- **obagent's proven OCR + LLM pipeline** (Mistral OCR + OpenAI extraction over
  ~4,000 files). No reason to replace it with an unproven black box.
- **`render` preserving manual frontmatter edits** — the built-in override layer
  (render.py:159–167, and `consumed_at` preserved at render.py:170–181).
- **Git as a versioned, open-format archive** of the **entire vault** (`.md` *and*
  the `_assets_` originals + OCR/LLM caches — GitHub already holds everything) — this
  *is* the durable, no-lock-in backup, which matters once edits can originate in Notion.
- **Not relying on Notion for binaries** — Notion is a poor binary system-of-record
  (temporary signed URLs, no clean export, WAF blocks ~0.3% of upload-API files). In
  Notion the attached scan is just a *preview*; the durable copy lives in git.

---

## 4. Goals & non-goals

**Goals**
- Ingestion (consume) runs **automatically** on the always-on NAS — laptop out of
  the loop.
- Documents are **browsable and editable on a phone** via Notion.
- Edits made in Notion **propagate back** into the vault and onward to GitHub/Drive.
- The vault remains the **source of truth** and the **iterable pipeline**.
- Publishing (to GitHub + Drive) becomes **automatic** too.

**Non-goals / explicit exclusions**
- Notion does **not** do OCR or extraction (axis C, rejected — §17).
- No standalone "notion-ingest" NAS daemon separate from obagent (rejected — §17).
- No custom web UI (rejected — §17).
- Deletes are **not** auto-propagated from Notion to the vault (safety — §11).
- **Bank Statements are not synced to Notion** (decided). They're still auto-consumed
  into the vault and published to GitHub/Drive — just no Notion row. Only **Receipts**
  and **Documents** sync to Notion. (Sync is per-type: a type with no Notion DB in
  config is consume + publish only.)

---

## 5. Target architecture

```
                         ┌──────────────────────── NAS (always on, Docker) ───────────────────────┐
 scanner ─► NAS inbox ─► │  [quiescence gate] ─► obagent consume (ocr→llm→render) ─► VAULT (git)   │
                         │                                                              │           │
                         │   ┌── forward register (create row + attachments, write notion_id) ─────┘ │
                         │   ▼                                                                       │
                         │  NOTION  ◄────────── one row per note, all files attached, notion_id link │
                         │   ▲   │                                                                   │
                         │   │   └── two-way field merge (3-way vs SHADOW) ─► .md frontmatter        │
                         │   │                                          └─► obagent render ─► git    │
                         │   │                                                                       │
                         │  edit on phone / desktop                                                  │
                         │                                                                           │
                         │  publish ─► GitHub + GitLab (full vault) ─► Drive (browsable PDFs via export)│
                         └───────────────────────────────────────────────────────────────────────────┘
```

Flows, all running on the NAS:

1. **Auto-consume** (new scans → vault) — §13.
2. **Forward register** (vault → Notion: create rows, attachments, `notion_id`) — §10.
3. **Two-way field merge** (reconcile field edits in *both* directions) — §11.
4. **Publish** (vault → GitHub + GitLab + Drive) — §12.

The **vault is canonical** (the OCR/LLM pipeline + the published artifact). But
fields are **editable on both sides** — Obsidian *and* Notion — so the merge (§11)
is a real bidirectional reconciliation against a stored base (the **shadow**), not a
one-way push. The vault is what gets published.

---

## 6. Components

1. **Quiescence gate** — decides when a scanned file is fully written (§13).
2. **obagent consume** (unchanged pipeline) — `ingest → ocr → llm → render`, run
   automatically on the NAS.
3. **Forward register** — create a Notion row for each new note (write `notion_id`
   back + initialize the shadow); keep attachments/`Sha` current (§10).
4. **Two-way field merge** — reconcile field edits on *either* side via a 3-way merge
   against the shadow; write the winning value into the `.md` override layer and/or
   Notion, re-render (§11).
5. **Publisher** — commit the vault and `git push` to GitHub + GitLab; run
   `obagent export` → Cloud Sync to Drive (browsable PDFs) (§12). Replaces the manual
   batch-publish.
6. **Sync state** — the per-note `notion_id` (in frontmatter), the **shadow**
   (`notion_id → base field values`), and a Notion watermark + last-sync git commit
   (both narrowing hints only) (§8, §11).

obagent stays the engine; items 3–5 are the new surface (most of item 5 already
exists as `commands/export.py`).

---

## 7. Vault structure (reference)

Path: `~/Workspace/obsidian-vaults/paperless` (will move to the NAS — §15).

```
paperless/
  Receipts/          <YYYY-MM-DD - Merchant - $Amount>.md
  Bank Statements/   <YYYY-MM-DD to YYYY-MM-DD - Bank - Account - LastFour>.md
  Documents/         <YYYY-MM-DD - Title>.md
  <type>/_assets_/<sha256>/
      src/   original.pdf|jpg, metadata.json   (original_filepath, sha256, consumed_at)
      ocr/   mistral-ocr-latest.json, .txt      ← OCR output, keyed by MODEL
      llm/   gpt-5-mini.json                     ← extraction output, keyed by MODEL
  .obagent/  {merchant,bank,people}-{aliases,pinned}.json
  <type>.base   Obsidian "Bases" table views (the current desktop DB UI)
```

- **Pipeline:** `PDF → ingest (sha256 dedup) → ocr (Mistral) → llm (OpenAI) →
  render (.md note)`. Run per-type via `obagent <type> consume ./inbox`.
- **A note embeds its asset(s)** via `![[_assets_/<sha>/src/original.pdf#height]]`
  (+ a `metadata.json` embed). One note can embed **several** assets (§9).
- **Frontmatter schemas:**
  - Receipts: `merchant, date, total, consumed_at`
  - Bank Statements: `bank_name, date, end_date, account_name, account_number, consumed_at`
  - Documents: `title, date, tags, people, consumed_at` + a `> [!summary]` body callout
- **`render` override semantics** (the linchpin, render.py):
  - Default: `fields.apply_frontmatter(existing_fm)` — **existing frontmatter wins**
    over fresh LLM output (manual/Notion edits are sticky across re-renders).
  - `--overwrite`: LLM wins (`fill_gaps`), only fills missing fields.
  - `--overwrite-fields a,b`: only those fields take new LLM data.
  - `consumed_at` is read from existing frontmatter and carried forward.
  - Render statuses: `created / updated / renamed / appended / unchanged / skipped`.
- **Aliases** normalize names (e.g. `Costco Wholesale → Costco`) at render time;
  currency is normalized (`USD$88.41 → $88.41`, `RMB 224.00 → ¥224.00`). The
  per-document frontmatter is a *further* override on top of aliases.

---

## 8. The join: `notion_id` in vault frontmatter

The link between a vault **note** and its **Notion row** is an explicit pointer
stored on **both** ends. This is more robust than inferring identity from content.

- **Vault side:** add `notion_id: <page-uuid>` to the note's frontmatter.
  - **Preserved across re-renders** the same way `consumed_at` already is (small
    obagent change — §14). So model iteration never drops it.
  - One frontmatter per note ⇒ exactly one `notion_id` per Notion row (clean even
    for multi-asset notes — §9).
- **Notion side:** the row *is* its page id; additionally keep a **`Sha` text
  property** holding the note's sha set (newline-joined) — used only as a
  **create-crash dedup guard** (see below) and human reference.

Why frontmatter, not a sidecar `.json` or an external ledger:
- One-per-note (matches "row = note"); no "which asset is primary?" ambiguity.
- Git-versioned, travels with the note, self-describing — no separate index to keep
  consistent or back up.
- Makes **forward dedup local**: a note with `notion_id` is "already pushed"; a note
  without it is new — **no Notion query needed** to decide.

**Only `notion_id` goes in frontmatter — no sync timestamps.** `notion_id` is written
*once* and is stable, so it belongs with the note. Anything that changes every sync
(a `last_synced` time, the base values) must **not** live in frontmatter: it would
rewrite the note on every run → git/publish churn, and a `last_synced` in the file
would be *circular* (writing it bumps the mtime that change-detection reads). All
mutable sync bookkeeping lives in the **shadow** state file instead (§11). Because the
**NAS is the sole sync runner**, the shadow is single-writer — no concurrent-write or
git-merge worry.

**Create-crash dedup guard.** The only failure window is: create the row → crash
*before* writing `notion_id` back. Next run would create a duplicate. Guard: when
`notion_id` is absent, before creating, query Notion for a row whose `Sha` contains
this note's sha(s); if found, adopt it instead of creating. This is the sole reason
`Sha` is mirrored into Notion.

---

## 9. Notion DB design (row = note, not sha)

A note↔asset relationship is **many-to-many** (rare): **39 of 5,691 notes (~0.7%)**
embed multiple assets, created when several scans render to the same
`date · merchant · total` title and obagent merges their embeds (the `appended`
render path). Example: `2022-09-29 - United Airlines - $0.00` embeds **3** scans
(2 PDFs + 1 JPG). A sha can in principle also appear in more than one note.

**Therefore a Notion row represents a NOTE, not a sha:**

- **One row per `.md`.** Carries the editable metadata (the unit you edit on the
  phone), which is shared across the note's assets by design.
- **Attach all the note's files** to the `File` property — Notion's `File` is
  natively a list (`{"files":[…]}`), so a 3-scan note simply holds 3 attachments.
- **`Sha` is a plain `text` property** holding the sha set (newline-joined).
  - **Gotcha:** do *not* make `Sha` a multi-select — 64-char hashes would spawn
    thousands of junk options. Text supports a `contains` filter for the
    crash-guard lookup.
- The **join is note-level** (`notion_id`), so both edge cases dissolve: a 3-sha
  note is one row; a shared sha still maps cleanly because we join note↔row, never
  sha↔row.

**Field maps** (vault frontmatter ↔ Notion property; conversions matter — §11):

| Type | Vault frontmatter | Notion property | Direction / notes |
|---|---|---|---|
| Receipts | `merchant` | `Merchant` (text) | two-way (merge) |
| | `date` (`YYYY-MM-DD` str) | `Date` (date) | two-way; type conversion |
| | `total` if USD (`$22.92`) | `Total` (number $) | two-way; string ↔ number |
| | `total` if non-USD (`¥9,860`) | `Non-USD Total` (text, e.g. `JPY 9,860`) | two-way; **symbol↔ISO** (caveat: vault `¥` is ambiguous JPY/CNY — disambiguate from the LLM extraction, not the rendered string) |
| Documents | `title` | `Name` (title) | two-way |
| | `date` | `Date` (date) | two-way |
| | `tags` (list) | `Tags` (multi-select) | two-way |
| | `people` (list) | `People` (multi-select) | two-way |
| | `summary` (body callout) | `Summary` (text) | two-way |
| **both** | `consumed_at` (ISO datetime) | `Consumed At` (date + time) | **one-way** (vault → Notion); machine-set, never edited, not in the merge |
| Bank Stmts | — | — | **not synced to Notion** (consume + publish only) |

**`Name` is handled per type:**
- **Receipts** — the `.md` has *no* title field, and Notion's `Name` is a **formula**
  (composed from Merchant/Date/Total). **Not synced** — edit via `Merchant`/`Total`/
  `Date`; the formula and the vault filename (`make_title`) each regenerate.
- **Documents** — the `.md` `title` field maps **two-way to Notion's `Name`** (the
  title property *is* the editable document title).

**Required Notion schema changes** (Receipts + Documents): add **`Sha` (text)** and
**`Consumed At` (date + time)** to **both** — nothing else. Documents needs no separate
title column (it uses `Name`); Receipts already has `Total` + `Non-USD Total`. The
existing field-map targets — Receipts `Merchant`/`Total`/`Non-USD Total`, Documents
`People`/`Tags`/`Summary` — are filled by obagent (not Notion AI).

---

## 10. Forward register (vault → Notion: structural)

This is the **structural** half — creating rows and keeping files attached. It does
**not** decide field values for existing notes; all field reconciliation (in *both*
directions, including obagent's own `--overwrite-fields` re-renders) goes through the
merge in §11. Runs per **note** (not per asset).

For each note in the vault:
1. If `notion_id` present → it's linked. Update the row's *attachments and `Sha`* only
   if the asset set changed (e.g. a scan was appended). Field values are left to §11.
2. If `notion_id` absent → it's new:
   a. Crash-guard: query Notion `Sha contains <sha>`; if a row exists, adopt its id.
   b. Else **create** the row: title + initial mapped fields + all files attached +
      `Sha`. Use the proven uploader from `reference_importer.py` (multipart >20 MB,
      429/CDN/WAF retries, 60 s timeout, `File` name ≤100 UTF-16, rich_text ≤2000).
   c. **Write the new `notion_id` into the note's frontmatter** (`git commit`) **and
      initialize the shadow** with the note's current field values (so the next merge
      sees a base where both sides already agree).
3. WAF-blocked file upload (~0.3%): create the row *without* that attachment (data
   still present from the vault); the original is safe in the vault/git. Not a
   data-loss event — at worst a missing phone preview. (No `scan_pending`/quarantine
   machinery needed, unlike the original design.)

---

## 11. Two-way field merge (3-way against the shadow)

Fields are editable on **both** sides — Obsidian *and* Notion — so a two-way diff
("Notion vs frontmatter") isn't enough: it can't tell *which* side changed. We need a
**common base** and a git-style **3-way merge**.

### The shadow (the merge base)
Keep, per record, the field values **as of the last successful sync** — the *shadow*.
- Store: a single state file `.obagent/notion-shadow.json` → `notion_id → {field:
  base_value, notion_last_edited, synced_at}`, values stored **canonical/normalized**.
- Single-writer (the NAS runs all syncs), git-versioned, a few hundred KB.
- **Not** in frontmatter (would churn the note every sync — §8).

### Algorithm (each run, on the NAS)
1. **Narrow candidates** (optimization only):
   - Notion side → rows with `last_edited_time >= watermark`.
   - Vault side → `git diff --name-only <last-sync-commit> HEAD` (catches even
     uncommitted Obsidian edits, since it diffs the working tree).
   - Candidates = union, joined by `notion_id` (build a `notion_id → note` index).
2. **Per candidate, per field**, normalize all three to canonical values, then:

   ```
   base   = shadow[notion_id][field]
   vault  = normalize(frontmatter[field])
   notion = normalize(notion_row[field])

   if vault == notion:   new = vault                 # agree (covers no-op echoes)
   elif vault == base:   new = notion → write VAULT  # only Notion changed
   elif notion == base:  new = vault  → write NOTION # only vault changed
   else:                 new = resolve(vault, notion)# CONFLICT → write the loser
   shadow[...][field] = new                          # advance the base
   ```

   This is **field-level**: editing `merchant` in Notion and `date` in Obsidian on the
   *same* receipt between syncs both survive — different fields, no conflict.
3. **Apply vault writes** through `obagent <type> apply <note> --field=…` (uses
   `fields_class`/`format_frontmatter`/`make_title` so currency formatting, list
   fields, and the `date·merchant·total` **filename rename** are correct), then
   `obagent render` (preserves frontmatter), then `git commit` → publish (§12).
   **Apply Notion writes** via the importer-core PATCH (with the same normalization).
4. **Advance hints:** watermark → `max(last_edited_time)` of processed rows (Notion's
   clock, never local `now()`, using `>=`); last-sync commit → current `HEAD`.

### Conflict resolution — LWW + log (decided)
True conflict = same field changed on **both** sides to **different** values (rare).
`resolve()` = **last-writer-wins by timestamp** — Notion `last_edited_time` vs the
vault file's git-commit time — and **log it** so it's reviewable. This is the chosen
policy; it's cheap and conflicts are rare and low-cost to re-fix by hand. (A
machine-tracked `conflicts` report was considered and deemed unnecessary — §17.)

### Why this is robust
- **Echo loop is a no-op.** Forward register / a prior merge bumps `last_edited_time`;
  next run the row is a candidate, but `vault == notion`, so nothing happens.
- **Hints are disposable.** Lose the watermark or commit pointer → a full pass (every
  linked record vs. shadow) self-heals. Minute-granularity, mid-run crashes, and
  no-op "noise" edits all degrade to re-check-and-no-op. **Correctness lives in the
  shadow comparison; the watermark/git-diff are pure narrowing.**
- **No false churn.** Comparing canonical *values* (not mtimes) means an unchanged
  re-save on either side produces no write.
- **Model iteration is preserved.** `obagent render --overwrite-fields total` changes
  the vault value → the merge sees `vault != base, notion == base` → pushes the better
  extraction to Notion. Default re-renders keep your corrections (frontmatter wins).

### Deletes
**Not auto-propagated** either direction. A deleted vault file (seen in `git diff`) or
an archived Notion row is **flagged/logged**, never mirrored — removal happens only
through obagent. (Avoids a stray UI deletion nuking an original.)

---

## 12. Publish (vault → GitHub + GitLab + Drive)

Replaces the manual batch-publish; triggered after any vault change (consume or
reverse-sync commit).

- **GitHub + GitLab** = two **off-site** redundant git mirrors of the **entire vault**
  — `.md` *and* the `_assets_` originals + OCR/LLM caches. **GitHub already holds
  everything**, so git *is* the complete versioned, open-format, no-lock-in backup.
  Publish = `git push` to both.
  - **Drop the old NAS git remote.** The vault's canonical working checkout now lives
    *on the NAS* (§15), so a bare repo also on the NAS is the same failure domain — no
    redundancy. Distinct-domain copies remain: NAS (working) + GitHub + GitLab = 3.
- **Google Drive — KEPT** (decided), for two reasons: (a) provider-diversity
  redundancy, and (b) a **human-browsable PDF archive** — the vault's originals live at
  `_assets_/<sha>/src/original.pdf` (content-addressed, *not* browsable by date/
  merchant), so Drive is where you actually flip through receipts.
  - **Fed by `obagent export`** (the existing `commands/export.py`), which copies each
    original out of the sha tree into a **renamed, date-bucketed** layout —
    `YYYY/YYYY-MM/<date> - merchant - total>.pdf` — idempotently (size+mtime check,
    prunes deletions). That export root is what **Cloud-Syncs to Drive** (no Drive API,
    no WAF). *Not* a raw sync of `_assets_` (that would just replicate the unbrowsable
    hash layout).

---

## 13. Auto-consume on the NAS + quiescence gate

**Auto-consume** kills the "manual consume" pain: the **`obagent monitor`** loop (§14)
runs on the always-on NAS **in a Docker container** (Container Manager, `restart:
always` — decided), watching the scan inbox and consuming each file as it lands. The
laptop is out of the ingest loop entirely.

**Quiescence gate** (hardened because the scanner→NAS upload is slow and can stall
mid-transfer, so a short window would grab a partial file):

- Per candidate (skip `ignore_globs`): track `(size, mtime)`; reset an
  `unchanged_since` timestamp whenever either changes.
- **Ready** when `(size, mtime)` unchanged for ≥ `stable_secs` (default **60 s**)
  **and** seen across ≥ `stable_polls` consecutive polls.
- Optional `use_lsof`: also require no open write handle (the SMB/FTP service on the
  NAS holds the fd during transfer).

```toml
poll_interval = 15
stable_secs   = 60
stable_polls  = 3
ignore_globs  = [".*", "*.tmp", "*.part", "*.filepart", "*.crdownload", "~$*"]
```

(Inotify/`CLOSE_WRITE` is a later optimization; polling is robust over SMB.)

---

## 14. obagent changes — command surface & code home

All Notion logic lives **inside obagent** (decided): the sync reuses
`fields_class`/`format_frontmatter`/`make_title`/`index_existing_notes`/render/ledger,
so a separate tool would import all of obagent anyway — coupling without separation.
One tool to deploy on the NAS; symmetric with the existing `obagent export`.

### New commands
| Command | Role |
|---|---|
| `obagent monitor` | The always-on NAS loop (decided) — a **thin scheduler**, not new logic. Polls the inbox with the quiescence gate, then sequences `consume → notion sync → export → git push` at appropriate cadences, with **per-step error isolation** (a Notion outage fails only that cycle's `sync`) and clean **SIGTERM** shutdown. Invokes the same code paths as the one-shot commands. |
| `obagent notion backfill [--dry-run]` | One-time reconciliation (§18): match existing rows (Receipts by `Name`, Documents by `(Name, Date)`), write `notion_id`/`Sha`/`Consumed At`, init the shadow, create missing rows, log orphans. **`--dry-run` = the read-only match report** (no writes). |
| `obagent notion sync [--dry-run]` | Steady-state pass: register new notes + two-way merge edits (§10–§11). The loop calls this. `--dry-run` = the diff report. |
| `obagent <type> apply <note> --field=…` | Write field overrides into a note's frontmatter (`fields_class`/`format_frontmatter`/`make_title`, then render). The reverse-merge vault writes call this. |

### Core change (must precede backfill)
- **Preserve `notion_id` in frontmatter** across re-render — mirror `consumed_at`
  (render.py:170–181). Small. If it's not in place, the first render after a backfill
  strips every `notion_id` link.

### Module boundary — one-directional
- New: `lib/notion_api.py` (HTTP/upload core lifted from `reference_importer.py` —
  retries/timeout/multipart) + the merge/shadow engine; `commands/notion/` (the `notion`
  group); `commands/monitor.py`.
- **obagent's pipeline/render core must NOT import Notion code** — only the
  `notion`/`monitor` commands do. A sync bug can never reach consume/render.
- Publish reuses the **existing `obagent export`** (→ Drive) + `git push`.

### Optional / future
- Stricter merge condition for multi-asset notes (§17); Notion webhook for
  lower-latency merge.

---

## 15. Deployment (NAS)

DS1817+ is x86 → **Container Manager / Docker**, `restart: always`.

- **The vault lives on the NAS** as the canonical git working checkout. Remotes =
  **GitHub + GitLab** (off-site redundancy); the **old NAS git remote is dropped**
  (same failure domain — §12). The laptop becomes just another clone for desktop
  Obsidian; it's no longer in the ingest loop.
- **Container `CMD` = `obagent monitor`** — one resident loop sequencing
  `consume → notion sync → export → git push` (quiescence gate on consume; per-step
  error isolation; SIGTERM-clean). One deploy unit; every step still runnable by hand.
- **Bind-mounts:** the scan `inbox/`, the vault/git dir, and a config/state dir —
  **mount the parent dir, not single files** (atomic saves change the inode).
- **Secrets via env:** `NOTION_TOKEN`, plus the OCR/LLM keys (`MISTRAL_*`,
  `OPENAI_*`). The Notion integration must be **connected to each target DB** or the
  API 404s.
- **Sync state:** `notion_id` in frontmatter (git); the **shadow**
  `.obagent/notion-shadow.json` (`notion_id → base field values`, git-versioned,
  single-writer = the NAS); and a small hints file with the Notion watermark +
  last-sync git commit. The shadow is the merge base; the hints are disposable.
- Logs → stdout (Container Manager).
- *Fallback if obagent is hard to containerize:* a laptop **launch-agent** watching
  the NAS folder auto-runs consume — but only when the laptop is awake (worse for
  "always-on"). Confirm obagent has no laptop-only deps (local models, config).

---

## 16. Key design decisions (with rationale)

| Decision | Choice | Why |
|---|---|---|
| Source of truth | **The vault** (Notion is a two-way projection) | Preserves the content-addressed structure + cheap model iteration the user values; Notion edits flow back into the frontmatter override layer. |
| Who does OCR/extraction | **obagent** (Mistral + OpenAI) | Proven over ~4,000 files; controllable/versionable; Notion-AI extraction (axis C) buys nothing for the actual drivers and adds black-box + WAF-extraction risk. |
| Where consume runs | **On the NAS, in a Docker container** (Container Manager, `restart: always`) — decided | Always-on box does the always-on job; kills the "manual consume" pain; laptop out of the loop. |
| Code home | **All Notion logic in obagent** — `obagent notion {backfill,sync}` + `obagent <type> apply`; `--dry-run` on backfill/sync = the match/diff report | Sync reuses obagent's vault model (fields/render/make_title/ledger); a separate tool would import it all anyway. One deploy unit; symmetric with `obagent export`. One-directional module boundary (core never imports Notion). |
| Orchestration | **`obagent monitor`** — a thin resident loop over the subcommands | Sub-minute poll + stateful quiescence gate need a Python loop anyway; single container `CMD`; per-step error isolation; subcommands stay independently runnable. (External scheduler only if platform-managed orchestration is wanted.) |
| Notion sync scope | **Receipts + Documents only** (decided); Bank Statements = consume + publish, no Notion | Sync is per-type (type→DB in config); Bank Statements has no Notion DB → skipped for now. |
| Mobile access/editing | **Notion** | Hosted, loads on demand (no GB phone sync), structured DB views, editable — directly fixes "vault too big for phone." |
| Vault↔Notion join | **`notion_id` in frontmatter** (+ `Sha` text as crash-guard) | Explicit pointer on both ends; local forward dedup (no query); dissolves multi-asset/shared-sha identity problems. |
| Notion row granularity | **One row per note**, all files attached | Matches the editable unit; handles the 0.7% multi-asset notes natively (Notion `File` is a list). |
| Two-way field sync | **3-way merge against a stored shadow (base)** | Both Obsidian *and* Notion edit fields; only a 3-way merge can tell which side changed and merge independent fields without loss. |
| Sync base storage | **Shadow state file keyed by `notion_id`** (not a per-`.md` timestamp, not in frontmatter) | A timestamp only gives record-level "something changed" (forces lossy whole-record LWW); the value shadow gives field-level truth. Frontmatter timestamps would churn the note + be circular (§8). |
| Change narrowing | **Notion watermark + `git diff` since last-sync commit** | Optimization only; correctness is the shadow comparison, so losing the hints just triggers a self-healing full pass. |
| Field comparison | **Normalize to canonical values first** | Vault `total:$22.92` (string) vs Notion `Total` (number) would false-diff and churn formatting otherwise. |
| Conflict (same field, both sides) | **Last-writer-wins by timestamp + log** (decided) | Rare, low-cost to re-fix; LWW tiebreak (Notion `last_edited_time` vs git-commit time). A machine-tracked conflicts-report was considered and rejected as unnecessary (§17). |
| Publish targets | **GitHub + GitLab = full vault (git holds *everything*)**; NAS git remote dropped; **Drive KEPT via `obagent export`** | Git = complete open-format backup across 3 domains (no Notion lock-in); NAS bare remote = same failure domain as the on-NAS working copy → dropped. Drive stays for provider diversity + a **browsable** PDF archive (vault originals are sha-scattered), fed by the existing renamed/date-bucketed export. |
| Notion `Name` | **Not synced — it's a Notion formula** | Notion composes the title from the synced fields; both the vault filename and Notion `Name` derive from the same fields independently. |
| Avoid half-written files | **Quiescence gate** (size+mtime stable ≥60 s, ignore temp globs, optional lsof) | Slow scanner→NAS uploads stall mid-transfer; a short window reads a partial as "done." |
| Multi-asset notes | **Keep the merge** (don't enforce 1:1) | Merges are meaningful groupings; 1:1 risks aggregation double-counting and breaks multi-page docs (§17). |
| Deletes | **Not auto-propagated from Notion** | Never let a UI deletion nuke an archived original; remove via obagent only. |

---

## 17. Alternatives considered and rejected

Recorded so we don't re-walk them. Each entry: the idea, and **why not**.

1. **Notion AI does the OCR/extraction (axis C) — the original premise.**
   *Why not:* It's a black box (can't version the prompt, can't batch-reprocess
   deterministically, Notion can change the model under you); the Cloudflare WAF
   that blocks ~0.3% of files on the upload API would turn into an *extraction* tax
   (no file ⇒ no fields); there's **no API trigger** (only the property-change
   hack); and its quality was confirmed to *work* but never validated across 2,500
   receipts. Crucially, the user's drivers were consolidation + re-sync waste, **not
   OCR cost** — so axis C had no payoff to justify its risk. obagent's pipeline is
   proven; keep it.

2. **A standalone "notion-ingest" NAS daemon** (separate from obagent) that uploads
   raw scans. *Why not:* it duplicates obagent's consume/ledger/dedup, and a
   separate watcher + obagent watching the same inbox would fight over files. Extend
   obagent instead.

3. **Notion as the *single* source of truth; retire the vault.** *Why not:* it
   destroys the content-addressed structure and the cheap OCR/LLM model iteration
   the user values, and it requires a real bidirectional reconciliation. We instead
   keep the vault as SOR and let Notion edits flow back into the frontmatter — you
   get phone editing without surrendering the vault.

4. **Two-step `Status`-property trigger** (attach file, then PATCH `Status="Uploaded"`
   to fire the Notion AI agent). *Why not:* it only existed to drive axis C; with
   obagent doing extraction, there's nothing to trigger. (The finding that Notion
   can't trigger on file-attach, only property-change, is still recorded as the
   reason axis C was painful.)

5. **Custom web UI** over the vault/GitHub. *Why not:* it's the opposite of the
   "reduce burden" goal — you'd build and forever maintain frontend/backend/hosting/
   auth/mobile/preview that Notion gives you for free. Only justified by a bespoke
   UX neither Notion nor Obsidian can do (e.g., a spending dashboard), which isn't
   the need.

6. **Notion as a *read-only* one-way mirror** (publish vault → Notion, never edit
   there). *Why not:* the user firmly wants to **edit in Notion** (esp. on the
   phone). Read-only fails the core requirement.

7. **Drive as the editable-data archive / a Notion→Drive `.md` re-render.** *Why
   not:* once Notion is the rich UI, Drive's UI role disappears and it demotes to
   pure backup; **GitHub** is the better versioned open-format archive. No need to
   render `.md` *into* Drive from Notion — the publish path already writes `.md` to
   GitHub from the vault.

8. **`Sha` as the Notion join key / one row per sha.** *Why not:* breaks on the 0.7%
   multi-asset notes (a note has several shas) and on shared shas. Row-per-note +
   `notion_id` is exact.

9. **External ledger (`ledger.jsonl` / a vault `.obagent/notion-sync.json`) as the
   join.** *Why not:* an external index can drift and needs a stable note key.
   `notion_id` in frontmatter is colocated, git-versioned, and self-describing — and
   makes forward dedup local (no query).

10. **A per-note UUID (`id:`) for identity.** *Deferred, not rejected:* `notion_id`
    already provides an explicit link; a UUID is only worth it if the join anchor can
    vanish (e.g., you delete the anchoring asset). Add it later if it actually bites.

11. **A `.json` sidecar (or per-asset `_assets_/<sha>/notion.json`) for the row id.**
    *Why not:* per-asset is ambiguous for multi-asset notes ("which is primary?"); a
    paired sidecar must be renamed in lockstep on every title change. Frontmatter
    rides along automatically.

12. **A `Dirty` checkbox (set by a Notion automation) to mark rows needing reverse
    sync.** *Why not:* adds a Notion-automation dependency and a clear-the-flag echo
    subtlety, and you'd *still* need the diff for safety. Watermark + diff is more
    self-contained. (A Notion→NAS **webhook** is a possible *latency* optimization
    later, with polling kept as the backstop.)

13. **Local wall-clock as the reverse-sync watermark.** *Why not:* clock skew vs.
    Notion's timestamps, and it can drop an edit that lands during the run. Use
    `max(last_edited_time)` of processed rows instead.

14. **Enforce one file per note (no multi-asset).** *Why not:* the 39 multi-asset
    notes are meaningful groupings (receipt + card slip; a multi-page statement; one
    booking's 3 scans). Splitting them risks **aggregation double-counting** (two
    rows each carrying the same `$total`), **breaks multi-page docs/statements**, and
    pollutes the clean `date·merchant·total` filename with unstable `(2)` suffixes.
    The join already handles multi-asset, so 1:1 saves nothing. *Future refinement
    instead:* tighten the **merge condition** (e.g., merge only assets from the same
    batch / same `original_filepath` stem) to avoid wrongly merging two receipts that
    merely share `date·merchant·total`.

15. **Per-type subfolder routing to separate Notion DBs via a NAS uploader.** *Partly
    survives:* obagent already routes by type (`Receipts`/`Bank Statements`/
    `Documents`), and each maps to its DB. The *standalone uploader* is gone; routing
    is just `obagent notion sync` picking the DB per note type.

16. **Record-level last-writer-wins** (no value shadow; whole row vs. whole note,
    newest wins). *Why not (as the default):* it's much simpler but **loses one side's
    edit** whenever both touch the same record between syncs (even on *different*
    fields). The field-level 3-way merge avoids that. LWW survives only as the
    *tiebreak* for a true same-field conflict (§11).

17. **A per-`.md` `last_synced` timestamp as the sync mechanism.** *Why not:* a
    timestamp only signals "this side changed," not *what* changed — so it can only
    drive record-level LWW (see #16), not field-level merge. It also false-positives
    on no-op saves, and **must not live in frontmatter** (churns the note every sync;
    a `last_synced` in the file is circular — writing it bumps the mtime you read).
    The value **shadow** subsumes everything a timestamp would tell you and more; a
    **content hash** beats a timestamp even in the lighter record-level design. (§8, §11)

18. **A machine-tracked conflicts report / Notion callout** for same-field, both-sides
    conflicts. *Why not:* **LWW + a log line is good enough** (decided) — conflicts are
    rare and cheap to re-fix by hand; a tracked report/queue is more machinery than the
    problem warrants. (§11)

---

## 18. Initial backfill (one-time reconciliation)

Command: **`obagent notion backfill [--dry-run]`** (`--dry-run` = the read-only match
report, run first). The 2026-06 import already created rows, but with **no `notion_id`
link**. The backfill re-links existing rows to vault notes and **records `notion_id` in
the `.md` files** — without re-uploading the ~4,000 attachments. Current state (checked
2026-06-28):

| DB | Notion rows | Vault notes | Status |
|---|---|---|---|
| Receipts | **2,544** | 2,545 | **1 vault note missing** in Notion |
| Documents | **1,488** | 1,488 | exact |
| Bank Statements | — | 1,658 | not synced (by design) |

Data quality — **no real gaps**:
- Receipts: `Total` is null for 65 rows, but those are non-USD and their amount is in
  the **`Non-USD Total`** text column ("JPY 3,775", …) — **0 true gaps**. `Date` 100%.
- Documents: `Summary` + `Date` 100% populated.
- So existing field data is complete; the backfill is purely **linking**, not resyncing.
- No `.md` has `notion_id` yet; neither DB has `Sha`/`Consumed At`.
- Receipts `Name` is unique; Documents `Name` is **not** unique alone (e.g. "Room 1
  Routine Report Childcare" ×7) but `(Name, Date)` has **zero collisions**.

### Step 1 — schema
Add `Sha` (text) + `Consumed At` (date+time) to both DBs (§9).

### Step 2 — match existing rows ↔ vault notes (deterministic keys)
- **Receipts → by `Name`** (`= date - merchant - total = make_title()`, unique both sides).
- **Documents → by `(Name, Date)`** (Notion `Name` = bare title; match to vault
  `(title, date)`).
Build a vault index keyed accordingly, page through each DB, pair them up.

### Step 3 — write the link (the "record `notion_id`" step)
For each matched pair: write `notion_id` (and `Sha`, `Consumed At`) into the `.md`
frontmatter; set `Sha`/`Consumed At` on the Notion row; `git commit`; initialize the
shadow with the agreed field values.

### Step 4 — reconcile the residue
- **Unmatched vault notes** (the 1 missing receipt; any doc whose title changed
  post-import) → forward-register (create the row).
- **Unmatched Notion rows** (orphans — a vault title edited after import, or a manual
  row) → **log for review**, never auto-delete.

No field resync is needed — the existing data is complete (USD in `Total`, non-USD in
`Non-USD Total`). The backfill only adds the link + the new `Sha`/`Consumed At` values.

---

## 19. References / reusable assets

- **obagent** (`~/Workspace/obagent`): `commands/` = `consume, ingest, ocr, llm,
  render, export, merchant, bank, people, scan, remove`; type modules under
  `commands/{receipt,document,bank_statement}`; `lib/pipeline`, `lib/constants`
  (`ASSETS_DIR`), `lib/utils` (`SHA_RE`, `iter_entries`, `newest_file`, …).
  - `render.py`: frontmatter-preservation logic (`apply_frontmatter` ~:159–167,
    `consumed_at` ~:170–181), `index_existing_notes`, `make_title`,
    `format_frontmatter`, render statuses.
- **Vault** (`~/Workspace/obsidian-vaults/paperless`): structure + frontmatter
  schemas in §7; `.obagent/*-aliases.json`; `<type>.base` views; vault `CLAUDE.md`
  (note: its "don't edit, obagent overwrites" guidance is stale — render preserves
  edits by default).
- **`reference_importer.py`** (this repo root): the proven Notion upload core — `api()`
  (throttle + 429/CDN/WAF retries + 60 s timeout), `upload_scan()`/`_send_part()`
  (single + multipart >20 MB + complete), `u16len()`/`truncate_u16()`, the page-
  property pattern. (`md_to_blocks`/OCR/summary logic is **not** needed.)
- **Notion DBs:** 🧾 Receipts data source `<receipts-data-source-id>`
  (props: `Name`/`Date`/`File`/`Merchant`/`Total`/`Non-USD Total`); 🗃️ Documents data source
  `<documents-data-source-id>` (`Name`/`Date`/`File`/`People`/`Tags`/
  `Summary`); Bank Statements — **not synced to Notion** (no DB needed for now). The
  two synced DBs each need a new `Sha` (text) property.
- **Claude memory:** `reference_notion_api.md` (Notion API/MCP reference);
  `project_notion_paperless_migration.md` (migration history + importer gotchas).
- **Conventions:** Python with `uv`/`hatchling`/`ruff`/`ty`; `just check` / `just fix`.
