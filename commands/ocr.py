import base64
import json
import time
from contextlib import ExitStack
from pathlib import Path

import click
from mistralai import Mistral
from mistralai.models import OCRResponse, SDKError
from mistralai.models.ocrrequest import DocumentURLChunk, ImageURLChunk

from constants import ASSETS_DIR, OCR_MODEL
from utils import interruptible, iter_entries, source_file

MAX_RETRIES = 5
INITIAL_BACKOFF = 2


def _build_ocr_document(src_path: Path) -> DocumentURLChunk | ImageURLChunk:
    """Build the Mistral OCR document payload for a source file."""
    raw = base64.standard_b64encode(src_path.read_bytes()).decode("utf-8")
    ext = src_path.suffix.lower()
    if ext == ".pdf":
        return DocumentURLChunk(
            document_url=f"data:application/pdf;base64,{raw}",
        )
    return ImageURLChunk(
        image_url=f"data:image/jpeg;base64,{raw}",
    )


def _ocr_with_retry(
    client: Mistral,
    model: str,
    document: DocumentURLChunk | ImageURLChunk,
    *,
    max_retries: int = MAX_RETRIES,
) -> OCRResponse:
    """Call OCR with exponential backoff on retryable (429, 5xx) responses."""
    for attempt in range(max_retries + 1):
        try:
            return client.ocr.process(model=model, document=document)
        except SDKError as e:
            retryable = e.status_code == 429 or e.status_code >= 500
            if not retryable or attempt == max_retries:
                raise
            wait = INITIAL_BACKOFF * (2**attempt)
            reason = "Rate limited" if e.status_code == 429 else "Server error"
            click.secho(f"  {reason}, retrying in {wait}s…", fg="yellow")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def run_ocr(
    target_dir: Path,
    client: Mistral,
    *,
    model: str = OCR_MODEL,
    overwrite: bool = False,
) -> None:
    """Run Mistral OCR on the consumed source file and save results.

    If OCR output exists and not overwrite, skips the API call.
    Otherwise runs OCR and saves JSON + TXT.
    """
    ocr_dir = target_dir / "ocr"
    txt_path = ocr_dir / f"{model}.txt"

    if txt_path.exists() and not overwrite:
        click.secho("  OCR already exists, skipping", fg="yellow")
        return

    src_path = source_file(target_dir)
    if src_path is None:
        click.secho("  No source file found, skipping OCR", fg="yellow")
        return
    document = _build_ocr_document(src_path)

    ocr_response = _ocr_with_retry(client, model, document=document)

    ocr_dir.mkdir(exist_ok=True)
    (ocr_dir / f"{model}.json").write_text(
        json.dumps(ocr_response.model_dump(), indent=2)
    )
    pages_md = [page.markdown for page in ocr_response.pages]
    txt_path.write_text("\n\n".join(pages_md))
    click.secho(f"  OCR completed ({len(ocr_response.pages)} pages)", fg="green")


def make_ocr_command(*, pipeline):
    """Factory: create a click ocr command with type-specific config."""

    @click.command()
    @click.option(
        "--mistral-api-key",
        envvar="MISTRAL_API_KEY",
        required=True,
        help="Mistral API key for OCR processing.",
    )
    @click.option(
        "--ocr-model",
        default=OCR_MODEL,
        show_default=True,
        help="Mistral OCR model name.",
    )
    @click.option("--overwrite", is_flag=True, help="Overwrite existing OCR results.")
    @click.option(
        "--continue",
        "continue_",
        is_flag=True,
        help="Continue to LLM extraction and render after OCR.",
    )
    @click.option(
        "--openai-api-key",
        envvar="OPENAI_API_KEY",
        required=False,
        help="OpenAI API key (required with --continue).",
    )
    @click.option(
        "--llm-model",
        default=None,
        help="OpenAI model name for field extraction (used with --continue).",
    )
    @click.argument("sha256", nargs=-1)
    @click.pass_context
    def ocr(
        ctx,
        mistral_api_key,
        ocr_model,
        overwrite,
        continue_,
        openai_api_key,
        llm_model,
        sha256,
    ):
        if continue_ and not openai_api_key:
            raise click.UsageError(
                "--continue requires --openai-api-key or OPENAI_API_KEY env var."
            )

        vault = Path(ctx.obj["vault"])
        path = ctx.obj["path"]
        if sha256:
            entries = [vault / path / ASSETS_DIR / s for s in sha256]
        else:
            entries = iter_entries(vault, path)

        if continue_:
            from commands.llm import extract_fields
            from commands.render import index_existing_notes, render_note
            from constants import LLM_MODEL
            from openai import OpenAI

            if llm_model is None:
                llm_model = LLM_MODEL
            note_index = index_existing_notes(vault / path)
            pipeline.prepare_context(vault)

        with ExitStack() as stack:
            client = stack.enter_context(Mistral(api_key=mistral_api_key))
            if continue_:
                openai_client = stack.enter_context(OpenAI(api_key=openai_api_key))

            for target_dir in interruptible(entries):
                click.secho(f"OCR: {target_dir}", bold=True)
                run_ocr(target_dir, client, model=ocr_model, overwrite=overwrite)

                if not continue_:
                    continue

                try:
                    fields = extract_fields(
                        target_dir,
                        openai_client,
                        path,
                        model=llm_model,
                        overwrite=overwrite,
                        pipeline=pipeline,
                    )
                except Exception as e:
                    click.secho(f"  Warning: field extraction failed: {e}", fg="red")
                    continue

                if fields is not None:
                    try:
                        render_note(
                            target_dir,
                            overwrite=overwrite,
                            note_index=note_index,
                            pipeline=pipeline,
                        )
                    except Exception as e:
                        click.secho(f"  Warning: note rendering failed: {e}", fg="red")

    ocr.__doc__ = f"Run OCR on ingested {pipeline.name} files in the vault."
    return ocr
