import json
import re
from pathlib import Path

import click
import questionary

from commands.people import _iter_notes
from commands.render import _parse_frontmatter

ALIASES_FILE = ".obagent/bank-aliases.json"
PINNED_FILE = ".obagent/bank-pinned.json"


def _load_bank_aliases(vault: Path) -> dict[str, str]:
    """Load the bank aliases mapping from the vault, or return {}."""
    path = vault / ALIASES_FILE
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save_to_bank_aliases(vault: Path, mapping: dict[str, str]) -> None:
    """Merge mapping into the bank aliases JSON file, keeping keys sorted."""
    path = vault / ALIASES_FILE
    if path.exists():
        existing = json.loads(path.read_text())
    else:
        existing = {}
    existing.update(mapping)
    sorted_mapping = dict(sorted(existing.items()))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted_mapping, indent=2, ensure_ascii=False) + "\n")


def _remap_bank_in_file(md_path: Path, mapping: dict[str, str]) -> bool:
    """Apply a bank name mapping to the bank_name frontmatter field.

    mapping values: non-empty = rename. Returns True if the file was modified.
    """
    text = md_path.read_text()
    fm = _parse_frontmatter(text)
    if not fm or "bank_name" not in fm or not fm["bank_name"]:
        return False

    old_name = fm["bank_name"]
    if old_name not in mapping:
        return False

    new_name = mapping[old_name]
    if not new_name or new_name == old_name:
        return False

    new_text = re.sub(
        r"^(bank_name:)\s*.*$",
        rf"\1 {new_name}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if new_text == text:
        return False
    md_path.write_text(new_text)
    return True


def _load_pinned_banks(vault: Path) -> list[str]:
    """Load the pinned bank names from the vault, or return []."""
    path = vault / PINNED_FILE
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _save_pinned_banks(vault: Path, names: list[str]) -> None:
    """Save a deduplicated, sorted list of pinned bank names."""
    path = vault / PINNED_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    sorted_names = sorted(set(names))
    path.write_text(json.dumps(sorted_names, indent=2, ensure_ascii=False) + "\n")


def _collect_bank_names(vault: Path) -> list[str]:
    """Return sorted unique bank names across all vault notes."""
    names: set[str] = set()
    for md in _iter_notes(vault):
        fm = _parse_frontmatter(md.read_text())
        if fm and fm.get("bank_name"):
            names.add(fm["bank_name"])
    return sorted(names)


@click.group()
def bank():
    """Manage bank names across vault notes."""


@bank.command()
@click.argument("old_name", required=False, default=None)
@click.argument("new_name", required=False, default=None)
@click.pass_context
def rename(ctx, old_name, new_name):
    """Rename a bank across all notes in the vault."""
    vault = Path(ctx.obj["vault"])
    if old_name is None:
        all_names = _collect_bank_names(vault)
        if not all_names:
            click.echo("No bank names found in vault.")
            return
        pinned = set(_load_pinned_banks(vault))
        candidates = [n for n in all_names if n not in pinned]
        if not candidates:
            click.echo("All bank names are pinned.")
            return
        old_name = questionary.select(
            "Select bank to rename:", choices=candidates
        ).ask()
        if not old_name:
            return
        new_name = questionary.text("New name:").ask()
        if not new_name:
            return
    count = 0
    for md in _iter_notes(vault):
        if _remap_bank_in_file(md, {old_name: new_name}):
            click.secho(f"  Updated: {md.relative_to(vault)}", fg="green")
            count += 1
    click.secho(f"{count} file(s) updated", bold=True)
    if (
        count > 0
        and questionary.confirm("Save to bank-aliases.json?", default=False).ask()
    ):
        _save_to_bank_aliases(vault, {old_name: new_name})


@bank.command()
@click.argument("mapping_file", required=False, default=None, type=click.Path())
@click.pass_context
def remap(ctx, mapping_file):
    """Batch rename banks from a JSON mapping file."""
    vault = Path(ctx.obj["vault"])
    if mapping_file is not None:
        mapping_path = Path(mapping_file)
        if not mapping_path.exists():
            raise click.ClickException(f"Mapping file not found: {mapping_path}")
        mapping = json.loads(mapping_path.read_text())
    else:
        mapping = _load_bank_aliases(vault)
        if not mapping:
            raise click.ClickException(
                f"Mapping file not found: {vault / ALIASES_FILE}"
            )
    if not isinstance(mapping, dict):
        raise click.ClickException("Mapping file must contain a JSON object")
    total = 0
    for md in _iter_notes(vault):
        if _remap_bank_in_file(md, mapping):
            click.secho(f"  Updated: {md.relative_to(vault)}", fg="green")
            total += 1
    click.secho(f"{total} file(s) updated", bold=True)


@bank.command("list")
@click.pass_context
def list_banks(ctx):
    """List all unique bank names across vault notes."""
    vault = Path(ctx.obj["vault"])
    for name in _collect_bank_names(vault):
        click.echo(name)


@bank.command()
@click.argument("names", nargs=-1)
@click.pass_context
def pin(ctx, names):
    """Pin bank names to exclude them from interactive rename."""
    vault = Path(ctx.obj["vault"])
    interactive = not names
    if interactive:
        existing = set(_load_pinned_banks(vault))
        candidates = [n for n in _collect_bank_names(vault) if n not in existing]
        if not candidates:
            click.echo("No new bank names to pin.")
            return
        selected = questionary.checkbox(
            "Select banks to pin:", choices=candidates
        ).ask()
        if not selected:
            click.echo("No names selected.")
            return
        names = tuple(selected)
    existing = _load_pinned_banks(vault)
    merged = list(existing) + list(names)
    _save_pinned_banks(vault, merged)
    click.secho(f"Pinned: {', '.join(names)}", fg="green")


@bank.command()
@click.argument("names", nargs=-1)
@click.pass_context
def unpin(ctx, names):
    """Unpin bank names."""
    vault = Path(ctx.obj["vault"])
    existing = _load_pinned_banks(vault)
    if not existing:
        click.echo("No pinned bank names.")
        return
    interactive = not names
    if interactive:
        selected = questionary.checkbox(
            "Select banks to unpin:", choices=existing
        ).ask()
        if not selected:
            click.echo("No names selected.")
            return
        names = tuple(selected)
    to_remove = set(names)
    remaining = [n for n in existing if n not in to_remove]
    _save_pinned_banks(vault, remaining)
    click.secho(f"Unpinned: {', '.join(names)}", fg="green")
