# obagent

## Project Setup

- Python 3.14, managed with **uv**
- Build backend: hatchling
- CLI framework: click
- Entry point: `obagent` → `main:cli`

## Project Structure

- `main.py` — CLI entry point, click group with subgroups per document type
- `lib/` — shared infrastructure (not CLI commands)
  - `lib/fields.py` — `Fields[K]` ABC: dict-based field container with postprocess, defaults, title, and formatting
  - `lib/pipeline.py` — `Pipeline` ABC: orchestration (prompt, CLI command factories)
  - `lib/name_store.py` — shared JSON store helpers for aliases and pinned names
  - `lib/constants.py` — shared constants (OCR_MODEL, LLM_MODEL, ASSETS_DIR)
  - `lib/utils.py` — shared utilities (iter_entries, newest_file, source_file, `SHA_RE`)
  - `lib/notion_api.py` — Notion HTTP client (stdlib urllib): throttle, retry (429 / Cloudflare-WAF / 5xx / timeout), file upload, and data-source page/query wrappers. Pinned to API version `2025-09-03`.
  - `lib/notion_fieldmap.py` — vault frontmatter ↔ Notion property codecs, per type (see Notion sync)
- `commands/{receipt,bank_statement,document}/pipeline.py` — concrete `Fields` + `Pipeline` per type
- `commands/` — CLI command modules (consume, ingest, ocr, llm, render, scan, remove)
- `commands/export.py` — shared `export` subcommand (registered on `document`, `receipt`, and `bank_statement`); also exposes the top-level `obagent export` aggregator
- `commands/{bank,merchant,people}.py` — top-level name-management groups built on `lib/name_store.py`
- `commands/notion/` — Notion sync: `sync.py` (the `obagent notion sync` command + the two-way merge engine) and `backfill.py` (the one-time link, run as a one-off — not a CLI command)
- `scripts/`, `Dockerfile`, `.dockerignore` — deployment bundle (see Deployment)
- `tests/` — unit and integration tests with shared fixtures in `conftest.py`

## Architecture

Each document type (receipt, bank_statement, document) defines:
- A **Fields** subclass (`dict[Literal[...], str]`) that owns field behavior: postprocess, defaults, title formatting
- A **Pipeline** subclass that owns orchestration: LLM prompt, `fields_class` reference

`Fields.__init__` automatically calls `postprocess()` then `apply_defaults()`, so construction is all that's needed.

## Pipeline

Each document goes through: **ingest → ocr → llm → render** (or all at once via `consume`). Use `scan` to preview without side effects.

Vault layout:
```
vault/{path}/
  *.md                          ← rendered notes (flat, browsable)
  _assets_/{sha256}/
    src/   ocr/   llm/          ← per-entry data dirs
```

## Consume and Export

`consume` (inbound) and `export` (outbound) share the same I/O convention: a positional dir is treated verbatim, while the option/env-var form is a *root* with the per-type subdir auto-appended.

| Per-type command | Positional | Option (env var) | Default (option set) | Both empty |
|---|---|---|---|---|
| `obagent {type} consume [PATHS...]` | source files/dirs, used verbatim | `--input-dir DIR` (`OBAGENT_CONSUME`) | sources = `DIR/{path}/` | `UsageError` |
| `obagent {type} export [OUTPUT_DIR]` | dest dir, used verbatim | `--output-dir DIR` (`OBAGENT_EXPORT`) | dest = `DIR/{path}/` | `UsageError` |

Top-level forms (`obagent consume`, `obagent export`) drop the positional argument entirely and require the option/env var. They loop over `Pipeline._registry` and apply the same `DIR/{path}/` convention to each type — `Documents`, `Receipts`, `Bank Statements`. A matching `obagent render` aggregator (no `--input-dir`/`--output-dir`) re-renders every type's notes in one go.

The natural round-trip layout (export root inverted into a consume root):

```
DIR/
├── Documents/         {YYYY/YYYY-MM,undated}/{note-stem}{.pdf|.jpg|.jpeg}
├── Receipts/
└── Bank Statements/
```

### Consume specifics

- Missing `DIR/{path}/` is a **soft skip** (warning, exit 0). Per-type consume warns and returns without opening API clients; `obagent consume` warns per missing type and continues.
- The per-type command keeps its existing positional `PATHS` (variadic — multiple files/dirs OK).
- **`obagent consume`** (top-level only) accepts `--prehook CMD` (env var: `OBAGENT_CONSUME_PREHOOK`). The shell command runs before the per-type loop and before API clients are opened; a non-zero exit aborts with `Prehook failed`. Useful for populating `$OBAGENT_CONSUME` from an outside source (email sync, scanner upload, etc.).
- **`--min-age N`** (both consume entry points) skips files modified within the last N seconds — a stateless quiescence gate (mtime-based) so a slow scanner→inbox upload isn't grabbed mid-write. Default 0 (off).

### Export specifics

- **Idempotent**: a destination file with matching size + integer-second mtime is left alone (counted as `unchanged`); otherwise `shutil.copy2` overwrites it. `shutil.copy2` preserves mtime, so re-runs against an unchanged vault perform no I/O.
- **Multi-embed notes**: first source uses the bare note stem, extras get a `-{sha12}` suffix.
- **Dangling cleanup**: scoped to the chosen export root. Removes any file under top-level / `YYYY/YYYY-MM/` / `undated/` of that root that wasn't written this run, then prunes empty managed dirs. Other folders inside the parent dir (e.g. sibling type subdirs) are untouched.
- **Summary counters**: `exported`, `unchanged`, `removed`, `missing` (source file referenced by a note not found on disk).

## Name Management (People, Banks & Merchants)

`commands/people.py`, `commands/bank.py`, and `commands/merchant.py` share the same pattern via `lib/name_store.py` (shared JSON store helpers and command factories: `make_rename_command`, `make_list_command`, `make_remap_command`, `make_pin_command`, `make_unpin_command`, `make_auto_rename_command`). All three are registered as **top-level** groups on the root `cli` (not nested inside their respective document-type groups).

### People (documents)
- Aliases file: `{vault}/.obagent/people-aliases.json` — maps old names to new (empty string = remove)
- Pinned file: `{vault}/.obagent/people-pinned.json` — names always included in LLM context
- `DocumentPipeline.prepare_context()` loads aliases into `DocumentFields._aliases`, which `postprocess()` auto-applies on render

### Banks (bank statements)
- Aliases file: `{vault}/.obagent/bank-aliases.json` — maps old bank names to new
- Pinned file: `{vault}/.obagent/bank-pinned.json` — pinned bank names
- `BankStatementPipeline.prepare_context()` loads aliases into `BankStatementFields._aliases`, which `postprocess()` auto-applies on render

### Merchants (receipts)
- Aliases file: `{vault}/.obagent/merchant-aliases.json` — maps old merchant names to new
- Pinned file: `{vault}/.obagent/merchant-pinned.json` — pinned merchant names
- `ReceiptPipeline.prepare_context()` loads aliases into `ReceiptFields._aliases`, which `postprocess()` auto-applies on render
- Has an extra `auto-rename` subcommand: asks an LLM (`AUTO_RENAME_MODEL`) to cluster variants of the same merchant, then prompts the user to accept/reject each suggested rename before applying

## Notion sync

obagent keeps the vault and a Notion workspace (🧾 Receipts + 🗃️ Documents data
sources) reconciled **two ways**. The vault stays the source of truth and the
OCR/LLM pipeline; Notion is an editable mobile view. Bank statements are not synced.

- **Link:** each note carries a `notion_id` in frontmatter (the Notion page id).
  `render` preserves it across re-renders/renames, exactly like `consumed_at`.
  Notion rows carry a `Sha` text property (the note's sha set) as a create-crash
  dedup guard, plus a `Consumed At` date.
- **Field map** (`lib/notion_fieldmap.py`), per type: receipt `merchant`/`date`/
  `total` (USD → `Total` number, non-USD → `Non-USD Total` ISO text); document
  `title`↔`Name`, `tags`/`people`↔multi-select, `summary` (body callout)↔`Summary`.
  Receipt `Name` is a Notion formula → **not** synced.
- **`obagent notion sync`** — one reconciliation pass. A git-style **3-way merge**
  against the **shadow** (`{vault}/.obagent/notion-shadow.json` = field values at
  last sync): Notion-changed adopts into the vault, vault-changed pushes to Notion,
  both-moved is a conflict → last-writer-wins by timestamp + log. Notes with no
  `notion_id` yet (new since the last link) get a **row created** — source file(s)
  uploaded, fields + `Sha` + `Consumed At` set, the id written back — guarded by the
  `Sha` property (a row already bearing the sha is adopted, not duplicated). Merge
  candidates are narrowed by the Notion `last_edited_time` watermark + `git diff`
  since the last-sync commit (`{vault}/.obagent/notion-sync-hints.json`); the create
  pass instead scans all notes for a missing `notion_id`. Correctness rests on the
  shadow, so losing the hints just triggers a self-healing `--full` pass.
  `--dry-run` reports without writing. Token from `NOTION_TOKEN`; data-source ids
  from `OBAGENT_NOTION_<TYPE>_DS` (env-only, no defaults — an unset type is skipped).
- **Deletions are not propagated by default** — the field merge only ever adopts/
  pushes values, never deletes (the vault is the source of truth and holds the
  original scan). **`--prune`** opts into two-way **DELETION** propagation: a trashed
  Notion row deletes its linked vault note **and its source file** (`delete_note`);
  a vault note gone since the last sync trashes its Notion row (`client.trash_page`,
  a recoverable soft-delete). `--prune` forces a **full scan** (the complete live-row
  set is needed to tell "trashed" from "unchanged") and is guarded against mass
  deletion — a data source that returns zero live rows, or a vault that scans to zero
  linked notes, is treated as an outage and skipped, not a mass-trash. Pair with
  `--dry-run` to preview (`would_delete_vault` / `would_trash_notion`). (vault →
  export deletion already happens via `export`'s dangling cleanup.)
- **Backfill** (`obagent notion backfill`, `commands/notion/backfill.py`): match
  existing rows by a normalized key, write `notion_id` + init the shadow, and
  **canonicalize** each linked row's `Sha`/`File` to the note's sources — re-uploading
  attachments with sha-encoded `-<sha12>` names only when they've drifted (the
  migration that enables the per-file two-way sync). Idempotent (an already-linked,
  already-canonical row is untouched); `--dry-run` reports without writing.
- **Boundary:** Notion code is one-directional — `lib`/pipeline/render never import
  it; only `commands/notion` + `main` do.

## Deployment

Built to run on a Synology NAS via **Container Manager (docker compose)**, so the
NAS needs no Python — the image bundles Python 3.14 + uv + deps. Step-by-step NAS
setup is in **`DEPLOY.md`**.

- `Dockerfile` — the self-contained image (+ git/ssh for the push).
- `scripts/run.sh` — one pass: `consume --min-age` → `obagent notion sync` →
  `publish.sh`, with per-step error isolation and a `flock` no-overlap guard.
- `scripts/publish.sh` — `obagent export` (→ Drive via Cloud Sync) + a **guarded
  fast-forward** (`git fetch` then `merge --ff-only`; integrates remote commits so
  the push stays a clean fast-forward, and aborts cleanly on divergence — never
  rebases/merges) + a plain machine `git commit` of the vault changes (the NAS has
  no Claude/LLM committer; skipped when nothing changed) + `git push` to the vault's
  remotes. Author falls back to `OBAGENT_GIT_NAME`/`OBAGENT_GIT_EMAIL` only if the
  repo has no identity.
- `scripts/loop.sh` — runs `run.sh` every `$OBAGENT_INTERVAL` seconds (the compose
  service command; SIGTERM-clean).
- `docker-compose.yml` — the Container Manager Project: build + bind-mounts (inbox,
  vault repo, Drive-export, git ssh key) + env. Secrets in a gitignored `.env`
  (see `.env.example`).

Either model works: the compose service loops (`restart: always`), **or** schedule
one-off passes with Synology Task Scheduler via `docker run --rm --name
paperless-sync … obagent` (the `--name` prevents overlap). The monitor is
deliberately shell, not an obagent subcommand.

## Email ingest

Selected incoming Gmail is fed into the pipeline — a **feeder**, no obagent-core
change. It reuses the **Drive consume inbox**: the script drops files into the same
`consume/{type}/` tree obagent already ingests, so there is no email-specific wiring
on the obagent side. Full design + one-time setup is in `plan-email-ingest.md`.

- **`scripts/gmail-ingest.gs`** (Apps Script, paste-deployed, runs in Google with
  your own Gmail+Drive auth — no creds on the NAS): on a ~15-min trigger it finds
  threads labeled `obagent/inbox`, and for each not-yet-processed message routes it
  to a type (subject/sender `ROUTING_RULES` → `Receipts`, default `Documents`),
  renders the body → PDF, pulls every non-inline attachment, and
  writes them into `consume/<Type>/` on Drive. Then it swaps labels (`-obagent/inbox
  +obagent/ingested`). Dedup is a per-message processed-id set in `PropertiesService`
  (not the labels — Gmail labels are thread-level); the `CONSUME_FOLDER_ID` script
  property holds the Drive `consume/` folder id (kept out of this repo).
- **Drain:** the Drive `consume/` tree is two-way Cloud-Synced to the NAS consume
  mount (`OBAGENT_CONSUME`). `consume` **moves** source files out, so the local
  delete propagates back up and empties the Drive folder — same as any consume.
- **No extra obagent wiring:** because email lands in the normal consume tree, the
  existing `obagent consume` ingests it. Body PDF + each attachment become separate
  notes. (`OBAGENT_CONSUME` points at the Drive-synced consume folder in compose.)

## Commands

```bash
uv sync                              # Install dependencies
uv run obagent                       # Run the CLI
just run notion sync --dry-run       # Alias for `uv run obagent ...`
uv run obagent notion sync --dry-run # Preview a vault <-> Notion reconciliation
just install                         # Install to PATH with zsh completions
just uninstall                       # Remove CLI and completions
```

## Code Quality

- Formatter/linter: **ruff** (dev dependency)
- Pre-commit hook runs `ruff format --check` and `ruff check`
- Always run `just fix` before committing
- Run `just check` to verify formatting, lint, and tests

## Testing

- Always write unit tests and integration tests whenever applicable
- Test framework: **pytest** (dev dependency)
- Tests live in `tests/` with shared fixtures in `tests/conftest.py`
- Run tests: `just check`
