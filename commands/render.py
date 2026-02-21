import json
from pathlib import Path

import click

from constants import ASSETS_DIR
from utils import iter_entries, newest_file


def clear_notes(path_dir):
    """Delete all .md files in path_dir."""
    for md in path_dir.glob("*.md"):
        md.unlink()


def render_note(target_dir):
    """Read LLM JSON and create an Obsidian markdown note.

    Writes .md to target_dir's grandparent (vault/path/) for a flat, browsable layout.
    Skips if .md already exists. Call clear_notes() first to force re-render.
    Returns safe_title on success, None if skipped.
    """
    json_path = newest_file(target_dir / "llm", "*.json")
    if json_path is None:
        click.echo("  No LLM result found, skipping render")
        return None

    fields = json.loads(json_path.read_text())
    merchant = fields["merchant"]
    date = fields["date"]
    total = fields["total"]
    title = f"{date} - {merchant} - {total}"
    safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()

    path_dir = target_dir.parent.parent
    md_path = path_dir / f"{safe_title}.md"

    if md_path.exists():
        click.echo("  Markdown already exists, skipping")
        return None

    frontmatter = (
        f'---\nmerchant: "{merchant}"\ndate: "{date}"\ntotal: "{total}"\n---\n'
    )
    md_path.write_text(
        frontmatter + f"![[{ASSETS_DIR}/{target_dir.name}/src/original.pdf#height]]\n"
    )
    click.echo(f"  Title: {safe_title}")
    return safe_title


@click.command()
@click.option(
    "--overwrite",
    is_flag=True,
    help="Delete all .md notes and re-render from LLM metadata.",
)
@click.pass_context
def render(ctx, overwrite):
    """Render Obsidian notes from LLM-extracted metadata."""
    vault = Path(ctx.obj["vault"])
    path = ctx.obj["path"]
    if overwrite:
        clear_notes(vault / path)
    for target_dir in iter_entries(vault, path):
        click.echo(f"Render: {target_dir}")
        try:
            render_note(target_dir)
        except Exception as e:
            click.echo(f"  Warning: note rendering failed: {e}")
