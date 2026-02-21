import click

from commands.consume import consume
from commands.ingest import ingest
from commands.llm import llm
from commands.ocr import ocr


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


cli.add_command(consume)
cli.add_command(ingest)
cli.add_command(ocr)
cli.add_command(llm)

if __name__ == "__main__":
    cli()
