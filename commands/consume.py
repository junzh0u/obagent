import base64
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import click
from mistralai import Mistral


@click.command()
@click.option(
    "--path", required=True, help="Subdirectory within the vault to store PDFs."
)
@click.option(
    "--mistral-api-key",
    envvar="MISTRAL_API_KEY",
    default=None,
    help="Mistral API key for OCR processing.",
)
@click.option("--keep-original", is_flag=True, help="Copy PDFs instead of moving them.")
@click.option(
    "--overwrite", is_flag=True, help="Overwrite existing entries and force re-OCR."
)
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.pass_context
def consume(ctx, path, mistral_api_key, keep_original, overwrite, directory):
    """Consume PDFs from a directory into the vault."""
    vault = Path(ctx.obj["vault"])
    for pdf in sorted(Path(directory).rglob("*.pdf")):
        sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()
        target_dir = vault / path / sha256
        if target_dir.exists() and not overwrite:
            click.echo(f"Warning: {pdf} already consumed ({sha256}), skipping")
            continue
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

        if mistral_api_key:
            _run_ocr(target_dir, mistral_api_key)


def _run_ocr(target_dir, api_key):
    """Run Mistral OCR on the consumed PDF and save results."""
    pdf_bytes = (target_dir / "original.pdf").read_bytes()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    client = Mistral(api_key=api_key)
    ocr_response = client.ocr.process(
        model="mistral-ocr-latest",
        document={
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{pdf_b64}",
        },
    )

    ocr_dir = target_dir / "ocr"
    ocr_dir.mkdir(exist_ok=True)
    (ocr_dir / "mistral-ocr-latest.json").write_text(
        json.dumps(ocr_response.model_dump(), indent=2)
    )
    pages_md = [page.markdown for page in ocr_response.pages]
    (ocr_dir / "mistral-ocr-latest.txt").write_text("\n\n".join(pages_md))
    click.echo(f"  OCR completed ({len(ocr_response.pages)} pages)")
