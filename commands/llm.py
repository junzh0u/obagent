import json
from pathlib import Path

import click
from openai import OpenAI


def extract_title(target_dir, api_key, ocr_text, path, *, overwrite=False):
    """Use OpenAI to extract metadata from OCR text and create a markdown note.

    If .md file exists and not overwrite, skips and returns None.
    If overwrite, deletes old .md files first.
    Returns safe_title on success, None if skipped.
    """
    existing_md = list(target_dir.glob("*.md"))
    if existing_md and not overwrite:
        click.echo("  Markdown already exists, skipping")
        return None
    if existing_md and overwrite:
        for md in existing_md:
            md.unlink()

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
    return safe_title


@click.command()
@click.option(
    "--openai-api-key",
    envvar="OPENAI_API_KEY",
    required=True,
    help="OpenAI API key for title extraction.",
)
@click.option("--overwrite", is_flag=True, help="Overwrite existing markdown files.")
@click.pass_context
def llm(ctx, openai_api_key, overwrite):
    """Extract metadata via LLM from OCR'd entries in the vault."""
    vault = Path(ctx.obj["vault"])
    path = ctx.obj["path"]
    for txt_path in sorted((vault / path).rglob("mistral-ocr-latest.txt")):
        target_dir = txt_path.parent.parent
        ocr_text = txt_path.read_text()
        click.echo(f"LLM: {target_dir}")
        try:
            extract_title(
                target_dir, openai_api_key, ocr_text, path, overwrite=overwrite
            )
        except Exception as e:
            click.echo(f"  Warning: title extraction failed: {e}")
