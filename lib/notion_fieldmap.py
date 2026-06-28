"""Vault frontmatter <-> Notion property mapping, per document type.

Bridges obagent's frontmatter string values and Notion property JSON. Each
synced field is a :class:`Field` with three operations:

- ``to_notion(value)``   -> a dict of Notion property values (a field may set
  more than one property, e.g. receipt ``total`` -> ``Total`` / ``Non-USD Total``)
- ``from_notion(props)`` -> the canonical string value (read from a page's
  ``properties``)
- ``normalize(value)``   -> a comparable canonical form, for the 3-way merge diff

Notes:
- Receipts ``Name`` is a Notion formula -> **not synced**.
- ``Sha`` / ``Consumed At`` are one-way machine fields (vault -> Notion), set via
  the helpers below, not part of the two-way merge.
- Bank statements are not synced (no entry in ``FIELD_MAPS``).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lib.notion_api import RICH_TEXT_LIMIT, truncate_u16

# -- low-level property codecs ---------------------------------------------


def read_plain_text(prop: dict[str, Any]) -> str:
    """Concatenate the plain text of a ``title`` or ``rich_text`` property."""
    t = prop.get("type")
    items = prop.get(t, []) if t in ("title", "rich_text") else []
    return "".join(
        i.get("plain_text") or i.get("text", {}).get("content", "") for i in items
    )


def _rich_text_value(s: str) -> dict[str, Any]:
    s = truncate_u16(s, RICH_TEXT_LIMIT)
    return {"rich_text": [{"type": "text", "text": {"content": s}}] if s else []}


def _title_value(s: str) -> dict[str, Any]:
    s = truncate_u16(s, RICH_TEXT_LIMIT)
    return {"title": [{"type": "text", "text": {"content": s}}] if s else []}


def _read_date(prop: dict[str, Any]) -> str:
    d = prop.get("date") or {}
    return d.get("start") or ""


def _multi_select_value(s: str) -> dict[str, Any]:
    names = [x.strip() for x in s.split(",") if x.strip()] if s else []
    return {"multi_select": [{"name": n} for n in names]}


def _read_multi_select(prop: dict[str, Any]) -> str:
    return ",".join(opt.get("name", "") for opt in prop.get("multi_select", []))


def _norm_list(s: str) -> str:
    """Order-independent canonical form of a comma-joined list."""
    return ",".join(sorted(x.strip() for x in s.split(",") if x.strip()))


# -- money (receipt total: USD number vs non-USD ISO text) -----------------


def _parse_usd(v: str) -> float:
    digits = re.sub(r"[^\d.\-]", "", v)
    return float(digits) if digits else 0.0


def _total_to_notion(v: str) -> dict[str, Any]:
    """Set ``Total`` (USD number) or ``Non-USD Total`` (ISO text); clear the other."""
    v = v.strip()
    if v.startswith("$"):
        return {"Total": {"number": _parse_usd(v)}, "Non-USD Total": {"rich_text": []}}
    return {"Total": {"number": None}, "Non-USD Total": _rich_text_value(v)}


def _total_from_notion(props: dict[str, Any]) -> str:
    num = (props.get("Total") or {}).get("number")
    if num is not None:
        return f"${num:.2f}"
    return read_plain_text(props.get("Non-USD Total", {}))


_TOTAL_SYMBOLS = "$¥€£₩₹₽₫₱฿₺₴₸₦₵"


def _norm_total(v: str) -> str:
    """Canonical ``currency|amount`` for diffing.

    Collapses decimal/sign/separator formatting (``$2140`` == ``$2140.00``,
    ``-$73.11`` == ``$-73.11``) but keeps the currency distinct
    (``¥230.40`` != ``CNY 230.40``), so legacy symbol-vs-ISO totals still
    surface for adoption.
    """
    v = (v or "").strip()
    num = re.sub(r"[^\d.\-]", "", v)
    try:
        amount = f"{float(num):.2f}" if re.search(r"\d", num) else ""
    except ValueError:
        amount = ""
    m = re.match(r"[A-Z]{3}", v)
    cur = (
        {"RMB": "CNY"}.get(m.group(), m.group())
        if m
        else next((c for c in v if c in _TOTAL_SYMBOLS), "")
    )
    return f"{cur}|{amount}"


# -- field spec ------------------------------------------------------------


@dataclass(frozen=True)
class Field:
    vault_key: str
    to_notion: Callable[[str], dict[str, Any]]
    from_notion: Callable[[dict[str, Any]], str]
    normalize: Callable[[str], str] = field(default=lambda s: s.strip())


def _text_field(vault_key: str, prop: str) -> Field:
    return Field(
        vault_key,
        lambda v: {prop: _rich_text_value(v)},
        lambda props: read_plain_text(props.get(prop, {})),
    )


def _date_field(vault_key: str, prop: str) -> Field:
    return Field(
        vault_key,
        lambda v: {prop: {"date": {"start": v} if v else None}},
        lambda props: _read_date(props.get(prop, {})),
    )


def _multi_select_field(vault_key: str, prop: str) -> Field:
    return Field(
        vault_key,
        lambda v: {prop: _multi_select_value(v)},
        lambda props: _read_multi_select(props.get(prop, {})),
        _norm_list,
    )


RECEIPT_FIELDS: list[Field] = [
    _text_field("merchant", "Merchant"),
    _date_field("date", "Date"),
    Field("total", _total_to_notion, _total_from_notion, _norm_total),
]

DOCUMENT_FIELDS: list[Field] = [
    Field(
        "title",
        lambda v: {"Name": _title_value(v)},
        lambda props: read_plain_text(props.get("Name", {})),
    ),
    _date_field("date", "Date"),
    _multi_select_field("tags", "Tags"),
    _multi_select_field("people", "People"),
    _text_field("summary", "Summary"),
]

# Keyed by Pipeline.name; bank_statement is intentionally absent (not synced).
FIELD_MAPS: dict[str, list[Field]] = {
    "receipt": RECEIPT_FIELDS,
    "document": DOCUMENT_FIELDS,
}


def editable_properties(type_name: str, frontmatter: dict[str, str]) -> dict[str, Any]:
    """Build the Notion property dict for a note's two-way (editable) fields."""
    props: dict[str, Any] = {}
    for f in FIELD_MAPS.get(type_name, []):
        props.update(f.to_notion(frontmatter.get(f.vault_key, "")))
    return props


def read_editable(type_name: str, page_properties: dict[str, Any]) -> dict[str, str]:
    """Read a page's two-way fields into ``{vault_key: value}``."""
    return {
        f.vault_key: f.from_notion(page_properties)
        for f in FIELD_MAPS.get(type_name, [])
    }


# -- machine / structural properties (one-way vault -> Notion) -------------


def sha_property(shas: list[str]) -> dict[str, Any]:
    """The ``Sha`` text property (newline-joined sha set; the join/crash-guard key)."""
    return {"Sha": _rich_text_value("\n".join(shas))}


def consumed_at_property(iso: str) -> dict[str, Any]:
    """The ``Consumed At`` date property (ISO datetime in ``start``)."""
    return {"Consumed At": {"date": {"start": iso} if iso else None}}


def file_property(upload_ids_and_names: list[tuple[str, str]]) -> dict[str, Any]:
    """The ``File`` property from ``(file_upload_id, display_name)`` pairs."""
    return {
        "File": {
            "files": [
                {"type": "file_upload", "file_upload": {"id": uid}, "name": name}
                for uid, name in upload_ids_and_names
            ]
        }
    }
