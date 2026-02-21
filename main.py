import click

from commands.consume import consume


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

if __name__ == "__main__":
    cli()
