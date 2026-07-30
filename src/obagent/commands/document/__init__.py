import click

from obagent.commands.document.pipeline import document_pipeline
from obagent.commands.export import export
from obagent.commands.ingest import ingest
from obagent.commands.remove import remove
from obagent.commands.scan import scan


@click.group()
@click.option(
    "--path",
    default=document_pipeline.default_path,
    show_default=True,
    help="Subdirectory within the vault.",
)
@click.pass_context
def document(ctx, path):
    """Document processing commands."""
    ctx.obj["path"] = path


document.add_command(document_pipeline.consume_command, "consume")
document.add_command(export)
document.add_command(document_pipeline.llm_command, "llm")
document.add_command(document_pipeline.render_command, "render")
document.add_command(ingest)
document.add_command(document_pipeline.ocr_command, "ocr")
document.add_command(remove)
document.add_command(scan)
document.add_command(document_pipeline.set_command, "set")
