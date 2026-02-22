# obagent

CLI tool that ingests PDFs into an [Obsidian](https://obsidian.md) vault, runs OCR + LLM extraction, and renders browsable markdown notes.

## Pipeline

```
PDF  ──►  ingest  ──►  ocr  ──►  llm  ──►  render  ──►  .md note
```

Each step can be run individually or all at once with `consume`:

| Command   | What it does                                              |
|-----------|-----------------------------------------------------------|
| `scan`    | Preview which PDFs are new vs already in the vault        |
| `ingest`  | Copy/move PDFs into the vault, deduplicated by SHA-256    |
| `ocr`     | Run Mistral OCR on ingested PDFs                          |
| `llm`     | Extract structured fields (merchant, date, total) via LLM |
| `render`  | Generate Obsidian markdown notes from extracted metadata   |
| `consume` | Run the full pipeline (ingest → ocr → llm → render)      |

## Vault structure

```
vault/
  Receipts/
    2024-06-01 - Coffee Shop - $5.75.md
    2024-09-20 - Bookstore - $29.99.md
    _assets_/
      <sha256a>/
        src/        ← original.pdf + metadata.json
        ocr/        ← OCR output (json + txt)
        llm/        ← extracted fields (json)
      <sha256b>/
        ...
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
```

## Usage

```bash
# Preview what would happen (no files moved, no API calls)
obagent receipt scan ./inbox

# Full pipeline — consume all PDFs from a directory
obagent receipt consume ./inbox

# Or run steps individually
obagent receipt ingest ./inbox
obagent receipt ocr
obagent receipt llm
obagent receipt render

# Render a single entry by sha256
obagent receipt render <sha256>

# Re-process everything from scratch
obagent receipt consume --overwrite ./inbox

# Keep original PDFs (copy instead of move)
obagent receipt consume --keep-original ./inbox

# Use a custom vault subdirectory
obagent receipt --path Invoices consume ./inbox
```

## Development

```bash
just check   # verify formatting, lint, and run tests
just fix     # auto-fix formatting and lint issues
```
