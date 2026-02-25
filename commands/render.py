import json
import re
from pathlib import Path

import click

from constants import ASSETS_DIR
from utils import (
    interruptible,
    iter_entries,
    make_safe_title,
    newest_file,
    parse_frontmatter,
    source_file,
)

_SHA_RE = re.compile(r"_assets_/([^/]+)/src/")


def index_existing_notes(path_dir):
    """Read all .md files once and build a sha-indexed lookup.

    Returns {sha: (frontmatter_dict_or_None, [md_paths])} for every sha
    referenced in embed links.
    """
    index = {}
    for md in path_dir.glob("*.md"):
        text = md.read_text()
        shas = set(_SHA_RE.findall(text))
        if not shas:
            continue
        fm = parse_frontmatter(text)
        for sha in shas:
            if sha not in index:
                index[sha] = (fm, [md])
            else:
                index[sha][1].append(md)
    return index


def clear_notes(path_dir):
    """Delete all .md files in path_dir."""
    mds = list(path_dir.glob("*.md"))
    for md in mds:
        md.unlink()
    if mds:
        click.secho(f"  Removed {len(mds)} notes", fg="green")


def render_note(target_dir, *, overwrite=False, note_index=None):
    """Read LLM JSON and create an Obsidian markdown note.

    Writes .md to target_dir's grandparent (vault/path/) for a flat, browsable layout.
    If overwrite, deletes any existing .md referencing this sha256 first.
    If .md already exists with a different sha256, appends the PDF embed.
    Skips if this sha256 is already referenced.
    Returns safe_title on success, None if skipped.

    note_index: pre-built {sha: (frontmatter, [md_paths])} from
    index_existing_notes; required when overwrite=True.
    """
    json_path = newest_file(target_dir / "llm", "*.json")
    if json_path is None:
        click.secho("  No LLM result found, skipping render", fg="yellow")
        return None

    path_dir = target_dir.parent.parent

    fields = json.loads(json_path.read_text())
    merchant = fields["merchant"]
    date = fields["date"] or ""
    total = fields["total"] or "$0.00"

    if overwrite:
        entry = note_index.get(target_dir.name)
        if entry:
            existing_fm, md_paths = entry
            if existing_fm:
                merchant = existing_fm.get("merchant") or merchant
                date = existing_fm.get("date") or date
                total = existing_fm.get("total") or total
            for md in md_paths:
                if md.exists() and target_dir.name in md.read_text():
                    click.secho(f"  Removed: {md.name}", fg="green")
                    md.unlink()
    safe_title = make_safe_title(merchant, date, total)

    md_path = path_dir / f"{safe_title}.md"

    src = source_file(target_dir)
    src_name = src.name if src else "original.pdf"
    suffix = src.suffix.lower() if src else ".pdf"
    anchor = "#height" if suffix == ".pdf" else ""
    embed = f"![[{ASSETS_DIR}/{target_dir.name}/src/{src_name}{anchor}]]\n"
    meta_embed = f"![[{ASSETS_DIR}/{target_dir.name}/src/metadata.json]]\n"

    if md_path.exists():
        if target_dir.name in md_path.read_text():
            click.secho("  Markdown already exists, skipping", fg="yellow")
            return None
        with md_path.open("a") as f:
            f.write(embed)
            f.write(meta_embed)
        click.secho(f"  Appended to: {safe_title}", fg="green")
        return safe_title

    frontmatter = f"---\nmerchant: {merchant}\ndate: {date}\ntotal: {total}\n---\n"
    md_path.write_text(frontmatter + embed + meta_embed)
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
    note_index = index_existing_notes(vault / path) if overwrite else None
    if sha256:
        entries = [vault / path / ASSETS_DIR / sha256]
    else:
        if overwrite:
            clear_notes(vault / path)
        entries = iter_entries(vault, path)
    for target_dir in interruptible(entries):
        click.secho(f"Render: {target_dir}", bold=True)
        try:
            render_note(target_dir, overwrite=overwrite, note_index=note_index)
        except Exception as e:
            click.secho(f"  Warning: note rendering failed: {e}", fg="red")
