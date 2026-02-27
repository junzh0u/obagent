import click

from commands.document.consume import consume
from commands.document.llm import llm
from commands.document.render import render
from commands.ingest import ingest
from commands.ocr import ocr
from commands.remove import remove
from commands.scan import scan


@click.group()
@click.option(
    "--path",
    default="Documents",
    show_default=True,
    help="Subdirectory within the vault.",
)
@click.pass_context
def document(ctx, path):
    """Document processing commands."""
    ctx.obj["path"] = path


document.add_command(consume)
document.add_command(llm)
document.add_command(render)
document.add_command(ingest)
document.add_command(ocr)
document.add_command(remove)
document.add_command(scan)
