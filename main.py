from pathlib import Path

import click

from commands.bank import bank
from commands.bank_statement import bank_statement
from commands.check import check
from commands.consume import consume_all
from commands.document import document
from commands.export import export_all
from commands.merchant import merchant
from commands.notion.sync import notion
from commands.people import people
from commands.receipt import receipt
from commands.render import render_all


def _vault_root(value: str) -> str:
    """Resolve --vault to the vault root, requiring the ``.obagent/`` marker.

    Walks up git-style, so pointing inside the vault (e.g. at ``Receipts/``)
    resolves to the root instead of silently half-working against a directory
    that has no assets. A directory with no marker anywhere above it is
    rejected — for a brand-new vault, creating ``.obagent/`` is the opt-in.
    """
    p = Path(value).resolve()
    root = next((q for q in (p, *p.parents) if (q / ".obagent").is_dir()), None)
    if root is None:
        raise click.UsageError(
            f"{value} is not an obagent vault: no .obagent/ directory found "
            "there or in any parent. For a new vault, initialize it with: "
            f"mkdir '{value}/.obagent'"
        )
    if root != p:
        click.secho(f"note: using vault root {root} ({p} is inside it)", fg="yellow")
    return str(root)


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
    ctx.obj["vault"] = _vault_root(vault)


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
cli.add_command(check)

if __name__ == "__main__":
    cli()
