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
  - `lib/utils.py` — shared utilities (iter_entries, newest_file)
- `commands/{receipt,bank_statement,document}/pipeline.py` — concrete `Fields` + `Pipeline` per type
- `commands/` — CLI command modules (consume, ingest, ocr, llm, render, scan)
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

## People Aliases

- `commands/people.py` — people management commands and helpers
- Aliases file: `{vault}/.obagent/people-aliases.json` — maps old names to new (empty string = remove)
- `_load_aliases(vault)` loads the JSON, `_apply_mapping(names, mapping)` applies rename/remove/dedup/sort
- `DocumentPipeline.prepare_context()` loads aliases into `DocumentFields._aliases`, which `postprocess()` auto-applies on render
- `remap` command also uses `_load_aliases` for its default-path case

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
