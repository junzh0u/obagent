import json
from pathlib import Path

import click
from openai import OpenAI

from constants import ASSETS_DIR, LLM_MODEL
from utils import interruptible, iter_entries, newest_file


def extract_fields(
    target_dir,
    client,
    path,
    *,
    model=LLM_MODEL,
    overwrite=False,
    pipeline,
):
    """Use OpenAI to extract metadata from OCR text and save as JSON.

    Discovers the newest OCR .txt file under target_dir/ocr/.
    If llm/<model>.json exists and not overwrite, skips and returns None.
    Returns the parsed fields dict on success, None if skipped.

    pipeline: Pipeline providing prompt() and postprocess() methods.
    """
    llm_dir = target_dir / "llm"
    json_path = llm_dir / f"{model}.json"
    if json_path.exists() and not overwrite:
        click.secho("  LLM result already exists, skipping", fg="yellow")
        return None

    txt_path = newest_file(target_dir / "ocr", "*.txt")
    if txt_path is None:
        click.secho("  No OCR result found, skipping LLM", fg="yellow")
        return None
    ocr_text = txt_path.read_text()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": pipeline.prompt(path, ocr_text),
            },
        ],
    )
    raw = response.choices[0].message.content.strip()
    fields = json.loads(raw)
    pipeline.postprocess(fields)
    llm_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(fields, indent=2) + "\n")
    click.secho(f"  Extracted: {fields}", fg="green")
    return fields


def make_llm_command(*, pipeline):
    """Factory: create a click llm command with type-specific config."""

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
    @click.option(
        "--overwrite", is_flag=True, help="Overwrite existing markdown files."
    )
    @click.option(
        "--continue",
        "continue_",
        is_flag=True,
        help="Continue to render after LLM extraction.",
    )
    @click.argument("sha256", nargs=-1)
    @click.pass_context
    def llm(ctx, openai_api_key, llm_model, overwrite, continue_, sha256):
        vault = Path(ctx.obj["vault"])
        path = ctx.obj["path"]
        if sha256:
            entries = [vault / path / ASSETS_DIR / s for s in sha256]
        else:
            entries = iter_entries(vault, path)

        note_index = None
        if continue_:
            from commands.render import index_existing_notes

            if sha256 or not overwrite:
                note_index = index_existing_notes(vault / path)

        with OpenAI(api_key=openai_api_key) as client:
            for target_dir in interruptible(entries):
                click.secho(f"LLM: {target_dir}", bold=True)
                try:
                    fields = extract_fields(
                        target_dir,
                        client,
                        path,
                        model=llm_model,
                        overwrite=overwrite,
                        pipeline=pipeline,
                    )
                except Exception as e:
                    click.secho(f"  Warning: field extraction failed: {e}", fg="red")
                    continue

                if continue_ and fields is not None:
                    from commands.render import render_note

                    try:
                        render_note(
                            target_dir,
                            overwrite=overwrite,
                            note_index=note_index,
                            pipeline=pipeline,
                        )
                    except Exception as e:
                        click.secho(f"  Warning: note rendering failed: {e}", fg="red")

    llm.__doc__ = pipeline.help_llm
    return llm
