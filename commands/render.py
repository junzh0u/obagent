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
    Handles YAML list values (``- item``) by joining them as comma-separated.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None

    fields: dict[str, str] = {}
    current_key: str | None = None
    list_items: list[str] = []

    def _flush() -> None:
        if current_key is not None and list_items:
            fields[current_key] = ",".join(list_items)

    for line in lines[1:]:
        if line.strip() == "---":
            _flush()
            break
        if line.startswith("  - "):
            list_items.append(line[4:].strip())
            continue
        _flush()
        list_items = []
        if ":" in line:
            key, _, value = line.partition(":")
            value = value.strip().strip('"')
            current_key = key.strip()
            fields[current_key] = value
        else:
            current_key = None
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


def _remove_orphans(path_dir: Path, rendered: set[Path]) -> None:
    """Delete .md files in path_dir that were not rendered (orphans)."""
    for md in path_dir.glob("*.md"):
        if md not in rendered:
            click.secho(f"  Removed: {md.name}", fg="green")
            md.unlink()


def render_note(
    target_dir: Path,
    *,
    overwrite: bool = False,
    note_index: dict[str, tuple[dict[str, str] | None, list[Path]]] | None = None,
    pipeline: Pipeline,
) -> Path | None:
    """Read LLM JSON and create an Obsidian markdown note.

    Writes .md to target_dir's grandparent (vault/path/) for a flat, browsable layout.
    When note_index is provided, preserves manually-edited frontmatter (unless
    overwrite=True).  Compares new content against existing note and only writes
    when something actually changed.
    Returns the md_path on success, None if skipped.
    """
    json_path = newest_file(target_dir / "llm", "*.json")
    if json_path is None:
        click.secho("  No LLM result found, skipping render", fg="yellow")
        return None

    path_dir = target_dir.parent.parent

    fields = pipeline.fields_class(json.loads(json_path.read_text()))

    old_md_paths: list[Path] = []
    if note_index:
        entry = note_index.get(target_dir.name)
        if entry:
            existing_fm, old_md_paths = entry
            if existing_fm:
                if overwrite:
                    fields.fill_gaps(existing_fm)
                else:
                    fields.apply_frontmatter(existing_fm)

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

    frontmatter = fields.format_frontmatter(consumed_at=consumed_at)
    body = fields.format_body()
    content = frontmatter + body + embed + meta_embed

    # Find existing note for this sha
    old_md = None
    for candidate in old_md_paths:
        if candidate.exists() and target_dir.name in candidate.read_text():
            old_md = candidate
            break

    if old_md is not None:
        if old_md == md_path:
            # Same path — check if content changed
            if old_md.read_text() == content:
                click.secho("  Unchanged", fg="yellow")
                return md_path
            # Shared note (has other embeds): only check frontmatter portion
            old_text = old_md.read_text()
            if embed in old_text and old_text.startswith(frontmatter + body):
                click.secho("  Unchanged", fg="yellow")
                return md_path
            md_path.write_text(content)
            click.secho(f"  Updated: {safe_title}", fg="green")
            return md_path
        # Title changed — delete old, create at new path
        old_md.unlink()
        click.secho(f"  Renamed: {old_md.name} -> {md_path.name}", fg="green")
        md_path.write_text(content)
        return md_path

    # No existing note for this sha
    if md_path.exists():
        # Another sha already has a note at this path — append
        if target_dir.name in md_path.read_text():
            click.secho("  Unchanged", fg="yellow")
            return md_path
        with md_path.open("a") as f:
            f.write(embed)
            f.write(meta_embed)
        click.secho(f"  Appended to: {safe_title}", fg="green")
        return md_path

    md_path.write_text(content)
    click.secho(f"  Created: {safe_title}", fg="green")
    return md_path


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
        path_dir = vault / path
        note_index = index_existing_notes(path_dir)
        if sha256:
            entries = [path_dir / ASSETS_DIR / s for s in sha256]
        else:
            entries = iter_entries(vault, path)
        rendered: set[Path] = set()
        for target_dir in interruptible(entries):
            click.secho(f"Render: {target_dir}", bold=True)
            try:
                md_path = render_note(
                    target_dir,
                    overwrite=overwrite,
                    note_index=note_index,
                    pipeline=pipeline,
                )
                if md_path:
                    rendered.add(md_path)
            except Exception as e:
                click.secho(f"  Warning: note rendering failed: {e}", fg="red")
        if not sha256:
            _remove_orphans(path_dir, rendered)

    render.__doc__ = pipeline.help_render
    return render


@click.command("render")
@click.option(
    "--overwrite",
    is_flag=True,
    help="Discard manually-edited frontmatter values and use LLM data.",
)
@click.pass_context
def render_all(ctx, overwrite):
    """Re-render Obsidian notes for all document types."""
    vault = Path(ctx.obj["vault"])
    for pipeline in Pipeline._registry:
        path = pipeline.default_path
        path_dir = vault / path
        click.secho(f"\n=== {pipeline.name.title()} ({path}) ===", bold=True)
        note_index = index_existing_notes(path_dir)
        rendered: set[Path] = set()
        for target_dir in interruptible(iter_entries(vault, path)):
            click.secho(f"Render: {target_dir}", bold=True)
            try:
                md_path = render_note(
                    target_dir,
                    overwrite=overwrite,
                    note_index=note_index,
                    pipeline=pipeline,
                )
                if md_path:
                    rendered.add(md_path)
            except Exception as e:
                click.secho(f"  Warning: note rendering failed: {e}", fg="red")
        _remove_orphans(path_dir, rendered)
