import click

from commands.ingest import ingest
from commands.ocr import ocr
from commands.receipt.pipeline import receipt_pipeline
from commands.remove import remove
from commands.scan import scan


@click.group()
@click.option(
    "--path",
    default="Receipts",
    show_default=True,
    help="Subdirectory within the vault.",
)
@click.pass_context
def receipt(ctx, path):
    """Receipt processing commands."""
    ctx.obj["path"] = path


receipt.add_command(receipt_pipeline.consume_command, "consume")
receipt.add_command(receipt_pipeline.llm_command, "llm")
receipt.add_command(receipt_pipeline.render_command, "render")
receipt.add_command(remove)
receipt.add_command(ingest)
receipt.add_command(ocr)
receipt.add_command(scan)
