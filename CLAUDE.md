# obagent

## Project Setup

- Python 3.14, managed with **uv**
- Build backend: hatchling
- CLI framework: click
- Entry point: `obagent` → `main:cli`

## Project Structure

- `main.py` — CLI entry point, click group definition
- `commands/` — subcommand modules (each file exports a click command)

## Commands

```bash
uv sync              # Install dependencies
uv run obagent       # Run the CLI
```

## Code Quality

- Formatter/linter: **ruff** (dev dependency)
- Pre-commit hook runs `ruff format --check` and `ruff check`
- Always run `uv run ruff format .` before committing
