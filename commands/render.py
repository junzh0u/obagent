import json
import re
from pathlib import Path

import click

from commands.pipeline import Pipeline
from constants import ASSETS_DIR
from utils import (
    interruptible,
    iter_entries,
    newest_file,
    source_file,
)

_SHA_RE = re.compile(r"_assets_/([^/]+)/src/")


def _parse_frontmatter(text: str) -> dict[str, str] | None:
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


def index_existing_notes(
    path_dir: Path,
) -> dict[str, tuple[dict[str, str] | None, list[Path]]]:
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
        fm = _parse_frontmatter(text)
        for sha in shas:
            if sha not in index:
                index[sha] = (fm, [md])
            else:
                index[sha][1].append(md)
    return index


def _clear_notes(path_dir: Path) -> None:
    """Delete all .md files in path_dir."""
    mds = list(path_dir.glob("*.md"))
    for md in mds:
        md.unlink()
    if mds:
        click.secho(f"  Removed {len(mds)} notes", fg="green")


def render_note(
    target_dir: Path,
    *,
    overwrite: bool = False,
    note_index: dict[str, tuple[dict[str, str] | None, list[Path]]] | None = None,
    pipeline: Pipeline,
) -> str | None:
    """Read LLM JSON and create an Obsidian markdown note.

    Writes .md to target_dir's grandparent (vault/path/) for a flat, browsable layout.
    When note_index is provided, deletes any existing .md referencing this sha256
    and preserves manually-edited frontmatter (unless overwrite=True).
    If .md already exists with a different sha256, appends the PDF embed.
    Returns safe_title on success, None if skipped.

    note_index: pre-built {sha: (frontmatter, [md_paths])} from
    index_existing_notes; used for per-entry cleanup and frontmatter preservation.
    overwrite: if True, discard existing frontmatter and use fresh LLM values.
    pipeline: Pipeline providing apply_defaults(), make_title(),
    format_frontmatter(), and format_body().
    """
    json_path = newest_file(target_dir / "llm", "*.json")
    if json_path is None:
        click.secho("  No LLM result found, skipping render", fg="yellow")
        return None

    path_dir = target_dir.parent.parent

    fields = pipeline.fields_class(json.loads(json_path.read_text()))

    if note_index:
        entry = note_index.get(target_dir.name)
        if entry:
            existing_fm, md_paths = entry
            if not overwrite and existing_fm:
                fields.apply_frontmatter(existing_fm)
            for md in md_paths:
                if md.exists() and target_dir.name in md.read_text():
                    click.secho(f"  Removed: {md.name}", fg="green")
                    md.unlink()

    consumed_at = ""
    metadata_path = target_dir / "src" / "metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
        consumed_at = metadata.get("consumed_at", "")

    safe_title = fields.make_title()

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

    frontmatter = fields.format_frontmatter(consumed_at=consumed_at)
    body = fields.format_body()
    content = frontmatter + body + embed + meta_embed
    md_path.write_text(content)
    click.secho(f"  Title: {safe_title}", fg="green")
    return safe_title


def make_render_command(*, pipeline: Pipeline) -> click.Command:
    """Factory: create a click render command with type-specific config."""

    @click.command()
    @click.option(
        "--overwrite",
        is_flag=True,
        help="Discard manually-edited frontmatter values and use LLM data.",
    )
    @click.argument("sha256", nargs=-1)
    @click.pass_context
    def render(ctx, overwrite, sha256):
        vault = Path(ctx.obj["vault"])
        path = ctx.obj["path"]
        note_index = None
        if sha256 or not overwrite:
            note_index = index_existing_notes(vault / path)
        if sha256:
            entries = [vault / path / ASSETS_DIR / s for s in sha256]
        else:
            _clear_notes(vault / path)
            entries = iter_entries(vault, path)
        for target_dir in interruptible(entries):
            click.secho(f"Render: {target_dir}", bold=True)
            try:
                render_note(
                    target_dir,
                    overwrite=overwrite,
                    note_index=note_index,
                    pipeline=pipeline,
                )
            except Exception as e:
                click.secho(f"  Warning: note rendering failed: {e}", fg="red")

    render.__doc__ = pipeline.help_render
    return render
