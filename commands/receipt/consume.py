from commands.consume import make_consume_command
from commands.receipt.llm import _postprocess, _prompt
from commands.receipt.render import (
    FIELD_DEFAULTS,
    format_frontmatter,
    make_title,
)

consume = make_consume_command(
    prompt_fn=_prompt,
    postprocess=_postprocess,
    field_defaults=FIELD_DEFAULTS,
    make_title=make_title,
    format_frontmatter=format_frontmatter,
    help_text="Consume receipt files into the vault. Accepts files and/or directories.",
)
