import hashlib
from pathlib import Path

import click

from commands.ingest import resolve_pdfs
from constants import ASSETS_DIR


@click.command()
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True))
@click.pass_context
def scan(ctx, paths):
    """Scan input paths and report which PDFs are new vs already in the vault."""
    vault = Path(ctx.obj["vault"])
    path = ctx.obj["path"]
    new_count = 0
    dup_count = 0
    for pdf in resolve_pdfs(paths):
        sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()
        target_dir = vault / path / ASSETS_DIR / sha256
        if target_dir.exists():
            click.secho(f"  {pdf.name}  duplicate ({sha256[:12]}…)", fg="yellow")
            dup_count += 1
        else:
            click.secho(f"  {pdf.name}  new ({sha256[:12]}…)", fg="green")
            new_count += 1
    total = new_count + dup_count
    click.secho(
        f"{total} PDFs found: {new_count} new, {dup_count} already consumed", bold=True
    )
