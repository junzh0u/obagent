import base64
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import click
from mistralai import Mistral
from openai import OpenAI


@click.command()
@click.option(
    "--path", required=True, help="Subdirectory within the vault to store PDFs."
)
@click.option(
    "--mistral-api-key",
    envvar="MISTRAL_API_KEY",
    required=True,
    help="Mistral API key for OCR processing.",
)
@click.option(
    "--openai-api-key",
    envvar="OPENAI_API_KEY",
    required=True,
    help="OpenAI API key for title extraction.",
)
@click.option("--keep-original", is_flag=True, help="Copy PDFs instead of moving them.")
@click.option(
    "--overwrite", is_flag=True, help="Overwrite existing entries and force re-OCR."
)
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.pass_context
def consume(
    ctx, path, mistral_api_key, openai_api_key, keep_original, overwrite, directory
):
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

        ocr_text = _run_ocr(target_dir, mistral_api_key)
        try:
            _extract_title(target_dir, openai_api_key, ocr_text, path)
        except Exception as e:
            click.echo(f"  Warning: title extraction failed: {e}")


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
    """Use OpenAI to extract metadata from OCR text and create a markdown note."""
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {
                "role": "user",
                "content": (
                    "I will provide you with the content of a document that has been "
                    "partially read by OCR (so it may contain errors).\n"
                    f'The document is stored under the path "{path}".\n'
                    "Extract the following fields:\n"
                    "- merchant: the merchant or vendor name\n"
                    "- date: the document date in YYYY-MM-DD format\n"
                    "- total: the total amount (number with currency symbol)\n"
                    "Respond ONLY with a JSON object containing these three fields, "
                    "no additional text!\n\n" + ocr_text[:4000]
                ),
            },
        ],
    )
    raw = response.choices[0].message.content.strip()
    fields = json.loads(raw)
    merchant = fields["merchant"]
    date = fields["date"]
    total = fields["total"]
    title = f"{date} - {merchant} - {total}"
    safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()
    frontmatter = (
        f'---\nmerchant: "{merchant}"\ndate: "{date}"\ntotal: "{total}"\n---\n'
    )
    (target_dir / f"{safe_title}.md").write_text(frontmatter + "![[original.pdf]]\n")
    click.echo(f"  Title: {safe_title}")
