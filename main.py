import click

from commands.bank import bank
from commands.bank_statement import bank_statement
from commands.consume import consume_all
from commands.document import document
from commands.export import export_all
from commands.merchant import merchant
from commands.notion.sync import notion
from commands.people import people
from commands.receipt import receipt
from commands.render import render_all


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


cli.add_command(receipt)
cli.add_command(bank_statement)
cli.add_command(document)
cli.add_command(bank)
cli.add_command(merchant)
cli.add_command(people)
cli.add_command(notion)
cli.add_command(consume_all, "consume")
cli.add_command(export_all, "export")
cli.add_command(render_all, "render")

if __name__ == "__main__":
    cli()
