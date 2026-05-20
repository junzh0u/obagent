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
- `commands/{receipt,bank_statement,document}/pipeline.py` — concrete `Fields` + `Pipeline` per type
- `commands/` — CLI command modules (consume, ingest, ocr, llm, render, scan)
- `commands/export.py` — shared `export` subcommand (registered on `document` and `receipt`)
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

## Consume

`obagent {document,receipt,bank-statement} consume [PATHS...]` ingests source files into the vault. When `PATHS` are omitted, the command falls back to `--input-dir DIR` (env var: `OBAGENT_CONSUME`) and consumes from `DIR/{path}/`. Use `obagent consume` (top-level, no group) to run every type in one invocation:

```
$OBAGENT_CONSUME/
├── Documents/         ← drop .pdf/.jpg/.jpeg here
├── Receipts/
└── Bank Statements/
```

Per-type consume input-source resolution:

| Positional `PATHS` | `--input-dir` / `OBAGENT_CONSUME` | Result |
|---|---|---|
| given | ignored | Consume `PATHS` verbatim. |
| empty | set, `DIR/{path}/` exists | Consume `DIR/{path}/`. |
| empty | set, `DIR/{path}/` missing | Warn `No inbox at …`, exit 0. |
| empty | unset | `UsageError` mentioning both `--input-dir` and `OBAGENT_CONSUME`. |

The top-level `obagent consume` is stricter: `--input-dir` (or `OBAGENT_CONSUME`) is **required**, no positional `PATHS` are accepted. Inside the loop, each pipeline's `DIR/{default_path}/` follows the same "missing → soft skip" rule, so a partial inbox (e.g. only `Documents/` present) processes the populated types and warns on the rest.

## Export

`obagent {document,receipt,bank-statement} export --output-dir DIR` (env var: `OBAGENT_EXPORT`) copies source files out of the vault, named after their `.md` notes and grouped by date. The per-type subdir is appended automatically — pointing every subcommand at the same `DIR` is safe and expected. Use `obagent export` (top-level, no group) to run all three types in one invocation:

```
DIR/
  Documents/
    YYYY/YYYY-MM/{note-stem}{.pdf|.jpg|.jpeg}
    undated/{note-stem}{.pdf|.jpg|.jpeg}      ← notes whose filename has no YYYY-MM prefix
  Receipts/
    YYYY/YYYY-MM/...
    undated/...
  Bank Statements/
    YYYY/YYYY-MM/...
    undated/...
```

The top-level `obagent export` uses each pipeline's `default_path` (`Documents`, `Receipts`, `Bank Statements`) and does **not** accept a `--path` override — use the per-type subcommand for that (e.g. `obagent receipt --path Invoices export`).

Behavior:
- Idempotent: a destination file with matching size + integer-second mtime is left alone (counted as `unchanged`), otherwise `shutil.copy2` overwrites it. `shutil.copy2` preserves mtime, so re-runs against an unchanged vault perform no I/O.
- Multi-embed notes: first source uses the bare note stem, extras get a `-{sha12}` suffix.
- Dangling cleanup: scoped to the type subdir (`DIR/{path}/`). Removes any file under top-level / `YYYY/YYYY-MM/` / `undated/` of that subdir that wasn't written this run, then prunes empty managed dirs. Other type subdirs and unrelated folders inside `DIR` are untouched.
- Summary counters: `exported`, `unchanged`, `removed`, `missing` (source file not found on disk).

## Name Management (People & Banks)

Both `commands/people.py` and `commands/bank.py` share the same pattern via `lib/name_store.py` (shared JSON store helpers and command factories: `make_rename_command`, `make_list_command`, `make_remap_command`, `make_pin_command`, `make_unpin_command`).

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

## Commands

```bash
uv sync              # Install dependencies
uv run obagent       # Run the CLI
just install         # Install to PATH with zsh completions
just uninstall       # Remove CLI and completions
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
