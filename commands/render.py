import json
import re
from collections import defaultdict
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


def _remove_orphans(path_dir: Path, rendered: set[Path]) -> int:
    """Delete .md files in path_dir that were not rendered (orphans)."""
    count = 0
    for md in path_dir.glob("*.md"):
        if md not in rendered:
            click.secho(f"  Removed: {md.name}", fg="green")
            md.unlink()
            count += 1
    return count


def _print_stats(stats: dict[str, int]) -> None:
    """Print render summary stats."""
    parts = [f"{v} {k}" for k, v in stats.items() if v]
    if parts:
        click.secho(", ".join(parts), bold=True)


def render_note(
    target_dir: Path,
    *,
    overwrite: bool = False,
    note_index: dict[str, tuple[dict[str, str] | None, list[Path]]] | None = None,
    pipeline: Pipeline,
) -> tuple[Path | None, str]:
    """Read LLM JSON and create an Obsidian markdown note.

    Writes .md to target_dir's grandparent (vault/path/) for a flat, browsable layout.
    When note_index is provided, preserves manually-edited frontmatter (unless
    overwrite=True).  Compares new content against existing note and only writes
    when something actually changed.
    Returns (md_path, status) where status is one of: "created", "updated",
    "renamed", "appended", "unchanged", "skipped".
    """
    def _log_target() -> None:
        click.secho(f"Render: {target_dir}", bold=True)

    json_path = newest_file(target_dir / "llm", "*.json")
    if json_path is None:
        _log_target()
        click.secho("  No LLM result found, skipping render", fg="yellow")
        return None, "skipped"

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
                return md_path, "unchanged"
            # Shared note (has other embeds): only check frontmatter portion
            old_text = old_md.read_text()
            if embed in old_text and old_text.startswith(frontmatter + body):
                return md_path, "unchanged"
            md_path.write_text(content)
            _log_target()
            click.secho(f"  Updated: {safe_title}", fg="green")
            return md_path, "updated"
        # Title changed — delete old, create at new path
        old_md.unlink()
        _log_target()
        click.secho(f"  Renamed: {old_md.name} -> {md_path.name}", fg="green")
        md_path.write_text(content)
        return md_path, "renamed"

    # No existing note for this sha
    if md_path.exists():
        # Another sha already has a note at this path — append
        if target_dir.name in md_path.read_text():
            return md_path, "unchanged"
        with md_path.open("a") as f:
            f.write(embed)
            f.write(meta_embed)
        _log_target()
        click.secho(f"  Appended to: {safe_title}", fg="green")
        return md_path, "appended"

    md_path.write_text(content)
    _log_target()
    click.secho(f"  Created: {safe_title}", fg="green")
    return md_path, "created"


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
        stats: defaultdict[str, int] = defaultdict(int)
        for target_dir in interruptible(entries):
            try:
                md_path, status = render_note(
                    target_dir,
                    overwrite=overwrite,
                    note_index=note_index,
                    pipeline=pipeline,
                )
                stats[status] += 1
                if md_path:
                    rendered.add(md_path)
            except Exception as e:
                click.secho(f"Render: {target_dir}", bold=True)
                click.secho(f"  Warning: rendering failed: {e}", fg="red")
        if not sha256:
            removed = _remove_orphans(path_dir, rendered)
            if removed:
                stats["removed"] = removed
        _print_stats(stats)

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
        stats: defaultdict[str, int] = defaultdict(int)
        for target_dir in interruptible(iter_entries(vault, path)):
            try:
                md_path, status = render_note(
                    target_dir,
                    overwrite=overwrite,
                    note_index=note_index,
                    pipeline=pipeline,
                )
                stats[status] += 1
                if md_path:
                    rendered.add(md_path)
            except Exception as e:
                click.secho(f"Render: {target_dir}", bold=True)
                click.secho(f"  Warning: rendering failed: {e}", fg="red")
        removed = _remove_orphans(path_dir, rendered)
        if removed:
            stats["removed"] = removed
        _print_stats(stats)
