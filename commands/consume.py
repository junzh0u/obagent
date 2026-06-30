import subprocess
import time
from collections.abc import Iterable
from pathlib import Path

import click
from mistralai.client import Mistral
from openai import OpenAI

from commands.ingest import ingest_source, resolve_sources
from commands.llm import extract_fields
from commands.ocr import run_ocr
from commands.render import index_existing_notes, render_note
from lib.constants import LLM_MODEL, OCR_MODEL
from lib.pipeline import Pipeline
from lib.utils import interruptible


def _queue_append(queue: Path, source: Path) -> None:
    """Append a consumed source's resolved path to the purge queue (one per line).

    O_APPEND makes each small write atomic, so a host-side drain that renames the
    queue away mid-run never tears a line. ``source.resolve()`` matches the
    container absolute path metadata.json records (e.g. ``/consume/Receipts/x.pdf``).
    """
    queue.parent.mkdir(parents=True, exist_ok=True)
    with queue.open("a") as f:
        f.write(f"{source.resolve()}\n")


def _consume_path(
    vault: Path,
    path: str,
    sources: Iterable[Path],
    *,
    pipeline: Pipeline,
    mistral_client: Mistral,
    openai_client: OpenAI,
    ocr_model: str,
    llm_model: str,
    keep_original: bool,
    overwrite: bool,
    purge_queue: Path | None = None,
) -> tuple[int, int]:
    """Run the consume pipeline for one vault subdir. Returns (consumed, skipped).

    When ``purge_queue`` is set, sources are **copied** (never moved) and each
    consumed source's path is appended to the queue file for a host-side job to
    delete — Cloud Sync can't observe the container's own unlink, so the inbox
    file must outlive consume and be removed on the host. See DEPLOY.md.
    """
    pipeline.prepare_context(vault)
    note_index = index_existing_notes(vault / path) if overwrite else None
    # Purge-queue mode hands deletion to the host, so the source must survive
    # consume: force copy regardless of --keep-original.
    effective_keep = keep_original or purge_queue is not None
    consumed = 0
    skipped = 0
    for source in interruptible(sources):
        click.secho(f"Consume: {source}", bold=True)
        target_dir = ingest_source(
            source,
            vault,
            path,
            keep_original=effective_keep,
            overwrite=overwrite,
        )
        if target_dir is None:
            # Already in the vault — the inbox copy is redundant, queue it now.
            if purge_queue is not None:
                _queue_append(purge_queue, source)
            skipped += 1
            continue
        try:
            run_ocr(target_dir, mistral_client, model=ocr_model, overwrite=overwrite)
        except Exception as e:
            raise click.ClickException(f"OCR failed: {e}") from e
        try:
            extract_fields(
                target_dir,
                openai_client,
                path,
                model=llm_model,
                overwrite=overwrite,
                pipeline=pipeline,
            )
        except Exception as e:
            raise click.ClickException(f"Field extraction failed: {e}") from e
        try:
            render_note(
                target_dir,
                overwrite=overwrite,
                note_index=note_index,
                pipeline=pipeline,
            )
        except Exception as e:
            click.secho(f"  Warning: note rendering failed: {e}", fg="red")
        # Asset bytes are safely in the vault; record the source for host-side
        # purge. A mid-pipeline OCR/LLM raise above skips this, leaving the source
        # in the inbox for a clean retry next pass.
        if purge_queue is not None:
            _queue_append(purge_queue, source)
        consumed += 1
    return consumed, skipped


def _resolve_consume_sources(
    paths: tuple[str, ...], input_dir: Path | None, type_path: str
) -> list[Path] | None:
    """Pick sources from positional PATHS, falling back to {input_dir}/{type_path}/.

    Returns ``None`` if the env-var inbox is missing (caller should skip the
    whole run — the warning is already logged). Returns a (possibly empty)
    list of source paths otherwise.
    """
    if paths:
        return resolve_sources(paths)
    if input_dir is not None:
        type_inbox = input_dir / type_path
        if not type_inbox.is_dir():
            click.secho(f"No inbox at {type_inbox}, nothing to consume.", fg="yellow")
            return None
        return resolve_sources((str(type_inbox),))
    raise click.UsageError("Either provide PATHS or set --input-dir / OBAGENT_CONSUME.")


def _filter_stable(sources: list[Path], min_age: int) -> list[Path]:
    """Drop files modified within the last ``min_age`` seconds (quiescence gate).

    Stateless: a slow upload keeps bumping its mtime, so it stays skipped until
    it has settled for ``min_age`` seconds. ``min_age=0`` disables the gate.
    """
    if not min_age:
        return sources
    cutoff = time.time() - min_age
    stable, settling = [], 0
    for s in sources:
        try:
            settled = s.stat().st_mtime <= cutoff
        except OSError:
            settled = False
        if settled:
            stable.append(s)
        else:
            settling += 1
    if settling:
        click.secho(
            f"  Skipping {settling} file(s) modified in the last {min_age}s "
            "(still settling).",
            fg="yellow",
        )
    return stable


def _print_summary(consumed: int, skipped: int) -> None:
    total = consumed + skipped
    click.secho(
        f"{total} files found: {consumed} consumed, {skipped} already in vault",
        bold=True,
    )


def _api_and_model_options(f):
    """Apply the API key, model, and flag options shared by both consume entry points.

    Options are applied bottom-up so --help renders them in the natural order:
    min-age, mistral-api-key, openai-api-key, ocr-model, llm-model, keep-original,
    overwrite, purge-queue.
    """
    f = click.option(
        "--purge-queue",
        envvar="OBAGENT_PURGE_QUEUE",
        type=click.Path(dir_okay=False, path_type=Path),
        default=None,
        help="Copy (not move) sources and record their paths to this queue file "
        "for a host-side job to delete (drains a Cloud-Synced inbox). See DEPLOY.md.",
    )(f)
    f = click.option(
        "--overwrite",
        is_flag=True,
        help="Overwrite existing entries and force re-OCR.",
    )(f)
    f = click.option(
        "--keep-original",
        is_flag=True,
        help="Copy files instead of moving them.",
    )(f)
    f = click.option(
        "--llm-model",
        default=LLM_MODEL,
        show_default=True,
        help="OpenAI model name for field extraction.",
    )(f)
    f = click.option(
        "--ocr-model",
        default=OCR_MODEL,
        show_default=True,
        help="Mistral OCR model name.",
    )(f)
    f = click.option(
        "--openai-api-key",
        envvar="OPENAI_API_KEY",
        required=True,
        help="OpenAI API key for title extraction.",
    )(f)
    f = click.option(
        "--mistral-api-key",
        envvar="MISTRAL_API_KEY",
        required=True,
        help="Mistral API key for OCR processing.",
    )(f)
    f = click.option(
        "--min-age",
        type=int,
        default=0,
        show_default=True,
        help="Skip files modified within the last N seconds (let slow uploads settle).",
    )(f)
    return f


def make_consume_command(*, pipeline: Pipeline) -> click.Command:
    """Factory: create a click consume command with type-specific config."""

    @click.command()
    @_api_and_model_options
    @click.option(
        "--input-dir",
        envvar="OBAGENT_CONSUME",
        type=click.Path(file_okay=False, path_type=Path),
        help="Inbox root; the per-type subdir is appended. Used when no PATHS are given.",
    )
    @click.argument("paths", nargs=-1, type=click.Path(exists=True))
    @click.pass_context
    def consume(
        ctx,
        mistral_api_key,
        openai_api_key,
        ocr_model,
        llm_model,
        keep_original,
        overwrite,
        purge_queue,
        min_age,
        input_dir,
        paths,
    ):
        vault = Path(ctx.obj["vault"])
        path = ctx.obj["path"]
        sources = _resolve_consume_sources(paths, input_dir, path)
        if sources is None:
            return
        sources = _filter_stable(sources, min_age)
        with (
            Mistral(api_key=mistral_api_key) as mistral_client,
            OpenAI(api_key=openai_api_key) as openai_client,
        ):
            consumed, skipped = _consume_path(
                vault,
                path,
                sources,
                pipeline=pipeline,
                mistral_client=mistral_client,
                openai_client=openai_client,
                ocr_model=ocr_model,
                llm_model=llm_model,
                keep_original=keep_original,
                overwrite=overwrite,
                purge_queue=purge_queue,
            )
        _print_summary(consumed, skipped)

    consume.__doc__ = pipeline.help_consume
    return consume


@click.command("consume")
@_api_and_model_options
@click.option(
    "--prehook",
    envvar="OBAGENT_CONSUME_PREHOOK",
    type=str,
    metavar="CMD",
    help="Shell command to run before consume (e.g. fetch new files into the inbox). Aborts on non-zero exit.",
)
@click.option(
    "--input-dir",
    envvar="OBAGENT_CONSUME",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Inbox root; per-type subdirs (Documents/, Receipts/, ...) are appended.",
)
@click.pass_context
def consume_all(
    ctx,
    mistral_api_key,
    openai_api_key,
    ocr_model,
    llm_model,
    keep_original,
    overwrite,
    purge_queue,
    min_age,
    prehook,
    input_dir,
):
    """Consume source files for every document type from --input-dir/{type}/."""
    if prehook:
        click.secho("\n=== Prehook ===", bold=True)
        click.secho(f"$ {prehook}", fg="cyan")
        try:
            subprocess.run(prehook, shell=True, check=True)
        except subprocess.CalledProcessError as e:
            raise click.ClickException(
                f"Prehook failed with exit code {e.returncode}"
            ) from e
    vault = Path(ctx.obj["vault"])
    with (
        Mistral(api_key=mistral_api_key) as mistral_client,
        OpenAI(api_key=openai_api_key) as openai_client,
    ):
        for pipeline in Pipeline._registry:
            path = pipeline.default_path
            click.secho(f"\n=== {path} ===", bold=True)
            type_inbox = input_dir / path
            if not type_inbox.is_dir():
                click.secho(f"  No inbox at {type_inbox}, skipping.", fg="yellow")
                continue
            sources = _filter_stable(resolve_sources((str(type_inbox),)), min_age)
            consumed, skipped = _consume_path(
                vault,
                path,
                sources,
                pipeline=pipeline,
                mistral_client=mistral_client,
                openai_client=openai_client,
                ocr_model=ocr_model,
                llm_model=llm_model,
                keep_original=keep_original,
                overwrite=overwrite,
                purge_queue=purge_queue,
            )
            _print_summary(consumed, skipped)
