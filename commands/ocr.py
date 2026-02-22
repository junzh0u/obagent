import base64
import json
import time
from pathlib import Path

import click
from mistralai import Mistral
from mistralai.models import SDKError

from constants import ASSETS_DIR, OCR_MODEL
from utils import iter_entries

MAX_RETRIES = 5
INITIAL_BACKOFF = 2


def _ocr_with_retry(client, model, document, *, max_retries=MAX_RETRIES):
    """Call OCR with exponential backoff on rate-limit (429) responses."""
    for attempt in range(max_retries + 1):
        try:
            return client.ocr.process(model=model, document=document)
        except SDKError as e:
            if e.status_code != 429 or attempt == max_retries:
                raise
            wait = INITIAL_BACKOFF * (2**attempt)
            click.secho(f"  Rate limited, retrying in {wait}s…", fg="yellow")
            time.sleep(wait)


def run_ocr(target_dir, client, *, model=OCR_MODEL, overwrite=False):
    """Run Mistral OCR on the consumed PDF and save results.

    If OCR output exists and not overwrite, skips the API call.
    Otherwise runs OCR and saves JSON + TXT.
    """
    ocr_dir = target_dir / "ocr"
    txt_path = ocr_dir / f"{model}.txt"

    if txt_path.exists() and not overwrite:
        click.secho("  OCR already exists, skipping", fg="yellow")
        return

    pdf_bytes = (target_dir / "src" / "original.pdf").read_bytes()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    ocr_response = _ocr_with_retry(
        client,
        model,
        document={
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{pdf_b64}",
        },
    )

    ocr_dir.mkdir(exist_ok=True)
    (ocr_dir / f"{model}.json").write_text(
        json.dumps(ocr_response.model_dump(), indent=2)
    )
    pages_md = [page.markdown for page in ocr_response.pages]
    txt_path.write_text("\n\n".join(pages_md))
    click.secho(f"  OCR completed ({len(ocr_response.pages)} pages)", fg="green")


@click.command()
@click.option(
    "--mistral-api-key",
    envvar="MISTRAL_API_KEY",
    required=True,
    help="Mistral API key for OCR processing.",
)
@click.option(
    "--ocr-model", default=OCR_MODEL, show_default=True, help="Mistral OCR model name."
)
@click.option("--overwrite", is_flag=True, help="Overwrite existing OCR results.")
@click.argument("sha256", required=False)
@click.pass_context
def ocr(ctx, mistral_api_key, ocr_model, overwrite, sha256):
    """Run OCR on ingested PDFs in the vault."""
    vault = Path(ctx.obj["vault"])
    path = ctx.obj["path"]
    if sha256:
        entries = [vault / path / ASSETS_DIR / sha256]
    else:
        entries = iter_entries(vault, path)
    with Mistral(api_key=mistral_api_key) as client:
        for target_dir in entries:
            click.secho(f"OCR: {target_dir}", bold=True)
            run_ocr(target_dir, client, model=ocr_model, overwrite=overwrite)
