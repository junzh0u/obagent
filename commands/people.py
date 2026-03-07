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
    for md in sorted(vault.rglob("*.md")):
        # Skip asset directories
        if "_assets_" in md.parts:
            continue
        if _rename_in_file(md, old_name, new_name):
            click.secho(f"  Updated: {md.relative_to(vault)}", fg="green")
            count += 1
    click.secho(f"{count} file(s) updated", bold=True)
