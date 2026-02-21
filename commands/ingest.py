import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import click


def ingest_pdf(pdf, vault, path, *, keep_original=False, overwrite=False):
    """Ingest a single PDF into the vault.

    Returns target_dir on success, None if duplicate skipped.
    """
    sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()
    target_dir = vault / path / sha256
    if target_dir.exists() and not overwrite:
        click.echo(f"Warning: {pdf} already consumed ({sha256}), skipping")
        return None
    target_dir.mkdir(parents=True, exist_ok=True)
    if keep_original:
        shutil.copy2(pdf, target_dir / "original.pdf")
    else:
        shutil.move(pdf, target_dir / "original.pdf")
    metadata = {
        "original_filepath": str(pdf.resolve()),
        "sha256": sha256,
        "consumed_at": datetime.now(timezone.utc).isoformat(),
    }
    (target_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    click.echo(f"Consumed {pdf} -> {target_dir}")
    return target_dir


@click.command()
@click.option(
    "--path", required=True, help="Subdirectory within the vault to store PDFs."
)
@click.option("--keep-original", is_flag=True, help="Copy PDFs instead of moving them.")
@click.option("--overwrite", is_flag=True, help="Overwrite existing entries.")
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.pass_context
def ingest(ctx, path, keep_original, overwrite, directory):
    """Ingest PDFs from a directory into the vault."""
    vault = Path(ctx.obj["vault"])
    for pdf in sorted(Path(directory).rglob("*.pdf")):
        ingest_pdf(pdf, vault, path, keep_original=keep_original, overwrite=overwrite)
