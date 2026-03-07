import re
from pathlib import Path

import click

from commands.render import _parse_frontmatter

_PEOPLE_BLOCK_RE = re.compile(
    r"(people:)\n((?:  - [^\n]*\n)*)",
)


def _rename_in_file(md_path: Path, old_name: str, new_name: str) -> bool:
    """Replace old_name with new_name in the people frontmatter list.

    Deduplicates if new_name already exists.  Returns True if the file was
    modified.
    """
    text = md_path.read_text()
    fm = _parse_frontmatter(text)
    if not fm or "people" not in fm or not fm["people"]:
        return False

    names = [n.strip() for n in fm["people"].split(",")]
    if old_name not in names:
        return False

    updated: list[str] = []
    for n in names:
        replacement = new_name if n == old_name else n
        if replacement not in updated:
            updated.append(replacement)

    people_lines = "".join(f"  - {n}\n" for n in updated)
    new_text = _PEOPLE_BLOCK_RE.sub(rf"\1\n{people_lines}", text, count=1)
    if new_text == text:
        return False
    md_path.write_text(new_text)
    return True


def _remove_in_file(md_path: Path, names_to_remove: set[str]) -> bool:
    """Remove names from the people frontmatter list.

    Returns True if the file was modified.
    """
    text = md_path.read_text()
    fm = _parse_frontmatter(text)
    if not fm or "people" not in fm or not fm["people"]:
        return False

    names = [n.strip() for n in fm["people"].split(",")]
    if not any(n in names_to_remove for n in names):
        return False

    updated = [n for n in names if n not in names_to_remove]
    people_lines = "".join(f"  - {n}\n" for n in updated)
    new_text = _PEOPLE_BLOCK_RE.sub(rf"\1\n{people_lines}", text, count=1)
    if new_text == text:
        return False
    md_path.write_text(new_text)
    return True


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
        if _rename_in_file(md, old_name, new_name):
            click.secho(f"  Updated: {md.relative_to(vault)}", fg="green")
            count += 1
    click.secho(f"{count} file(s) updated", bold=True)


@people.command("list")
@click.pass_context
def list_people(ctx):
    """List all unique people names across vault notes."""
    vault = Path(ctx.obj["vault"])
    names: set[str] = set()
    for md in _iter_notes(vault):
        fm = _parse_frontmatter(md.read_text())
        if fm and fm.get("people"):
            for n in fm["people"].split(","):
                n = n.strip()
                if n:
                    names.add(n)
    for name in sorted(names):
        click.echo(name)


@people.command()
@click.argument("names", nargs=-1, required=True)
@click.pass_context
def remove(ctx, names):
    """Remove one or more people from all notes in the vault."""
    vault = Path(ctx.obj["vault"])
    to_remove = set(names)
    count = 0
    for md in _iter_notes(vault):
        if _remove_in_file(md, to_remove):
            click.secho(f"  Updated: {md.relative_to(vault)}", fg="green")
            count += 1
    click.secho(f"{count} file(s) updated", bold=True)
