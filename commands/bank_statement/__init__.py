import click

from commands.bank_statement.pipeline import bank_statement_pipeline
from commands.ingest import ingest
from commands.remove import remove
from commands.scan import scan


@click.group()
@click.option(
    "--path",
    default=bank_statement_pipeline.default_path,
    show_default=True,
    help="Subdirectory within the vault.",
)
@click.pass_context
def bank_statement(ctx, path):
    """Bank statement processing commands."""
    ctx.obj["path"] = path


bank_statement.add_command(bank_statement_pipeline.consume_command, "consume")
bank_statement.add_command(bank_statement_pipeline.llm_command, "llm")
bank_statement.add_command(bank_statement_pipeline.render_command, "render")
bank_statement.add_command(ingest)
bank_statement.add_command(bank_statement_pipeline.ocr_command, "ocr")
bank_statement.add_command(remove)
bank_statement.add_command(scan)
