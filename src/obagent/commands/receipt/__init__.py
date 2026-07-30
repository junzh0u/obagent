import click

from obagent.commands.export import export
from obagent.commands.ingest import ingest
from obagent.commands.receipt.pipeline import receipt_pipeline
from obagent.commands.remove import remove
from obagent.commands.scan import scan


@click.group()
@click.option(
    "--path",
    default=receipt_pipeline.default_path,
    show_default=True,
    help="Subdirectory within the vault.",
)
@click.pass_context
def receipt(ctx, path):
    """Receipt processing commands."""
    ctx.obj["path"] = path


receipt.add_command(receipt_pipeline.consume_command, "consume")
receipt.add_command(export)
receipt.add_command(receipt_pipeline.llm_command, "llm")
receipt.add_command(receipt_pipeline.render_command, "render")
receipt.add_command(remove)
receipt.add_command(ingest)
receipt.add_command(receipt_pipeline.ocr_command, "ocr")
receipt.add_command(scan)
receipt.add_command(receipt_pipeline.set_command, "set")
