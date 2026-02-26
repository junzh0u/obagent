import click

from commands.bank_statement.consume import consume
from commands.bank_statement.llm import llm
from commands.bank_statement.render import render
from commands.ingest import ingest
from commands.ocr import ocr
from commands.remove import remove
from commands.scan import scan


@click.group()
@click.option(
    "--path",
    default="Bank Statements",
    show_default=True,
    help="Subdirectory within the vault.",
)
@click.pass_context
def bank_statement(ctx, path):
    """Bank statement processing commands."""
    ctx.obj["path"] = path


bank_statement.add_command(consume)
bank_statement.add_command(llm)
bank_statement.add_command(render)
bank_statement.add_command(ingest)
bank_statement.add_command(ocr)
bank_statement.add_command(remove)
bank_statement.add_command(scan)
