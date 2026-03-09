import json
import re
from pathlib import Path

import click
import questionary

from commands.render import _parse_frontmatter
from utils import pinyin_sort_key

REMAP_FILE = ".obagent/people-aliases.json"
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


def _load_aliases(vault: Path) -> dict[str, str]:
    """Load the people aliases mapping from the vault, or return {}."""
    path = vault / REMAP_FILE
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _load_pinned(vault: Path) -> list[str]:
    """Load the pinned people names from the vault, or return []."""
    path = vault / PINNED_FILE
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _save_pinned(vault: Path, names: list[str]) -> None:
    """Save a deduplicated, sorted list of pinned names."""
    path = vault / PINNED_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    sorted_names = sorted(set(names), key=pinyin_sort_key)
    path.write_text(json.dumps(sorted_names, indent=2, ensure_ascii=False) + "\n")


def _save_to_aliases(vault: Path, mapping: dict[str, str]) -> None:
    """Merge mapping into the aliases JSON file, keeping keys sorted."""
    path = vault / REMAP_FILE
    if path.exists():
        existing = json.loads(path.read_text())
    else:
        existing = {}
    existing.update(mapping)
    sorted_mapping = dict(sorted(existing.items()))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted_mapping, indent=2, ensure_ascii=False) + "\n")


def _iter_notes(vault: Path):
    """Yield .md files in the vault, skipping _assets_ directories."""
    for md in sorted(vault.rglob("*.md")):
        if "_assets_" not in md.parts:
            yield md


@click.group()
def people():
    """Manage people across vault notes."""


@people.command()
@click.argument("old_name", required=False, default=None)
@click.argument("new_name", required=False, default=None)
@click.pass_context
def rename(ctx, old_name, new_name):
    """Rename a person across all notes in the vault."""
    vault = Path(ctx.obj["vault"])
    if old_name is None:
        all_names = _collect_names(vault)
        if not all_names:
            click.echo("No people found in vault.")
            return
        pinned = set(_load_pinned(vault))
        candidates = [n for n in all_names if n not in pinned]
        if not candidates:
            click.echo("All people are pinned.")
            return
        old_name = questionary.select(
            "Select person to rename:", choices=candidates
        ).ask()
        if not old_name:
            return
        new_name = questionary.text("New name:").ask()
        if not new_name:
            return
    count = 0
    for md in _iter_notes(vault):
        if _remap_in_file(md, {old_name: new_name}):
            click.secho(f"  Updated: {md.relative_to(vault)}", fg="green")
            count += 1
    click.secho(f"{count} file(s) updated", bold=True)
    if (
        count > 0
        and questionary.confirm("Save to people-aliases.json?", default=False).ask()
    ):
        _save_to_aliases(vault, {old_name: new_name})


@people.command()
@click.argument("mapping_file", required=False, default=None, type=click.Path())
@click.pass_context
def remap(ctx, mapping_file):
    """Batch rename people from a JSON mapping file."""
    vault = Path(ctx.obj["vault"])
    if mapping_file is not None:
        mapping_path = Path(mapping_file)
        if not mapping_path.exists():
            raise click.ClickException(f"Mapping file not found: {mapping_path}")
        mapping = json.loads(mapping_path.read_text())
    else:
        mapping = _load_aliases(vault)
        if not mapping:
            raise click.ClickException(f"Mapping file not found: {vault / REMAP_FILE}")
    if not isinstance(mapping, dict):
        raise click.ClickException("Mapping file must contain a JSON object")
    total = 0
    for md in _iter_notes(vault):
        if _remap_in_file(md, mapping):
            click.secho(f"  Updated: {md.relative_to(vault)}", fg="green")
            total += 1
    click.secho(f"{total} file(s) updated", bold=True)


def _collect_names(vault: Path) -> list[str]:
    """Return sorted unique people names across all vault notes."""
    names: set[str] = set()
    for md in _iter_notes(vault):
        fm = _parse_frontmatter(md.read_text())
        if fm and fm.get("people"):
            for n in fm["people"].split(","):
                n = n.strip()
                if n:
                    names.add(n)
    return sorted(names, key=pinyin_sort_key)


@people.command("list")
@click.pass_context
def list_people(ctx):
    """List all unique people names across vault notes."""
    vault = Path(ctx.obj["vault"])
    for name in _collect_names(vault):
        click.echo(name)


def _remove_names(vault: Path, names: set[str]) -> None:
    """Remove names from all vault notes, with optional alias save."""
    mapping = {n: "" for n in names}
    count = 0
    for md in _iter_notes(vault):
        if _remap_in_file(md, mapping):
            click.secho(f"  Updated: {md.relative_to(vault)}", fg="green")
            count += 1
    click.secho(f"{count} file(s) updated", bold=True)
    if (
        count > 0
        and questionary.confirm("Save to people-aliases.json?", default=False).ask()
    ):
        _save_to_aliases(vault, mapping)


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
            "Select people to remove:", choices=all_names
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


@people.command()
@click.argument("names", nargs=-1)
@click.pass_context
def pin(ctx, names):
    """Pin people names so the LLM prefers them."""
    vault = Path(ctx.obj["vault"])
    interactive = not names
    if interactive:
        existing = set(_load_pinned(vault))
        candidates = [n for n in _collect_names(vault) if n not in existing]
        if not candidates:
            click.echo("No new names to pin.")
            return
        selected = questionary.checkbox(
            "Select people to pin:", choices=candidates
        ).ask()
        if not selected:
            click.echo("No names selected.")
            return
        names = tuple(selected)
    existing = _load_pinned(vault)
    merged = list(existing) + list(names)
    _save_pinned(vault, merged)
    click.secho(f"Pinned: {', '.join(names)}", fg="green")
    if not interactive:
        return
    # Offer to remove non-pinned names from vault notes
    pinned = set(_load_pinned(vault))
    unpinned = [n for n in _collect_names(vault) if n not in pinned]
    if unpinned:
        click.echo("Non-pinned names: " + ", ".join(unpinned))
        if questionary.confirm("Remove all from vault notes?", default=False).ask():
            _remove_names(vault, set(unpinned))


@people.command()
@click.argument("names", nargs=-1)
@click.pass_context
def unpin(ctx, names):
    """Unpin people names."""
    vault = Path(ctx.obj["vault"])
    existing = _load_pinned(vault)
    if not existing:
        click.echo("No pinned names.")
        return
    interactive = not names
    if interactive:
        selected = questionary.checkbox(
            "Select people to unpin:", choices=existing
        ).ask()
        if not selected:
            click.echo("No names selected.")
            return
        names = tuple(selected)
    to_remove = set(names)
    remaining = [n for n in existing if n not in to_remove]
    _save_pinned(vault, remaining)
    click.secho(f"Unpinned: {', '.join(names)}", fg="green")
    if not interactive:
        return
    if questionary.confirm("Also remove from vault notes?", default=False).ask():
        _remove_names(vault, to_remove)
