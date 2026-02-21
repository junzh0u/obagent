# obagent

## Project Setup

- Python 3.14, managed with **uv**
- Build backend: hatchling
- CLI framework: click
- Entry point: `obagent` → `main:cli`

## Project Structure

- `main.py` — CLI entry point, click group with `receipt` subgroup
- `commands/` — subcommand modules (consume, ingest, ocr, llm, render)
- `constants.py` — shared constants (OCR_MODEL, LLM_MODEL, ASSETS_DIR)
- `utils.py` — shared utilities (iter_entries, newest_file)
- `tests/` — unit and integration tests with shared fixtures in `conftest.py`

## Pipeline

Each receipt goes through: **ingest → ocr → llm → render** (or all at once via `consume`).

Vault layout:
```
vault/{path}/
  *.md                          ← rendered notes (flat, browsable)
  _assets_/{sha256}/
    src/   ocr/   llm/          ← per-entry data dirs
```

## Commands

```bash
uv sync              # Install dependencies
uv run obagent       # Run the CLI
```

## Code Quality

- Formatter/linter: **ruff** (dev dependency)
- Pre-commit hook runs `ruff format --check` and `ruff check`
- Always run `uv run ruff format .` before committing

## Testing

- Always write unit tests and integration tests whenever applicable
- Test framework: **pytest** (dev dependency)
- Tests live in `tests/` with shared fixtures in `tests/conftest.py`
- Run tests: `uv run pytest tests/ -v`
