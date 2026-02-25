from pathlib import Path

import click

from utils import make_safe_title, parse_frontmatter


def fix_metadata_embeds(md_path):
    """Ensure each source embed is followed by its metadata.json embed.

    Adds missing metadata embeds and moves misplaced ones.
    Returns True if the file was modified.
    """
    lines = md_path.read_text().splitlines()

    # First pass: strip all metadata.json embed lines
    cleaned = [
        ln
        for ln in lines
        if not (ln.startswith("![[") and "/src/metadata.json]]" in ln)
    ]

    # Second pass: re-insert after each source embed
    result = []
    for line in cleaned:
        result.append(line)
        if line.startswith("![[") and "/src/original." in line:
            prefix = line.split("/src/original.")[0]
            result.append(f"{prefix}/src/metadata.json]]")

    if result != lines:
        md_path.write_text("\n".join(result) + "\n")
        return True
    return False


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
    embeds_fixed = 0
    for md_path in sorted(path_dir.glob("*.md")):
        fields = parse_frontmatter(md_path.read_text())
        if fields is None:
            click.secho(f"  Skip (no frontmatter): {md_path.name}", fg="yellow")
            continue

        if fix_metadata_embeds(md_path):
            click.secho(f"  Fixed embeds: {md_path.name}", fg="green")
            embeds_fixed += 1

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

    click.secho(f"Fixed {renamed} name(s), {embeds_fixed} embed(s)", bold=True)
