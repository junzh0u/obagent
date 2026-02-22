from pathlib import Path

import click

from utils import make_safe_title


def parse_frontmatter(text):
    """Extract frontmatter fields from markdown text.

    Returns a dict of key-value pairs, or None if no valid frontmatter found.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None

    fields = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, value = line.partition(":")
            value = value.strip().strip('"')
            fields[key.strip()] = value
    else:
        return None

    return fields


@click.command()
@click.pass_context
def fix(ctx):
    """Fix note filenames to match their frontmatter metadata."""
    vault = Path(ctx.obj["vault"])
    path = ctx.obj["path"]
    path_dir = vault / path

    if not path_dir.is_dir():
        click.secho(f"Directory not found: {path_dir}", fg="red")
        return

    renamed = 0
    for md_path in sorted(path_dir.glob("*.md")):
        fields = parse_frontmatter(md_path.read_text())
        if fields is None:
            click.secho(f"  Skip (no frontmatter): {md_path.name}", fg="yellow")
            continue

        merchant = fields.get("merchant")
        date = fields.get("date")
        total = fields.get("total")

        if not merchant or not date:
            click.secho(f"  Skip (missing fields): {md_path.name}", fg="yellow")
            continue

        expected_stem = make_safe_title(merchant, date, total)

        if md_path.stem == expected_stem:
            continue

        new_path = md_path.with_name(f"{expected_stem}.md")
        if new_path.exists():
            click.secho(
                f"  Skip (target exists): {md_path.name} -> {new_path.name}",
                fg="yellow",
            )
            continue

        md_path.rename(new_path)
        click.secho(f"  Renamed: {md_path.name} -> {new_path.name}", fg="green")
        renamed += 1

    click.secho(f"Fixed {renamed} note(s)", bold=True)
