import click

from commands.consume import consume
from commands.remove import remove
from commands.ingest import ingest
from commands.llm import llm
from commands.ocr import ocr
from commands.render import render


@click.group()
@click.option(
    "--vault",
    envvar="OBAGENT_VAULT",
    required=True,
    type=click.Path(exists=True, file_okay=False),
    help="Path to the vault directory.",
)
@click.pass_context
def cli(ctx, vault):
    ctx.ensure_object(dict)
    ctx.obj["vault"] = vault


@cli.group()
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


receipt.add_command(consume)
receipt.add_command(remove)
receipt.add_command(ingest)
receipt.add_command(ocr)
receipt.add_command(llm)
receipt.add_command(render)

if __name__ == "__main__":
    cli()
