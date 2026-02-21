import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import click

from constants import ASSETS_DIR


def ingest_pdf(pdf, vault, path, *, keep_original=False, overwrite=False):
    """Ingest a single PDF into the vault.

    Returns target_dir on success, None if duplicate skipped.
    """
    sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()
    target_dir = vault / path / ASSETS_DIR / sha256
    if target_dir.exists() and not overwrite:
        click.secho(f"  Warning: already consumed ({sha256}), skipping", fg="yellow")
        return None
    src_dir = target_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    if keep_original:
        shutil.copy2(pdf, src_dir / "original.pdf")
    else:
        shutil.move(pdf, src_dir / "original.pdf")
    metadata = {
        "original_filepath": str(pdf.resolve()),
        "sha256": sha256,
        "consumed_at": datetime.now(timezone.utc).isoformat(),
    }
    (src_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    click.secho(f"  Ingested -> {target_dir}", fg="green")
    return target_dir


def resolve_pdfs(paths):
    """Resolve a list of paths to PDF files, recursing into directories."""
    pdfs = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            pdfs.extend(sorted(p.rglob("*.pdf")))
        elif p.suffix.lower() == ".pdf":
            pdfs.append(p)
        else:
            click.secho(f"Warning: skipping non-PDF file: {p}", fg="yellow")
    return pdfs


@click.command()
@click.option("--keep-original", is_flag=True, help="Copy PDFs instead of moving them.")
@click.option("--overwrite", is_flag=True, help="Overwrite existing entries.")
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True))
@click.pass_context
def ingest(ctx, keep_original, overwrite, paths):
    """Ingest PDFs into the vault. Accepts PDF files and/or directories."""
    vault = Path(ctx.obj["vault"])
    path = ctx.obj["path"]
    for pdf in resolve_pdfs(paths):
        click.secho(f"Ingest: {pdf}", bold=True)
        ingest_pdf(pdf, vault, path, keep_original=keep_original, overwrite=overwrite)
