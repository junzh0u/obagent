from pathlib import Path

import click
from mistralai import Mistral
from openai import OpenAI

from commands.ingest import ingest_pdf, resolve_pdfs
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
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True))
@click.pass_context
def consume(
    ctx,
    mistral_api_key,
    openai_api_key,
    ocr_model,
    llm_model,
    keep_original,
    overwrite,
    paths,
):
    """Consume PDFs into the vault. Accepts PDF files and/or directories."""
    vault = Path(ctx.obj["vault"])
    path = ctx.obj["path"]
    if overwrite:
        clear_notes(vault / path)
    consumed = 0
    skipped = 0
    with (
        Mistral(api_key=mistral_api_key) as mistral_client,
        OpenAI(api_key=openai_api_key) as openai_client,
    ):
        for pdf in resolve_pdfs(paths):
            click.secho(f"Consume: {pdf}", bold=True)
            target_dir = ingest_pdf(
                pdf, vault, path, keep_original=keep_original, overwrite=overwrite
            )
            if target_dir is None:
                skipped += 1
                continue
            try:
                run_ocr(
                    target_dir, mistral_client, model=ocr_model, overwrite=overwrite
                )
            except Exception as e:
                raise click.ClickException(f"OCR failed: {e}") from e
            try:
                extract_fields(
                    target_dir,
                    openai_client,
                    path,
                    model=llm_model,
                    overwrite=overwrite,
                )
            except Exception as e:
                raise click.ClickException(f"Field extraction failed: {e}") from e
            try:
                render_note(target_dir)
            except Exception as e:
                click.secho(f"  Warning: note rendering failed: {e}", fg="red")
            consumed += 1
    total = consumed + skipped
    click.secho(
        f"{total} PDFs found: {consumed} consumed, {skipped} already in vault",
        bold=True,
    )
