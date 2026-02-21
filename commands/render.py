import json
from pathlib import Path

import click


def render_note(target_dir, *, overwrite=False):
    """Read LLM JSON and create an Obsidian markdown note.

    If .md file exists and not overwrite, skips and returns None.
    If overwrite, deletes old .md files first.
    Returns safe_title on success, None if skipped.
    """
    llm_dir = target_dir / "llm"
    json_files = (
        sorted(llm_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if llm_dir.exists()
        else []
    )
    if not json_files:
        click.echo("  No LLM result found, skipping render")
        return None
    json_path = json_files[0]

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
    (target_dir / f"{safe_title}.md").write_text(frontmatter + "![[original.pdf]]\n")
    click.echo(f"  Title: {safe_title}")
    return safe_title


@click.command()
@click.option("--overwrite", is_flag=True, help="Overwrite existing markdown files.")
@click.pass_context
def render(ctx, overwrite):
    """Render Obsidian notes from LLM-extracted metadata."""
    vault = Path(ctx.obj["vault"])
    path = ctx.obj["path"]
    entries = {}
    for json_path in (vault / path).rglob("*.json"):
        if json_path.parent.name != "llm":
            continue
        td = json_path.parent.parent
        if td not in entries or json_path.stat().st_mtime > entries[td].stat().st_mtime:
            entries[td] = json_path
    for target_dir in sorted(entries):
        click.echo(f"Render: {target_dir}")
        try:
            render_note(target_dir, overwrite=overwrite)
        except Exception as e:
            click.echo(f"  Warning: note rendering failed: {e}")
