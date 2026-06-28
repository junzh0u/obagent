"""Initial backfill: link existing Notion rows to vault notes (one-time).

The 2026-06 import created rows with no ``notion_id`` link. This matches each
existing row to its vault note and (when not a dry run) records the link —
without re-uploading attachments.

Matching keys are normalized so they survive cosmetic differences:
- **receipt**  -> ``(date, merchant, numeric-amount)`` — robust to currency-format
  (``¥3,775`` vs ``JPY 3,775``), decimals (``$600`` vs ``$600.00``), and the
  quoted ``"76"`` merchant.
- **document** -> ``(title, date)`` — bare ``Name`` alone is not unique.

``--dry-run`` reports matched / vault-only (would create) / notion-only
(orphans) / ambiguous (key collisions) and writes nothing.
"""

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from commands.render import _SUMMARY_RE, _parse_frontmatter
from lib import notion_fieldmap as fm
from lib.notion_api import NotionClient
from lib.utils import SHA_RE

FOLDER = {"receipt": "Receipts", "document": "Documents"}
# Fields that appear in the filename/title (a change here triggers a rename).
TITLE_FIELDS = {"receipt": {"merchant", "date", "total"}, "document": {"title", "date"}}
SHADOW_PATH = ".obagent/notion-shadow.json"


def _amount(s: str) -> str:
    """Numeric value of a total, currency-agnostic: '$600' and '$600.00' -> '600.00';
    '¥3,775' and 'JPY 3,775' -> '3775.00'. (Matching ignores decimal/format noise.)"""
    digits = re.sub(r"[^\d.]", "", s or "")
    try:
        return f"{float(digits):.2f}" if digits else ""
    except ValueError:
        return ""


def _merchant(s: str) -> str:
    """Strip surrounding quotes/space (Notion stores the '76' brand as '\"76\"')."""
    return (s or "").strip().strip('"').strip()


# -- match keys ------------------------------------------------------------

Key = tuple[str, ...]


def notion_match_key(type_name: str, props: dict) -> Key:
    """Normalized match key for a Notion page's properties."""
    ed = fm.read_editable(type_name, props)
    if type_name == "receipt":
        return (ed["date"], _merchant(ed["merchant"]), _amount(ed["total"]))
    return (ed["title"].strip(), ed["date"])  # document


def vault_match_key(type_name: str, frontmatter: dict[str, str]) -> Key:
    """Normalized match key for a vault note's frontmatter (same shape as above)."""
    if type_name == "receipt":
        return (
            frontmatter.get("date", ""),
            _merchant(frontmatter.get("merchant", "")),
            _amount(frontmatter.get("total", "")),
        )
    return (frontmatter.get("title", "").strip(), frontmatter.get("date", ""))


# -- gathering -------------------------------------------------------------


@dataclass
class VaultNote:
    path: Path
    key: Key
    shas: list[str]
    frontmatter: dict[str, str]
    notion_id: str = ""


@dataclass
class NotionRow:
    page_id: str
    key: Key
    sha_text: str  # current Sha property value (for idempotency / re-link)


def gather_vault(type_dir: Path, type_name: str) -> list[VaultNote]:
    """Read every note in ``type_dir`` into a VaultNote (key + shas + frontmatter)."""
    notes: list[VaultNote] = []
    for md in sorted(type_dir.glob("*.md")):
        text = md.read_text()
        front = _parse_frontmatter(text) or {}
        # Documents keep `summary` in a body callout, not frontmatter (mirror
        # render.index_existing_notes so the value round-trips for diffing).
        m = _SUMMARY_RE.search(text)
        if m:
            front["summary"] = m.group(1)
        notes.append(
            VaultNote(
                path=md,
                key=vault_match_key(type_name, front),
                shas=sorted(set(SHA_RE.findall(text))),
                frontmatter=front,
                notion_id=front.get("notion_id", ""),
            )
        )
    return notes


def gather_notion(client: NotionClient, ds_id: str, type_name: str) -> list[NotionRow]:
    """Query every row in a data source into a NotionRow (key + current Sha)."""
    rows: list[NotionRow] = []
    for page in client.iter_pages(ds_id):
        props = page.get("properties", {})
        rows.append(
            NotionRow(
                page_id=page["id"],
                key=notion_match_key(type_name, props),
                sha_text=fm.read_plain_text(props.get("Sha", {})),
            )
        )
    return rows


# -- classification --------------------------------------------------------


@dataclass
class MatchReport:
    matched: list[tuple[Key, str, Path]] = field(
        default_factory=list
    )  # key, page_id, md
    vault_only: list[VaultNote] = field(default_factory=list)  # would be created
    notion_only: list[tuple[Key, str]] = field(default_factory=list)  # orphan rows
    ambiguous: list[tuple[Key, list[str], list[Path]]] = field(default_factory=list)


def classify(notes: list[VaultNote], rows: list[NotionRow]) -> MatchReport:
    """Pair vault notes with Notion rows by key; bucket the rest."""
    vault_by_key: dict[Key, list[VaultNote]] = defaultdict(list)
    for n in notes:
        vault_by_key[n.key].append(n)
    rows_by_key: dict[Key, list[NotionRow]] = defaultdict(list)
    for r in rows:
        rows_by_key[r.key].append(r)

    report = MatchReport()
    for key, rs in rows_by_key.items():
        ns = vault_by_key.get(key, [])
        if len(rs) > 1 or len(ns) > 1:
            report.ambiguous.append(
                (key, [r.page_id for r in rs], [n.path for n in ns])
            )
        elif ns:
            report.matched.append((key, rs[0].page_id, ns[0].path))
        else:
            report.notion_only.append((key, rs[0].page_id))
    for key, ns in vault_by_key.items():
        if key not in rows_by_key:
            report.vault_only.extend(ns)
    return report


# -- write step (link + reconcile + shadow) --------------------------------


def load_shadow(vault: Path) -> dict[str, dict[str, str]]:
    p = vault / SHADOW_PATH
    return json.loads(p.read_text()) if p.exists() else {}


def save_shadow(vault: Path, shadow: dict[str, dict[str, str]]) -> None:
    p = vault / SHADOW_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(shadow, ensure_ascii=False, indent=2, sort_keys=True))


def inject_notion_id(text: str, notion_id: str) -> str:
    """Insert ``notion_id`` as the last frontmatter line (idempotent)."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return text
    end = lines.index("---", 1)
    if any(ln.startswith("notion_id:") for ln in lines[1:end]):
        return text
    lines.insert(end, f"notion_id: {notion_id}")
    return "\n".join(lines)


def reconcile(
    type_name: str, note: VaultNote, ned: dict[str, str]
) -> tuple[dict[str, str], dict, dict[str, str]]:
    """Decide per-field winners between a vault note and its Notion row.

    Returns (vault_updates, notion_property_updates, shadow_values). Default:
    Notion wins on a diff (adopt into the vault). Exception: a merchant diff
    that is only stray quotes is a Notion import artifact -> push the clean
    vault value to Notion instead.
    """
    vault_updates: dict[str, str] = {}
    notion_updates: dict = {}
    shadow: dict[str, str] = {}
    for f in fm.FIELD_MAPS.get(type_name, []):
        v = note.frontmatter.get(f.vault_key, "")
        nv = ned.get(f.vault_key, "")
        if f.normalize(v) == f.normalize(nv):
            shadow[f.vault_key] = v
        elif f.vault_key == "merchant" and nv.strip().strip('"') == v.strip():
            notion_updates.update(f.to_notion(v))  # artifact -> vault wins
            shadow[f.vault_key] = v
        else:
            vault_updates[f.vault_key] = nv  # Notion wins -> adopt into vault
            shadow[f.vault_key] = nv
    return vault_updates, notion_updates, shadow


def _stem(type_name: str, front: dict[str, str]) -> str:
    if type_name == "receipt":
        from commands.receipt.pipeline import ReceiptFields

        return ReceiptFields(
            {k: front.get(k, "") for k in ("merchant", "date", "total")}
        ).make_title()
    from commands.document.pipeline import DocumentFields

    return DocumentFields(
        {k: front.get(k, "") for k in ("title", "date", "tags", "people")}
    ).make_title()


def _apply_vault(
    note: VaultNote, notion_id: str, vault_updates: dict[str, str], type_name: str
) -> Path:
    """Write notion_id + adopted scalar fields into the .md, renaming if needed."""
    text = note.path.read_text()
    for k, val in vault_updates.items():
        text = re.sub(rf"(?m)^{re.escape(k)}: .*$", f"{k}: {val}", text, count=1)
    text = inject_notion_id(text, notion_id)
    note.path.write_text(text)
    if vault_updates.keys() & TITLE_FIELDS.get(type_name, set()):
        new_front = {**note.frontmatter, **vault_updates}
        new_path = note.path.with_name(_stem(type_name, new_front) + ".md")
        if new_path != note.path and not new_path.exists():
            note.path.rename(new_path)
            return new_path
    return note.path


def run_backfill(
    client: NotionClient,
    vault: Path,
    type_name: str,
    ds_id: str,
    *,
    dry_run: bool = True,
    limit: int | None = None,
) -> dict[str, int]:
    """Link matched rows: write notion_id (+ adopt diffs) to the vault, set
    Sha/Consumed At (+ artifact fixes) on the row, and record the shadow base.
    Skips notes already linked (idempotent/resumable)."""
    notes = {n.key: n for n in gather_vault(vault / FOLDER[type_name], type_name)}
    shadow = load_shadow(vault)
    stats: defaultdict[str, int] = defaultdict(int)
    done = 0
    for page in client.iter_pages(ds_id):
        if limit and done >= limit:
            break
        props = page.get("properties", {})
        note = notes.get(notion_match_key(type_name, props))
        if note is None:
            stats["unmatched_row"] += 1
            continue
        if note.notion_id:
            stats["already_linked"] += 1
            continue
        page_id = page["id"]
        ned = fm.read_editable(type_name, props)
        vu, nu, sh = reconcile(type_name, note, ned)
        if dry_run:
            stats["would_link"] += 1
            if vu:
                stats["would_adopt"] += 1
                for k, val in vu.items():
                    print(
                        f"  adopt {note.path.name[:36]!r} {k}: "
                        f"{note.frontmatter.get(k, '')!r} -> {val!r}"
                    )
            if nu:
                stats["would_fix_notion"] += 1
            continue
        # vault side: notion_id + adopted fields (+ rename)
        _apply_vault(note, page_id, vu, type_name)
        # notion side: Sha + Consumed At (+ any artifact fixes)
        row_props = {
            **fm.sha_property(note.shas),
            **fm.consumed_at_property(note.frontmatter.get("consumed_at", "")),
            **nu,
        }
        client.update_page(page_id, row_props)
        shadow[page_id] = sh
        stats["linked"] += 1
        done += 1
    if not dry_run:
        save_shadow(vault, shadow)
    return dict(stats)
