import re
from pathlib import Path

import click
import questionary

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
from lib.utils import pinyin_sort_key

ALIASES_FILE = ".obagent/people-aliases.json"
PINNED_FILE = ".obagent/people-pinned.json"

_PEOPLE_BLOCK_RE = re.compile(
    r"(people:)\n((?:  - [^\n]*\n)*)",
)


def _apply_mapping(names: list[str], mapping: dict[str, str]) -> list[str]:
    """Apply a name mapping: rename, remove (empty value), deduplicate."""
    result: list[str] = []
    for n in names:
        replacement = mapping.get(n, n)  # unmapped names pass through
        if replacement and replacement not in result:
            result.append(replacement)
    result.sort(key=pinyin_sort_key)
    return result


def _remap_in_file(md_path: Path, mapping: dict[str, str]) -> bool:
    """Apply a name mapping to the people frontmatter list.

    mapping values: non-empty = rename, empty = remove.
    Deduplicates. Returns True if the file was modified.
    """
    text = md_path.read_text()
    fm = _parse_frontmatter(text)
    if not fm or "people" not in fm or not fm["people"]:
        return False

    names = [n.strip() for n in fm["people"].split(",")]
    if not any(n in mapping for n in names):
        return False

    updated = _apply_mapping(names, mapping)
    people_lines = "".join(f"  - {n}\n" for n in updated)
    new_text = _PEOPLE_BLOCK_RE.sub(rf"\1\n{people_lines}", text, count=1)
    if new_text == text:
        return False
    md_path.write_text(new_text)
    return True


def _collect_names(vault: Path) -> list[str]:
    """Return sorted unique people names across all vault notes."""
    names: set[str] = set()
    for md in iter_notes(vault):
        fm = _parse_frontmatter(md.read_text())
        if fm and fm.get("people"):
            for n in fm["people"].split(","):
                n = n.strip()
                if n:
                    names.add(n)
    return sorted(names, key=pinyin_sort_key)


def _load_pinned(vault):
    pinned = load_json_list(vault, PINNED_FILE)
    aliases = load_json_dict(vault, ALIASES_FILE)
    return list(set(pinned) | set(aliases.values()))


def _save_pinned(vault, names):
    return save_json_list(vault, PINNED_FILE, names, sort_key=pinyin_sort_key)


def _load_aliases(vault):
    return load_json_dict(vault, ALIASES_FILE)


def _save_aliases(vault, mapping):
    return save_json_dict(vault, ALIASES_FILE, mapping)


@click.group()
def people():
    """Manage people across vault notes."""


def _remove_names(vault: Path, names: set[str]) -> None:
    """Remove names from all vault notes, with optional alias save."""
    mapping = {n: "" for n in names}
    count = 0
    for md in iter_notes(vault):
        if _remap_in_file(md, mapping):
            click.secho(f"  Updated: {md.relative_to(vault)}", fg="green")
            count += 1
    click.secho(f"{count} file(s) updated", bold=True)
    if (
        count > 0
        and questionary.confirm("Save to people-aliases.json?", default=False).ask()
    ):
        _save_aliases(vault, mapping)


@people.command()
@click.argument("names", nargs=-1)
@click.pass_context
def remove(ctx, names):
    """Remove one or more people from all notes in the vault."""
    vault = Path(ctx.obj["vault"])
    interactive = not names
    if interactive:
        pinned = set(_load_pinned(vault))
        all_names = [n for n in _collect_names(vault) if n not in pinned]
        if not all_names:
            click.echo("No people found in vault.")
            return
        selected = questionary.checkbox(
            "Select people to remove:",
            choices=all_names,
            use_search_filter=True,
            use_jk_keys=False,
        ).ask()
        if not selected:
            click.echo("No names selected.")
            return
        to_remove = set(selected)
    else:
        to_remove = set(names)
    _remove_names(vault, to_remove)
    if not interactive:
        return
    # Offer to pin the remaining (non-removed) names
    remaining = [n for n in _collect_names(vault) if n not in set(_load_pinned(vault))]
    if remaining:
        click.echo("Remaining unpinned names: " + ", ".join(remaining))
        if questionary.confirm("Pin all?", default=False).ask():
            existing = _load_pinned(vault)
            _save_pinned(vault, list(existing) + remaining)
            click.secho(f"Pinned: {', '.join(remaining)}", fg="green")


def _on_pin(vault: Path) -> None:
    """Post-pin hook: offer to remove non-pinned names from vault notes."""
    pinned = set(_load_pinned(vault))
    unpinned = [n for n in _collect_names(vault) if n not in pinned]
    if unpinned:
        click.echo("Non-pinned names: " + ", ".join(unpinned))
        if questionary.confirm("Remove all from vault notes?", default=False).ask():
            _remove_names(vault, set(unpinned))


def _on_unpin(vault: Path, to_remove: set[str]) -> None:
    """Post-unpin hook: offer to remove unpinned names from vault notes."""
    if questionary.confirm("Also remove from vault notes?", default=False).ask():
        _remove_names(vault, to_remove)


make_rename_command(
    people,
    collect_names=_collect_names,
    load_pinned=_load_pinned,
    remap_in_file=_remap_in_file,
    save_aliases=_save_aliases,
    aliases_label="people-aliases.json",
    label="person",
)
make_remap_command(
    people,
    aliases_file=ALIASES_FILE,
    load_aliases=_load_aliases,
    remap_in_file=_remap_in_file,
    label="person",
)
make_list_command(people, collect_names=_collect_names, label="person")
make_pin_command(
    people,
    load_pinned=_load_pinned,
    save_pinned=_save_pinned,
    collect_names=_collect_names,
    label="person",
    on_pin=_on_pin,
)
make_unpin_command(
    people,
    load_pinned=_load_pinned,
    save_pinned=_save_pinned,
    label="person",
    on_unpin=_on_unpin,
)
