import shutil
from pathlib import Path
from typing import NamedTuple

import click

from lib.constants import ASSETS_DIR
from lib.utils import target_shas


class Removed(NamedTuple):
    """What ``remove_entry`` touched, for the caller to report.

    ``notes`` is ``(md_name, kept_other_embeds)`` per affected note — ``kept`` True
    means an embed was stripped but the note survived; False means it was deleted.
    """

    notes: list[tuple[str, bool]]
    data_dir: str


def remove_entry(path_dir: Path, sha256: str) -> Removed | None:
    """Remove one vault entry by sha. Strips its embed from any ``.md`` in
    ``path_dir`` (deleting the ``.md`` when no embeds remain), then deletes its
    ``_assets_/<sha>`` dir. Returns ``None`` if the entry's data dir did not exist
    (nothing removed), else a :class:`Removed` report. Pure — no click; callers
    handle reporting and exit."""
    target_dir = path_dir / ASSETS_DIR / sha256
    if not target_dir.exists():
        return None

    notes: list[tuple[str, bool]] = []
    for md in path_dir.glob("*.md"):
        content = md.read_text()
        if sha256 not in content:
            continue
        remaining = [ln for ln in content.splitlines(keepends=True) if sha256 not in ln]
        kept = any("![[" in ln for ln in remaining)
        if kept:
            md.write_text("".join(remaining))  # other embeds remain
        else:
            md.unlink()  # no embeds left — drop the whole note
        notes.append((md.name, kept))

    shutil.rmtree(target_dir)
    return Removed(notes, target_dir.name)


@click.command()
@click.argument("targets", metavar="[SHA256|NOTE]...", nargs=-1, required=True)
@click.pass_context
def remove(ctx, targets):
    """Remove vault entries by sha256 hash or note path.

    A note target (a path to a ``.md``, or its bare filename inside the type
    dir) removes every source it embeds — i.e. the whole note.
    """
    path_dir = Path(ctx.obj["vault"]) / ctx.obj["path"]
    shas = [s for t in targets for s in target_shas(path_dir, t)]
    for s in dict.fromkeys(shas):
        result = remove_entry(path_dir, s)
        if result is None:
            click.secho(f"Entry not found: {s}", fg="red")
            ctx.exit(1)
            return
        for name, kept in result.notes:
            verb = "Removed embed from" if kept else "Removed"
            click.secho(f"  {verb}: {name}", fg="green")
        click.secho(f"  Removed: {result.data_dir}", fg="green")
