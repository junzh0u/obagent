import json
import re
from pathlib import Path

import click
import questionary

from commands.render import _parse_frontmatter
from utils import pinyin_sort_key

REMAP_FILE = ".obagent/people-aliases.json"

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
@click.argument("old_name")
@click.argument("new_name")
@click.pass_context
def rename(ctx, old_name, new_name):
    """Rename a person across all notes in the vault."""
    vault = Path(ctx.obj["vault"])
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


@people.command()
@click.argument("names", nargs=-1)
@click.pass_context
def remove(ctx, names):
    """Remove one or more people from all notes in the vault."""
    vault = Path(ctx.obj["vault"])
    if not names:
        all_names = _collect_names(vault)
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
    count = 0
    mapping = {n: "" for n in to_remove}
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
