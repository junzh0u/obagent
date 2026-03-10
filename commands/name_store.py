"""Shared helpers and command factories for name management (bank, people)."""

import json
from collections.abc import Callable
from pathlib import Path

import click
import questionary


def iter_notes(vault: Path):
    """Yield .md files in the vault, skipping _assets_ directories."""
    for md in sorted(vault.rglob("*.md")):
        if "_assets_" not in md.parts:
            yield md


# --- Generic JSON I/O ---


def load_json_dict(vault: Path, rel_path: str) -> dict[str, str]:
    """Load a JSON object from vault/rel_path, or return {}."""
    path = vault / rel_path
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_json_dict(vault: Path, rel_path: str, mapping: dict[str, str]) -> None:
    """Merge mapping into a JSON object file, keeping keys sorted."""
    path = vault / rel_path
    if path.exists():
        existing = json.loads(path.read_text())
    else:
        existing = {}
    existing.update(mapping)
    sorted_mapping = dict(sorted(existing.items()))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted_mapping, indent=2, ensure_ascii=False) + "\n")


def load_json_list(vault: Path, rel_path: str) -> list[str]:
    """Load a JSON list from vault/rel_path, or return []."""
    path = vault / rel_path
    if not path.exists():
        return []
    return json.loads(path.read_text())


def save_json_list(
    vault: Path,
    rel_path: str,
    names: list[str],
    sort_key: Callable | None = None,
) -> None:
    """Save a deduplicated, sorted JSON list."""
    path = vault / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    sorted_names = sorted(set(names), key=sort_key)
    path.write_text(json.dumps(sorted_names, indent=2, ensure_ascii=False) + "\n")


# --- Command factories ---


def make_rename_command(
    group: click.Group,
    *,
    collect_names: Callable[[Path], list[str]],
    load_pinned: Callable[[Path], list[str]],
    remap_in_file: Callable[[Path, dict[str, str]], bool],
    save_aliases: Callable[[Path, dict[str, str]], None],
    aliases_label: str,
    label: str,
):
    """Create a rename command on *group*."""

    @group.command()
    @click.argument("old_name", required=False, default=None)
    @click.argument("new_name", required=False, default=None)
    @click.pass_context
    def rename(ctx, old_name, new_name):
        f"""Rename a {label} across all notes in the vault."""
        vault = Path(ctx.obj["vault"])
        if old_name is None:
            all_names = collect_names(vault)
            if not all_names:
                click.echo(f"No {label} names found in vault.")
                return
            pinned = set(load_pinned(vault))
            candidates = [n for n in all_names if n not in pinned]
            if not candidates:
                click.echo(f"All {label} names are pinned.")
                return
            old_name = questionary.select(
                f"Select {label} to rename:", choices=candidates
            ).ask()
            if not old_name:
                return
            new_name = questionary.text("New name:").ask()
            if not new_name:
                return
        count = 0
        for md in iter_notes(vault):
            if remap_in_file(md, {old_name: new_name}):
                click.secho(f"  Updated: {md.relative_to(vault)}", fg="green")
                count += 1
        click.secho(f"{count} file(s) updated", bold=True)
        if (
            count > 0
            and questionary.confirm(f"Save to {aliases_label}?", default=False).ask()
        ):
            save_aliases(vault, {old_name: new_name})

    return rename


def make_remap_command(
    group: click.Group,
    *,
    aliases_file: str,
    load_aliases: Callable[[Path], dict[str, str]],
    remap_in_file: Callable[[Path, dict[str, str]], bool],
    label: str,
):
    """Create a remap (batch rename) command on *group*."""

    @group.command()
    @click.argument("mapping_file", required=False, default=None, type=click.Path())
    @click.pass_context
    def remap(ctx, mapping_file):
        f"""Batch rename {label}s from a JSON mapping file."""
        vault = Path(ctx.obj["vault"])
        if mapping_file is not None:
            mapping_path = Path(mapping_file)
            if not mapping_path.exists():
                raise click.ClickException(f"Mapping file not found: {mapping_path}")
            mapping = json.loads(mapping_path.read_text())
        else:
            mapping = load_aliases(vault)
            if not mapping:
                raise click.ClickException(
                    f"Mapping file not found: {vault / aliases_file}"
                )
        if not isinstance(mapping, dict):
            raise click.ClickException("Mapping file must contain a JSON object")
        total = 0
        for md in iter_notes(vault):
            if remap_in_file(md, mapping):
                click.secho(f"  Updated: {md.relative_to(vault)}", fg="green")
                total += 1
        click.secho(f"{total} file(s) updated", bold=True)

    return remap


def make_list_command(
    group: click.Group,
    *,
    collect_names: Callable[[Path], list[str]],
    label: str,
):
    """Create a list command on *group*."""

    @group.command("list")
    @click.pass_context
    def list_names(ctx):
        f"""List all unique {label} names across vault notes."""
        vault = Path(ctx.obj["vault"])
        for name in collect_names(vault):
            click.echo(name)

    return list_names


def make_pin_command(
    group: click.Group,
    *,
    load_pinned: Callable[[Path], list[str]],
    save_pinned: Callable[[Path, list[str]], None],
    collect_names: Callable[[Path], list[str]],
    label: str,
    on_pin: Callable[[Path], None] | None = None,
):
    """Create a pin command on *group*."""

    @group.command()
    @click.argument("names", nargs=-1)
    @click.pass_context
    def pin(ctx, names):
        f"""Pin {label} names to exclude them from interactive rename."""
        vault = Path(ctx.obj["vault"])
        interactive = not names
        if interactive:
            existing = set(load_pinned(vault))
            candidates = [n for n in collect_names(vault) if n not in existing]
            if not candidates:
                click.echo(f"No new {label} names to pin.")
                return
            selected = questionary.checkbox(
                f"Select {label}s to pin:", choices=candidates
            ).ask()
            if not selected:
                click.echo("No names selected.")
                return
            names = tuple(selected)
        existing = load_pinned(vault)
        merged = list(existing) + list(names)
        save_pinned(vault, merged)
        click.secho(f"Pinned: {', '.join(names)}", fg="green")
        if interactive and on_pin:
            on_pin(vault)

    return pin


def make_unpin_command(
    group: click.Group,
    *,
    load_pinned: Callable[[Path], list[str]],
    save_pinned: Callable[[Path, list[str]], None],
    label: str,
    on_unpin: Callable[[Path, set[str]], None] | None = None,
):
    """Create an unpin command on *group*."""

    @group.command()
    @click.argument("names", nargs=-1)
    @click.pass_context
    def unpin(ctx, names):
        f"""Unpin {label} names."""
        vault = Path(ctx.obj["vault"])
        existing = load_pinned(vault)
        if not existing:
            click.echo(f"No pinned {label} names.")
            return
        interactive = not names
        if interactive:
            selected = questionary.checkbox(
                f"Select {label}s to unpin:", choices=existing
            ).ask()
            if not selected:
                click.echo("No names selected.")
                return
            names = tuple(selected)
        to_remove = set(names)
        remaining = [n for n in existing if n not in to_remove]
        save_pinned(vault, remaining)
        click.secho(f"Unpinned: {', '.join(names)}", fg="green")
        if interactive and on_unpin:
            on_unpin(vault, to_remove)

    return unpin
