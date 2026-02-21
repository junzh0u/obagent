import hashlib
from pathlib import Path

import click


@click.command()
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
def consume(directory):
    """Scan a directory for PDFs and print their SHA256 hashes."""
    for pdf in sorted(Path(directory).rglob("*.pdf")):
        sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()
        click.echo(f"{sha256}  {pdf}")
