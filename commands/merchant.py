import re
from pathlib import Path

import click

from lib.name_store import (
    iter_notes,
    load_json_dict,
    load_json_list,
    make_list_command,
    make_pin_command,
    make_rename_command,
    make_remap_command,
    make_unpin_command,
    save_json_dict,
    save_json_list,
)
from commands.render import _parse_frontmatter

ALIASES_FILE = ".obagent/merchant-aliases.json"
PINNED_FILE = ".obagent/merchant-pinned.json"


def _remap_merchant_in_file(md_path: Path, mapping: dict[str, str]) -> bool:
    """Apply a merchant name mapping to the merchant frontmatter field.

    mapping values: non-empty = rename. Returns True if the file was modified.
    """
    text = md_path.read_text()
    fm = _parse_frontmatter(text)
    if not fm or "merchant" not in fm or not fm["merchant"]:
        return False

    old_name = fm["merchant"]
    if old_name not in mapping:
        return False

    new_name = mapping[old_name]
    if not new_name or new_name == old_name:
        return False

    new_text = re.sub(
        r"^(merchant:)\s*.*$",
        rf"\1 {new_name}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if new_text == text:
        return False
    md_path.write_text(new_text)
    return True


def _collect_merchant_names(vault: Path) -> list[str]:
    """Return sorted unique merchant names across all vault notes."""
    names: set[str] = set()
    for md in iter_notes(vault):
        fm = _parse_frontmatter(md.read_text())
        if fm and fm.get("merchant"):
            names.add(fm["merchant"])
    return sorted(names)


def _load_pinned(vault):
    return load_json_list(vault, PINNED_FILE)


def _save_pinned(vault, names):
    return save_json_list(vault, PINNED_FILE, names)


def _load_aliases(vault):
    return load_json_dict(vault, ALIASES_FILE)


def _save_aliases(vault, mapping):
    return save_json_dict(vault, ALIASES_FILE, mapping)


@click.group()
def merchant():
    """Manage merchant names across vault notes."""


make_rename_command(
    merchant,
    collect_names=_collect_merchant_names,
    load_pinned=_load_pinned,
    remap_in_file=_remap_merchant_in_file,
    save_aliases=_save_aliases,
    aliases_label="merchant-aliases.json",
    label="merchant",
)
make_remap_command(
    merchant,
    aliases_file=ALIASES_FILE,
    load_aliases=_load_aliases,
    remap_in_file=_remap_merchant_in_file,
    label="merchant",
)
make_list_command(merchant, collect_names=_collect_merchant_names, label="merchant")
make_pin_command(
    merchant,
    load_pinned=_load_pinned,
    save_pinned=_save_pinned,
    collect_names=_collect_merchant_names,
    label="merchant",
)
make_unpin_command(
    merchant,
    load_pinned=_load_pinned,
    save_pinned=_save_pinned,
    label="merchant",
)
