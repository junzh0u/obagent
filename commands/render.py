import json
from pathlib import Path

import click

from utils import newest_file


def render_note(target_dir, *, overwrite=False):
    """Read LLM JSON and create an Obsidian markdown note.

    If .md file exists and not overwrite, skips and returns None.
    If overwrite, deletes old .md files first.
    Returns safe_title on success, None if skipped.
    """
    json_path = newest_file(target_dir / "llm", "*.json")
    if json_path is None:
        click.echo("  No LLM result found, skipping render")
        return None

    existing_md = list(target_dir.glob("*.md"))
    if existing_md and not overwrite:
        click.echo("  Markdown already exists, skipping")
        return None
    if existing_md and overwrite:
        for md in existing_md:
            md.unlink()

    fields = json.loads(json_path.read_text())
    merchant = fields["merchant"]
    date = fields["date"]
    total = fields["total"]
    title = f"{date} - {merchant} - {total}"
    safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()
    frontmatter = (
        f'---\nmerchant: "{merchant}"\ndate: "{date}"\ntotal: "{total}"\n---\n'
    )
    (target_dir / f"{safe_title}.md").write_text(
        frontmatter + "![[src/original.pdf]]\n"
    )
    click.echo(f"  Title: {safe_title}")
    return safe_title


@click.command()
@click.option("--overwrite", is_flag=True, help="Overwrite existing markdown files.")
@click.pass_context
def render(ctx, overwrite):
    """Render Obsidian notes from LLM-extracted metadata."""
    vault = Path(ctx.obj["vault"])
    path = ctx.obj["path"]
    for target_dir in sorted(p for p in (vault / path).iterdir() if p.is_dir()):
        click.echo(f"Render: {target_dir}")
        try:
            render_note(target_dir, overwrite=overwrite)
        except Exception as e:
            click.echo(f"  Warning: note rendering failed: {e}")
