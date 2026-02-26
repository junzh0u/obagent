from commands.bank_statement.llm import _prompt
from commands.bank_statement.render import (
    FIELD_DEFAULTS,
    format_frontmatter,
    make_title,
)
from commands.consume import make_consume_command

consume = make_consume_command(
    prompt_fn=_prompt,
    postprocess=lambda fields: None,
    field_defaults=FIELD_DEFAULTS,
    make_title=make_title,
    format_frontmatter=format_frontmatter,
    help_text="Consume bank statement files into the vault. Accepts files and/or directories.",
)
