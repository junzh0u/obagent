import base64
import json
from pathlib import Path

import click
from mistralai import Mistral


def run_ocr(target_dir, api_key, *, overwrite=False):
    """Run Mistral OCR on the consumed PDF and save results.

    If OCR output exists and not overwrite, returns existing text (skip API call).
    Otherwise runs OCR, saves JSON + TXT, returns concatenated text.
    """
    ocr_dir = target_dir / "ocr"
    txt_path = ocr_dir / "mistral-ocr-latest.txt"

    if txt_path.exists() and not overwrite:
        click.echo("  OCR already exists, skipping")
        return txt_path.read_text()

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

    ocr_dir.mkdir(exist_ok=True)
    (ocr_dir / "mistral-ocr-latest.json").write_text(
        json.dumps(ocr_response.model_dump(), indent=2)
    )
    pages_md = [page.markdown for page in ocr_response.pages]
    ocr_text = "\n\n".join(pages_md)
    txt_path.write_text(ocr_text)
    click.echo(f"  OCR completed ({len(ocr_response.pages)} pages)")
    return ocr_text


@click.command()
@click.option("--path", required=True, help="Subdirectory within the vault to scan.")
@click.option(
    "--mistral-api-key",
    envvar="MISTRAL_API_KEY",
    required=True,
    help="Mistral API key for OCR processing.",
)
@click.option("--overwrite", is_flag=True, help="Overwrite existing OCR results.")
@click.pass_context
def ocr(ctx, path, mistral_api_key, overwrite):
    """Run OCR on ingested PDFs in the vault."""
    vault = Path(ctx.obj["vault"])
    for pdf_path in sorted((vault / path).rglob("original.pdf")):
        target_dir = pdf_path.parent
        click.echo(f"OCR: {target_dir}")
        run_ocr(target_dir, mistral_api_key, overwrite=overwrite)
