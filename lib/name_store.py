"""Shared helpers and command factories for name management (bank, people)."""

import json
import re
from collections.abc import Callable
from pathlib import Path

import click
import questionary

from lib.constants import AUTO_RENAME_MODEL

# TODO: Remove after questionary fixes the checkbox instruction text upstream.
# Workaround for questionary bug: instruction text shows <ctrl-a> for both
# "toggle" and "invert" when use_search_filter=True. Invert is actually <ctrl-i>.
# See https://github.com/tmbo/questionary/blob/master/questionary/prompts/checkbox.py
_CHECKBOX_INSTRUCTION = (
    "(Use arrow keys to move, <space> to select, "
    "<ctrl-a> to toggle, <ctrl-i> to invert, type to filter)"
)


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
    on_rename: Callable[[Path, list[Path]], None] | None = None,
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
                f"Select {label} to rename:",
                choices=candidates,
                use_search_filter=True,
                use_jk_keys=False,
            ).ask()
            if not old_name:
                return
            new_name = questionary.autocomplete("New name:", choices=all_names).ask()
            if not new_name:
                return
        modified: list[Path] = []
        for md in iter_notes(vault):
            if remap_in_file(md, {old_name: new_name}):
                click.secho(f"  Updated: {md.relative_to(vault)}", fg="green")
                modified.append(md)
        click.secho(f"{len(modified)} file(s) updated", bold=True)
        if modified and on_rename:
            on_rename(vault, modified)
        if (
            modified
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
    on_rename: Callable[[Path, list[Path]], None] | None = None,
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
        modified: list[Path] = []
        for md in iter_notes(vault):
            if remap_in_file(md, mapping):
                click.secho(f"  Updated: {md.relative_to(vault)}", fg="green")
                modified.append(md)
        click.secho(f"{len(modified)} file(s) updated", bold=True)
        if modified and on_rename:
            on_rename(vault, modified)

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
                f"Select {label}s to pin:",
                choices=candidates,
                instruction=_CHECKBOX_INSTRUCTION,
                use_search_filter=True,
                use_jk_keys=False,
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
                f"Select {label}s to unpin:",
                choices=existing,
                instruction=_CHECKBOX_INSTRUCTION,
                use_search_filter=True,
                use_jk_keys=False,
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


_AUTO_RENAME_PROMPT = """\
I have the following list of {label} names from my documents:
{names}

{pinned_block}\
Find names that are likely duplicates or variants of the same entity \
(e.g. different casing, abbreviations, store numbers, extra whitespace).
Return ONLY a JSON object mapping each variant to its canonical form.
Only include names that should be renamed — omit names that are already canonical.
{pinned_rule}\
Example: {{"STARBUCKS #1234": "Starbucks", "starbucks coffee": "Starbucks"}}"""


def make_auto_rename_command(
    group: click.Group,
    *,
    collect_names: Callable[[Path], list[str]],
    load_pinned: Callable[[Path], list[str]],
    remap_in_file: Callable[[Path, dict[str, str]], bool],
    save_aliases: Callable[[Path, dict[str, str]], None],
    aliases_label: str,
    label: str,
    on_rename: Callable[[Path, list[Path]], None] | None = None,
):
    """Create an auto-rename command that uses an LLM to find duplicates."""

    @group.command("auto-rename")
    @click.option(
        "--openai-api-key",
        envvar="OPENAI_API_KEY",
        required=True,
        help="OpenAI API key.",
    )
    @click.option(
        "--llm-model",
        default=AUTO_RENAME_MODEL,
        show_default=True,
        help="OpenAI model name.",
    )
    @click.pass_context
    def auto_rename(ctx, openai_api_key, llm_model):
        f"""Use LLM to find duplicate {label} names and batch rename."""
        from openai import OpenAI

        vault = Path(ctx.obj["vault"])
        all_names = collect_names(vault)
        if not all_names:
            click.echo(f"No {label} names found in vault.")
            return

        pinned = load_pinned(vault)
        pinned_block = ""
        pinned_rule = ""
        if pinned:
            pinned_block = (
                "Pinned names (canonical — do not rename these, "
                "but others can map to them):\n"
                f"{json.dumps(pinned, ensure_ascii=False)}\n\n"
            )
            pinned_rule = "Do not rename pinned names.\n"

        prompt_text = _AUTO_RENAME_PROMPT.format(
            label=label,
            names=json.dumps(all_names, ensure_ascii=False),
            pinned_block=pinned_block,
            pinned_rule=pinned_rule,
        )

        click.echo("Asking LLM to find duplicates...")
        with OpenAI(api_key=openai_api_key) as client:
            response = client.chat.completions.create(
                model=llm_model,
                messages=[{"role": "user", "content": prompt_text}],
            )
        raw = (response.choices[0].message.content or "").strip()
        # Strip markdown fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        try:
            mapping = json.loads(raw)
        except json.JSONDecodeError:
            raise click.ClickException(f"LLM returned invalid JSON:\n{raw}")
        if not isinstance(mapping, dict):
            raise click.ClickException("LLM returned non-object JSON.")

        # Filter out pinned names from the "from" side
        pinned_set = set(pinned)
        mapping = {k: v for k, v in mapping.items() if k not in pinned_set and k != v}

        if not mapping:
            click.echo("No duplicates found.")
            return

        choices = [f"{old} → {new}" for old, new in mapping.items()]
        selected = questionary.checkbox(
            "Select renames to apply:",
            choices=choices,
            instruction=_CHECKBOX_INSTRUCTION,
            use_search_filter=True,
            use_jk_keys=False,
        ).ask()
        if not selected:
            click.echo("No renames selected.")
            return

        # Parse selected choices back to mapping
        accepted = {}
        for choice in selected:
            old, new = choice.split(" → ", 1)
            accepted[old] = new

        modified: list[Path] = []
        for md in iter_notes(vault):
            if remap_in_file(md, accepted):
                click.secho(f"  Updated: {md.relative_to(vault)}", fg="green")
                modified.append(md)
        click.secho(f"{len(modified)} file(s) updated", bold=True)
        if modified and on_rename:
            on_rename(vault, modified)

        if (
            modified
            and questionary.confirm(f"Save to {aliases_label}?", default=False).ask()
        ):
            save_aliases(vault, accepted)

    return auto_rename
