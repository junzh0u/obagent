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
| `consume` | Run the full pipeline (ingest → ocr → llm → render)   |
| `export`  | Copy source files out of the vault under their note names (documents + receipts) |

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
export OBAGENT_EXPORT=/path/to/export/dir            # default for `document export` and `receipt export`
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

# Re-process everything from scratch
obagent receipt consume --overwrite ./inbox

# Keep original PDFs (copy instead of move)
obagent receipt consume --keep-original ./inbox

# Use a custom vault subdirectory
obagent receipt --path Invoices consume ./inbox

# Export source files out of the vault, grouped by year/month under their note names.
# The type subdir (Documents/, Receipts/, or your --path override) is appended automatically.
obagent document export --output-dir /tmp/exported
obagent receipt export --output-dir /tmp/exported
# Layout: /tmp/exported/{Documents,Receipts}/YYYY/YYYY-MM/{note}.{pdf,jpg,jpeg}
# Notes without a YYYY-MM filename prefix land in {type}/undated/.
# Also reads OBAGENT_EXPORT as the default for --output-dir.
```

## Development

```bash
just check   # verify formatting, lint, and run tests
just fix     # auto-fix formatting and lint issues
```
