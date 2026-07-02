from collections import defaultdict
from pathlib import Path

import click

from commands.render import _parse_frontmatter
from lib.pipeline import Pipeline


def _casefold_groups(path_dir: Path) -> list[list[Path]]:
    """Return groups of notes in path_dir whose stems collide case-insensitively.

    Only groups with more than one member are returned. Each group is sorted by
    name, so the first member is the lexicographically-first casing.
    """
    groups: dict[str, list[Path]] = defaultdict(list)
    for md in sorted(path_dir.glob("*.md")):
        groups[md.stem.casefold()].append(md)
    return [g for g in groups.values() if len(g) > 1]


def _notion_id(md: Path) -> str:
    fm = _parse_frontmatter(md.read_text()) or {}
    return (fm.get("notion_id") or "").strip()


def _embed_lines(text: str) -> list[str]:
    return [ln for ln in text.split("\n") if ln.startswith("![[")]


def _merge_group(canonical: Path, others: list[Path]) -> None:
    """Append the others' embeds into canonical (deduped), then delete them."""
    text = canonical.read_text()
    seen = set(_embed_lines(text))
    extra: list[str] = []
    for other in others:
        for ln in _embed_lines(other.read_text()):
            if ln not in seen:
                seen.add(ln)
                extra.append(ln)
    if extra:
        if not text.endswith("\n"):
            text += "\n"
        text += "\n".join(extra) + "\n"
        canonical.write_text(text)
    for other in others:
        other.unlink()


def _handle_group(group: list[Path], apply_: bool) -> int:
    """Report (and optionally resolve) one collision group.

    Returns 1 if the collision remains after this call (report-only, or an
    unresolvable notion_id conflict), else 0.
    """
    names = " / ".join(m.name for m in group)

    # Canonical = the linked note (notion_id set); ambiguous if two notes carry
    # *different* ids, in which case we never merge — the user must pick.
    ids: dict[str, Path] = {}
    for md in group:
        nid = _notion_id(md)
        if nid:
            ids.setdefault(nid, md)
    if len(ids) > 1:
        click.secho(f"  Conflict (different notion_id, skipped): {names}", fg="red")
        return 1

    canonical = next(iter(ids.values())) if ids else group[0]
    others = [m for m in group if m != canonical]

    if not apply_:
        click.secho(f"  Collision: {names}", fg="yellow")
        click.secho(f"    would merge into {canonical.name}", fg="yellow")
        return 1

    _merge_group(canonical, others)
    merged = ", ".join(m.name for m in others)
    click.secho(f"  Merged into {canonical.name}: {merged}", fg="green")
    return 0


@click.command()
@click.option(
    "--apply",
    "apply_",
    is_flag=True,
    help="Merge each collision into one note (default: report only).",
)
@click.pass_context
def check(ctx, apply_):
    """Scan the vault for case-colliding note filenames.

    Two notes whose names differ only in case (e.g. ``Costco.md`` /
    ``costco.md``) are distinct on the Linux vault but collide on a
    case-insensitive export target (Google Drive, macOS). Reports each
    collision; with ``--apply`` it merges each group into one canonical note
    (the linked one, else the first by name), moving the others' embeds in and
    deleting them. A group whose notes carry different ``notion_id`` values is
    skipped as ambiguous. Exit status is non-zero when unresolved collisions
    remain.
    """
    vault = Path(ctx.obj["vault"])
    remaining = 0
    for pipeline in Pipeline._registry:
        path_dir = vault / pipeline.default_path
        if not path_dir.is_dir():
            continue
        groups = _casefold_groups(path_dir)
        if not groups:
            continue
        click.secho(f"=== {pipeline.default_path} ===", bold=True)
        for group in groups:
            remaining += _handle_group(group, apply_)

    if remaining:
        raise SystemExit(1)
    click.secho("No case collisions.", fg="green")
