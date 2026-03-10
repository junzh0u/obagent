import shutil
from pathlib import Path

import click

from lib.constants import ASSETS_DIR


def _remove_entry(path_dir: Path, sha256: str, ctx: click.Context) -> None:
    """Remove a single vault entry and its .md references."""
    target_dir = path_dir / ASSETS_DIR / sha256

    if not target_dir.exists():
        click.secho(f"Entry not found: {sha256}", fg="red")
        ctx.exit(1)
        return

    # Remove or update .md files that reference this sha256
    for md in path_dir.glob("*.md"):
        content = md.read_text()
        if sha256 not in content:
            continue
        lines = content.splitlines(keepends=True)
        remaining = [line for line in lines if sha256 not in line]
        # Check if any embed lines remain (lines with ![[)
        if not any("![[" in line for line in remaining):
            # No embeds left — delete the whole file
            md.unlink()
            click.secho(f"  Removed: {md.name}", fg="green")
        else:
            md.write_text("".join(remaining))
            click.secho(f"  Removed embed from: {md.name}", fg="green")

    # Remove the data directory
    shutil.rmtree(target_dir)
    click.secho(f"  Removed: {target_dir.name}", fg="green")


@click.command()
@click.argument("sha256", nargs=-1, required=True)
@click.pass_context
def remove(ctx, sha256):
    """Remove vault entries by their sha256 hashes."""
    vault = Path(ctx.obj["vault"])
    path = ctx.obj["path"]
    path_dir = vault / path
    for s in sha256:
        _remove_entry(path_dir, s, ctx)
