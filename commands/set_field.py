"""Set one field on an entry and re-render its note.

The sanctioned way to correct an extraction (a total misread as USD, a wrong
date) without hand-editing generated files: the value is written into the
entry's LLM JSON — the render source, so the fix survives future re-renders —
then the note is re-rendered with ``overwrite_fields`` for that field so the
correction beats the preserved frontmatter. Renames flow through the normal
render path.
"""

import json
from pathlib import Path

import click

from lib.constants import ASSETS_DIR
from lib.pipeline import Pipeline
from lib.utils import newest_file, target_shas


def make_set_command(*, pipeline: Pipeline) -> click.Command:
    """Factory: create a click set command with type-specific config."""

    @click.command("set")
    @click.argument("target", metavar="SHA256|NOTE")
    @click.argument("field")
    @click.argument("value")
    @click.pass_context
    def set_field(ctx, target, field, value):
        from commands.render import _render_entries

        vault = Path(ctx.obj["vault"])
        path_dir = vault / ctx.obj["path"]
        keys = pipeline.fields_class.expected_keys()
        if field not in keys:
            raise click.UsageError(
                f"Unknown {pipeline.name} field {field!r}; expected one of: "
                + ", ".join(sorted(keys))
            )
        shas = target_shas(path_dir, target)
        if len(shas) > 1:
            raise click.UsageError(
                f"{target} embeds {len(shas)} sources; pass the sha256 of the "
                "one whose extraction is wrong"
            )
        target_dir = path_dir / ASSETS_DIR / shas[0]
        json_path = newest_file(target_dir / "llm", "*.json")
        if json_path is None:
            raise click.ClickException(f"No LLM result found for {shas[0]}")
        data = json.loads(json_path.read_text())
        data[field] = value
        json_path.write_text(json.dumps(data, indent=2) + "\n")
        pipeline.prepare_context(vault)
        _render_entries(
            [target_dir],
            path_dir=path_dir,
            pipeline=pipeline,
            overwrite_fields=field,
            log_header=True,
        )

    set_field.__doc__ = pipeline.help_set
    return set_field
