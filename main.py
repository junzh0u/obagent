import click

from commands.consume import consume


@click.group()
def cli():
    pass


cli.add_command(consume)

if __name__ == "__main__":
    cli()
