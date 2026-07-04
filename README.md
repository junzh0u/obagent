# obagent

CLI tool that ingests PDFs into an [Obsidian](https://obsidian.md) vault, runs OCR + LLM extraction, and renders browsable markdown notes.

Supports multiple document types — **receipts**, **bank statements**, and **documents** — each with their own field extraction and formatting.

## Pipeline

```
PDF  ──►  ingest  ──►  ocr  ──►  llm  ──►  render  ──►  .md note
```

Each step can be run individually or all at once with `consume`:

| Command   | What it does                                           |
|-----------|--------------------------------------------------------|
| `scan`    | Preview which PDFs are new vs already in the vault     |
| `ingest`  | Copy/move PDFs into the vault, deduplicated by SHA-256 |
| `ocr`     | Run Mistral OCR on ingested PDFs                       |
| `llm`     | Extract structured fields via LLM                      |
| `render`  | Generate Obsidian markdown notes from extracted fields  |
| `consume` | Run the full pipeline (ingest → ocr → llm → render)    |

Outside the pipeline:

| Command   | What it does                                           |
|-----------|--------------------------------------------------------|
| `export`  | Inverse of ingest — copy source files out of the vault under their note names |

Top-level aggregators (`obagent consume`, `obagent export`, `obagent render`) loop over every document type (receipts, bank statements, documents) in one go.

## Vault structure

```
vault/
  Receipts/
    2024-06-01 - Coffee Shop - $5.75.md
    _assets_/
      <sha256>/
        src/        ← original.pdf + metadata.json
        ocr/        ← OCR output (json + txt)
        llm/        ← extracted fields (json)
  Bank Statements/
    2024-01-01 to 2024-01-31 - Chase - Checking - 1234.md
    _assets_/...
  Documents/
    2024-04-15 - Tax Return 2024.md
    _assets_/...
```

## Setup

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

### Install to PATH

Requires [just](https://github.com/casey/just).

```bash
just install     # install CLI + zsh completions
just uninstall   # remove both
```

Set API keys as environment variables or pass them as CLI flags:

```bash
export MISTRAL_API_KEY=...
export OPENAI_API_KEY=...
export OBAGENT_VAULT=/path/to/your/vault
export OBAGENT_CONSUME=/path/to/inbox/dir            # default `--input-dir` for the consume commands
export OBAGENT_CONSUME_PREHOOK='~/bin/fetch-scans.sh' # default `--prehook` for `obagent consume`
export OBAGENT_EXPORT=/path/to/export/dir            # default `--output-dir` for the export commands
```

## Usage

```bash
# Document types: receipt, bank-statement, document
obagent receipt consume ./inbox
obagent bank-statement consume ./inbox
obagent document consume ./inbox

# Preview what would happen (no files moved, no API calls)
obagent receipt scan ./inbox

# Or run steps individually
obagent receipt ingest ./inbox
obagent receipt ocr
obagent receipt llm
obagent receipt render

# Target specific entries by sha256 (ocr, llm, render, remove)
obagent receipt render <sha256> <sha256> ...
obagent receipt remove <sha256>

# People management (documents only)
obagent people list                       # list all unique names
obagent people rename "Old Name" "New"    # rename across all notes
obagent people remove "Name"              # remove from all notes
obagent people remap                      # batch rename from aliases file
obagent people pin "Name"                 # pin names to the known-names list
obagent people unpin "Name"               # unpin names
# Aliases in .obagent/people-aliases.json are auto-applied on render

# Bank management (bank statements only)
obagent bank list                         # list all unique bank names
obagent bank rename "Old Bank" "New"      # rename across all notes
obagent bank remap                        # batch rename from aliases file
obagent bank pin "Name"                   # pin bank names
obagent bank unpin "Name"                 # unpin bank names
# Aliases in .obagent/bank-aliases.json are auto-applied on render

# Merchant management (receipts only)
obagent merchant list                     # list all unique merchant names
obagent merchant rename "Old" "New"       # rename across all notes
obagent merchant remap                    # batch rename from aliases file
obagent merchant pin "Name"               # pin merchant names
obagent merchant unpin "Name"             # unpin merchant names
obagent merchant auto-rename              # LLM-assisted duplicate detection
# Aliases in .obagent/merchant-aliases.json are auto-applied on render

# Re-process everything from scratch
obagent receipt consume --overwrite ./inbox

# Keep original PDFs (copy instead of move)
obagent receipt consume --keep-original ./inbox

# Use a custom vault subdirectory
obagent receipt --path Invoices consume ./inbox

# Round-trip with a shared root layout — drop scans into $OBAGENT_CONSUME/{type}/,
# files exit at $OBAGENT_EXPORT/{type}/{YYYY}/{YYYY-MM}/{note}.{pdf,jpg,jpeg}.
obagent document consume                  # consume $OBAGENT_CONSUME/Documents/
obagent consume                           # consume every type in one go
obagent document export                   # export to $OBAGENT_EXPORT/Documents/
obagent export                            # export every type in one go
obagent render                            # re-render every type's notes in one go

# Positional dirs override the env var / option for the per-type commands:
obagent receipt consume ./tmp-inbox       # consume from ./tmp-inbox verbatim
obagent document export /tmp/just-here    # export to /tmp/just-here verbatim (no subdir)
```

Per-type `consume` and `export` resolve their directory the same way:

| Per-type command | Positional | Option (env var) | Default (option set) | Both empty |
|---|---|---|---|---|
| `obagent {type} consume [PATHS...]` | source files/dirs, used verbatim | `--input-dir DIR` (`OBAGENT_CONSUME`) | sources = `DIR/{path}/` | error |
| `obagent {type} export [OUTPUT_DIR]` | dest dir, used verbatim | `--output-dir DIR` (`OBAGENT_EXPORT`) | dest = `DIR/{path}/` | error |

Top-level `obagent consume` / `obagent export` drop the positional and require the option/env var; both loop over every type and apply `DIR/{path}/` per pipeline. Missing type subdirs are soft-skipped on consume; export will happily create them.

**Smart inbox:** files dropped **loose in the inbox root** (not pre-sorted into a type subdir) are auto-classified by `obagent consume` — OCR'd once, then an LLM decides the type (receipt / bank statement / document) and routes them, skipping a second OCR. Pass `--no-classify` to disable, or `--classify-model` to pick the model.

The top-level `obagent consume` also accepts `--prehook CMD` (env var: `OBAGENT_CONSUME_PREHOOK`), a shell command that runs before the per-type loop. Useful for populating the inbox from an outside source. A non-zero exit aborts before any API clients are opened.

```bash
OBAGENT_CONSUME_PREHOOK='rclone copy gdrive:scans $OBAGENT_CONSUME' obagent consume
```

## Notion sync

Keep the vault and a Notion workspace (Receipts + Documents) reconciled **two-way** —
edit in either and changes flow both directions. The vault stays the source of truth;
Notion is an editable mobile view.

```bash
export NOTION_TOKEN=ntn_...
obagent notion sync --dry-run            # preview
obagent notion sync                      # reconcile vault <-> Notion (field edits)
obagent notion sync --prune --dry-run    # preview deletions too
obagent notion sync --prune              # also propagate deletions both ways
```

Each note is linked by a `notion_id` in its frontmatter. Sync does a 3-way merge
against a *shadow* (the values at last sync): a change on either side propagates; a
genuine both-sides conflict is resolved last-writer-wins and logged. `--full` ignores
the incremental hints and re-checks every linked record.

By default sync moves *field edits*, never deletions. `--prune` opts into two-way
**deletion** propagation: trashing a row in Notion deletes its vault note **and the
original scanned file**; deleting a vault note trashes its Notion row (a recoverable
soft-delete). It forces a full scan and refuses to act when a data source or the
vault scans to zero (an outage shouldn't wipe everything) — preview with
`--prune --dry-run` first. (Deleting a vault note already removes its exported copy
via `export`.)

Attachments sync per file too (the vault owns the files). Remove a source from a
multi-file note (`obagent <type> remove <sha>`) and `sync` drops that attachment from
the Notion row; remove a file *in Notion* and it's reasserted from the vault — or,
under `--prune`, that vault source (original scan included) is deleted instead.

The initial link (matching existing Notion rows to vault notes by a normalized key)
is `obagent notion backfill` — it also canonicalizes each row's attachments
(`Sha`/`File`) to the note's sources. Idempotent and safe to re-run; `--dry-run`
previews.

## Deployment

Runs **natively on a Synology NAS** (no Docker). [`uv`](https://docs.astral.sh/uv/)
installs a standalone Python 3.14 on the host, so the NAS needs no system Python:

```bash
uv tool install .                # obagent -> ~/.local/bin (a Python 3.14 CLI)
```

A DSM **Task Scheduler** job then runs one pass on an interval via `scripts/run.sh`:
`consume --min-age` → `notion sync` → publish (`export` + a guarded fast-forward + a
machine `git commit` + `git push`), `flock`-guarded against overlap. The pass logic
lives in the repo; a thin wrapper in your dotfiles loads the env and calls it.

Running on the host (not a container) is deliberate: Synology **Cloud Sync** drains the
consume inbox and removes stale exports from Google Drive only when the delete happens
**host-side** — a delete from inside a container is invisible to its watcher. See
`DEPLOY.md` for the full setup.

## Email ingest

Optionally feed selected incoming Gmail into the vault. A small **Apps Script**
(`scripts/gmail-ingest/`, deployed with clasp) watches a Gmail label, renders each message body to a
PDF, pulls every attachment, and drops them into your Google Drive **consume** inbox —
into `consume/{type}/` when the thread is pinned with an `obagent/inbox/{receipt,document}`
label, otherwise into the `consume/` root for obagent's smart inbox to classify.
**Synology Cloud Sync** (two-way) mirrors that inbox to the NAS, and the normal
`obagent consume` ingests it each pass — consume *moves* the source out, and (running on
the host) that delete propagates back up to empty the Drive folder.

Because email reuses the existing consume inbox, there's no email-specific obagent
wiring. No Gmail credentials live on the NAS (the script runs in Google with your
own auth). Setup and design notes are in `plans/2026-06-29-email-ingest.md`.

## Development

```bash
just check   # verify formatting, lint, and run tests
just fix     # auto-fix formatting and lint issues
```
