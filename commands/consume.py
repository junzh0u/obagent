from pathlib import Path

import click

from commands.ingest import ingest_pdf
from commands.llm import extract_title
from commands.ocr import run_ocr


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
        target_dir = ingest_pdf(
            pdf, vault, path, keep_original=keep_original, overwrite=overwrite
        )
        if target_dir is None:
            continue
        ocr_text = run_ocr(target_dir, mistral_api_key, overwrite=overwrite)
        try:
            extract_title(
                target_dir, openai_api_key, ocr_text, path, overwrite=overwrite
            )
        except Exception as e:
            click.echo(f"  Warning: title extraction failed: {e}")
