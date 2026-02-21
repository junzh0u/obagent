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
    If .md already exists with a different sha256, appends the PDF embed.
    Skips if this sha256 is already referenced. Call clear_notes() first to force re-render.
    Returns safe_title on success, None if skipped.
    """
    json_path = newest_file(target_dir / "llm", "*.json")
    if json_path is None:
        click.secho("  No LLM result found, skipping render", fg="yellow")
        return None

    fields = json.loads(json_path.read_text())
    merchant = fields["merchant"]
    date = fields["date"]
    total = fields["total"]
    title = f"{date} - {merchant} - {total}"
    safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()

    path_dir = target_dir.parent.parent
    md_path = path_dir / f"{safe_title}.md"

    embed = f"![[{ASSETS_DIR}/{target_dir.name}/src/original.pdf#height]]\n"

    if md_path.exists():
        if target_dir.name in md_path.read_text():
            click.secho("  Markdown already exists, skipping", fg="yellow")
            return None
        with md_path.open("a") as f:
            f.write(embed)
        click.secho(f"  Appended to: {safe_title}", fg="green")
        return safe_title

    frontmatter = (
        f'---\nmerchant: "{merchant}"\ndate: "{date}"\ntotal: "{total}"\n---\n'
    )
    md_path.write_text(frontmatter + embed)
    click.secho(f"  Title: {safe_title}", fg="green")
    return safe_title


@click.command()
@click.option(
    "--overwrite",
    is_flag=True,
    help="Delete all .md notes and re-render from LLM metadata.",
)
@click.argument("sha256", required=False)
@click.pass_context
def render(ctx, overwrite, sha256):
    """Render Obsidian notes from LLM-extracted metadata."""
    vault = Path(ctx.obj["vault"])
    path = ctx.obj["path"]
    if sha256:
        entries = [vault / path / ASSETS_DIR / sha256]
    else:
        if overwrite:
            clear_notes(vault / path)
        entries = iter_entries(vault, path)
    for target_dir in entries:
        click.secho(f"Render: {target_dir}", bold=True)
        try:
            render_note(target_dir)
        except Exception as e:
            click.secho(f"  Warning: note rendering failed: {e}", fg="red")
