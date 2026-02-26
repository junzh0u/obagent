from pathlib import Path

import click

from commands.receipt.render import make_safe_title
from utils import parse_frontmatter


def _body_lines(text):
    """Return everything after the closing --- as a list of lines."""
    lines = text.split("\n")
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return lines[i + 1 :]
    return lines


def _merge_notes(source_path, target_path):
    """Append unique body lines from source into target, then delete source.

    Deduplicates by comparing stripped line strings so shared embeds
    aren't doubled.
    """
    target_text = target_path.read_text()
    source_text = source_path.read_text()

    target_body = _body_lines(target_text)
    source_body = _body_lines(source_text)

    existing = {line.strip() for line in target_body}
    new_lines = [line for line in source_body if line.strip() not in existing]

    if new_lines:
        # Ensure target ends with a newline before appending
        if not target_text.endswith("\n"):
            target_text += "\n"
        target_text += "\n".join(new_lines) + "\n"
        target_path.write_text(target_text)

    source_path.unlink()


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
    merged = 0
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
            target_fields = parse_frontmatter(new_path.read_text())
            if target_fields == fields:
                _merge_notes(md_path, new_path)
                if fix_metadata_embeds(new_path):
                    embeds_fixed += 1
                click.secho(f"  Merged: {md_path.name} -> {new_path.name}", fg="green")
                merged += 1
            else:
                click.secho(
                    f"  Skip (frontmatter differs): {md_path.name} -> {new_path.name}",
                    fg="yellow",
                )
            continue

        md_path.rename(new_path)
        click.secho(f"  Renamed: {md_path.name} -> {new_path.name}", fg="green")
        renamed += 1

    click.secho(
        f"Fixed {renamed} name(s), {merged} merged, {embeds_fixed} embed(s)",
        bold=True,
    )
