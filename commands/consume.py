import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import click


@click.command()
@click.option(
    "--path", required=True, help="Subdirectory within the vault to store PDFs."
)
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.pass_context
def consume(ctx, path, directory):
    """Consume PDFs from a directory into the vault."""
    vault = Path(ctx.obj["vault"])
    for pdf in sorted(Path(directory).rglob("*.pdf")):
        sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()
        target_dir = vault / path / sha256
        if target_dir.exists():
            click.echo(f"Warning: {pdf} already consumed ({sha256}), skipping")
            continue
        target_dir.mkdir(parents=True)
        shutil.move(pdf, target_dir / "original.pdf")
        metadata = {
            "original_filepath": str(pdf.resolve()),
            "sha256": sha256,
            "consumed_at": datetime.now(timezone.utc).isoformat(),
        }
        (target_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
        click.echo(f"Consumed {pdf} -> {target_dir}")
