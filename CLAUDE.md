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

## Consume and Export

`consume` (inbound) and `export` (outbound) share the same I/O convention: a positional dir is treated verbatim, while the option/env-var form is a *root* with the per-type subdir auto-appended.

| Per-type command | Positional | Option (env var) | Default (option set) | Both empty |
|---|---|---|---|---|
| `obagent {type} consume [PATHS...]` | source files/dirs, used verbatim | `--input-dir DIR` (`OBAGENT_CONSUME`) | sources = `DIR/{path}/` | `UsageError` |
| `obagent {type} export [OUTPUT_DIR]` | dest dir, used verbatim | `--output-dir DIR` (`OBAGENT_EXPORT`) | dest = `DIR/{path}/` | `UsageError` |

Top-level forms (`obagent consume`, `obagent export`) drop the positional argument entirely and require the option/env var. They loop over `Pipeline._registry` and apply the same `DIR/{path}/` convention to each type — `Documents`, `Receipts`, `Bank Statements`.

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

### Export specifics

- **Idempotent**: a destination file with matching size + integer-second mtime is left alone (counted as `unchanged`); otherwise `shutil.copy2` overwrites it. `shutil.copy2` preserves mtime, so re-runs against an unchanged vault perform no I/O.
- **Multi-embed notes**: first source uses the bare note stem, extras get a `-{sha12}` suffix.
- **Dangling cleanup**: scoped to the chosen export root. Removes any file under top-level / `YYYY/YYYY-MM/` / `undated/` of that root that wasn't written this run, then prunes empty managed dirs. Other folders inside the parent dir (e.g. sibling type subdirs) are untouched.
- **Summary counters**: `exported`, `unchanged`, `removed`, `missing` (source file referenced by a note not found on disk).

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
