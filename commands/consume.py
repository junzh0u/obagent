import base64
import hashlib
import json
import shutil
import time
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
            ocr_text = _run_ocr(target_dir, mistral_api_key)
            _extract_title(target_dir, mistral_api_key, ocr_text, path)


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
    ocr_text = "\n\n".join(pages_md)
    (ocr_dir / "mistral-ocr-latest.txt").write_text(ocr_text)
    click.echo(f"  OCR completed ({len(ocr_response.pages)} pages)")
    return ocr_text


def _extract_title(target_dir, api_key, ocr_text, path):
    """Use Mistral LLM to extract a title from OCR text and create a markdown note."""
    client = Mistral(api_key=api_key)
    messages = [
        {
            "role": "user",
            "content": (
                "I will provide you with the content of a document that has been "
                "partially read by OCR (so it may contain errors).\n"
                f'The document is stored under the path "{path}".\n'
                "Your task is to find a suitable document title that I can use as "
                "the title in Obsidian.\n"
                "Respond only with the title in plain text, no markdown, "
                "no additional information!\n\n" + ocr_text[:4000]
            ),
        },
    ]
    response = _chat_with_retry(client, "mistral-large-latest", messages)
    title = response.choices[0].message.content.strip()
    # Sanitize for use as filename
    safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()
    (target_dir / f"{safe_title}.md").write_text("![[original.pdf]]\n")
    click.echo(f"  Title: {safe_title}")


def _chat_with_retry(client, model, messages, max_retries=3):
    """Call chat.complete with retry on rate limit (429) errors."""
    from mistralai.models import SDKError

    for attempt in range(max_retries):
        try:
            return client.chat.complete(model=model, messages=messages)
        except SDKError as e:
            if "429" in str(e) and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                click.echo(f"  Rate limited, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
