# Smart inbox: auto-classify loose files in the consume root — plan

**Status (2026-07-01): BUILT.** Drop a file into `$OBAGENT_CONSUME/` (not pre-sorted
into a type subdir) and obagent decides its type: **OCR once → LLM classify → run the
normal per-type llm→render, no re-OCR.** Pre-sorted files in `{type}/` subdirs are
untouched. Landed: `Pipeline.classify_description` + `CLASSIFY_MODEL`;
`commands/classify.py`; `_classify_and_consume_root` + `--classify`/`--classify-model`
in `consume_all`; tests; docs; and the `gmail-ingest.gs` follow-on (dropped
`ROUTING_RULES`, unpinned mail → consume root). **Deploy note:** the NAS must
`git pull && uv tool install .` before the gmail change takes effect (else root mail is
ignored). Recommend gitignoring `.obagent/staging/` in the vault repo.

## Goal / UX
- `$OBAGENT_CONSUME/Receipts/…`, `Documents/…`, `Bank Statements/…` → per-type consume,
  exactly as today.
- `$OBAGENT_CONSUME/<loose file>` → **classified**: OCR, ask an LLM which registered
  type it is, place it in `vault/{Type}/…`, extract + render. No pre-sorting needed.

## Core challenge
Type determines the vault location (`vault/{Type}/_assets_/{sha}/`), but the type is
only known **after** OCR + classification. OCR is type-independent. So the pipeline
reorders to **OCR → classify → place**, where today it's ingest-into-known-type → OCR.

## Design — the flow (per loose root file)
```
sha = sha256(file)
if sha already under any vault/{Type}/_assets_/:          # global dedup, pre-OCR
    file.unlink()  → host delete drains Drive; continue   # already consumed elsewhere

staging = ingest_source(file, vault, ".obagent/staging", keep_original=True)  # COPY → neutral asset dir
run_ocr(staging)                                          # OCR once (Mistral)
pipeline = classify_document(read_ocr_text(staging), openai)   # NEW: LLM → a registered Pipeline
move(staging → vault/{pipeline.default_path}/_assets_/{sha})   # relocate (same-fs rename)
file.unlink()                                            # root original now committed → drains Drive
extract_fields(final, pipeline)                          # OCR already present → not re-run
render_note(final, pipeline)
```

**Why staging + relocate:** reuses `ingest_source` / `run_ocr` / `extract_fields` /
`render_note` **unchanged** — only the classifier + orchestration are new.
`.obagent/staging` is same-filesystem, so the relocate is an atomic `rename`; it's
transient (cleaned at the start of each root pass, so it's empty by publish time — never
committed; belt-and-suspenders: gitignore `.obagent/staging/` in the vault repo).

**"Skip OCR" is free:** after relocation the asset already has `ocr/`, so
`extract_fields` reads it and `run_ocr` (its existing `overwrite` guard) would no-op.
No new "skip" flag.

**Alternative considered:** decouple `run_ocr` to OCR a temp file first, then
ingest-into-type + drop the OCR in. More invasive (touches a tested function) — rejected
in favor of staging+relocate.

## New pieces
- **`commands/classify.py` — `classify_document(ocr_text, openai_client, *, model, default_pipeline, max_chars=8000)`**
  → returns a `Pipeline`. Builds the prompt from `Pipeline._registry`
  (`default_path` + `classify_description` per type), one small chat completion, matches
  the answer case-insensitively to a registered `default_path`, falls back to
  `default_pipeline` (Documents) on no-match / empty OCR. Bounds tokens with `max_chars`.
- **`Pipeline.classify_description` (classvar)** — one line per type for the prompt.
  Keeps the classifier decoupled and auto-extensible (a newly-registered type is
  included automatically):
  - Receipt — "A purchase receipt, invoice, or order confirmation: a transaction with a
    merchant, amount(s), and date."
  - Bank Statement — "A bank or credit-card account statement: a statement period, an
    account number, balances/transactions."
  - Document — "Any other document (letters, forms, tax filings, contracts, notices,
    IDs). The catch-all when it's not clearly a receipt or a bank statement."
- **`lib/constants.py` — `CLASSIFY_MODEL = LLM_MODEL`** (the task is simple; a cheaper
  model is fine). CLI `--classify-model` overrides.

## Integration — `consume_all` only (top-level `obagent consume`)
Classification is inherently cross-type, so it lives in the aggregator (which
`run.sh` already invokes — no `run.sh` change). After the existing per-type subdir loop:
```
if classify:                                      # --classify / --no-classify, default ON
    root_sources = [f for f in input_dir.iterdir()
                    if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS]  # depth-1, loose
    root_sources = _filter_stable(root_sources, min_age)                          # same quiescence gate
    _classify_and_consume_root(vault, root_sources, ..., classify_model=classify_model)
```
- `_classify_and_consume_root` lives in `commands/consume.py`; cleans `.obagent/staging`
  at the start, then runs the flow above per file. Resolves the default pipeline as the
  registered one with `default_path == "Documents"`.
- Per-type `obagent {type} consume` is **unchanged** (it knows its type).

## Dedup, retry, failure isolation
- **Global dedup before OCR** — sha checked against *all* type dirs first, so a
  re-dropped already-consumed file is removed (drains) without wasting an OCR/classify
  call, and the same sha can't land under two types.
- **Retry-safe** — stage as a **copy** (`keep_original=True`); `unlink` the root original
  only *after* relocation. OCR/classify failure → remove the staging copy, leave the
  original in the root for the next pass. (Post-relocation llm/render failure leaves the
  asset for manual `obagent {type} llm|render {sha}` — same as today's per-type consume.)
- **Error policy** matches `_consume_path`: OCR/classify/extract failure raises
  (`ClickException`), render failure warns. *(Optional refinement: per-file isolation so
  one bad scan doesn't abort the batch — note it, not in v1.)*

## Follow-on — simplify `gmail-ingest.gs` (replace ROUTING_RULES with the smart inbox)
Once the classifier exists, the Apps Script no longer guesses the type — it drops
**unpinned** mail into the consume **root** and lets obagent classify. Pins still work.
- **Delete** `ROUTING_RULES` and `DEFAULT_TYPE`.
- `typeFor_(forcedType)` → just `return forcedType;` (the pin label, or `null`).
- `exportMessage_`: `const folder = type ? subfolder_(consumeFolder, type) : consumeFolder;`
  — pinned (`obagent/inbox/receipt|document`) → `consume/<Type>/`; unpinned → `consume/`
  root → obagent classifies. (Files in `<Type>/` bypass classification; root files get it.)
- Update the header docstring + the SEARCH/label comments.
- **Ordering:** this lands **after** the obagent classifier ships (dropping mail in the
  root only works once obagent processes root files). The OCR-based classifier is far
  more accurate than a subject/sender regex, so this is a net simplification.

## Tests
- `classify_document`: mocked OpenAI → each type returned for representative text;
  unknown/empty answer → Documents default.
- `_classify_and_consume_root` (real `ingest_source`, mocked `run_ocr`/`extract_fields`/
  `render_note`, mocked `classify_document`): loose file → relocated under the classified
  type, root original removed, staging cleaned; global-dedup file (sha pre-seeded under a
  type) → removed, no OCR; OCR/classify failure → staging cleaned, root original kept.
- `consume_all`: `--classify` (default) processes root loose files; `--no-classify`
  ignores them; type-subdir files still handled; per-type banner + a classify banner.
- Every registered `Pipeline` has a non-empty `classify_description`.

## Docs
- `README.md` — a "smart inbox" line in the consume section (drop into the root → auto
  type).
- `CLAUDE.md` — Consume section: the classify flow + `Pipeline.classify_description` +
  `CLASSIFY_MODEL`; Email-ingest: unpinned mail → root → classified (once the follow-on
  lands).
- `.env.example` — no new required var (`CLASSIFY_MODEL` has a default; `--classify` is a
  flag).

## Risks
- **Misclassification** — bounded by the catch-all Documents default and the pin escape
  hatch (drop into `{type}/` or use the Gmail pin label to force it). A wrong type is
  fixable by `obagent {type} remove <sha>` + re-drop, or a future `reclassify`/`move`.
- **Extra cost** — one small classify call per loose file (OCR + extract would run
  anyway). Negligible; `--classify-model` can point at a cheap model.
- **Staging leftovers** on a crash — cleaned at each root pass start; recommend
  gitignoring `.obagent/staging/` in the vault.

## Build order
1. `Pipeline.classify_description` on the ABC + the three pipelines; `CLASSIFY_MODEL`.
2. `commands/classify.py` `classify_document` + unit tests.
3. `_classify_and_consume_root` + root scan + `--classify`/`--classify-model` wired into
   `consume_all`; integration tests.
4. Docs.
5. (Follow-on) `gmail-ingest.gs`: drop `ROUTING_RULES`, unpinned → root.
