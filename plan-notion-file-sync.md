# Notion ↔ vault per-file two-way sync — plan

**Status (2026-06-30): DESIGNED.** Per-file (per-sha) two-way sync of a multi-file
note's sources against its Notion row's `File` attachments. Whole-note create/delete
is already handled (`create_unlinked` / `--prune` row delete); this adds the
per-file granularity *within* a surviving multi-file note.

## Goal

- `obagent <type> remove <sha>` (drops one source from a multi-file note) → remove
  that file from the Notion row.
- Delete a file from a Notion row's `File` property → delete that source
  (`_assets_/<sha>/`, the **original scan**) from the vault. **Destructive.**

## Core constraint — no shared file identity

The vault identifies a source by **sha**; Notion's `File` property identifies a file
by **name** + an expiring URL — no sha, no stable id we can read back. The `Sha`
text property is a parallel list with no explicit binding to `File` entries. So:

- **Encode the sha in the upload filename** for multi-file notes, and
- use the **`Sha` property as the 3-way base** (it already records the last-synced
  set).

## Identity & naming

- `_upload_sources`: for **multi-file** notes (`len(shas) > 1`) name every file
  `{stem}-{sha12}{ext}` (today only the *extras* are; the first uses the bare stem).
  Single-file notes keep the clean stem (no ambiguity; per-file removal of the only
  file = whole-note delete, already covered by `--prune`).
- Recover identity: `File` entry name → `sha12` (regex `-([0-9a-f]{12})…$`) → full
  sha (matched against `base ∪ vault`).

## 3-way model (per sha)

- **base** = row `Sha` property (last-synced set)
- **vault** = `set(note.shas)`
- **notion** = shas recovered from the current `File` entry names

| per-sha state | meaning | action | destructive |
|---|---|---|---|
| base+vault, not notion | removed in Notion | `remove_entry(path_dir, sha)` | **yes** |
| base+notion, not vault | removed in vault | drop the `File` entry | no |
| gone from both | converged | update `Sha` only | no |
| in both | unchanged | — | — |

After reconciling, push `File` + `Sha` = the **final vault set** so drift clears.

## Directions & gating

- **vault → Notion** (drop a file from the row): non-destructive → **default-on**.
- **Notion → vault** (delete the original scan): destructive → **under `--prune`**,
  reusing `remove_entry`, with the same outage guards as row-deletion.

## Safety

- **Unparseable `File` name on a row** (renamed in Notion, or un-migrated) → **skip
  the destructive direction for that row**; still do the safe push. Notion→vault
  deletion fires only when `File` names are a clean, fully-parseable subset of `Sha`.
- The existing `--prune` guards (zero live rows / empty-vault scan) still apply.

## Backfill: the migration + a real command

`obagent notion backfill` — currently a one-off, **not** wired as a command. This
makes it the canonical "reconcile existing rows" op and wires it:

- Link unlinked notes to existing rows by normalized key (existing logic) → write
  `notion_id`.
- **Canonicalize** each linked row (idempotent): set `Sha` = `note.shas`; for
  multi-file notes, ensure `File` names are sha-encoded (re-upload only if not).
- Init/update the shadow.
- `--dry-run`. Idempotent → safe to re-run; one run migrates existing rows so the
  per-file mapping works, and closes the "backfilled rows have empty `Sha`" gap.

## Touch points

- `lib/notion_fieldmap.py` — `read_sha(props) -> set[str]`,
  `read_file_sha12(props) -> tuple[set[str], int]` (shas, unparseable count).
- `commands/notion/sync.py` — capture `Sha`/`File` from the page (query + GET);
  per-file 3-way in the reconcile loop; multi-file upload naming in `_upload_sources`.
- `commands/notion/backfill.py` — canonicalize + wire as a CLI command.
- Stats: `files_pushed`, `vault_files_deleted` (+ `would_*` in `--dry-run`).

## Build stages (one commit each)

1. **Naming + fieldmap helpers** — ✅ **done.** `upload_sources` sha-encodes
   multi-file names; `read_sha` / `read_file_sha12`. Pure, non-destructive.
2. **Default-on vault→Notion file push** — *remaining.* drift = `note.shas` vs
   `Sha`; re-push `File`+`Sha` during normal sync.
3. **Backfill as a command + canonicalization** — ✅ **done** (3a: wire
   `obagent notion backfill`; 3b: `upload_sources` relocated to `backfill.py`,
   `run_backfill` canonicalizes every linked row's `Sha`/`File`, idempotent).
4. **`--prune` Notion→vault per-file delete** — *remaining.* parse `File` names,
   3-way, `remove_entry`, fail-safe guards.

## Risks

- A Notion-side file **rename** breaks the sha↔name mapping → mitigated by the
  fail-safe skip (a row with any unparseable name does no destructive deletes).
- One-time re-upload cost in backfill, bounded to multi-file rows.
