from pathlib import Path

import click

from commands.ingest import ingest_pdf
from commands.llm import extract_fields
from commands.ocr import run_ocr
from commands.render import clear_notes, render_note
from constants import LLM_MODEL, OCR_MODEL


@click.command()
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
@click.option(
    "--ocr-model", default=OCR_MODEL, show_default=True, help="Mistral OCR model name."
)
@click.option(
    "--llm-model",
    default=LLM_MODEL,
    show_default=True,
    help="OpenAI model name for field extraction.",
)
@click.option("--keep-original", is_flag=True, help="Copy PDFs instead of moving them.")
@click.option(
    "--overwrite", is_flag=True, help="Overwrite existing entries and force re-OCR."
)
@click.argument("directory", type=click.Path(exists=True, file_okay=False))
@click.pass_context
def consume(
    ctx,
    mistral_api_key,
    openai_api_key,
    ocr_model,
    llm_model,
    keep_original,
    overwrite,
    directory,
):
    """Consume PDFs from a directory into the vault."""
    vault = Path(ctx.obj["vault"])
    path = ctx.obj["path"]
    if overwrite:
        clear_notes(vault / path)
    for pdf in sorted(Path(directory).rglob("*.pdf")):
        target_dir = ingest_pdf(
            pdf, vault, path, keep_original=keep_original, overwrite=overwrite
        )
        if target_dir is None:
            continue
        run_ocr(target_dir, mistral_api_key, model=ocr_model, overwrite=overwrite)
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
            continue
        try:
            render_note(target_dir)
        except Exception as e:
            click.echo(f"  Warning: note rendering failed: {e}")
