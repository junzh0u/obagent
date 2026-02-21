import json
from pathlib import Path

import click
from openai import OpenAI

from constants import LLM_MODEL
from utils import newest_file


def extract_fields(target_dir, api_key, path, *, model=LLM_MODEL, overwrite=False):
    """Use OpenAI to extract metadata from OCR text and save as JSON.

    Discovers the newest OCR .txt file under target_dir/ocr/.
    If llm/<model>.json exists and not overwrite, skips and returns None.
    Returns the parsed fields dict on success, None if skipped.
    """
    llm_dir = target_dir / "llm"
    json_path = llm_dir / f"{model}.json"
    if json_path.exists() and not overwrite:
        click.echo("  LLM result already exists, skipping")
        return None

    txt_path = newest_file(target_dir / "ocr", "*.txt")
    if txt_path is None:
        click.echo("  No OCR result found, skipping LLM")
        return None
    ocr_text = txt_path.read_text()

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
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
    llm_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(fields, indent=2) + "\n")
    click.echo(f"  Extracted: {fields}")
    return fields


@click.command()
@click.option(
    "--openai-api-key",
    envvar="OPENAI_API_KEY",
    required=True,
    help="OpenAI API key for title extraction.",
)
@click.option(
    "--llm-model",
    default=LLM_MODEL,
    show_default=True,
    help="OpenAI model name for field extraction.",
)
@click.option("--overwrite", is_flag=True, help="Overwrite existing markdown files.")
@click.pass_context
def llm(ctx, openai_api_key, llm_model, overwrite):
    """Extract metadata via LLM from OCR'd entries in the vault."""
    vault = Path(ctx.obj["vault"])
    path = ctx.obj["path"]
    for target_dir in sorted(p for p in (vault / path).iterdir() if p.is_dir()):
        click.echo(f"LLM: {target_dir}")
        try:
            extract_fields(
                target_dir,
                openai_api_key,
                path,
                model=llm_model,
                overwrite=overwrite,
            )
        except Exception as e:
            click.echo(f"  Warning: field extraction failed: {e}")
