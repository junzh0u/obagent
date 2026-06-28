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

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from commands.render import _SUMMARY_RE, _parse_frontmatter
from lib import notion_fieldmap as fm
from lib.notion_api import NotionClient
from lib.utils import SHA_RE


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
