"""Two-way sync: reconcile vault notes and Notion rows after the initial link.

A git-style 3-way merge against the **shadow** (the field values at last sync):

    base = shadow[notion_id]; v = vault now; n = Notion now
      v == n            -> agree
      v == base, n != base -> Notion changed  -> adopt into vault
      n == base, v != base -> vault changed   -> push to Notion
      else (both moved)    -> conflict -> last-writer-wins by timestamp + log

Correctness lives in the shadow comparison; the watermark (Notion
``last_edited_time``) and the last-sync git commit only *narrow* candidates, so
losing them just triggers a full self-healing pass. Linked by ``notion_id``;
runs per type that has a configured data source (bank statements are skipped).
"""

import json
import os
import shutil
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import click

from commands.document.pipeline import DocumentFields
from commands.notion.backfill import (
    FOLDER,
    TITLE_FIELDS,
    VaultNote,
    gather_vault,
    inject_notion_id,
    load_shadow,
    save_shadow,
)
from commands.receipt.pipeline import ReceiptFields
from lib import notion_fieldmap as fm
from lib.constants import ASSETS_DIR
from lib.notion_api import FILE_NAME_LIMIT, NotionClient, truncate_u16
from lib.utils import source_file

HINTS_PATH = ".obagent/notion-sync-hints.json"
FIELDS_CLASS = {"receipt": ReceiptFields, "document": DocumentFields}


# -- 3-way merge (pure) ----------------------------------------------------


def merge_fields(
    type_name: str,
    base: dict[str, str],
    vault_front: dict[str, str],
    notion_ed: dict[str, str],
    conflict_winner: str,
) -> tuple[dict[str, str], dict, dict[str, str], list[tuple[str, str, str]]]:
    """Per-field 3-way merge. Returns (vault_updates, notion_property_updates,
    new_shadow, conflicts). ``conflict_winner`` ('vault'|'notion') decides
    fields that moved on both sides."""
    vault_updates: dict[str, str] = {}
    notion_updates: dict = {}
    shadow: dict[str, str] = {}
    conflicts: list[tuple[str, str, str]] = []
    for f in fm.FIELD_MAPS.get(type_name, []):
        k = f.vault_key
        v, n = vault_front.get(k, ""), notion_ed.get(k, "")
        nv, nn = f.normalize(v), f.normalize(n)
        b = base.get(k)
        nb = f.normalize(b) if b is not None else None
        if nv == nn:
            shadow[k] = v
        elif nb is not None and nb == nv:  # vault unchanged -> Notion wins
            vault_updates[k] = n
            shadow[k] = n
        elif nb is not None and nb == nn:  # Notion unchanged -> vault wins
            notion_updates.update(f.to_notion(v))
            shadow[k] = v
        else:  # both moved (or no base) -> conflict
            if conflict_winner == "notion":
                vault_updates[k] = n
                shadow[k] = n
            else:
                notion_updates.update(f.to_notion(v))
                shadow[k] = v
            conflicts.append((k, v, n))
    return vault_updates, notion_updates, shadow, conflicts


# -- vault write-back ------------------------------------------------------


def write_back(note: VaultNote, field_updates: dict[str, str], type_name: str) -> Path:
    """Apply adopted field values to a note (rebuild via the type's Fields so
    lists/summary/title are formatted correctly), renaming if a title field moved.
    Preserves consumed_at, notion_id, and the asset embeds."""
    front = {**note.frontmatter, **field_updates}
    cls = FIELDS_CLASS[type_name]
    fields = cls({k: front.get(k, "") for k in cls.expected_keys()})
    text = note.path.read_text()
    embeds = "".join(ln + "\n" for ln in text.split("\n") if ln.startswith("![["))
    content = (
        fields.format_frontmatter(
            consumed_at=front.get("consumed_at", ""),
            notion_id=front.get("notion_id", ""),
        )
        + fields.format_body()
        + embeds
    )
    note.path.write_text(content)
    if field_updates.keys() & TITLE_FIELDS.get(type_name, set()):
        new_path = note.path.with_name(fields.make_title() + ".md")
        if new_path != note.path and not new_path.exists():
            note.path.rename(new_path)
            return new_path
    return note.path


def delete_note(vault: Path, type_name: str, note: VaultNote) -> None:
    """Delete a linked note and its source asset dir(s). DESTRUCTIVE — removes the
    original scanned file(s). Used only by --prune to mirror a Notion-trash."""
    assets = vault / FOLDER[type_name] / ASSETS_DIR
    note.path.unlink(missing_ok=True)
    for sha in note.shas:
        d = assets / sha
        if d.exists():
            shutil.rmtree(d)


# -- sync state + candidate gathering --------------------------------------


def load_hints(vault: Path) -> dict[str, str]:
    p = vault / HINTS_PATH
    return json.loads(p.read_text()) if p.exists() else {}


def save_hints(vault: Path, hints: dict[str, str]) -> None:
    p = vault / HINTS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(hints, indent=2, sort_keys=True))


def vault_index(vault: Path) -> dict[str, tuple[str, VaultNote]]:
    """Map notion_id -> (type_name, VaultNote) for every linked note."""
    idx: dict[str, tuple[str, VaultNote]] = {}
    for t, folder in FOLDER.items():
        for n in gather_vault(vault / folder, t):
            if n.notion_id:
                idx[n.notion_id] = (t, n)
    return idx


def _git_changed_notion_ids(vault: Path, commit: str, idx: dict) -> set[str]:
    """notion_ids of vault notes changed since ``commit`` (incl. working tree)."""
    try:
        root = subprocess.run(
            ["git", "-C", str(vault), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        out = subprocess.run(
            ["git", "-C", str(vault), "diff", "--name-only", commit, "--", "*.md"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return set(idx.keys())  # can't diff -> full pass
    changed = {(Path(root) / line).resolve() for line in out.splitlines() if line}
    return {nid for nid, (_, n) in idx.items() if n.path.resolve() in changed}


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _dt(t0: float) -> str:
    return f"{time.monotonic() - t0:.1f}s"


def _head_commit(vault: Path) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(vault), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return ""


# -- new-note creation (push unlinked notes to Notion) ---------------------


def _existing_row_by_sha(
    client: NotionClient, ds_id: str, shas: list[str]
) -> str | None:
    """Page id of a row already carrying this note's sha, else None.

    The create-crash / dedup guard: a sha is effectively unique, so a row whose
    ``Sha`` contains the note's first sha is the same note — covers a crash
    between create and the notion_id write-back, and plain re-runs. Skipped when
    the note has no sha (nothing to match on).
    """
    if not shas:
        return None
    r = client.query(
        ds_id,
        filter={"property": "Sha", "rich_text": {"contains": shas[0]}},
        page_size=1,
    )
    results = r.get("results", [])
    return results[0]["id"] if results else None


def _upload_sources(
    client: NotionClient, vault: Path, type_name: str, note: VaultNote
) -> list[tuple[str, str]]:
    """Upload the note's source file(s); return (upload_id, name) pairs for the
    ``File`` property. The first file uses the note stem, extras get a -sha12
    suffix (mirrors export). A missing source is warned and skipped, not fatal."""
    base = vault / FOLDER[type_name] / ASSETS_DIR
    pairs: list[tuple[str, str]] = []
    for i, sha in enumerate(note.shas):
        src = source_file(base / sha)
        if src is None:
            print(
                f"  warning: no source for {sha[:12]} ({note.path.name!r})", flush=True
            )
            continue
        stem = note.path.stem if i == 0 else f"{note.path.stem}-{sha[:12]}"
        name = truncate_u16(stem, FILE_NAME_LIMIT - len(src.suffix)) + src.suffix
        pairs.append((client.upload_file(src, name), name))
    return pairs


def create_unlinked(
    client: NotionClient,
    vault: Path,
    ds_by_type: dict[str, str],
    shadow: dict[str, dict[str, str]],
    stats: defaultdict[str, int],
    *,
    dry_run: bool,
) -> None:
    """Create a Notion row for every note with no notion_id (new since the last
    link): upload its source file(s), set editable fields + Sha + Consumed At,
    write the new id back into the note, and seed the shadow. Adopts a row that
    already bears the note's sha instead of creating a duplicate."""
    for t, ds in ds_by_type.items():
        for note in gather_vault(vault / FOLDER[t], t):
            if note.notion_id:
                continue
            existing = _existing_row_by_sha(client, ds, note.shas)
            if dry_run:
                action = "adopt" if existing else "create"
                stats[f"would_{action}"] += 1
                print(f"  -> {action} {note.path.name!r}", flush=True)
                continue
            if existing:
                page_id, outcome = existing, "adopted"
            else:
                props = {
                    **fm.editable_properties(t, note.frontmatter),
                    **fm.sha_property(note.shas),
                    **fm.consumed_at_property(note.frontmatter.get("consumed_at", "")),
                    **fm.file_property(_upload_sources(client, vault, t, note)),
                }
                page_id, outcome = client.create_page(ds, props)["id"], "created"
            note.path.write_text(inject_notion_id(note.path.read_text(), page_id))
            shadow[page_id] = {
                f.vault_key: note.frontmatter.get(f.vault_key, "")
                for f in fm.FIELD_MAPS.get(t, [])
            }
            stats[outcome] += 1


# -- orchestration ---------------------------------------------------------


def run_sync(
    client: NotionClient,
    vault: Path,
    ds_by_type: dict[str, str],
    *,
    dry_run: bool = False,
    full: bool = False,
    prune: bool = False,
) -> dict[str, int]:
    """One reconciliation pass. ``full`` ignores the watermark/commit hints and
    checks every linked record (self-healing). ``prune`` propagates deletions both
    ways (DESTRUCTIVE): a trashed Notion row deletes its linked vault note + source
    file, and a deleted vault note trashes its Notion row. ``prune`` forces a full
    scan — the complete live-row set is needed to tell 'trashed' from 'unchanged'."""
    t_start = time.monotonic()
    shadow = load_shadow(vault)
    hints = load_hints(vault)
    watermark = None if full else hints.get("watermark")
    head = _head_commit(vault)
    if not head:
        print(
            "  note: no git repo visible at the vault — vault-side narrowing is "
            "disabled, so every run is a full pass. Mount the dir containing .git.",
            flush=True,
        )
    t0 = time.monotonic()
    idx = vault_index(vault)
    print(f"  vault scan: {len(idx)} linked notes [{_dt(t0)}]", flush=True)
    stats: defaultdict[str, int] = defaultdict(int)

    # Notion-changed candidates (+ advance the watermark to Notion's clock).
    # --prune needs the COMPLETE live-row set (to tell a trashed row from an
    # unchanged one), so it forces an unfiltered full scan.
    full_scan = full or prune or not watermark
    t0 = time.monotonic()
    notion_changed: dict[str, tuple[str, dict[str, str], str]] = {}
    live_by_type: dict[str, set[str]] = {t: set() for t in ds_by_type}
    max_edited = watermark or ""
    for t, ds in ds_by_type.items():
        flt = (
            None
            if full_scan
            else {
                "timestamp": "last_edited_time",
                "last_edited_time": {"on_or_after": watermark},
            }
        )
        for page in client.iter_pages(ds, filter=flt):
            le = page.get("last_edited_time", "")
            notion_changed[page["id"]] = (
                t,
                fm.read_editable(t, page["properties"]),
                le,
            )
            live_by_type[t].add(page["id"])
            max_edited = max(max_edited, le)
    scope = "FULL scan" if full_scan else f"since {watermark}"
    print(
        f"  notion query [{scope}]: {len(notion_changed)} rows [{_dt(t0)}]", flush=True
    )

    # -- prune: deletion propagation (DESTRUCTIVE, opt-in) --------------------
    # Direction 1 (Notion-trash -> vault-delete) needs the full live set above.
    pruned: set[str] = set()
    vault_missing = bool(prune and shadow and not idx)
    if vault_missing:
        print(
            "  prune: vault scan found 0 linked notes but the shadow is non-empty — "
            "skipping deletes (is the vault mounted/readable?)",
            flush=True,
        )
    if prune and not vault_missing:
        for t in ds_by_type:
            linked = {nid for nid, (tt, _) in idx.items() if tt == t}
            # A data source that returned zero live rows but still has linked notes
            # is almost certainly a bad id/outage, not a mass-trash — skip it
            # rather than wipe those notes.
            if linked and not live_by_type[t]:
                print(
                    f"  prune: 0 live {t} rows but {len(linked)} linked — skipping "
                    "delete (check the data source id)",
                    flush=True,
                )
                continue
            for nid in linked - live_by_type[t]:
                _, note = idx[nid]
                if dry_run:
                    print(
                        f"  -> DELETE {note.path.name[:40]!r} (Notion row trashed)",
                        flush=True,
                    )
                    stats["would_delete_vault"] += 1
                else:
                    delete_note(vault, t, note)
                    print(
                        f"  deleted {note.path.name[:40]!r} (Notion row trashed)",
                        flush=True,
                    )
                    stats["vault_deleted"] += 1
                pruned.add(nid)
        if not dry_run:
            for nid in pruned:
                idx.pop(nid, None)
                shadow.pop(nid, None)

    # vault-changed candidates (git diff since last sync; full pass if no commit)
    if full or not hints.get("commit"):
        vault_changed = set(idx)
        vsrc = "--full" if full else "FULL (no commit hint)"
    else:
        vault_changed = _git_changed_notion_ids(vault, hints["commit"], idx)
        vsrc = "git-diff"
    candidates = (set(notion_changed) | vault_changed) - pruned
    print(
        f"  candidates: {len(candidates)} (notion {len(notion_changed)}, "
        f"vault {len(vault_changed)} [{vsrc}])",
        flush=True,
    )

    t0 = time.monotonic()
    fetched = 0
    for nid in candidates:
        if nid not in idx:
            # The vault note is gone. Under --prune, a still-live row we had linked
            # (in the shadow) is propagated as a Notion-trash; else just flag it. A
            # live row never linked (not in the shadow) isn't ours to touch.
            if nid not in shadow:
                continue
            if prune and not vault_missing and nid in notion_changed:
                if dry_run:
                    print(
                        f"  -> TRASH notion row {nid} (vault note deleted)", flush=True
                    )
                    stats["would_trash_notion"] += 1
                else:
                    client.trash_page(nid)
                    shadow.pop(nid, None)
                    print(
                        f"  trashed notion row {nid} (vault note deleted)", flush=True
                    )
                    stats["notion_trashed"] += 1
            else:
                stats["deleted_in_vault"] += 1  # row exists, note gone -> flag only
            continue
        t, note = idx[nid]
        base = shadow.get(nid, {})
        if nid in notion_changed:
            _, ned, le = notion_changed[nid]
        else:  # vault-only candidate: fetch current Notion state
            fetched += 1
            page = client.api("GET", f"https://api.notion.com/v1/pages/{nid}")
            if page.get("archived") or page.get("in_trash"):
                stats["archived_in_notion"] += 1
                continue
            ned, le = (
                fm.read_editable(t, page["properties"]),
                page.get("last_edited_time", ""),
            )
        winner = "notion" if le >= _mtime_iso(note.path) else "vault"
        vu, nu, sh, conflicts = merge_fields(t, base, note.frontmatter, ned, winner)
        if not vu and not nu:
            shadow[nid] = sh
            stats["unchanged"] += 1
            continue
        for k, v, n in conflicts:
            print(
                f"  CONFLICT {note.path.name[:34]!r} {k}: vault={v!r} notion={n!r} "
                f"-> {winner} wins",
                flush=True,
            )
            stats["conflicts"] += 1
        if dry_run:
            if vu:
                print(f"  -> vault {note.path.name[:34]!r}: {vu}", flush=True)
            if nu:
                print(f"  -> notion {note.path.name[:34]!r}: {list(nu)}", flush=True)
            stats["would_change"] += 1
            continue
        if vu:
            write_back(note, vu, t)
            stats["vault_updated"] += 1
        if nu:
            client.update_page(nid, nu)
            stats["notion_updated"] += 1
        shadow[nid] = sh
    print(
        f"  reconcile: {len(candidates)} candidates, {fetched} per-note fetches "
        f"[{_dt(t0)}]",
        flush=True,
    )

    # Push notes that have no Notion row yet (new since the last link).
    t0 = time.monotonic()
    create_unlinked(client, vault, ds_by_type, shadow, stats, dry_run=dry_run)
    print(f"  create pass [{_dt(t0)}]", flush=True)

    if prune and not vault_missing and not dry_run:
        # GC shadow rows whose note AND row are both gone (deleted on both sides).
        # Safe only with the full live set in hand (which --prune guarantees).
        for nid in set(shadow) - set(idx) - set(notion_changed):
            shadow.pop(nid, None)
    if not dry_run:
        save_shadow(vault, shadow)
        save_hints(vault, {"watermark": max_edited, "commit": head})
    print(f"  total [{_dt(t_start)}]", flush=True)
    return dict(stats)


# -- CLI -------------------------------------------------------------------

# type -> env var holding its Notion data source id. No defaults: these are
# workspace-specific, so they must be configured explicitly.
_DS_ENV = {
    "receipt": "OBAGENT_NOTION_RECEIPT_DS",
    "document": "OBAGENT_NOTION_DOCUMENT_DS",
}


def data_sources() -> dict[str, str]:
    """Map type -> data source id from OBAGENT_NOTION_<TYPE>_DS. Types whose env
    var is unset are skipped (not synced)."""
    return {t: os.environ[ev] for t, ev in _DS_ENV.items() if os.environ.get(ev)}


@click.group()
def notion():
    """Sync the vault with Notion (Receipts + Documents)."""


@notion.command("sync")
@click.option("--dry-run", is_flag=True, help="Report changes without writing.")
@click.option(
    "--full", is_flag=True, help="Ignore the watermark; check every linked record."
)
@click.option(
    "--prune",
    is_flag=True,
    help="Propagate DELETIONS both ways (DESTRUCTIVE): trash a Notion row whose "
    "vault note is gone, and delete a vault note + its source file when its Notion "
    "row is trashed. Forces a full scan. Pair with --dry-run to preview.",
)
@click.pass_context
def sync_command(ctx, dry_run, full, prune):
    """Reconcile the vault and Notion two-way (3-way merge against the shadow)."""
    client = NotionClient()
    if not client.token:
        raise click.UsageError("NOTION_TOKEN is not set.")
    ds = data_sources()
    if not ds:
        raise click.UsageError(
            "No Notion data sources configured. Set OBAGENT_NOTION_RECEIPT_DS "
            "and/or OBAGENT_NOTION_DOCUMENT_DS."
        )
    stats = run_sync(
        client, Path(ctx.obj["vault"]), ds, dry_run=dry_run, full=full, prune=prune
    )
    summary = ", ".join(f"{v} {k}" for k, v in stats.items())
    click.secho(summary or "nothing to do", bold=True)
